"""E2b: errores HTTP (D78, D79, D80, D82, D83, D18).

Orden: 422 (solicitud) -> 404 (cliente, sin llamar al intérprete) -> 503 (intérprete). Todos los
503 llevan `Retry-After: 10`. Ningún error incluye el valor recibido, el texto de los mensajes,
el `cliente_id` ni detalles internos.
"""

import pytest

import app.servicio as servicio
from app.api.esquemas import SolicitudPedido
from app.dominio.entrada import EntradaInvalida
from app.dominio.habitual import HistorialInconsistente
from app.interprete.base import InterpreteNoDisponible
from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpreteFijo, InterpreteQueFalla

MARCA = "ZQXHTTP"
CUERPO_503 = {"detail": "No fue posible interpretar el pedido; intente de nuevo"}
VALIDA = {"eventos": [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")]}


def es_503(respuesta):
    return respuesta.status_code == 503 and respuesta.json() == CUERPO_503 and respuesta.headers["retry-after"] == "10"


# ====================================================================== 422


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"fecha_hora": "2026-12-01T10:00", "mensajes": ["hola"]},
        {"cliente_id": "K04", "mensajes": ["hola"]},
        {"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00"},
        solicitud(cliente=""),
        solicitud(cliente="K" * 65),
        solicitud(fecha_hora="2026-12-01 10:00"),
        solicitud(fecha_hora="2026-12-01T10:00:00"),
        solicitud(fecha_hora="2026-02-31T10:00"),
        solicitud(mensajes=[]),
        solicitud(mensajes=["", "  "]),
        solicitud(mensajes=["hola"] * 21),
        solicitud(mensajes=["x" * 2001]),
    ],
    ids=["sin_cliente", "sin_fecha", "sin_mensajes", "cliente_vacio", "cliente_65", "fecha_con_espacio", "fecha_con_segundos",
         "fecha_imposible", "lista_vacia", "todos_en_blanco", "21_mensajes", "2001_caracteres"],
)
def test_422_en_espanol_sin_llamar_al_interprete(cliente_con, cuerpo):
    interprete = InterpreteFijo(VALIDA)
    with cliente_con(interprete) as cliente:
        respuesta = cliente.post(RUTA, json=cuerpo)
    assert respuesta.status_code == 422 and interprete.llamadas == []
    detalle = respuesta.json()["detail"]
    assert detalle and all(set(e) == {"campo", "motivo"} for e in detalle)


@pytest.mark.parametrize("contenido", [b"no es json", b'{"cliente_id": "K04",', b"[1, 2]", b"null", b""])
def test_422_cuerpo_invalido(cliente_con, contenido):
    with cliente_con(InterpreteFijo(VALIDA)) as cliente:
        respuesta = cliente.post(RUTA, content=contenido, headers={"content-type": "application/json"})
    assert respuesta.status_code == 422
    assert {e["campo"] for e in respuesta.json()["detail"]} == {"cuerpo"}


def test_422_sin_eco(cliente_con):
    cuerpo = {"cliente_id": MARCA * 30, "fecha_hora": f"{MARCA}", "mensajes": [f"{MARCA} " * 600, {"x": MARCA}]}
    with cliente_con(InterpreteFijo(VALIDA)) as cliente:
        respuesta = cliente.post(RUTA, json=cuerpo)
    assert respuesta.status_code == 422 and MARCA not in respuesta.text


def test_entrada_invalida_residual_responde_422(cliente_con, monkeypatch):
    # No debería ocurrir (el esquema aplica los mismos límites que EntradaPedido); si ocurre, es 422.
    def falla(self):
        raise EntradaInvalida(f"mensaje con {MARCA}")

    monkeypatch.setattr(SolicitudPedido, "a_entrada", falla)
    with cliente_con(InterpreteFijo(VALIDA)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud())
    assert respuesta.status_code == 422 and MARCA not in respuesta.text


# ====================================================================== orden 422 -> 404 -> 503 (D83)


def test_solicitud_invalida_y_cliente_inexistente_da_422(cliente_con):
    with cliente_con(InterpreteQueFalla()) as cliente:
        assert cliente.post(RUTA, json=solicitud(cliente="NO-EXISTE", fecha_hora="mal")).status_code == 422


