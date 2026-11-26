"""E2c-1: K1, K2 (con sustituciones por SKU solicitado), K5 (contrato y recálculo con E1a) y la
evaluación completa de un caso. Catálogo sintético de E1b: PHD está agotado y su sustituto es PH4."""

import dataclasses
import json
from datetime import datetime
from decimal import Decimal

import pytest

from app.dominio.cierre import cerrar_pedido
from app.dominio.resultado import LineaSolicitada, Sustitucion
from evaluacion import criticos
from evaluacion.conjuntos import Caso
from evaluacion.criticos import evaluar_caso, recalculo_coincide
from tests.fixtures.evaluacion_e2c import NE, L, P, S, a_json, anot, cuerpo, esperado, medir
from tests.fixtures.historial_e1b2 import cargar_contexto

ENTRADA = {"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": ["zqx"]}


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("criticos")).datos


def cuerpo_valido(datos, lineas, sustituciones=()):
    """Respuesta coherente con E1a (precios, descuentos, total y fecha calculados por `cerrar_pedido`)."""
    r = cerrar_pedido(cliente_id="K04", fecha_hora=datetime(2026, 12, 1, 10, 0), lineas_solicitadas=[LineaSolicitada(s, Decimal(c)) for s, c in lineas],
                      pendientes=[], sustituciones=[Sustitucion(a, b, Decimal(c)) for a, b, c in sustituciones], hay_eventos_pedido=True, datos=datos)
    return cuerpo({
        "estado": r.estado.value, "total": r.total, "fecha_entrega": r.fecha_entrega.isoformat() if r.fecha_entrega else None,
        "lineas": [{"sku": l.sku, "cantidad": l.cantidad, "precio_unitario": l.precio_unitario, "descuento_pct": l.descuento_pct, "subtotal": l.subtotal} for l in r.lineas],
        "sustituciones": [S(s.sku_solicitado, s.sku_entregado, int(s.cantidad)) for s in r.sustituciones],
        "pendientes": [], "motivos_revision": [m.value for m in r.motivos_revision],
    })


@pytest.fixture(scope="module")
def esperado_sust(datos):
    c = cuerpo_valido(datos, [("PH4", 3)], [("PHD", "PH4", 3)])
    return {k: v for k, v in c.items() if k not in ("cliente_id", "mensaje_cliente")}


# (caso, líneas obtenidas, sustituciones obtenidas, alterar, K2, K5)
KK = [
    ("KK-1", [("PH4", 2)], [("PHD", "PH4", 2)], None, 1, 0),  # ambas cantidades difieren: K2 cuenta 1
    ("KK-2", [("PH4", 3)], [("PHD", "PH4", 2)], None, 1, 0),  # la sustitución difiere; 2 <= 3 es válido en E1a
    ("KK-3", [("PH4", 2)], [("PHD", "PH4", 3)], None, 1, 1),  # la sustitución supera la línea: E1a la rechaza
    ("KK-4", [("PH4", 3)], [("PHD", "PH4", 3)], "subtotal", 0, 1),  # cantidades correctas; falla el recálculo
    ("KK-5", [("PH4", 3)], [], None, 0, 0),  # sin sustitución: incorrecto, pero sin K2 ni K5
]


@pytest.mark.parametrize(("nombre", "lineas", "sustituciones", "alterar", "k2_esperado", "k5_esperado"), KK, ids=[k[0] for k in KK])
def test_k2_frente_a_k5(datos, esperado_sust, nombre, lineas, sustituciones, alterar, k2_esperado, k5_esperado):
    if nombre == "KK-3":  # E1a no construye una respuesta incoherente: se arma a mano
        obtenido = cuerpo_valido(datos, [("PH4", 2)], [("PHD", "PH4", 2)])
        obtenido["sustituciones"][0]["cantidad"] = Decimal(3)
    else:
        obtenido = cuerpo_valido(datos, lineas, sustituciones)
    if alterar == "subtotal":
        obtenido["lineas"][0]["subtotal"] += Decimal("1.00")
    assert medir(esperado_sust, obtenido, anot(["zqxpapel"]))[0]["K2"] == k2_esperado
    assert (0 if recalculo_coincide(obtenido, ENTRADA, datos) else 1) == k5_esperado


def test_kk6_afinidad_de_tipo_para_k2():
    esp = esperado([L("GS6", 2)], [P("GS6", "GS2")])
    obtenido = cuerpo(esperado([L("GS6", 3)], [P("GS6")]))
    assert medir(esp, obtenido, anot(["zqxa"], ["zqxb"]))[0]["K2"] == 1


def test_k2_compara_la_sustitucion_por_su_sku_solicitado():
    esp = esperado([L("PH4", 3)], sustituciones=[S("PHD", "PH4", 3)])
    otro_solicitado = cuerpo(esperado([L("PH4", 3)], sustituciones=[S("ZZ9", "PH4", 1)]))
    assert medir(esp, otro_solicitado, anot(["zqxpapel"]))[0]["K2"] == 0  # otro solicitado: no es la misma sustitución


