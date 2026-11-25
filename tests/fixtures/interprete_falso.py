"""Intérpretes de prueba para la API (E2b). Solo existen en las pruebas: el intérprete de
producción hasta E3 es `InterpreteNoConfigurado` (D80)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.dominio.entrada import EntradaPedido
from app.interprete.base import InterpreteNoDisponible


class InterpreteFijo:
    """Devuelve siempre la misma interpretación (dict, JSON o modelo) y registra las llamadas."""

    def __init__(self, interpretacion: Any, disponible: bool = True):
        self.interpretacion = interpretacion
        self.disponible = disponible
        self.llamadas: list[EntradaPedido] = []

    def interpretar(self, entrada: EntradaPedido) -> Any:
        self.llamadas.append(entrada)
        return self.interpretacion

    def estado(self) -> tuple[bool, str | None]:
        return self.disponible, None if self.disponible else "intérprete de prueba no disponible"


class InterpretePorFuncion(InterpreteFijo):
    """Calcula la interpretación a partir de la entrada."""

    def __init__(self, funcion: Callable[[EntradaPedido], Any]):
        super().__init__(None)
        self.funcion = funcion

    def interpretar(self, entrada: EntradaPedido) -> Any:
        self.llamadas.append(entrada)
        return self.funcion(entrada)


class InterpreteQueFalla(InterpreteFijo):
    """Lanza la excepción indicada (por defecto, InterpreteNoDisponible)."""

    def __init__(self, error: BaseException | None = None):
        super().__init__(None)
        self.error = error or InterpreteNoDisponible("caído")

    def interpretar(self, entrada: EntradaPedido) -> Any:
        self.llamadas.append(entrada)
        raise self.error
