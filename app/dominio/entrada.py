"""Entrada de un pedido: cliente, fecha y hora de recepción y mensajes originales."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

MAX_MENSAJES = 20
MAX_CARACTERES_MENSAJE = 2000


class EntradaInvalida(ValueError):
    """La entrada del pedido no cumple su contrato."""


@dataclass(frozen=True)
class EntradaPedido:
    """Datos de entrada del pedido.

    - `fecha_hora` no lleva zona horaria: representa la hora local de Guatemala (UTC-6,
      sin horario de verano) del último mensaje. Nunca se convierte ni se consulta el reloj.
    - `mensajes` son las cadenas originales; todas las posiciones (`Span`) se refieren a ellas.
    """

    cliente_id: str
    fecha_hora: datetime
    mensajes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.cliente_id, str) or not self.cliente_id.strip():
            raise EntradaInvalida("cliente_id debe ser un texto no vacío")
        if not isinstance(self.fecha_hora, datetime):
            raise EntradaInvalida("fecha_hora debe ser un datetime")
        if self.fecha_hora.tzinfo is not None:
            raise EntradaInvalida("fecha_hora no debe tener zona horaria (es hora local de Guatemala)")
        if isinstance(self.mensajes, str) or not isinstance(self.mensajes, Sequence):
            raise EntradaInvalida("mensajes debe ser una secuencia de textos")
        mensajes = tuple(self.mensajes)
        if not 1 <= len(mensajes) <= MAX_MENSAJES:
            raise EntradaInvalida(f"se requieren entre 1 y {MAX_MENSAJES} mensajes")
        for indice, mensaje in enumerate(mensajes):
            if not isinstance(mensaje, str):
                raise EntradaInvalida(f"el mensaje {indice} no es texto")
            if len(mensaje) > MAX_CARACTERES_MENSAJE:
                raise EntradaInvalida(f"el mensaje {indice} supera {MAX_CARACTERES_MENSAJE} caracteres")
        if not any(m.strip() for m in mensajes):
            raise EntradaInvalida("todos los mensajes están vacíos")
        object.__setattr__(self, "mensajes", mensajes)
