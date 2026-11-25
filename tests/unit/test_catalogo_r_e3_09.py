"""D92 (R-E3-09): evidencia textual en la resolución, sobre el catálogo sintético de E1b-1.

- R1-a (prioridad sobre R1-b): sin ancla y con un token conocido -> NO_EXISTE, con o sin
  candidatos del LLM ("levadura en polvo" no da Leche en Polvo; "chocolates amargos" no da
  Galletas Chocolate).
- R1-b (D45, sin cambios): jerga pura con candidatos -> ambiguo con los hermanos; nunca una línea.
- R1-c: sin ancla y sin candidatos -> NO_EXISTE.
- R2: ancla y token desconocido (marca o variante que no vendemos) -> ambiguo **sin opciones**.
- Ningún candidato del LLM produce una línea sin evidencia textual.
"""

import random

import pytest

from app.dominio.catalogo import Evidencia, IndiceCatalogo, Resolucion, TipoResolucion
from app.dominio.unidades import LexicoUnidades
from tests.fixtures import catalogo_e1b

R, A, N, AG = TipoResolucion.RESUELTO, TipoResolucion.AMBIGUO, TipoResolucion.NO_EXISTE, TipoResolucion.AGOTADO_SIN_SUSTITUTO


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    return catalogo_e1b.cargar(tmp_path_factory.mktemp("r_e3_09"))


@pytest.fixture(scope="module")
def indice(datos):
    return IndiceCatalogo(datos, LexicoUnidades(datos).palabras_cantidad())


def res(indice, texto, candidatos=()):
    r = indice.resolver(texto, list(candidatos))
    return r.tipo, r.sku, r.opciones


# ====================================================================== R1-a


@pytest.mark.parametrize("candidatos", [(), ("LP3",), ("LP3", "GS6")], ids=["sin", "LP3", "LP3_GS6"])
def test_r1a_levadura_en_polvo_no_existe_con_o_sin_candidatos(indice, candidatos):
    assert res(indice, "levadura en polvo", candidatos) == (N, None, ())
    assert "SIN_ANCLA_CATALOGO" in indice.resolver("levadura en polvo", list(candidatos)).codigos


@pytest.mark.parametrize("texto", ["chocolates amargos", "chocolate amargo"])
@pytest.mark.parametrize("candidatos", [(), ("GC1",), ("GC1", "GV1")], ids=["sin", "GC1", "GC1_GV1"])
def test_r1a_chocolate_amargo_no_existe_con_o_sin_candidatos(indice, texto, candidatos):
    assert res(indice, texto, candidatos) == (N, None, ())


def test_r1a_prevalece_sobre_r1b(indice):
    # Sin D92, la resolución por texto confirmaría LP3 ("polvo" es un token del nombre Leche en Polvo);
    # con candidatos, D45 daría opciones. R1-a se aplica antes: NO_EXISTE, sin opciones.
    assert indice._resolver_por_texto("levadura en polvo", ["LP3"]).tipo is R
    assert indice.evidencia("levadura en polvo") is Evidencia.SIN_ANCLA_CON_CONOCIDO
    assert res(indice, "levadura en polvo", ["LP3"]) == (N, None, ())


@pytest.mark.parametrize(
    ("candidatos", "codigos"),
    [
        ((), ("SIN_ANCLA_CATALOGO",)),
        (("LP3",), ("CANDIDATOS_LLM_IGNORADOS", "SIN_ANCLA_CATALOGO")),
        (("LP3", "GS6"), ("CANDIDATOS_LLM_IGNORADOS", "SIN_ANCLA_CATALOGO")),
        (("ZZ9",), ("SKU_LLM_INEXISTENTE", "SIN_ANCLA_CATALOGO")),
        (("ZZ9", "LP3"), ("SKU_LLM_INEXISTENTE", "CANDIDATOS_LLM_IGNORADOS", "SIN_ANCLA_CATALOGO")),
    ],
    ids=["sin", "uno_valido", "dos_validos", "solo_inexistente", "mixto"],
)
def test_r1a_registra_candidatos_llm_ignorados(indice, candidatos, codigos):
    # Solo cuando R1-a descarta candidatos válidos; el resultado no cambia (sin línea ni opciones).
    r = indice.resolver("levadura en polvo", list(candidatos))
    assert (r.tipo, r.sku, r.opciones, r.codigos) == (N, None, (), codigos)


