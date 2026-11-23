"""Resolución y unidades sobre el catálogo real (local; se omite sin DATA_DIR).

Las descripciones son texto propio; los resultados esperados se derivan de las políticas y
de las decisiones aprobadas (no se copian respuestas publicadas).
"""

from decimal import Decimal

import pytest

from app.dominio.catalogo import IndiceCatalogo, TipoResolucion
from app.dominio.unidades import CodigoConversion, LexicoUnidades, convertir

R, A, N, G = TipoResolucion.RESUELTO, TipoResolucion.AMBIGUO, TipoResolucion.NO_EXISTE, TipoResolucion.AGOTADO_SIN_SUSTITUTO


@pytest.fixture(scope="module")
def lexico(datos_reales):
    return LexicoUnidades(datos_reales)


@pytest.fixture(scope="module")
def indice(datos_reales, lexico):
    return IndiceCatalogo(datos_reales, lexico.palabras_cantidad())


@pytest.mark.parametrize(
    ("descripcion", "candidatos", "tipo", "sku", "opciones"),
    [
        ("pasta", [], A, None, ("A09", "A10", "P03")),
        ("pasta bella", [], A, None, ("A09", "A10")),
        ("jabón", [], A, None, ("L02", "P01")),
        ("frijol", [], A, None, ("A03", "A04")),
        ("naranjitas", [], A, None, ("B04", "B05")),
        ("aceite", [], A, None, ("A06", "A07")),
        ("papel higiénico", [], A, None, ("L04", "L05")),
        ("galletas", [], A, None, ("S01", "S02", "S03")),
        ("juguitos", [], A, None, ("B09", "B10")),
        ("kola 600", [], R, "B01", ("B01",)),
        ("kola norte 600 ml", ["B02"], R, "B01", ("B01",)),
        ("kola de litro y medio", [], R, "B02", ("B02",)),
        ("kola norte 1.5 l", [], R, "B02", ("B02",)),
        ("agua pura 600", [], R, "B07", ("B07",)),
        ("aceite girasol dordo", [], R, "A06", ("A06",)),
        ("shampoo birsa sobre 10 ml", [], R, "P02", ("P02",)),
        ("arroz ceiba de libra", [], R, "A01", ("A01",)),
        ("arroz quintal", [], R, "A02", ("A02",)),
        ("jugo de naranja", [], R, "B09", ("B09",)),
        ("cocas", ["B01"], A, None, ("B01", "B02", "B03")),
        ("cerveza", [], N, None, ()),
        ("kola de 5 litros", [], N, None, ()),
        ("dulcitas chocolate", [], G, "S02", ("S02",)),
        ("desodorante fresco", [], G, "P04", ("P04",)),
    ],
)
def test_resolucion(indice, descripcion, candidatos, tipo, sku, opciones):
    r = indice.resolver(descripcion, candidatos)
    assert (r.tipo, r.sku, r.opciones) == (tipo, sku, opciones)


@pytest.mark.parametrize(
    ("sku", "cantidad", "unidad", "codigo", "resultado"),
    [
        ("B11", 48, "latas", CodigoConversion.OK, 4),
        ("B07", 72, "botellas", CodigoConversion.OK, 3),
        ("A12", 36, "bolsas", CodigoConversion.OK, 3),
        ("L03", 1, "docena", CodigoConversion.OK, 1),
        ("B01", 36, "botellas", CodigoConversion.NO_EXACTA, None),
        ("S03", 2, "paquetes", CodigoConversion.NO_EXACTA, None),
        ("A01", 2, "paquetes", CodigoConversion.UNIDAD_INCOMPATIBLE, None),
        ("B01", 1, "caja", CodigoConversion.UNIDAD_INCOMPATIBLE, None),
        ("A06", 2, "fardos", CodigoConversion.UNIDAD_INCOMPATIBLE, None),
        ("L04", 48, "rollos", CodigoConversion.UNIDAD_INCOMPATIBLE, None),
        ("A14", 10, "cajitas", CodigoConversion.OK, 10),
        ("B11", None, "latas", CodigoConversion.SUELTA_SIN_NUMERO, None),
    ],
)
def test_unidades(datos_reales, lexico, sku, cantidad, unidad, codigo, resultado):
    c = convertir(
        cantidad=None if cantidad is None else Decimal(cantidad),
        cantidad_incierta=False,
        unidad_declarada="suelta",
        unidad_texto=unidad,
        producto=datos_reales.productos[sku],
        lexico=lexico,
    )
    assert c.codigo is codigo and c.cantidad_venta == (None if resultado is None else Decimal(resultado))
