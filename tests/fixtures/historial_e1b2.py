"""Historial sintético para el catálogo de E1b-1 y utilidades para las pruebas de E1b-2a.

No modifica ningún fixture existente: usa `catalogo_e1b.escribir(reemplazos=...)`.

Clientes (de los datos sintéticos de E1a): K01 (lunes y jueves), K02 (saldo = límite),
K03 (saldo > límite), K04 (lunes, miércoles y viernes; saldo 0).

Historial:
- K01: P-0009 entregado (02-nov), P-0010 entregado (09-nov, con agotados y un SKU que ya no
  existe), P-0011 cancelado (16-nov).
- K02: P-9 y P-10 entregados el mismo día (gana P-10 por orden natural) y P-11 cancelado
  el mismo día con identificador mayor.
- K03: solo un pedido cancelado (sin historial entregado).
- K04: P-20 entregado el 01-dic (mismo día de la recepción de prueba) y P-21 entregado el
  05-dic (posterior a la recepción).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.datos.carga import cargar_datos
from app.datos.modelos import Datos
from app.dominio.atributos import VocabularioAtributos
from app.dominio.catalogo import IndiceCatalogo
from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Interpretacion
from app.dominio.plegado import ResultadoPlegado, plegar
from app.dominio.sustitucion import Salida, aplicar_sustituciones
from app.dominio.texto import anclar
from app.dominio.unidades import LexicoUnidades
from tests.fixtures import catalogo_e1b

MARTES = datetime(2026, 12, 1, 10, 0)

FILAS = [
    ("P-0009", "K01", datetime(2026, 11, 2), "GS6", 2, "entregado"),
    ("P-0009", "K01", datetime(2026, 11, 2), "FN1", 1, "entregado"),
    ("P-0010", "K01", datetime(2026, 11, 9), "GS3", 3, "entregado"),
    ("P-0010", "K01", datetime(2026, 11, 9), "AC2", 1, "entregado"),
    ("P-0010", "K01", datetime(2026, 11, 9), "PC2", 2, "entregado"),
    ("P-0010", "K01", datetime(2026, 11, 9), "GC1", 1, "entregado"),
    ("P-0010", "K01", datetime(2026, 11, 9), "ZZ9", 1, "entregado"),
    ("P-0011", "K01", datetime(2026, 11, 16), "GL2", 5, "cancelado"),
    ("P-9", "K02", datetime(2026, 11, 10), "CF1", 1, "entregado"),
    ("P-10", "K02", datetime(2026, 11, 10), "DT5", 2, "entregado"),
    ("P-11", "K02", datetime(2026, 11, 10), "CL1", 1, "cancelado"),
    ("P-30", "K03", datetime(2026, 11, 5), "GS6", 1, "cancelado"),
    ("P-20", "K04", datetime(2026, 12, 1), "LP3", 1, "entregado"),
    ("P-21", "K04", datetime(2026, 12, 5), "GS6", 9, "entregado"),
]


def historial() -> pd.DataFrame:
    tabla = pd.DataFrame(FILAS, columns=["pedido_id", "cliente_id", "fecha_entrega", "sku", "cantidad", "estado"])
    tabla["fecha_entrega"] = tabla["fecha_entrega"].astype("datetime64[ms]")
    return tabla


def escribir(directorio: Path, historial_tabla: pd.DataFrame | None = None) -> Path:
    return catalogo_e1b.escribir(directorio, {"historial_pedidos": historial() if historial_tabla is None else historial_tabla})


@dataclass
class Contexto:
    datos: Datos
    indice: IndiceCatalogo
    lexico: LexicoUnidades
    vocabulario: VocabularioAtributos


def contexto(datos: Datos) -> Contexto:
    lexico = LexicoUnidades(datos)
    indice = IndiceCatalogo(datos, lexico.palabras_cantidad())
    return Contexto(datos, indice, lexico, VocabularioAtributos(datos, indice))


def cargar_contexto(directorio: Path) -> Contexto:
    return contexto(cargar_datos(escribir(directorio)))


def ev(numero: int, mensaje: int, tipo: str, texto: str, **campos) -> dict:
    return {"id": f"e{numero}", "mensaje": mensaje, "tipo": tipo, "texto": texto, **campos}


def plegar_mensajes(
    ctx: Contexto, mensajes, eventos, cliente: str = "K01", fecha_hora: datetime = MARTES
) -> tuple[ResultadoPlegado, Salida, EntradaPedido]:
    entrada = EntradaPedido(cliente, fecha_hora, tuple(mensajes))
    interpretacion = Interpretacion.validar({"eventos": list(eventos)}, len(mensajes))
    anclaje = anclar(interpretacion, entrada)
    resultado = plegar(
        entrada=entrada, eventos=anclaje.eventos, datos=ctx.datos, indice=ctx.indice, lexico=ctx.lexico, vocabulario=ctx.vocabulario
    )
    return resultado, aplicar_sustituciones(resultado.lineas_activas(), ctx.datos), entrada


def lineas(salida: Salida) -> list[tuple[str, str]]:
    return [(l.sku, f"{l.cantidad.normalize():f}") for l in salida.lineas]


def pendientes(resultado: ResultadoPlegado) -> list[tuple[str, tuple[str, ...]]]:
    return [(p.motivo.value, p.opciones) for p in resultado.pendientes()]
