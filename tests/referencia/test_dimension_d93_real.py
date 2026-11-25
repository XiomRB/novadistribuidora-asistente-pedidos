"""D93 con el catálogo real y los casos de desarrollo (local; se omite sin DATA_DIR / EVAL_DEV_PATH).

- Escenarios con productos reales que se venden por peso o por volumen (ejemplos sintéticos).
- D93 no se activa en ninguno de los 188 eventos de referencia (ninguno expresa la cantidad en una
  unidad física), así que su comportamiento no cambia.
- Sin dimensión, `resolver` da exactamente lo mismo en todo el corpus de nombres y alias.
"""

from datetime import datetime

import pytest

from app.dominio.catalogo import IndiceCatalogo
from app.dominio.entrada import EntradaPedido
from app.dominio.pedido import Recursos, procesar_pedido
from app.dominio.plegado import dimension_cantidad_total
from app.dominio.unidades import LexicoUnidades
from tests.referencia.formato_eventos_dev import cargar, reconstruir

NE, AM, CN = "producto_no_existe", "producto_ambiguo", "cantidad_no_convertible"


@pytest.fixture(scope="module")
def recursos(datos_reales):
    return Recursos.construir(datos_reales)


def pedido(recursos, datos, texto, producto, cantidad, unidad_texto):
    evento = {"id": "e1", "mensaje": 0, "tipo": "agregar", "texto": texto, "producto": producto,
              "cantidad": cantidad, "unidad": "otra", "unidad_texto": unidad_texto}
    entrada = EntradaPedido("C009", datetime(2026, 12, 1, 10, 0), (texto,))
    r = procesar_pedido(entrada, {"eventos": [evento]}, datos, recursos=recursos)
    return [(l.sku, f"{l.cantidad.normalize():f}") for l in r.cierre.lineas], [(p.motivo.value, p.opciones) for p in r.cierre.pendientes]


@pytest.mark.parametrize(
    ("texto", "producto", "cantidad", "unidad", "esperado"),
    [
        ("5 litros de detergente espumoso", "detergente espumoso", "5", "litros", ([], [(NE, ())])),  # 500 g
        ("3 libras de cloro blancura", "cloro blancura", "3", "libras", ([], [(NE, ())])),  # 1 L
        ("2 libras de pasta", "pasta", "2", "libras", ([], [(AM, ("A09", "A10"))])),  # se descarta la pasta dental
        ("1 litro de pasta", "pasta", "1", "litro", ([], [(AM, ("P03",))])),  # una opción: sigue ambiguo
        ("3 kilos de sal", "sal", "3", "kilos", ([], [(CN, ("A11",))])),  # misma dimensión
        ("3 libras de frijol negro", "frijol negro", "3", "libras", ([], [(CN, ("A03",))])),  # misma dimensión
        ("2 litros de agua pura", "agua pura", "2", "litros", ([], [(AM, ("B07", "B08"))])),  # todos compatibles
    ],
)
def test_escenarios_reales(recursos, datos_reales, texto, producto, cantidad, unidad, esperado):
    assert pedido(recursos, datos_reales, texto, producto, cantidad, unidad) == esperado


def test_dimension_de_los_productos_reales(datos_reales):
    dimension = IndiceCatalogo(datos_reales).dimension
    conteo = {d: sum(1 for v in dimension.values() if v == d) for d in ("volumen", "masa", None)}
    assert conteo == {"volumen": 17, "masa": 18, None: 9}
    assert {s for s, v in dimension.items() if v is None} == {"L04", "L05", "P02", "S01", "S02", "S03", "S04", "S05", "S06"}


def test_d93_no_se_activa_en_ninguno_de_los_188_eventos_de_referencia(casos_dev):
    documento = cargar()
    eventos = [e for caso in casos_dev for e in reconstruir(documento["casos"][caso["id"]], caso["entrada"]["mensajes"]).eventos]
    assert len(eventos) == 188
    assert [e.id for e in eventos if dimension_cantidad_total(e, e.texto) is not None] == []


def test_sin_dimension_resolver_da_lo_mismo_en_todo_el_corpus(datos_reales):
    indice = IndiceCatalogo(datos_reales, LexicoUnidades(datos_reales).palabras_cantidad())
    descripciones = {p.nombre for p in datos_reales.productos.values()} | {a.alias for a in datos_reales.alias}
    descripciones |= {f"{p.nombre} {p.presentacion}" for p in datos_reales.productos.values()}
    for d in sorted(descripciones):
        assert indice.resolver(d) == indice.resolver(d, (), frozenset())
