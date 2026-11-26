"""Cliente HTTP del evaluador: una sola petición por caso, timeout fijo y sin reintentos.

Devuelve un código fijo (OK, HTTP_<n>, TIMEOUT, CONEXION, JSON_INVALIDO) y el cuerpo analizado dos
veces en memoria (números normales para el contrato y `Decimal` para la comparación). Nunca guarda
ni registra la petición, la respuesta ni el texto de una excepción.
"""

from __future__ import annotations

import json
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


class ClienteEvaluacion:
    def __init__(self, base_url: str | None = None, timeout: float = 30, cliente: httpx.Client | None = None):
        if cliente is None:
            cliente = httpx.Client(
                base_url=base_url or "", timeout=httpx.Timeout(timeout),
                transport=httpx.HTTPTransport(retries=0), follow_redirects=False,
            )
        self._cliente = cliente
        self.peticiones = 0

    def enviar(self, entrada: Mapping[str, Any]) -> RespuestaHttp:
        cuerpo = {"cliente_id": entrada["cliente_id"], "fecha_hora": entrada["fecha_hora"], "mensajes": list(entrada["mensajes"])}
        self.peticiones += 1
        try:
            respuesta = self._cliente.post(RUTA, json=cuerpo)
        except httpx.TimeoutException:
            return RespuestaHttp("TIMEOUT")
        except httpx.HTTPError:
            return RespuestaHttp("CONEXION")
        if respuesta.status_code != 200:
            return RespuestaHttp(f"HTTP_{respuesta.status_code}")
        try:
            texto = respuesta.content.decode("utf-8")
            return RespuestaHttp("OK", json.loads(texto), json.loads(texto, parse_float=Decimal, parse_int=Decimal))
        except (UnicodeDecodeError, ValueError):
            return RespuestaHttp("JSON_INVALIDO")

    def cerrar(self) -> None:
        self._cliente.close()
