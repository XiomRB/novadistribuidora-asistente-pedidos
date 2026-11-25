"""Interfaz del intérprete (E2b). El intérprete con LLM llega en E3.

Un intérprete convierte la entrada de un pedido en una interpretación estructurada (eventos,
consultas e instrucciones rechazadas). Nunca calcula nada comercial. Lo que devuelva se valida
siempre con `validar_interpretacion` (D72) antes de llegar al motor.

En producción, hasta E3, el intérprete es `InterpreteNoConfigurado` (D80): toda solicitud válida
responde 503 y `/health` informa `degradado`. Los intérpretes falsos y el de referencia existen
solo en las pruebas.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Interpretacion

MOTIVO_NO_CONFIGURADO = "intérprete no configurado"


class InterpreteNoDisponible(Exception):
    """El intérprete no pudo producir una interpretación (no configurado, caído o con error).
    La API responde 503 con `Retry-After`. El mensaje nunca incluye contenido de la solicitud."""


@runtime_checkable
class Interprete(Protocol):
    def interpretar(self, entrada: EntradaPedido) -> Interpretacion | dict[str, Any] | str | bytes:
        """Interpretación de los mensajes. Lanza `InterpreteNoDisponible` si no puede hacerlo."""
        ...

    def estado(self) -> tuple[bool, str | None]:
        """(disponible, motivo si no lo está), para `/health`."""
        ...


class InterpreteNoConfigurado:
    """Intérprete de producción en E2: no interpreta nada (D80)."""

    def interpretar(self, entrada: EntradaPedido) -> Interpretacion:
        raise InterpreteNoDisponible(MOTIVO_NO_CONFIGURADO)

    def estado(self) -> tuple[bool, str | None]:
        return False, MOTIVO_NO_CONFIGURADO
