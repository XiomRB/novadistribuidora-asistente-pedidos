"""E2b: límite del cuerpo de 1 MiB (D87), contando los bytes recibidos.

Las pruebas en el nivel ASGI llaman al middleware con mensajes `http.request` construidos a mano:
así se prueba un `Content-Length` que declara menos de lo que llega (Uvicorn/h11 lo rechazaría
antes en el protocolo), cuerpos por partes y la desconexión del cliente.
"""

import asyncio
import json

import pytest

from app.api.limites_http import MAX_BYTES_CUERPO, MOTIVO_CUERPO_GRANDE, LimiteCuerpo
from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.interprete_falso import InterpreteFijo

MARCA = b"ZQXCUERPO"
LIMITE = MAX_BYTES_CUERPO
ERROR = {"detail": [{"campo": "cuerpo", "motivo": MOTIVO_CUERPO_GRANDE}]}


# ====================================================================== nivel ASGI


class AppEspia:
    """Aplicación ASGI que lee todo el cuerpo y registra lo que recibió."""

    def __init__(self):
        self.llamada = False
        self.cuerpo = b""

    async def __call__(self, scope, receive, send):
        self.llamada = True
        while True:
            mensaje = await receive()
            self.cuerpo += mensaje.get("body", b"")
            if not mensaje.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def ejecutar(partes, content_length=None, desconectar_despues=None):
    """Envía `partes` como mensajes http.request (o http.disconnect tras `desconectar_despues`)."""
    app = AppEspia()
    middleware = LimiteCuerpo(app)
    cabeceras = [(b"content-type", b"application/json")]
    if content_length is not None:
        cabeceras.append((b"content-length", str(content_length).encode()))
    scope = {"type": "http", "method": "POST", "path": RUTA, "headers": cabeceras}
    mensajes = []
    for k, parte in enumerate(partes):
        if desconectar_despues is not None and k == desconectar_despues:
            mensajes.append({"type": "http.disconnect"})
            break
        mensajes.append({"type": "http.request", "body": parte, "more_body": k < len(partes) - 1})
    leidos = []
    enviados = []

    async def receive():
        if len(leidos) < len(mensajes):
            leidos.append(mensajes[len(leidos)])
            return leidos[-1]
        return {"type": "http.disconnect"}

    async def send(mensaje):
        enviados.append(mensaje)

    asyncio.run(middleware(scope, receive, send))
    estado = next((m["status"] for m in enviados if m["type"] == "http.response.start"), None)
    cuerpo = b"".join(m.get("body", b"") for m in enviados if m["type"] == "http.response.body")
    return app, estado, cuerpo, len(leidos)


def partes_de(total, tamano=64 * 1024, relleno=b"a"):
    completas, resto = divmod(total, tamano)
    return [relleno * tamano] * completas + ([relleno * resto] if resto else [])


def test_asgi_cuerpo_exactamente_en_el_limite_no_se_rechaza():
    app, estado, _, _ = ejecutar(partes_de(LIMITE), content_length=LIMITE)
    assert estado == 200 and app.llamada and len(app.cuerpo) == LIMITE


def test_asgi_content_length_mayor_al_limite_se_rechaza_sin_leer():
    app, estado, cuerpo, leidos = ejecutar(partes_de(LIMITE + 1), content_length=LIMITE + 1)
    assert estado == 422 and json.loads(cuerpo) == ERROR and not app.llamada and leidos == 0


def test_asgi_content_length_menor_pero_cuerpo_real_mayor_se_rechaza():
    app, estado, cuerpo, _ = ejecutar(partes_de(LIMITE + 1), content_length=100)
    assert estado == 422 and json.loads(cuerpo) == ERROR and not app.llamada


def test_asgi_sin_content_length_por_partes_se_rechaza():
    app, estado, _, _ = ejecutar(partes_de(LIMITE + 1, tamano=10_000))
    assert estado == 422 and not app.llamada


def test_asgi_rechaza_en_cuanto_supera_y_no_lee_mas():
    partes = partes_de(LIMITE * 3)
    _, estado, _, leidos = ejecutar(partes, content_length=10)
    assert estado == 422 and leidos == LIMITE // (64 * 1024) + 1 < len(partes)


