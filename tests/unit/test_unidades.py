from decimal import Decimal

import pytest

from app.dominio.unidades import (
    CantidadInvalida,
    ClaseUnidad,
    CodigoConversion,
    LexicoUnidades,
    contenedor_declarado,
    convertir,
    parsear_cantidad,
    sueltas_compatibles,
)
from tests.fixtures import catalogo_e1b

D = Decimal
OK, INC, NE, NX, UI, UD, SSN, SP, INCI, CERO = (
    CodigoConversion.OK, CodigoConversion.UNIDAD_INCOMPATIBLE, CodigoConversion.NO_ENTERA, CodigoConversion.NO_EXACTA,
    CodigoConversion.UNIDAD_INCOMPATIBLE, CodigoConversion.UNIDAD_DESCONOCIDA, CodigoConversion.SUELTA_SIN_NUMERO,
    CodigoConversion.SIN_PALABRA, CodigoConversion.INCIERTA, CodigoConversion.CANTIDAD_CERO,
)


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    return catalogo_e1b.cargar(tmp_path_factory.mktemp("e1b"))


@pytest.fixture(scope="module")
def lexico(datos):
    return LexicoUnidades(datos)


def conv(datos, lexico, sku, cantidad, unidad_texto=None, declarada=None, incierta=False):
    if declarada is None:
        declarada = "venta" if unidad_texto is None else "suelta"
    return convertir(
        cantidad=None if cantidad is None else D(str(cantidad)),
        cantidad_incierta=incierta,
        unidad_declarada=declarada,
        unidad_texto=unidad_texto,
        producto=datos.productos[sku],
        lexico=lexico,
    )


class TestParsearCantidad:
    @pytest.mark.parametrize(("texto", "esperado"), [("2", D(2)), ("0,5", D("0.5")), ("48", D(48)), (" 3 ", D(3)), (None, None), ("0", D(0))])
    def test_validas(self, texto, esperado):
        assert parsear_cantidad(texto) == esperado

    @pytest.mark.parametrize("texto", ["-1", "1e3", "dos", "", "1/2", "2.5555"])
    def test_invalidas(self, texto):
        with pytest.raises(CantidadInvalida):
            parsear_cantidad(texto)


class TestCompatibilidad:
    @pytest.mark.parametrize(
        ("sku", "esperado"),
        [
            ("GV1", {"paquete", "unidad"}),  # 12 paquetes, UPE 12
            ("SH1", {"sobre", "unidad"}),
            ("CH1", {"bolsa", "unidad"}),  # 20 bolsitas, UPE 20
            ("PH4", set()),  # 4 rollos, UPE 12: subnivel
            ("ARQ", set()),  # UPE 1
            ("CF1", {"bolsa", "unidad"}),  # peso
            ("GS6", {"botella", "lata", "unidad"}),  # volumen
        ],
    )
    def test_sueltas_compatibles(self, datos, sku, esperado):
        assert sueltas_compatibles(datos.productos[sku]) == frozenset(esperado)

    def test_contenedor_declarado(self, datos):
        assert contenedor_declarado(datos.productos["GK1"]) == (D(10), "paquete")
        assert contenedor_declarado(datos.productos["GS6"]) is None


