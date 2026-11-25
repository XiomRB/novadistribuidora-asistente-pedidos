"""Utilidades de las pruebas de la API (E2b)."""

from __future__ import annotations

RUTA = "/v1/pedidos/interpretar"
MARTES = "2026-12-01T10:00"


def solicitud(mensajes=("hola",), cliente="K04", fecha_hora=MARTES, **extra) -> dict:
    return {"cliente_id": cliente, "fecha_hora": fecha_hora, "mensajes": list(mensajes), **extra}
