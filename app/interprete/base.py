"""Interfaz del intérprete (E2b) y estados de disponibilidad (hito 1).

Un intérprete convierte la entrada de un pedido en una interpretación estructurada (eventos,
consultas e instrucciones rechazadas). Nunca calcula nada comercial. Lo que devuelva se valida
siempre con `validar_interpretacion` (D72) antes de llegar al motor.

Estados que informa `estado()` a `/health` (motivos fijos, sin datos sensibles):
- `interprete_no_configurado`: falta la clave o el modelo; toda solicitud responde 503.
- `conectividad_no_verificada`: configurado, sin ninguna invocación exitosa aún.
- `error_al_invocar_modelo`: la última invocación falló (error del proveedor o salida inválida).
- operativo: la última invocación terminó bien con una interpretación válida.
`/health` nunca llama al proveedor: solo lee este estado.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Interpretacion

MOTIVO_NO_CONFIGURADO = "interprete_no_configurado"
MOTIVO_NO_VERIFICADO = "conectividad_no_verificada"
MOTIVO_ERROR_INVOCACION = "error_al_invocar_modelo"


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
    """Intérprete sin configuración (falta la clave o el modelo): no interpreta nada (D80)."""

    def interpretar(self, entrada: EntradaPedido) -> Interpretacion:
        raise InterpreteNoDisponible(MOTIVO_NO_CONFIGURADO)

    def estado(self) -> tuple[bool, str | None]:
        return False, MOTIVO_NO_CONFIGURADO
