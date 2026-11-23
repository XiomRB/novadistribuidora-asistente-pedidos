"""Máquina de estados del pedido, motivos de revisión e invariantes del contrato.

Prioridad de condiciones (se evalúan en este orden):

1. Sin eventos de pedido                      -> fuera_de_alcance (no se evalúa crédito).
2. Hay pendientes                             -> requiere_revision (aunque no haya líneas).
3. Sin líneas (pedido vaciado)                -> fuera_de_alcance.
4. Crédito excedido                           -> requiere_revision.
5. Hay líneas, sin pendientes ni crédito      -> confirmado.

No existe combinación que confirme un pedido con pendientes o crédito excedido, ni que
convierta una consulta pura (sin eventos de pedido) en requiere_revision.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.dominio.errores import InvarianteViolada
from app.dominio.reglas import total as sumar
from app.dominio.resultado import Estado, Motivo, Pendiente, ResultadoCierre


def determinar_estado(*, hay_eventos_pedido: bool, hay_lineas: bool, hay_pendientes: bool, credito: bool) -> Estado:
    if not hay_eventos_pedido:
        return Estado.FUERA_DE_ALCANCE
    if hay_pendientes:
        return Estado.REQUIERE_REVISION
    if not hay_lineas:
        return Estado.FUERA_DE_ALCANCE
    if credito:
        return Estado.REQUIERE_REVISION
    return Estado.CONFIRMADO


def motivos_revision(pendientes: Iterable[Pendiente], credito: bool) -> tuple[Motivo, ...]:
    """Motivos únicos en orden de aparición; credito_excedido siempre al final."""
    vistos: list[Motivo] = []
    for pendiente in pendientes:
        if pendiente.motivo not in vistos:
            vistos.append(pendiente.motivo)
    if credito:
        vistos.append(Motivo.CREDITO_EXCEDIDO)
    return tuple(vistos)


def verificar_invariantes(r: ResultadoCierre) -> None:
    """Lanza InvarianteViolada si el resultado no cumple el contrato."""

    def fallar(mensaje: str) -> None:
        raise InvarianteViolada(mensaje)

    if r.total != sumar(linea.subtotal for linea in r.lineas):
        fallar("total distinto de la suma de subtotales")
    if (r.fecha_entrega is None) != (not r.lineas):
        fallar("fecha_entrega debe ser nula si y solo si no hay líneas")
    if Motivo.CREDITO_EXCEDIDO in {p.motivo for p in r.pendientes}:
        fallar("credito_excedido no puede ser motivo de un pendiente")
    sin_credito = {m for m in r.motivos_revision if m is not Motivo.CREDITO_EXCEDIDO}
    if sin_credito != {p.motivo for p in r.pendientes}:
        fallar("motivos_revision no coincide con los motivos de los pendientes")
    if len(set(r.motivos_revision)) != len(r.motivos_revision):
        fallar("motivos_revision con duplicados")
    if Motivo.CREDITO_EXCEDIDO in r.motivos_revision and r.motivos_revision[-1] is not Motivo.CREDITO_EXCEDIDO:
        fallar("credito_excedido debe ir al final")

    if r.estado is Estado.CONFIRMADO:
        if not r.lineas or r.motivos_revision or r.pendientes:
            fallar("confirmado exige líneas y ningún pendiente ni motivo")
    elif r.estado is Estado.REQUIERE_REVISION:
        if not r.motivos_revision:
            fallar("requiere_revision exige al menos un motivo")
    elif r.estado is Estado.FUERA_DE_ALCANCE:
        if r.lineas or r.pendientes or r.motivos_revision or r.sustituciones:
            fallar("fuera_de_alcance no lleva líneas, pendientes, motivos ni sustituciones")
        if r.total != 0 or r.fecha_entrega is not None:
            fallar("fuera_de_alcance exige total 0 y fecha nula")