@pytest.mark.parametrize("cliente_id", ["NO-EXISTE", "k04", " K04", "K04 ", MARCA])
def test_404_sin_cliente_id_y_sin_llamar_al_interprete(cliente_con, cliente_id):
    interprete = InterpreteQueFalla()
    with cliente_con(interprete) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(cliente=cliente_id))
    assert respuesta.status_code == 404 and respuesta.json() == {"detail": "Cliente no encontrado"}
    assert interprete.llamadas == [] and cliente_id.strip() not in respuesta.text


def test_cliente_inexistente_con_interprete_no_configurado_da_404(cliente_con):
    with cliente_con() as cliente:
        assert cliente.post(RUTA, json=solicitud(cliente="NO-EXISTE")).status_code == 404


# ====================================================================== 503 (D18, D80)


def test_produccion_sin_interprete_configurado_da_503(cliente_con):
    with cliente_con() as cliente:  # el intérprete por defecto es InterpreteNoConfigurado
        assert es_503(cliente.post(RUTA, json=solicitud()))


@pytest.mark.parametrize("error", [InterpreteNoDisponible("caído"), RuntimeError(f"fallo con {MARCA}"), TimeoutError(), ValueError(MARCA)])
def test_cualquier_fallo_del_interprete_da_503(cliente_con, error):
    with cliente_con(InterpreteQueFalla(error)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud())
    assert es_503(respuesta) and MARCA not in respuesta.text


@pytest.mark.parametrize(
    "interpretacion",
    [
        {"eventos": [{"id": "e2", "mensaje": 0, "tipo": "agregar", "texto": "x"}]},  # id no consecutivo
        {"eventos": [ev(1, 3, "agregar", "hola", producto="frijol negro")]},  # mensaje inexistente
        {"eventos": [ev(1, 0, "corregir", "hola", cantidad="2", ref="e5")]},  # ref hacia adelante
        {"consultas": [{"mensaje": 0, "texto": "hola"}] * 11, "instrucciones_rechazadas": [{"mensaje": 0, "texto": "hola"}] * 10},  # D72
        {"eventos": [ev(1, 0, "agregar", "hola", precio="1")]},  # campo comercial no permitido
        "esto no es JSON",
        12345,
        None,
        {"eventos": "no es lista"},
    ],
    ids=["id_no_consecutivo", "mensaje_inexistente", "ref_adelante", "21_fragmentos", "campo_extra", "texto", "numero", "nulo", "eventos_no_lista"],
)
def test_interpretacion_invalida_da_503(cliente_con, interpretacion):
    with cliente_con(InterpreteFijo(interpretacion)) as cliente:
        assert es_503(cliente.post(RUTA, json=solicitud()))


def test_todos_los_503_usan_el_mismo_retry_after(cliente_con):
    respuestas = []
    for interprete in (None, InterpreteQueFalla(), InterpreteFijo("inválida")):
        with cliente_con(interprete) as cliente:
            respuestas.append(cliente.post(RUTA, json=solicitud()))
    assert {r.headers["retry-after"] for r in respuestas} == {"10"} and all(es_503(r) for r in respuestas)


# ====================================================================== 500 (D82)


@pytest.mark.parametrize("error", [HistorialInconsistente(MARCA, MARCA), RuntimeError(f"detalle {MARCA}"), KeyError(MARCA)])
def test_error_interno_da_500_generico(cliente_con, monkeypatch, error):
    def falla(*args, **kwargs):
        raise error

    monkeypatch.setattr(servicio, "procesar_pedido", falla)
    with cliente_con(InterpreteFijo(VALIDA)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(["2 de frijol negro"]))
    assert respuesta.status_code == 500 and respuesta.json() == {"detail": "Error interno"}
    assert MARCA not in respuesta.text and "Traceback" not in respuesta.text


def test_500_ante_un_error_inesperado_del_servicio(cliente_con, monkeypatch):
    def falla(self, solicitud):
        raise ZeroDivisionError(MARCA)

    monkeypatch.setattr(servicio.ServicioPedidos, "atender", falla)
    with cliente_con(InterpreteFijo(VALIDA)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud())
    assert respuesta.status_code == 500 and respuesta.json() == {"detail": "Error interno"} and MARCA not in respuesta.text
