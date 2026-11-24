"""Sustituciones de productos agotados (después del plegado).

- Una línea activa cuyo SKU está agotado y tiene sustituto disponible entrega la misma
  cantidad de unidades de venta del sustituto.
- Si la línea del sustituto ya existe, las cantidades se suman en la posición de su primera
  aparición (como en el caso publicado de "lo mismo de la otra vez" con aceite).
- Se registra una sustitución por cada par (solicitado, entregado), acumulada.
- El resultado cumple las validaciones de `cerrar_pedido` (E1a): SKU disponibles y únicos, y
  suma sustituida por línea <= cantidad de la línea.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.datos.modelos import Datos
from app.dominio.diagnostico import DiagSustitucion
from app.dominio.plegado import Item
from app.dominio.resultado import LineaSolicitada, Sustitucion


class LineaNoEntregable(ValueError):
    """Una línea quedó con un SKU agotado sin sustituto disponible (no debería ocurrir: el
    plegado lo convierte antes en pendiente)."""


@dataclass(frozen=True)
class Salida:
    lineas: tuple[LineaSolicitada, ...]
    sustituciones: tuple[Sustitucion, ...]
    items_por_linea: tuple[str, ...]
    diagnostico: tuple[DiagSustitucion, ...]


def aplicar_sustituciones(lineas: Sequence[Item], datos: Datos) -> Salida:
    acumulado: dict[str, Decimal] = {}
    primer_item: dict[str, str] = {}
    por_par: dict[tuple[str, str], Decimal] = {}
    diagnostico: list[DiagSustitucion] = []
    for item in lineas:
        producto = datos.productos[item.sku]
        entregado = item.sku
        if not producto.disponible:
            sustituto = datos.productos.get(producto.sustituto_sku) if producto.sustituto_sku else None
            if sustituto is None or not sustituto.disponible:
                raise LineaNoEntregable("línea con producto agotado sin sustituto disponible")
            entregado = sustituto.sku
            por_par[(item.sku, entregado)] = por_par.get((item.sku, entregado), Decimal(0)) + item.cantidad
            diagnostico.append(DiagSustitucion(item.id, item.sku, entregado, f"{item.cantidad.normalize():f}"))
        acumulado[entregado] = acumulado.get(entregado, Decimal(0)) + item.cantidad
        primer_item.setdefault(entregado, item.id)
    return Salida(
        lineas=tuple(LineaSolicitada(sku, cantidad) for sku, cantidad in acumulado.items()),
        sustituciones=tuple(Sustitucion(sol, ent, cantidad) for (sol, ent), cantidad in por_par.items()),
        items_por_linea=tuple(primer_item[sku] for sku in acumulado),
        diagnostico=tuple(diagnostico),
    )