def test_asgi_por_partes_dentro_del_limite_se_entrega_completo():
    partes = [b'{"a":', b' "', b"x" * 1000, b'"}']
    app, estado, _, _ = ejecutar(partes)
    assert estado == 200 and app.cuerpo == b"".join(partes)


def test_asgi_desconexion_a_mitad_de_la_lectura():
    app, estado, cuerpo, _ = ejecutar(partes_de(200_000, tamano=50_000), desconectar_despues=2)
    assert estado is None and cuerpo == b"" and not app.llamada  # termina sin responder


def test_asgi_content_length_invalido_no_se_usa_y_se_cuentan_los_bytes():
    app, estado, _, _ = ejecutar(partes_de(LIMITE + 1), content_length="no-numero")
    assert estado == 422 and not app.llamada


def test_asgi_el_error_no_incluye_el_contenido():
    _, estado, cuerpo, _ = ejecutar(partes_de(LIMITE + 1, relleno=MARCA), content_length=50)
    assert estado == 422 and MARCA not in cuerpo


def test_asgi_otros_tipos_de_scope_pasan_sin_cambios():
    llamadas = []

    async def app(scope, receive, send):
        llamadas.append(scope["type"])

    asyncio.run(LimiteCuerpo(app)({"type": "lifespan"}, None, None))
    assert llamadas == ["lifespan"]


# ====================================================================== por HTTP (TestClient)


def json_de_tamano(total):
    """Solicitud válida rellenada con espacios hasta `total` bytes (el JSON admite espacios)."""
    base = json.dumps(solicitud(["2 de frijol negro"])).encode()
    return base[:-1] + b" " * (total - len(base)) + b"}"


def test_http_cuerpo_valido_en_el_limite_se_procesa(cliente_con):
    interprete = InterpreteFijo({"eventos": []})
    with cliente_con(interprete) as cliente:
        cuerpo = json_de_tamano(LIMITE)
        assert len(cuerpo) == LIMITE
        respuesta = cliente.post(RUTA, content=cuerpo, headers={"content-type": "application/json"})
    assert respuesta.status_code == 200 and len(interprete.llamadas) == 1


def test_http_cuerpo_valido_de_peor_caso_se_acepta(cliente_con):
    pesado = solicitud(["👍" * 2000] * 20, cliente="👍" * 64)
    cuerpo = json.dumps(pesado, separators=(",", ":")).encode()  # emojis escapados: el peor caso válido calculado
    assert len(cuerpo) == 480_890
    interprete = InterpreteFijo({"eventos": []})
    with cliente_con(interprete) as cliente:
        respuesta = cliente.post(RUTA, content=cuerpo, headers={"content-type": "application/json"})
    assert respuesta.status_code == 404  # pasa el límite y el esquema; el cliente no existe


def test_http_un_byte_de_mas_se_rechaza_antes_del_json(cliente_con):
    interprete = InterpreteFijo({"eventos": []})
    with cliente_con(interprete) as cliente:
        respuesta = cliente.post(RUTA, content=json_de_tamano(LIMITE + 1), headers={"content-type": "application/json"})
    assert respuesta.status_code == 422 and respuesta.json() == ERROR and interprete.llamadas == []


def test_http_cuerpo_grande_e_invalido_da_el_error_de_tamano(cliente_con):
    # Prueba que el rechazo ocurre antes de analizar el JSON: no es "el cuerpo no es un JSON válido".
    with cliente_con() as cliente:
        respuesta = cliente.post(RUTA, content=b"{" + MARCA * 200_000, headers={"content-type": "application/json"})
    assert respuesta.status_code == 422 and respuesta.json() == ERROR and MARCA not in respuesta.content


def test_http_sin_content_length_por_partes(cliente_con):
    def partes():
        for _ in range(17):
            yield b"a" * 65_536

    with cliente_con() as cliente:
        respuesta = cliente.post(RUTA, content=partes(), headers={"content-type": "application/json"})
    assert respuesta.status_code == 422 and respuesta.json() == ERROR


def test_http_solicitud_normal_no_cambia(cliente_con):
    with cliente_con(InterpreteFijo({"eventos": []})) as cliente:
        assert cliente.post(RUTA, json=solicitud()).status_code == 200
