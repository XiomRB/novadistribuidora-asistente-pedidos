"""Cliente HTTP del evaluador: una sola petición por caso, timeout fijo y sin reintentos.

Devuelve un código fijo (OK, HTTP_<n>, TIMEOUT, CONEXION, JSON_INVALIDO) y el cuerpo analizado dos
veces en memoria (números normales para el contrato y `Decimal` para la comparación). Nunca guarda
ni registra la petición, la respuesta ni el texto de una excepción.

Hito 2: cada petición mide su latencia (ms) y puede llevar encabezados de correlación
(`X-Evaluacion-*`) para asociar la traza del servidor a la ejecución y al caso. Los encabezados no
forman parte del contrato JSON: el cuerpo enviado no cambia.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

RUTA = "/v1/pedidos/interpretar"


@dataclass(frozen=True)
class RespuestaHttp:
    codigo: str
    cuerpo: Any = None  # contrato
    cuerpo_decimal: Any = None  # comparación
    latencia_ms: int | None = None


class ClienteEvaluacion:
    def __init__(self, base_url: str | None = None, timeout: float = 30, cliente: httpx.Client | None = None):
        if cliente is None:
            cliente = httpx.Client(
                base_url=base_url or "", timeout=httpx.Timeout(timeout),
                transport=httpx.HTTPTransport(retries=0), follow_redirects=False,
            )
        self._cliente = cliente
        self.peticiones = 0

    def enviar(self, entrada: Mapping[str, Any], correlacion: Mapping[str, str] | None = None) -> RespuestaHttp:
        cuerpo = {"cliente_id": entrada["cliente_id"], "fecha_hora": entrada["fecha_hora"], "mensajes": list(entrada["mensajes"])}
        encabezados = {f"X-Evaluacion-{k.capitalize()}": v for k, v in (correlacion or {}).items()}
        self.peticiones += 1
        inicio = time.perf_counter()
        ms = lambda: round((time.perf_counter() - inicio) * 1000)  # noqa: E731
        try:
            respuesta = self._cliente.post(RUTA, json=cuerpo, headers=encabezados)
        except httpx.TimeoutException:
            return RespuestaHttp("TIMEOUT", latencia_ms=ms())
        except httpx.HTTPError:
            return RespuestaHttp("CONEXION", latencia_ms=ms())
        latencia = ms()
        if respuesta.status_code != 200:
            return RespuestaHttp(f"HTTP_{respuesta.status_code}", latencia_ms=latencia)
        try:
            texto = respuesta.content.decode("utf-8")
            return RespuestaHttp("OK", json.loads(texto), json.loads(texto, parse_float=Decimal, parse_int=Decimal), latencia)
        except (UnicodeDecodeError, ValueError):
            return RespuestaHttp("JSON_INVALIDO", latencia_ms=latencia)

    def cerrar(self) -> None:
        self._cliente.close()
