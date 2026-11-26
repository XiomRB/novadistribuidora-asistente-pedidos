"""Comparación de una respuesta con la esperada (D33, D91).

- Contrato: las 9 claves del Anexo y el modelo `RespuestaPedido` (incluye `mensaje_cliente`:
  presente y de tipo texto; no entra en la exactitud).
- Exactitud principal: `estado`, `total`, `fecha_entrega`, `lineas`, `sustituciones`, `pendientes`
  (motivo y opciones) y `motivos_revision`. Colecciones como multiconjuntos (sin orden, con
  multiplicidad); las opciones de un pendiente también; importes y cantidades como `Decimal`.
- Aparte (no cambian la exactitud): texto de los pendientes (normalizado) y su clasificación.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.api.esquemas import RespuestaPedido
from app.datos.normalizacion import normalizar_texto

CLAVES_CONTRATO = frozenset(RespuestaPedido.model_fields)
CAMPOS_EXACTITUD = ("estado", "total", "fecha_entrega", "lineas", "sustituciones", "pendientes", "motivos_revision")


def cumple_contrato(cuerpo: Any) -> bool:
    """Respuesta 200 con JSON válido: ¿cumple el contrato? (sin conservar ningún dato)."""
    if not isinstance(cuerpo, dict) or set(cuerpo) != CLAVES_CONTRATO:
        return False
    try:
        RespuestaPedido.model_validate(cuerpo)
    except ValidationError:
        return False
    return True


@dataclass(frozen=True)
class Normalizada:
    estado: str
    total: Decimal
    fecha_entrega: str | None
    lineas: Counter
    sustituciones: Counter
    pendientes: Counter
    motivos_revision: Counter
    textos: Counter
    clasificacion: Counter


def _d(valor: Any) -> Decimal:
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def normalizar(cuerpo: Mapping[str, Any]) -> Normalizada:
    """`cuerpo`: respuesta o esperado con los números leídos como `Decimal`."""
    pendientes = Counter((p["motivo"], tuple(sorted(p["opciones"]))) for p in cuerpo["pendientes"])
    return Normalizada(
        estado=cuerpo["estado"],
        total=_d(cuerpo["total"]),
        fecha_entrega=cuerpo["fecha_entrega"],
        lineas=Counter((l["sku"], _d(l["cantidad"]), _d(l["precio_unitario"]), _d(l["descuento_pct"]), _d(l["subtotal"])) for l in cuerpo["lineas"]),
        sustituciones=Counter((s["sku_solicitado"], s["sku_entregado"], _d(s["cantidad"])) for s in cuerpo["sustituciones"]),
        pendientes=pendientes,
        motivos_revision=Counter(cuerpo["motivos_revision"]),
        textos=Counter(normalizar_texto(p["texto"]) for p in cuerpo["pendientes"]),
        clasificacion=pendientes,
    )


def campos_distintos(obtenido: Normalizada, esperado: Normalizada) -> tuple[str, ...]:
    """Nombres de los campos de la exactitud principal que no coinciden (nunca sus valores)."""
    return tuple(c for c in CAMPOS_EXACTITUD if getattr(obtenido, c) != getattr(esperado, c))


def textos_coinciden(obtenido: Normalizada, esperado: Normalizada) -> bool:
    return obtenido.textos == esperado.textos


def clasificacion_coincide(obtenido: Normalizada, esperado: Normalizada) -> bool:
    return obtenido.clasificacion == esperado.clasificacion
