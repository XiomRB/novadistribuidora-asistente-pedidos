"""Clasificación del mensaje (sección 3.1 del plan corregido de E1b).

Distingue una consulta pura de un pedido vaciado sin cambiar el cierre de E1a: el
orquestador clasifica antes de cerrar y de ahí salen `hay_eventos_pedido` y el mensaje.

| Clasificación      | Condición                                                          | hay_eventos_pedido |
|--------------------|--------------------------------------------------------------------|--------------------|
| CONSULTA           | Ningún evento efectivo y ningún pendiente por omisión              | False              |
| PEDIDO_CANCELADO   | Algún evento efectivo creó ítems y al final no queda ninguno       | True (listas vacías) |
| SIN_EFECTO         | Hubo eventos efectivos, pero ninguno creó ítems y no queda nada    | True (listas vacías) |
| PEDIDO             | Quedan líneas o pendientes                                         | True               |

Un evento efectivo es un evento de pedido que sigue en pie después del anclaje y del filtro
de consultas puras (no `SIN_ANCLA` ni `DESCARTADO_CONSULTA`).
"""

from __future__ import annotations

from enum import StrEnum


class Clasificacion(StrEnum):
    CONSULTA = "CONSULTA"
    PEDIDO_CANCELADO = "PEDIDO_CANCELADO"
    SIN_EFECTO = "SIN_EFECTO"
    PEDIDO = "PEDIDO"

    @property
    def hay_eventos_pedido(self) -> bool:
        return self is not Clasificacion.CONSULTA


def clasificar(*, eventos_efectivos: int, creo_items: bool, quedan_items: bool, pendientes_omision: int) -> Clasificacion:
    if quedan_items or pendientes_omision:
        return Clasificacion.PEDIDO
    if eventos_efectivos == 0:
        return Clasificacion.CONSULTA
    if creo_items:
        return Clasificacion.PEDIDO_CANCELADO
    return Clasificacion.SIN_EFECTO
