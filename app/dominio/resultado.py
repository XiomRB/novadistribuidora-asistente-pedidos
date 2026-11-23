"""Tipos del resultado de un pedido (equivalentes al contrato del Anexo)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class Estado(StrEnum):
    CONFIRMADO = "confirmado"
    REQUIERE_REVISION = "requiere_revision"
    FUERA_DE_ALCANCE = "fuera_de_alcance"


class Motivo(StrEnum):
    PRODUCTO_AMBIGUO = "producto_ambiguo"
    PRODUCTO_NO_EXISTE = "producto_no_existe"
    AGOTADO_SIN_SUSTITUTO = "agotado_sin_sustituto"
    CANTIDAD_NO_CONVERTIBLE = "cantidad_no_convertible"
    CREDITO_EXCEDIDO = "credito_excedido"


MOTIVOS_DE_PENDIENTE = frozenset(m for m in Motivo if m is not Motivo.CREDITO_EXCEDIDO)


@dataclass(frozen=True)
class LineaSolicitada:
    """Línea ya resuelta (sku disponible y cantidad entera en unidades de venta)."""

    sku: str
    cantidad: Decimal


@dataclass(frozen=True)
class Linea:
    sku: str
    cantidad: Decimal
    precio_unitario: Decimal
    descuento_pct: Decimal
    subtotal: Decimal


@dataclass(frozen=True)
class Sustitucion:
    sku_solicitado: str
    sku_entregado: str
    cantidad: Decimal


@dataclass(frozen=True)
class Pendiente:
    motivo: Motivo
    texto: str
    opciones: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.motivo not in MOTIVOS_DE_PENDIENTE:
            raise ValueError(f"Motivo no permitido en un pendiente: {self.motivo}")


@dataclass(frozen=True)
class ResultadoCierre:
    cliente_id: str
    estado: Estado
    lineas: tuple[Linea, ...]
    total: Decimal
    fecha_entrega: date | None
    sustituciones: tuple[Sustitucion, ...]
    pendientes: tuple[Pendiente, ...]
    motivos_revision: tuple[Motivo, ...]