class TestConversion:
    @pytest.mark.parametrize(
        ("sku", "cantidad", "unidad", "codigo", "resultado"),
        [
            # Unidad de venta propia, variantes y sin unidad.
            ("GS6", 2, "fardos", OK, 2), ("GS6", 4, "farditos", OK, 4), ("AC1", 10, "cajitas", OK, 10),
            ("GV1", 5, "displays", OK, 5), ("ARQ", 3, "quintales", OK, 3), ("GS6", 3, None, OK, 3),
            ("GS6", None, None, OK, 1), ("GS6", "2.5", "fardos", NE, None), ("GS6", "0.5", None, NE, None),
            # Empaque ajeno: no se asume.
            ("GS6", 1, "caja", UI, None), ("AC1", 2, "fardos", UI, None), ("GV1", 1, "caja", UI, None),
            ("FN1", 3, "quintales", UI, None),
            # Sueltas compatibles.
            ("RY4", 48, "latas", OK, 4), ("GS6", 72, "botellas", OK, 3), ("CF1", 36, "bolsas", OK, 3),
            ("GK1", 20, "paquetes", OK, 2), ("SH1", 24, "sobres", OK, 1), ("CH1", 40, "bolsitas", OK, 2),
            ("CL1", 1, "docena", OK, 1), ("CL1", 24, "unidades", OK, 2),
            # Sueltas no exactas.
            ("GS6", 36, "botellas", NX, None), ("GK1", 2, "paquetes", NX, None), ("SH1", 2, "sobres", NX, None),
            ("CL1", "0.5", "docena", NX, None), ("CH1", 6, "bolsas", NX, None),
            # Sueltas incompatibles con la presentación o la UPE.
            ("AR1", 2, "paquetes", UI, None), ("CF1", 2, "sobres", UI, None), ("LP3", 24, "latas", UI, None),
            ("PH4", 48, "rollos", UI, None), ("ARQ", 2, "bolsas", UI, None), ("PH4", 1, "docena", UI, None),
            ("GS6", 24, "bolsas", UI, None),
            # Desconocidas.
            ("GS6", 3, "pacas", UD, None), ("AR1", 50, "libras", UD, None),
        ],
    )
    def test_tabla(self, datos, lexico, sku, cantidad, unidad, codigo, resultado):
        c = conv(datos, lexico, sku, cantidad, unidad)
        assert c.codigo is codigo
        assert c.cantidad_venta == (None if resultado is None else D(resultado))
        if c.cantidad_venta is not None:
            assert isinstance(c.cantidad_venta, Decimal)

    def test_cantidad_incierta_nunca_se_convierte(self, datos, lexico):
        for unidad in (None, "fardos", "botellas"):
            assert conv(datos, lexico, "GS6", 24, unidad, incierta=True).codigo is INCI

    def test_d46_suelta_sin_numero(self, datos, lexico):
        assert conv(datos, lexico, "RY4", None, "latas").codigo is SSN

    def test_declarada_suelta_sin_palabra(self, datos, lexico):
        assert conv(datos, lexico, "RY4", 48, None, declarada="suelta").codigo is SP
        assert conv(datos, lexico, "RY4", 48, None, declarada="otra").codigo is SP

    def test_docena_declarada_sin_palabra(self, datos, lexico):
        assert conv(datos, lexico, "CL1", 1, None, declarada="docena").cantidad_venta == D(1)

    def test_cero(self, datos, lexico):
        assert conv(datos, lexico, "GS6", 0, "fardos").codigo is CERO
        assert conv(datos, lexico, "GS6", 0, "botellas").codigo is CERO

    def test_palabra_manda_sobre_lo_declarado(self, datos, lexico):
        c = conv(datos, lexico, "RY4", 48, "latas", declarada="venta")
        assert c.cantidad_venta == D(4) and c.desacuerdo_llm and c.clase is ClaseUnidad.SUELTA
        c = conv(datos, lexico, "GS6", 2, "fardos", declarada="suelta")
        assert c.cantidad_venta == D(2) and c.desacuerdo_llm

    def test_presentacion_no_es_cantidad(self, datos, lexico):
        # "papel nube 12 rollos" con la presentación interpretada como cantidad: 1 fardo, no 12.
        assert conv(datos, lexico, "PHD", 12, "rollos").cantidad_venta == D(1)

    def test_usa_la_upe_del_producto_solicitado(self, datos, lexico):
        # GS3 (agotado, UPE 6) se convierte con su propia UPE aunque se sustituya por GS2.
        assert conv(datos, lexico, "GS3", 12, "botellas").cantidad_venta == D(2)