def test_candidatos_llm_ignorados_no_lleva_datos_del_mensaje_ni_llega_al_contrato(indice):
    marca = "ZQXPRIVADO"
    r = indice.resolver(f"levadura en polvo {marca}", ["LP3"])
    assert "CANDIDATOS_LLM_IGNORADOS" in r.codigos
    assert all(c.isupper() and c.replace("_", "").isalpha() for c in r.codigos)  # códigos fijos, sin texto
    assert not any(marca.lower() in c.lower() or "LP3" in c for c in r.codigos)
    assert r.tipo is N and r.opciones == ()  # el contrato solo ve el pendiente producto_no_existe


def test_otras_reglas_no_registran_candidatos_llm_ignorados(indice):
    for texto, candidatos in [("chescos", ["GS6"]), ("leche Lala", ["LP3"]), ("gaseosa sol 600", ["GS6"])]:
        assert "CANDIDATOS_LLM_IGNORADOS" not in indice.resolver(texto, candidatos).codigos


def test_clasificacion_de_la_evidencia(indice):
    assert indice.evidencia("levadura en polvo") is Evidencia.SIN_ANCLA_CON_CONOCIDO
    assert indice.evidencia("chescos") is Evidencia.JERGA
    assert indice.evidencia("leche Lala") is Evidencia.TOKEN_DESCONOCIDO
    assert indice.evidencia("gaseosa sol 600") is Evidencia.NORMAL
    assert indice.evidencia("3 cajas de frijol negro") is Evidencia.NORMAL  # las unidades no cuentan
    assert indice.evidencia("la de 24") is Evidencia.NORMAL  # sin tokens significativos


# ====================================================================== R1-b (D45) y R1-c


def test_r1b_jerga_pura_conserva_d45(indice):
    assert res(indice, "chescos", ["GS6"]) == (A, None, ("GS6", "GS2", "GL2", "GS3"))


def test_r1b_d45_con_medida_filtra(indice):
    assert res(indice, "chescos de 600", ["GS2"]) == (A, None, ("GS6",))


@pytest.mark.parametrize("texto", ["fanta", "sprite", "vino tinto", "cerveza"])
def test_r1c_sin_ancla_y_sin_candidatos_no_existe(indice, texto):
    assert res(indice, texto) == (N, None, ())


@pytest.mark.parametrize("texto", ["fanta", "sprite"])
def test_marcas_ajenas_con_candidatos_son_ambiguas_nunca_linea(indice, texto):
    # D45: ambiguo con los hermanos de los candidatos; nunca una línea ni una sustitución.
    assert res(indice, texto, ["GS6", "GS2"]) == (A, None, ("GS6", "GS2", "GL2", "GS3"))


# ====================================================================== R2


@pytest.mark.parametrize(
    ("texto", "candidatos"),
    [("leche Lala", ()), ("leche Lala", ("LP3",)), ("cafe Sereno de 400 g", ()), ("cafe Sereno de 400 g", ("CF1",)),
     ("arroz integral", ()), ("arroz integral", ("AR1",)), ("arroz integral", ("AR1", "ARQ"))],
)
def test_r2_ancla_con_token_desconocido_es_ambiguo_sin_opciones(indice, texto, candidatos):
    r = indice.resolver(texto, list(candidatos))
    assert (r.tipo, r.sku, r.opciones) == (A, None, ()) and "TOKEN_DESCONOCIDO" in r.codigos


def test_r2_respeta_un_no_existe_por_medidas(indice):
    r = indice.resolver("arroz integral de 8 litros")
    assert (r.tipo, r.sku, r.opciones) == (N, None, ()) and "MEDIDA_SIN_PRODUCTO" in r.codigos
    assert "TOKEN_DESCONOCIDO" not in r.codigos


# Caminos de NO_EXISTE en la resolución de E1b-1 (`_resolver_por_texto`, sin cambios):
# - SIN_COINCIDENCIAS: ningún SKU con evidencia textual ni candidatos válidos (universo vacío);
# - MEDIDA_SIN_PRODUCTO: hay evidencia, pero las medidas explícitas descartan todo el universo.
# (SKU_LLM_INEXISTENTE puede acompañar a cualquiera de los dos; no es un camino propio.)


