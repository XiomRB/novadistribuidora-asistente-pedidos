"""Intérpretes de los mensajes. En E2 solo existe la interfaz y el intérprete no configurado."""

from app.interprete.base import MOTIVO_NO_CONFIGURADO, Interprete, InterpreteNoConfigurado, InterpreteNoDisponible

__all__ = ["MOTIVO_NO_CONFIGURADO", "Interprete", "InterpreteNoConfigurado", "InterpreteNoDisponible"]