def test_c1_k1_cuenta_skus_distintos():
    esp = esperado([L("GS6")])
    obtenido = cuerpo(esperado([L("CL1")], sustituciones=[S("GS6", "CL1", 1)]))
    assert medir(esp, obtenido, anot(["gaseosa sol"]))[0]["K1"] == 1  # línea y sustitución con el mismo SKU: 1


# ---------------------------------------------------------------- evaluación completa


def _caso(esp):
    return Caso("Z01", "sintetico", ENTRADA, esp)


def test_respuesta_correcta(datos, esperado_sust):
    obtenido = cuerpo_valido(datos, [("PH4", 3)], [("PHD", "PH4", 3)])
    r = evaluar_caso(_caso(esperado_sust), anot(["zqxpapel"]), "OK", json.loads(a_json(obtenido)), obtenido, datos)
    assert r.correcto and r.valido and r.k5 == 0 and r.campos_distintos == ()


@pytest.mark.parametrize("codigo", ["HTTP_503", "HTTP_500", "TIMEOUT", "CONEXION", "JSON_INVALIDO"])
def test_invalidos_son_incorrectos_y_no_k5(datos, esperado_sust, codigo):
    r = evaluar_caso(_caso(esperado_sust), anot(["zqxpapel"]), codigo, None, None, datos)
    assert not r.correcto and not r.valido and r.codigo == codigo and r.k5 == 0


def test_respuesta_200_fuera_del_contrato_es_k5(datos, esperado_sust):
    obtenido = cuerpo_valido(datos, [("PH4", 3)], [("PHD", "PH4", 3)])
    normal = json.loads(a_json(obtenido))
    del normal["mensaje_cliente"]
    r = evaluar_caso(_caso(esperado_sust), anot(["zqxpapel"]), "OK", normal, obtenido, datos)
    assert r.codigo == "CONTRATO" and r.k5 == 1 and not r.correcto


def test_un_k_hace_incorrecto_el_caso_y_marca_el_critico(datos):
    esp = esperado(pendientes=[P(motivo=NE)])
    obtenido = cuerpo_valido(datos, [("CL1", 1)])
    r = evaluar_caso(_caso(esp), anot(["zqxkiwi"]), "OK", json.loads(a_json(obtenido)), obtenido, datos)
    assert r.k1 == 1 and r.k3 == 1 and not r.correcto and r.critico_con_error


# ---------------------------------------------------------------- K5: sustituciones en el recálculo


def test_k5_compara_las_sustituciones_con_las_de_e1a(datos, esperado_sust, monkeypatch):
    """La respuesta es coherente, pero E1a devuelve otras sustituciones: el recálculo no coincide."""
    obtenido = cuerpo_valido(datos, [("PH4", 3)], [("PHD", "PH4", 3)])
    assert recalculo_coincide(obtenido, ENTRADA, datos)
    original = criticos.cerrar_pedido
    alternativas = {
        "cantidad": (Sustitucion("PHD", "PH4", Decimal(2)),),
        "sin_sustitucion": (),
        "duplicada": (Sustitucion("PHD", "PH4", Decimal(3)),) * 2,
    }
    for nombre, sustituciones in alternativas.items():
        monkeypatch.setattr(criticos, "cerrar_pedido", lambda **k: dataclasses.replace(original(**k), sustituciones=sustituciones))
        assert not recalculo_coincide(obtenido, ENTRADA, datos), nombre
        r = evaluar_caso(_caso(esperado_sust), anot(["zqxpapel"]), "OK", json.loads(a_json(obtenido)), obtenido, datos)
        assert r.k5 == 1 and not r.correcto and r.campos_distintos == () and r.k2 == 0, nombre  # solo K5 lo detecta


def test_k5_sustituciones_iguales_como_multiconjunto_y_decimal(datos):
    obtenido = cuerpo_valido(datos, [("PH4", 3)], [("PHD", "PH4", 3)])
    obtenido["sustituciones"][0]["cantidad"] = Decimal("3.0")
    assert recalculo_coincide(obtenido, ENTRADA, datos)


@pytest.mark.parametrize(
    ("nombre", "sustitucion"),
    [
        ("supera_la_linea", ("PHD", "PH4", 4)),
        ("hacia_sku_sin_linea", ("PHD", "GS6", 1)),
        ("no_respaldada_por_el_catalogo", ("GS2", "PH4", 1)),
        ("cantidad_no_positiva", ("PHD", "PH4", 0)),
    ],
)
def test_k5_invariantes_de_sustituciones_invalidas(datos, esperado_sust, nombre, sustitucion):
    obtenido = cuerpo_valido(datos, [("PH4", 3)], [("PHD", "PH4", 3)])
    obtenido["sustituciones"] = [S(*sustitucion)]
    assert not recalculo_coincide(obtenido, ENTRADA, datos)
    r = evaluar_caso(_caso(esperado_sust), anot(["zqxpapel"]), "OK", json.loads(a_json(obtenido)), obtenido, datos)
    assert r.k5 == 1 and not r.correcto
