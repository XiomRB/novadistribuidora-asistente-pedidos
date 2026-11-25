"""Formato de los errores de la API (E2a): D78, D79, D82 y D18.

- 422 (D78): `{"detail": [{"campo": ..., "motivo": ...}]}`, en español y **sin eco**: nunca se
  copia el valor recibido (ni `input` ni `ctx` de Pydantic) a la respuesta.
- 404 (D79): sin el `cliente_id`.
- 503 (D18, D80): mensaje fijo y `Retry-After: 10` en **todos** los 503.
- 500 (D82): genérico, sin identificadores.

Este módulo solo construye cuerpos y encabezados; los manejadores de FastAPI se registran en
E2b.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# D18: valor constante de Retry-After (segundos) en todos los 503. Los fallos de interpretación
# de E3 serán transitorios (proveedor, timeouts); reintentar de inmediato tiende a fallar otra vez
# y duplica el costo. Con el intérprete no configurado (E2) reintentar no sirve, pero se usa el
# mismo valor por uniformidad.
RETRY_AFTER_SEGUNDOS = 10

DETALLE_404 = "Cliente no encontrado"
DETALLE_503 = "No fue posible interpretar el pedido; intente de nuevo"
DETALLE_500 = "Error interno"

# Prefijo de los errores propios del contrato: su mensaje ya está en español y nunca incluye el
# valor recibido.
PREFIJO_CONTRATO = "contrato_"

MOTIVOS_PYDANTIC: Mapping[str, str] = {
    "missing": "es obligatorio",
    "string_type": "debe ser un texto",
    "list_type": "debe ser una lista de textos",
    "json_invalid": "el cuerpo no es un JSON válido",
    "json_type": "el cuerpo no es un JSON válido",
    "model_type": "el cuerpo debe ser un objeto JSON",
    "model_attributes_type": "el cuerpo debe ser un objeto JSON",
    "dict_type": "el cuerpo debe ser un objeto JSON",
}
MOTIVO_GENERICO = "valor inválido"
CAMPO_CUERPO = "cuerpo"


def _campo(loc: Sequence[Any]) -> str:
    partes = list(loc)
    if partes and partes[0] == "body":
        partes = partes[1:]
    texto = ""
    for parte in partes:
        if isinstance(parte, int):
            texto += f"[{parte}]"
        else:
            texto += ("." if texto else "") + str(parte)
    return texto or CAMPO_CUERPO


def _motivo(error: Mapping[str, Any]) -> str:
    tipo = str(error.get("type", ""))
    if tipo.startswith(PREFIJO_CONTRATO):
        return str(error.get("msg", MOTIVO_GENERICO))
    return MOTIVOS_PYDANTIC.get(tipo, MOTIVO_GENERICO)


def detalle_validacion(errores: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Errores de Pydantic o FastAPI -> lista D78. Solo usa `loc` y `type` (y el mensaje de los
    errores propios del contrato); nunca `input` ni `ctx`."""
    detalle: list[dict[str, str]] = []
    for error in errores:
        campo = _campo(error.get("loc", ()))
        if error.get("type") in ("json_invalid", "json_type", "model_type", "model_attributes_type", "dict_type"):
            campo = CAMPO_CUERPO
        entrada = {"campo": campo, "motivo": _motivo(error)}
        if entrada not in detalle:
            detalle.append(entrada)
    return detalle or [{"campo": CAMPO_CUERPO, "motivo": MOTIVO_GENERICO}]


def cuerpo_422(errores: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, str]]]:
    return {"detail": detalle_validacion(errores)}


def cuerpo_404() -> dict[str, str]:
    return {"detail": DETALLE_404}


def cuerpo_503() -> dict[str, str]:
    return {"detail": DETALLE_503}


def encabezados_503() -> dict[str, str]:
    return {"Retry-After": str(RETRY_AFTER_SEGUNDOS)}


def cuerpo_500() -> dict[str, str]:
    return {"detail": DETALLE_500}
