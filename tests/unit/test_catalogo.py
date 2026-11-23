import pandas as pd
import pytest

from app.datos.carga import cargar_datos
from app.dominio.catalogo import IndiceCatalogo, TipoResolucion
from app.dominio.unidades import LexicoUnidades
from tests.fixtures import catalogo_e1b

R, A, N, G = TipoResolucion.RESUELTO, TipoResolucion.AMBIGUO, TipoResolucion.NO_EXISTE, TipoResolucion.AGOTADO_SIN_SUSTITUTO


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    return catalogo_e1b.cargar(tmp_path_factory.mktemp("e1b"))


@pytest.fixture(scope="module")
def indice(datos):
    return IndiceCatalogo(datos, LexicoUnidades(datos).palabras_cantidad())


class TestIndice:
    def test_grupos(self, indice):
        assert indice.hermanos("GS6") == ("GS6", "GS2", "GL2", "GS3")
        assert indice.hermanos("PC2") == ("PC2", "PE2", "PD7")
        assert indice.hermanos("GV1") == ("GV1", "GC1", "GK1")
        assert indice.grupo("BR6") == "brio"
        assert indice.grupo("LP3") == "leche"

    def test_medidas_desde_presentacion_y_nombre(self, indice):
        assert indice.compatible_con_medidas("SH1", frozenset(indice.entradas["SH1"].medidas))
        medidas = {(m.valor, m.unidad) for m in indice.entradas["SH1"].medidas}
        assert ("24", "sobre") in {(str(v), u) for v, u in medidas} and ("10", "ml") in {(str(v), u) for v, u in medidas}


class TestResolucion:
    @pytest.mark.parametrize(
        ("descripcion", "tipo", "sku", "opciones"),
        [
            ("pasta", A, None, ("PC2", "PE2", "PD7")),
            ("pasta fina", A, None, ("PC2", "PE2")),
            ("pasta fina coditos", R, "PC2", ("PC2",)),
            ("frijol", A, None, ("FN1", "FR1")),
            ("frijoles negros", R, "FN1", ("FN1",)),
            ("gaseosa sol 600", R, "GS6", ("GS6",)),
            ("gaseosa de 600", R, "GS6", ("GS6",)),
            ("gaseosa de 2 litros", A, None, ("GS2", "GL2")),
            ("gaseosa sol de 2", R, "GS2", ("GS2",)),
            ("gaseosa sol 3 L", R, "GS3", ("GS3",)),  # agotado con sustituto: se resuelve (la sustitución es de E1b-2)
            ("gaseosa de 5 litros", N, None, ()),
            ("galletas", A, None, ("GV1", "GC1", "GK1")),
            ("galletas luna chocolate", G, "GC1", ("GC1",)),
            ("cafe monte instantaneo", G, "CI1", ("CI1",)),
            ("cafe monte", A, None, ("CF1", "CI1")),
            ("aceite", A, None, ("AC1", "AC2")),
            ("aceite girasol oro", R, "AC1", ("AC1",)),
            ("aceite palma", R, "AC2", ("AC2",)),
            ("papel higienico", A, None, ("PH4", "PHD")),
            ("papel nube 4", R, "PH4", ("PH4",)),
            ("shampo ola", R, "SH1", ("SH1",)),
            ("arroz sierra quintal", R, "ARQ", ("ARQ",)),
            ("arroz sierra de libra", R, "AR1", ("AR1",)),
            ("leche en polvo nieve", R, "LP3", ("LP3",)),
            ("cerveza", N, None, ()),
            ("brio 600", R, "BR6", ("BR6",)),
        ],
    )
    def test_casos(self, indice, descripcion, tipo, sku, opciones):
        r = indice.resolver(descripcion)
        assert (r.tipo, r.sku, r.opciones) == (tipo, sku, opciones)

    def test_d45_candidatos_sin_evidencia_textual(self, indice):
        r = indice.resolver("chescos", ["GS6"])
        assert r.tipo is A and r.opciones == ("GS6", "GS2", "GL2", "GS3")
        assert "SIN_EVIDENCIA_TEXTUAL" in r.codigos

    def test_d45_candidato_inventado_nunca_se_acepta(self, indice):
        r = indice.resolver("cerveza", ["GS6"])
        assert r.tipo is A and r.sku is None

    def test_d45_con_medida_filtra_pero_sigue_ambiguo(self, indice):
        r = indice.resolver("chescos de 600", ["GS2"])
        assert r.tipo is A and r.opciones == ("GS6",)

    def test_texto_contradice_al_llm(self, indice):
        r = indice.resolver("gaseosa sol 600 ml", ["GS2"])
        assert (r.tipo, r.sku) == (R, "GS6") and "CONTRADICCION_LLM" in r.codigos

    def test_sku_del_llm_inexistente(self, indice):
        r = indice.resolver("frijol negro", ["ZZZ"])
        assert r.sku == "FN1" and "SKU_LLM_INEXISTENTE" in r.codigos

    def test_llm_coincide(self, indice):
        r = indice.resolver("frijol negro", ["FN1"])
        assert r.sku == "FN1" and "CONTRADICCION_LLM" not in r.codigos

    def test_cantidades_en_la_descripcion_no_son_presentaciones(self, indice):
        assert indice.resolver("2 fardos de gaseosa sol 600").sku == "GS6"

