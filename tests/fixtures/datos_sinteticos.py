"""Datos sintéticos inventados para las pruebas (no provienen del material del curso).

Reproducen la estructura de los datos reales con productos y clientes ficticios:
hermanos de presentación, agotados con y sin sustituto, quintal con una unidad por empaque,
categoría sin escalas, clientes con uno, dos y tres días de visita, saldo igual al límite,
saldo mayor que el límite e historial cuyo último pedido está cancelado.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


def productos() -> pd.DataFrame:
    filas = [
        # sku, nombre, marca, categoria, presentacion, unidad_venta, upe, precio, disponible, sustituto
        ("G01", "Gaseosa Sol 600 ml", "Sol", "bebidas", "600 ml", "fardo", 24, 100.0, True, None),
        ("G02", "Gaseosa Sol 2 L", "Sol", "bebidas", "2 L", "fardo", 6, 90.5, True, None),
        ("G03", "Gaseosa Sol 3 L", "Sol", "bebidas", "3 L", "fardo", 6, 120.0, False, "G02"),
        ("C01", "Cereal Trigal 500 g", "Trigal", "abarrotes", "500 g", "caja", 12, 6.7, True, None),
        ("C02", "Cereal Trigal 1 kg", "Trigal", "abarrotes", "1 kg", "caja", 12, 11.0, False, None),
        ("Q01", "Harina Molino quintal", "Molino", "abarrotes", "100 lb", "quintal", 1, 300.0, True, None),
        ("L01", "Jabón Nube 200 g", "Nube", "limpieza", "200 g", "caja", 20, 45.25, True, None),
        ("S01", "Galleta Luna", "Luna", "snacks", "12 paquetes", "display", 12, 30.0, True, None),
    ]
    columnas = [
        "sku", "nombre", "marca", "categoria", "presentacion", "unidad_venta",
        "unidades_por_empaque", "precio", "disponible", "sustituto_sku",
    ]
    return pd.DataFrame(filas, columns=columnas)


def sinonimos() -> pd.DataFrame:
    return pd.DataFrame(
        [("G01", "sol 600"), ("G02", "sol de dos"), ("C01", "trigal chico"), ("L01", "jabon nube")],
        columns=["sku", "alias"],
    )


def precios_escala() -> pd.DataFrame:
    # "limpieza" no tiene escalas a propósito; las filas están desordenadas a propósito.
    return pd.DataFrame(
        [("bebidas", 20, 5), ("bebidas", 10, 3), ("abarrotes", 10, 4), ("abarrotes", 5, 2), ("snacks", 10, 3)],
        columns=["categoria", "cantidad_minima", "descuento_pct"],
    )


def clientes() -> pd.DataFrame:
    # Incluye columnas personales ficticias para comprobar que nunca se cargan.
    filas = [
        ("K01", "Tienda Ficticia Uno", "Persona Ficticia Uno", "Municipio X", "lunes,jueves", 5000, 1000),
        ("K02", "Tienda Ficticia Dos", "Persona Ficticia Dos", "Municipio Y", "Miércoles , SÁBADO", 2000, 2000),
        ("K03", "Tienda Ficticia Tres", "Persona Ficticia Tres", "Municipio Z", "domingo", 1000, 1200),
        ("K04", "Tienda Ficticia Cuatro", "Persona Ficticia Cuatro", "Municipio X", "lunes,miércoles,viernes", 10000, 0),
    ]
    columnas = ["cliente_id", "nombre_tienda", "propietario", "municipio", "dias_visita", "limite_credito", "saldo_pendiente"]
    return pd.DataFrame(filas, columns=columnas)


def historial_pedidos() -> pd.DataFrame:
    filas = [
        ("P-1", "K01", datetime(2026, 11, 2), "G01", 2, "entregado"),
        ("P-1", "K01", datetime(2026, 11, 2), "C01", 1, "entregado"),
        ("P-2", "K01", datetime(2026, 11, 9), "G03", 3, "entregado"),
        ("P-3", "K01", datetime(2026, 11, 16), "G02", 5, "cancelado"),
        ("P-4", "K04", datetime(2026, 11, 4), "L01", 1, "entregado"),
    ]
    tabla = pd.DataFrame(filas, columns=["pedido_id", "cliente_id", "fecha_entrega", "sku", "cantidad", "estado"])
    tabla["fecha_entrega"] = tabla["fecha_entrega"].astype("datetime64[ms]")
    return tabla


def tablas() -> dict[str, pd.DataFrame]:
    return {
        "productos": productos(),
        "sinonimos": sinonimos(),
        "precios_escala": precios_escala(),
        "clientes": clientes(),
        "historial_pedidos": historial_pedidos(),
    }


def escribir(directorio: Path, reemplazos: dict[str, pd.DataFrame] | None = None, omitir: tuple[str, ...] = ()) -> Path:
    """Escribe los cinco parquet en `directorio`, con tablas reemplazadas u omitidas."""
    directorio.mkdir(parents=True, exist_ok=True)
    datos = tablas()
    datos.update(reemplazos or {})
    for nombre, tabla in datos.items():
        if nombre not in omitir:
            tabla.to_parquet(directorio / f"{nombre}.parquet", index=False)
    return directorio
