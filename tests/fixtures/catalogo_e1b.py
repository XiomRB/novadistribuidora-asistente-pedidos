"""Catálogo sintético ampliado para E1b (productos y alias inventados).

Reutiliza las escalas, clientes e historial sintéticos de E1a sin modificarlos y reemplaza
productos y alias por un catálogo con hermanos, variantes, marcas, contenedores declarados,
peso, volumen, quintal y agotados con y sin sustituto.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.datos.carga import cargar_datos
from app.datos.modelos import Datos
from tests.fixtures import datos_sinteticos

COLUMNAS = [
    "sku", "nombre", "marca", "categoria", "presentacion", "unidad_venta",
    "unidades_por_empaque", "precio", "disponible", "sustituto_sku",
]

PRODUCTOS = [
    # Gaseosas (grupo "gaseosa"): dos marcas, varias presentaciones, una agotada con sustituto.
    ("GS6", "Gaseosa Sol 600 ml", "Sol", "bebidas", "600 ml", "fardo", 24, 100.0, True, None),
    ("GS2", "Gaseosa Sol 2 L", "Sol", "bebidas", "2 L", "fardo", 6, 90.0, True, None),
    ("GL2", "Gaseosa Luz 2 L", "Luz", "bebidas", "2 L", "fardo", 6, 85.0, True, None),
    ("GS3", "Gaseosa Sol 3 L", "Sol", "bebidas", "3 L", "fardo", 6, 120.0, False, "GS2"),
    # Marca como nombre (grupo "brio").
    ("BR6", "Brío 600 ml", "Brío", "bebidas", "600 ml", "fardo", 24, 95.0, True, None),
    ("RY4", "Bebida Rayo 473 ml", "Rayo", "bebidas", "473 ml", "fardo", 12, 150.0, True, None),
    # Frijol (variante negro / rojo).
    ("FN1", "Frijol Negro Campo 1 lb", "Campo", "abarrotes", "1 lb", "fardo", 25, 175.0, True, None),
    ("FR1", "Frijol Rojo Campo 1 lb", "Campo", "abarrotes", "1 lb", "fardo", 25, 190.0, True, None),
    # Arroz (libra / quintal con una unidad por empaque).
    ("AR1", "Arroz Sierra 1 lb", "Sierra", "abarrotes", "1 lb", "fardo", 25, 125.0, True, None),
    ("ARQ", "Arroz Sierra quintal", "Sierra", "abarrotes", "100 lb", "quintal", 1, 480.0, True, None),
    # Aceite (agotado con sustituto).
    ("AC1", "Aceite Girasol Oro 750 ml", "Oro", "abarrotes", "750 ml", "caja", 12, 228.0, True, None),
    ("AC2", "Aceite Palma Verde 750 ml", "Verde", "abarrotes", "750 ml", "caja", 12, 192.0, False, "AC1"),
    # Pasta (dos variantes de marca Fina y una pasta dental).
    ("PC2", "Pasta Fina Coditos 200 g", "Fina", "abarrotes", "200 g", "fardo", 24, 96.0, True, None),
    ("PE2", "Pasta Fina Espagueti 200 g", "Fina", "abarrotes", "200 g", "fardo", 24, 96.0, True, None),
    ("PD7", "Pasta Dental Clara 75 ml", "Clara", "cuidado_personal", "75 ml", "caja", 12, 144.0, True, None),
    # Galletas (contenedor declarado igual a la UPE; una agotada sin sustituto).
    ("GV1", "Galletas Luna Vainilla", "Luna", "snacks", "12 paquetes", "display", 12, 42.0, True, None),
    ("GC1", "Galletas Luna Chocolate", "Luna", "snacks", "12 paquetes", "display", 12, 48.0, False, None),
    ("GK1", "Galletas Saladas Kris", "Kris", "snacks", "10 paquetes", "display", 10, 35.0, True, None),
    # Papel (contenedor declarado distinto de la UPE).
    ("PH4", "Papel Higiénico Nube 4 rollos", "Nube", "limpieza", "4 rollos", "fardo", 12, 216.0, True, None),
    ("PHD", "Papel Higiénico Nube 12 rollos", "Nube", "limpieza", "12 rollos", "fardo", 6, 228.0, False, "PH4"),
    # Sobres y bolsitas declarados.
    ("SH1", "Shampoo Ola sobre 10 ml", "Ola", "cuidado_personal", "24 sobres", "display", 24, 36.0, True, None),
    ("CH1", "Chicharrines Picantes 30 g", "Chicharrines", "snacks", "20 bolsitas", "display", 20, 50.0, True, None),
    # Peso y volumen simples.
    ("CF1", "Café Monte Molido 400 g", "Monte", "abarrotes", "400 g", "caja", 12, 420.0, True, None),
    ("CI1", "Café Monte Instantáneo 50 g", "Monte", "abarrotes", "50 g", "caja", 24, 360.0, False, None),
    ("DT5", "Detergente Espuma 500 g", "Espuma", "limpieza", "500 g", "fardo", 24, 264.0, True, None),
    ("CL1", "Cloro Claro 1 L", "Claro", "limpieza", "1 L", "caja", 12, 108.0, True, None),
    ("LP3", "Leche en Polvo Nieve 360 g", "Nieve", "abarrotes", "360 g", "caja", 12, 384.0, True, None),
]

ALIAS = [
    ("GS6", "sol 600"),
    ("GS2", "sol de dos litros"),
    ("FN1", "frijol negro"),
    ("PC2", "coditos fina"),
    ("PH4", "papel nube 4"),
    ("PHD", "papel nube 12"),
    ("SH1", "shampoo ola"),
    ("CF1", "cafe monte molido"),
]


def productos() -> pd.DataFrame:
    return pd.DataFrame(PRODUCTOS, columns=COLUMNAS)


def sinonimos() -> pd.DataFrame:
    return pd.DataFrame(ALIAS, columns=["sku", "alias"])


def escribir(directorio: Path, reemplazos: dict[str, pd.DataFrame] | None = None) -> Path:
    tablas = {"productos": productos(), "sinonimos": sinonimos()}
    tablas.update(reemplazos or {})
    historial = datos_sinteticos.historial_pedidos()
    historial = historial[historial["sku"].isin(tablas["productos"]["sku"])]  # historial coherente con este catálogo
    tablas.setdefault("historial_pedidos", historial)
    return datos_sinteticos.escribir(directorio, tablas)


def cargar(directorio: Path) -> Datos:
    return cargar_datos(escribir(directorio))