class TestVariasMedidas:
    """Cada medida explícita es una restricción: ningún producto que contradiga alguna se acepta."""

    @pytest.mark.parametrize(
        "descripcion",
        [
            "gaseosa sol 600 ml de 5 litros",  # antes: GS6 resuelto pese a los 5 L
            "gaseosa sol 600 ml de 2 litros",  # antes: GS6 resuelto pese a los 2 L
            "shampoo ola 24 sobres de 20 ml",  # antes: SH1 resuelto pese a los 20 ml
            "papel nube 4 rollos de 12 rollos",
        ],
    )
    def test_contradiccion_explicita_no_se_acepta(self, indice, descripcion):
        r = indice.resolver(descripcion)
        assert (r.tipo, r.sku, r.opciones) == (N, None, ()) and "MEDIDA_SIN_PRODUCTO" in r.codigos

    def test_producto_con_varias_medidas_que_cumple_todas(self, indice):
        # SH1 tiene "24 sobres" (presentación) y "10 ml" (nombre).
        assert indice.resolver("shampoo ola 24 sobres de 10 ml").sku == "SH1"

    def test_numero_sin_unidad_se_ignora_si_hay_medida_explicita(self, indice):
        assert indice.resolver("2 de gaseosa sol 600 ml").sku == "GS6"

    def test_varios_numeros_sin_unidad_basta_uno(self, indice):
        assert indice.resolver("2 de gaseosa sol 600").sku == "GS6"

    @pytest.mark.parametrize(
        ("medidas_sku", "descripcion", "compatible"),
        [
            ("GS6", "600 ml", True), ("GS6", "600 ml 2 L", False), ("GS2", "600 ml 2 L", False),
            ("SH1", "10 ml 24 sobres", True), ("SH1", "10 ml 12 sobres", False), ("GS6", "2 600", True),
            ("GS6", "2 3", False), ("GS6", "", True),
        ],
    )
    def test_compatible_con_medidas(self, indice, medidas_sku, descripcion, compatible):
        from app.dominio.texto import extraer_medidas

        assert indice.compatible_con_medidas(medidas_sku, extraer_medidas(descripcion)) is compatible


class TestCasosEspeciales:
    def test_agotado_cuyo_sustituto_tambien_esta_agotado(self, tmp_path):
        productos = catalogo_e1b.productos()
        productos.loc[productos.sku == "GS2", "disponible"] = False
        datos = cargar_datos(catalogo_e1b.escribir(tmp_path / "d", {"productos": productos}))
        indice = IndiceCatalogo(datos)
        r = indice.resolver("gaseosa sol 3 L")
        assert (r.tipo, r.opciones) == (G, ("GS3",))

    def test_opciones_en_orden_del_catalogo(self, tmp_path):
        productos = catalogo_e1b.productos().iloc[::-1].reset_index(drop=True)
        datos = cargar_datos(catalogo_e1b.escribir(tmp_path / "d", {"productos": productos}))
        assert IndiceCatalogo(datos).resolver("frijol").opciones == ("FR1", "FN1")

    def test_funciona_sin_alias(self, tmp_path):
        datos = cargar_datos(catalogo_e1b.escribir(tmp_path / "d", {"sinonimos": pd.DataFrame(columns=["sku", "alias"])}))
        assert IndiceCatalogo(datos).resolver("gaseosa sol 600").sku == "GS6"
