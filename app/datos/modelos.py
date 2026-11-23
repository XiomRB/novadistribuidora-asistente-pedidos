"""Modelos inmutables de los datos de negocio.

`Cliente` solo contiene lo necesario para las reglas (minimización de datos): no incluye
nombre de la tienda, propietario ni municipio.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.dominio.errores import ProblemaDatos


@dataclass(frozen=True)
class Producto:
    sku: str
    nombre: str
    marca: str
    categoria: str
    presentacion: str
    unidad_venta: str
    unidades_por_empaque: Decimal
    precio: Decimal
    disponible: bool
    sustituto_sku: str | None


@dataclass(frozen=True)
class Alias:
    sku: str
    alias: str


@dataclass(frozen=True)
class Escala:
    categoria: str
    cantidad_minima: Decimal
    descuento_pct: Decimal


@dataclass(frozen=True)
class Cliente:
    cliente_id: str
    dias_visita: frozenset[int]
    limite_credito: Decimal
    saldo_pendiente: Decimal


@dataclass(frozen=True)
class LineaHistorica:
    sku: str
    cantidad: Decimal


@dataclass(frozen=True)
class PedidoHistorico:
    pedido_id: str
    cliente_id: str
    fecha_entrega: date
    estado: str
    lineas: tuple[LineaHistorica, ...]


@dataclass(frozen=True)
class Datos:
    productos: Mapping[str, Producto]
    alias: tuple[Alias, ...]
    escalas: Mapping[str, tuple[Escala, ...]]
    clientes: Mapping[str, Cliente]
    historial: Mapping[str, tuple[PedidoHistorico, ...]]
    advertencias: tuple[ProblemaDatos, ...] = ()