@pytest.mark.parametrize(
    ("texto", "candidatos", "codigo"),
    [("cerveza", (), "SIN_COINCIDENCIAS"), ("cerveza", ("ZZ9",), "SIN_COINCIDENCIAS"),
     ("gaseosa sol 600 ml de 5 litros", (), "MEDIDA_SIN_PRODUCTO"), ("arroz de 5 litros", ("ZZ9",), "MEDIDA_SIN_PRODUCTO")],
)
def test_caminos_de_no_existe_en_la_resolucion_de_e1b1(indice, texto, candidatos, codigo):
    r = indice._resolver_por_texto(texto, list(candidatos))
    assert r.tipo is N and codigo in r.codigos
    assert ("SKU_LLM_INEXISTENTE" in r.codigos) == bool(candidatos)


@pytest.mark.parametrize(
    "codigos",
    [("SIN_COINCIDENCIAS",), ("SKU_LLM_INEXISTENTE", "SIN_COINCIDENCIAS")],
    ids=["sin_coincidencias", "sin_coincidencias_y_sku_inexistente"],
)
def test_r2_convierte_en_ambiguo_un_no_existe_que_no_es_por_medidas(indice, monkeypatch, codigos):
    # Con anclas reales este camino no se observa (el ancla aporta evidencia en todos los casos medidos), así que se
    # aísla la regla: la resolución original devuelve NO_EXISTE sin contradicción de medidas.
    monkeypatch.setattr(indice, "_resolver_por_texto", lambda *_: Resolucion(N, codigos=codigos))
    r = indice.resolver("leche Lala")
    assert (r.tipo, r.sku, r.opciones, r.codigos) == (A, None, (), codigos + ("TOKEN_DESCONOCIDO",))


def test_r2_conserva_no_existe_solo_con_medida_sin_producto(indice, monkeypatch):
    monkeypatch.setattr(indice, "_resolver_por_texto", lambda *_: Resolucion(N, codigos=("MEDIDA_SIN_PRODUCTO",)))
    assert indice.resolver("leche Lala").tipo is N


def test_r2_barrido_de_anclas_con_token_desconocido(indice):
    # Cada ancla con un token desconocido: AMBIGUO sin opciones; con medidas contradictorias,
    # NO_EXISTE solo si el código es MEDIDA_SIN_PRODUCTO.
    for ancla in sorted(indice.anclas):
        for texto in (f"{ancla} zqxkw", f"{ancla} zqxkw de 5 litros", f"{ancla} zqxkw 999 g"):
            if indice.evidencia(texto) is not Evidencia.TOKEN_DESCONOCIDO:
                continue
            r = indice.resolver(texto)
            assert (r.tipo, r.opciones) == (A, ()) or (r.tipo is N and "MEDIDA_SIN_PRODUCTO" in r.codigos), texto


# ====================================================================== lo que no cambia


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("frijol", (A, None, ("FN1", "FR1"))), ("cloro", (R, "CL1", ("CL1",))), ("friijol negro", (R, "FN1", ("FN1",))),
     ("gaseosaa sol 600", (R, "GS6", ("GS6",))), ("galletas luna chocolate", (AG, "GC1", ("GC1",))), ("leche en polvo nieve", (R, "LP3", ("LP3",))),
     ("3 cajas de frijol negro", (R, "FN1", ("FN1",))), ("gaseosa sol 600 ml de 5 litros", (N, None, ()))],
)
def test_resultados_aprobados_no_cambian(indice, texto, esperado):
    assert res(indice, texto) == esperado


def test_sin_palabras_de_cantidad_las_unidades_de_venta_no_cuentan(datos):
    # Algunos usos construyen el índice sin el léxico: las unidades se toman también del catálogo.
    assert IndiceCatalogo(datos).resolver("3 cajas de frijol negro").sku == "FN1"


# ====================================================================== ninguna línea solo por el LLM


def test_ningun_candidato_del_llm_produce_una_linea_sin_evidencia(indice, datos):
    rnd = random.Random(20261125)
    silabas = ["ka", "lo", "pi", "su", "tra", "men", "dor", "quil", "xo", "bra", "nes", "to", "ri", "va", "zu"]
    inventadas = ["".join(rnd.choice(silabas) for _ in range(rnd.randint(2, 4))) for _ in range(100)]
    descripciones = inventadas + ["fanta", "sprite", "chescos", "levadura en polvo", "chocolates amargos", "vino tinto"]
    con_linea = [
        (t, s) for t in descripciones for s in datos.productos
        if indice.resolver(t, [s]).tipo in (R, AG)
    ]
    assert con_linea == []
