"""Utilidades para las pruebas del orquestador (E1b-2b) sobre el catálogo y el historial
sintéticos de E1b-1 y E1b-2a. No modifica ningún fixture existente."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.dominio.entrada import EntradaPedido
from app.dominio.pedido import Recursos, ResultadoPedido, procesar_pedido
from tests.fixtures.historial_e1b2 import MARTES, Contexto, cargar_contexto


def cargar_recursos(directorio: Path) -> tuple[Contexto, Recursos]:
    ctx = cargar_contexto(directorio)
    return ctx, Recursos.construir(ctx.datos, ctx.indice, ctx.lexico)


def frag(mensaje: int, texto: str) -> dict:
    return {"mensaje": mensaje, "texto": texto}


def procesar(
    recursos: Recursos,
    mensajes,
    eventos=(),
    cliente: str = "K04",
    fecha_hora: datetime = MARTES,
    consultas=(),
    rechazadas=(),
) -> ResultadoPedido:
    entrada = EntradaPedido(cliente, fecha_hora, tuple(mensajes))
    interpretacion = {
        "eventos": list(eventos),
        "consultas": list(consultas),
        "instrucciones_rechazadas": list(rechazadas),
    }
    return procesar_pedido(entrada, interpretacion, recursos.datos, recursos=recursos)


def lineas(resultado: ResultadoPedido) -> list[tuple[str, str]]:
    return [(l.sku, f"{l.cantidad.normalize():f}") for l in resultado.cierre.lineas]


def pendientes(resultado: ResultadoPedido) -> list[tuple[str, str, tuple[str, ...]]]:
    return [(p.motivo.value, p.texto, p.opciones) for p in resultado.cierre.pendientes]
