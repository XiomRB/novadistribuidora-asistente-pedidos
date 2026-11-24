"""Límites de la interpretación (D56, D72).

`Interpretacion` (E1b-1) ya limita cada lista por separado (40 eventos, 20 consultas y 20
instrucciones rechazadas). Este módulo agrega el límite combinado de fragmentos sin
modificar el esquema:

    len(consultas) + len(instrucciones_rechazadas) <= 20

Punto de entrada único: `validar_interpretacion`. El orquestador (E1b-2b) y el intérprete
LLM (E3) deben validar siempre a través de él; no pueden omitir `validar_limites`.
"""

from __future__ import annotations

from typing import Any

from app.dominio.esquema_eventos import Interpretacion

MAX_FRAGMENTOS_COMBINADOS = 20


class LimitesExcedidos(ValueError):
    """La interpretación supera un límite combinado. El mensaje nunca incluye contenido."""


def validar_limites(interpretacion: Interpretacion) -> None:
    consultas = len(interpretacion.consultas)
    rechazadas = len(interpretacion.instrucciones_rechazadas)
    if consultas + rechazadas > MAX_FRAGMENTOS_COMBINADOS:
        raise LimitesExcedidos(
            f"{consultas} consultas + {rechazadas} instrucciones rechazadas = {consultas + rechazadas} "
            f"fragmentos; el máximo combinado es {MAX_FRAGMENTOS_COMBINADOS}"
        )


def validar_interpretacion(datos: Any, n_mensajes: int) -> Interpretacion:
    """Valida el esquema (E1b-1, con sus límites individuales) y luego el límite combinado."""
    interpretacion = Interpretacion.validar(datos, n_mensajes)
    validar_limites(interpretacion)
    return interpretacion
