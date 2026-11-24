"""Pedido habitual ("lo de siempre"): selección determinista del último pedido entregado.

D53: se consideran los pedidos `entregado` con fecha de entrega <= fecha de recepción.
D70: gana la fecha mayor; con fechas iguales, el `pedido_id` mayor en orden natural y,
     si la clave natural empata, el `pedido_id` original (comparación por código Unicode).
     Los cancelados se excluyen antes de comparar. El orden de carga del historial no influye.
D73: dos o más pedidos del mismo cliente con el mismo `pedido_id` original (solo posible en
     un `Datos` construido a mano) lanzan `HistorialInconsistente`, aunque alguno esté
     cancelado. Nunca se elige uno. El mensaje no incluye identificadores.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import date

from app.datos.modelos import Datos, PedidoHistorico

_SEGMENTOS = re.compile(r"\d+|\D+")
_ESPACIOS = re.compile(r"\s+")

MENSAJE_INCONSISTENTE = "Historial con pedidos duplicados para un mismo cliente"


class HistorialInconsistente(ValueError):
    """Pedidos duplicados en el historial de un cliente.

    Los identificadores quedan solo como atributos para manejo interno; no forman parte de
    `args`, de `str()` ni de `repr()`.
    """

    def __init__(self, cliente_id: str, pedido_id: str):
        super().__init__(MENSAJE_INCONSISTENTE)
        self.cliente_id = cliente_id
        self.pedido_id = pedido_id


def normalizar_identificador(texto: str) -> str:
    """NFKD -> eliminar marcas de categoría Mn -> casefold -> espacios colapsados y recortados."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_marcas = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return _ESPACIOS.sub(" ", sin_marcas.casefold()).strip()


def clave_natural(texto: str) -> tuple[tuple[int, int | str], ...]:
    """Segmentos numéricos como (0, entero) y de texto como (1, texto normalizado)."""
    segmentos = []
    for segmento in _SEGMENTOS.findall(normalizar_identificador(texto)):
        if segmento.isdecimal():
            segmentos.append((0, int(segmento)))
        else:
            segmentos.append((1, segmento))
    return tuple(segmentos)


def clave_orden(pedido: PedidoHistorico) -> tuple:
    return (pedido.fecha_entrega, clave_natural(pedido.pedido_id), pedido.pedido_id)


def ultimo_entregado(datos: Datos, cliente_id: str, fecha_recepcion: date) -> PedidoHistorico | None:
    pedidos = datos.historial.get(cliente_id, ())
    repetidos = [pid for pid, n in Counter(p.pedido_id for p in pedidos).items() if n > 1]
    if repetidos:
        raise HistorialInconsistente(cliente_id, min(repetidos))
    candidatos = [p for p in pedidos if p.estado == "entregado" and p.fecha_entrega <= fecha_recepcion]
    return max(candidatos, key=clave_orden, default=None)
