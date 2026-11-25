"""Límite del cuerpo de la solicitud (D87): 1 MiB, contando los bytes **recibidos**.

Middleware ASGI propio (Starlette no trae uno):
1. Si `Content-Length` ya declara más que el límite, rechaza sin leer el cuerpo.
2. En cualquier caso cuenta los bytes de cada mensaje `http.request` y rechaza en cuanto el total
   supera el límite, aunque `Content-Length` haya declarado menos o falte (cuerpo por partes).
3. El rechazo ocurre **antes** de que la aplicación lea o analice el JSON: el cuerpo se acumula
   (como máximo el límite) y solo entonces se entrega a la aplicación.
4. Si el cliente se desconecta (`http.disconnect`) a mitad de la lectura, termina sin responder.
5. Respuesta: 422 con el formato de D78, en español y sin eco del contenido.

Nota: con Uvicorn y h11, un cuerpo más largo que su `Content-Length` declarado se rechaza en el
protocolo HTTP antes de llegar a la aplicación; este middleware cuenta los bytes de todos modos
(defensa en profundidad) y eso se prueba en el nivel ASGI.
"""

from __future__ import annotations

import json
from typing import Any

MAX_BYTES_CUERPO = 1_048_576  # D87: 1 MiB
MOTIVO_CUERPO_GRANDE = f"la solicitud supera el tamaño máximo de {MAX_BYTES_CUERPO} bytes"


def cuerpo_demasiado_grande() -> bytes:
    return json.dumps({"detail": [{"campo": "cuerpo", "motivo": MOTIVO_CUERPO_GRANDE}]}, ensure_ascii=False).encode("utf-8")


class LimiteCuerpo:
    def __init__(self, app: Any, max_bytes: int = MAX_BYTES_CUERPO):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        declarado = _content_length(scope)
        if declarado is not None and declarado > self.max_bytes:
            await _rechazar(send)
            return

        partes: list[bytes] = []
        recibidos = 0
        while True:
            mensaje = await receive()
            if mensaje["type"] == "http.disconnect":
                return  # el cliente se fue: no hay a quién responder
            if mensaje["type"] != "http.request":
                continue
            fragmento = mensaje.get("body", b"") or b""
            recibidos += len(fragmento)
            if recibidos > self.max_bytes:
                await _rechazar(send)  # no se lee nada más del cliente
                return
            partes.append(fragmento)
            if not mensaje.get("more_body", False):
                break

        cuerpo = b"".join(partes)
        entregado = False

        async def receive_con_cuerpo() -> dict[str, Any]:
            nonlocal entregado
            if not entregado:
                entregado = True
                return {"type": "http.request", "body": cuerpo, "more_body": False}
            return await receive()

        await self.app(scope, receive_con_cuerpo, send)


def _content_length(scope: dict[str, Any]) -> int | None:
    for nombre, valor in scope.get("headers", ()):
        if nombre.lower() == b"content-length":
            try:
                return int(valor)
            except ValueError:
                return None  # valor inválido: no se confía en él; se cuentan los bytes
    return None


async def _rechazar(send: Any) -> None:
    cuerpo = cuerpo_demasiado_grande()
    await send({
        "type": "http.response.start",
        "status": 422,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(cuerpo)).encode())],
    })
    await send({"type": "http.response.body", "body": cuerpo})
