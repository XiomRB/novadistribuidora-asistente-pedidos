"""E2c-1: contrato y comparación de la exactitud principal (D33, D91), con métricas aparte."""

import copy
import json
from decimal import Decimal

import pytest

from evaluacion import comparacion
from tests.fixtures.evaluacion_e2c import AM, NE, L, P, S, a_json, cuerpo, esperado

BASE = esperado([L("GS6", 2, "216.00"), L("FN1", 1, "50.50")], [P("GS6", "GS2", texto="Gaseosa"), P(motivo=NE, texto="zqx")],
                [S("GS3", "GS6", 2)], fecha="2026-12-02")


def normal(dato):
    return json.loads(a_json(dato))


def test_respuesta_identica_sin_campos_distintos():
    assert comparacion.campos_distintos(comparacion.normalizar(cuerpo(BASE)), comparacion.normalizar(BASE)) == ()


def test_importes_se_comparan_como_decimal():
    obtenido = json.loads(a_json(cuerpo(BASE)).replace("432.0", "432.00"), parse_float=Decimal, parse_int=Decimal)
    assert comparacion.campos_distintos(comparacion.normalizar(obtenido), comparacion.normalizar(BASE)) == ()
    assert Decimal("1164") == Decimal("1164.0")


def test_el_orden_es_indiferente_y_la_multiplicidad_cuenta():
    reordenado = copy.deepcopy(cuerpo(BASE))
    for k in ("lineas", "pendientes", "motivos_revision"):
        reordenado[k].reverse()
    reordenado["pendientes"][1]["opciones"].reverse()
    assert comparacion.campos_distintos(comparacion.normalizar(reordenado), comparacion.normalizar(BASE)) == ()
    duplicado = copy.deepcopy(cuerpo(BASE))
    duplicado["lineas"].append(duplicado["lineas"][0])
    assert comparacion.campos_distintos(comparacion.normalizar(duplicado), comparacion.normalizar(BASE)) == ("lineas",)


def test_opciones_como_multiconjunto():
    a, b = esperado(pendientes=[P("GS6", "GS2")]), esperado(pendientes=[P("GS2", "GS6")])
    c = esperado(pendientes=[P("GS6", "GS6", "GS2")])
    assert comparacion.campos_distintos(comparacion.normalizar(a), comparacion.normalizar(b)) == ()
    assert comparacion.campos_distintos(comparacion.normalizar(a), comparacion.normalizar(c)) == ("pendientes",)


@pytest.mark.parametrize(
    ("cambio", "campo"),
    [
        (lambda d: d.update(estado="confirmado"), "estado"),
        (lambda d: d.update(total=Decimal("1.00")), "total"),
        (lambda d: d.update(fecha_entrega="2026-12-03"), "fecha_entrega"),
        (lambda d: d["lineas"][0].update(cantidad=Decimal(3)), "lineas"),
        (lambda d: d["lineas"][0].update(precio_unitario=Decimal("1.00")), "lineas"),
        (lambda d: d["lineas"][0].update(descuento_pct=Decimal(5)), "lineas"),
        (lambda d: d["lineas"][0].update(subtotal=Decimal("1.00")), "lineas"),
        (lambda d: d["sustituciones"][0].update(cantidad=Decimal(1)), "sustituciones"),
        (lambda d: d["pendientes"][0].update(motivo=NE), "pendientes"),
        (lambda d: d["pendientes"][0].update(opciones=["GS6"]), "pendientes"),
        (lambda d: d["motivos_revision"].append("credito_excedido"), "motivos_revision"),
    ],
)
def test_cada_campo_de_la_exactitud_principal(cambio, campo):
    obtenido = copy.deepcopy(cuerpo(BASE))
    cambio(obtenido)
    assert comparacion.campos_distintos(comparacion.normalizar(obtenido), comparacion.normalizar(BASE)) == (campo,)


def test_texto_y_clasificacion_se_informan_aparte():
    otro_texto = copy.deepcopy(cuerpo(BASE))
    otro_texto["pendientes"][0]["texto"] = "otra cosa"
    o, e = comparacion.normalizar(otro_texto), comparacion.normalizar(BASE)
    assert comparacion.campos_distintos(o, e) == () and not comparacion.textos_coinciden(o, e) and comparacion.clasificacion_coincide(o, e)
    mayusculas = copy.deepcopy(cuerpo(BASE))
    mayusculas["pendientes"][0]["texto"] = "GASEOSA"
    assert comparacion.textos_coinciden(comparacion.normalizar(mayusculas), e)
    otro_motivo = copy.deepcopy(cuerpo(BASE))
    otro_motivo["pendientes"][0]["motivo"] = NE
    assert not comparacion.clasificacion_coincide(comparacion.normalizar(otro_motivo), e)


def test_contrato_nueve_claves_y_mensaje_cliente_texto():
    valido = normal(cuerpo(BASE))
    assert comparacion.cumple_contrato(valido)
    sin_mensaje = {k: v for k, v in valido.items() if k != "mensaje_cliente"}
    assert not comparacion.cumple_contrato(sin_mensaje)
    assert not comparacion.cumple_contrato({**valido, "mensaje_cliente": 5})
    assert not comparacion.cumple_contrato({**valido, "extra": 1})
    assert not comparacion.cumple_contrato({**valido, "estado": "inventado"})
    assert not comparacion.cumple_contrato([valido])


def test_mensaje_cliente_no_entra_en_la_exactitud():
    otro = copy.deepcopy(cuerpo(BASE, mensaje="otro mensaje"))
    assert comparacion.campos_distintos(comparacion.normalizar(otro), comparacion.normalizar(BASE)) == ()
    assert AM  # (constante usada en BASE)
