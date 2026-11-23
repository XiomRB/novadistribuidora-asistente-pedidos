"""Carga y validación de los archivos parquet de negocio.

- Solo se leen las columnas necesarias (los nombres de tiendas y propietarios nunca se cargan).
- Los valores numéricos se convierten con `Decimal(str(valor))` a través de `a_decimal`.
- Se reúnen todos los problemas y se lanza un único `DatosInvalidos`.
- Los problemas se identifican con códigos técnicos y claves (sku, cliente_id, pedido_id, fila).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from app.datos.modelos import Alias, Cliente, Datos, Escala, LineaHistorica, PedidoHistorico, Producto
from app.datos.normalizacion import parsear_dias_visita
from app.dominio.dinero import CANTIDAD, LIMITE, PORCENTAJE, PRECIO, SALDO, Validacion, a_decimal
from app.dominio.errores import DatosInvalidos, ProblemaDatos, ValorDecimalInvalido

COLUMNAS: dict[str, tuple[str, ...]] = {
    "productos": (
        "sku",
        "nombre",
        "marca",
        "categoria",
        "presentacion",
        "unidad_venta",
        "unidades_por_empaque",
        "precio",
        "disponible",
        "sustituto_sku",
    ),
    "sinonimos": ("sku", "alias"),
    "precios_escala": ("categoria", "cantidad_minima", "descuento_pct"),
    "clientes": ("cliente_id", "dias_visita", "limite_credito", "saldo_pendiente"),
    "historial_pedidos": ("pedido_id", "cliente_id", "fecha_entrega", "sku", "cantidad", "estado"),
}
ESTADOS_HISTORIAL = frozenset({"entregado", "cancelado"})


class _Registro:
    """Acumula errores y advertencias durante la carga."""

    def __init__(self) -> None:
        self.errores: list[ProblemaDatos] = []
        self.advertencias: list[ProblemaDatos] = []

    def error(self, codigo: str, archivo: str, columna: str | None = None, clave: str | None = None, detalle: str = "") -> None:
        self.errores.append(ProblemaDatos(codigo, archivo, columna, clave, detalle))

    def aviso(self, codigo: str, archivo: str, columna: str | None = None, clave: str | None = None, detalle: str = "") -> None:
        self.advertencias.append(ProblemaDatos(codigo, archivo, columna, clave, detalle))


def _es_nulo(valor: Any) -> bool:
    return valor is None or (not isinstance(valor, (str, bytes)) and bool(pd.isna(valor)))


def _leer(directorio: Path, nombre: str, registro: _Registro) -> list[dict[str, Any]] | None:
    archivo = f"{nombre}.parquet"
    ruta = directorio / archivo
    if not ruta.is_file():
        registro.error("ARCHIVO_FALTANTE", archivo)
        return None
    try:
        disponibles = set(pq.read_schema(ruta).names)
    except Exception as exc:  # noqa: BLE001 - archivo ilegible o corrupto
        registro.error("ARCHIVO_ILEGIBLE", archivo, detalle=type(exc).__name__)
        return None
    faltantes = [c for c in COLUMNAS[nombre] if c not in disponibles]
    for columna in faltantes:
        registro.error("COLUMNA_FALTANTE", archivo, columna)
    if faltantes:
        return None
    try:
        tabla = pd.read_parquet(ruta, columns=list(COLUMNAS[nombre]))
    except Exception as exc:  # noqa: BLE001 - error de lectura o decodificación de los datos
        # Solo el tipo de excepción: su mensaje puede contener rutas u otros datos innecesarios.
        registro.error("ARCHIVO_ILEGIBLE", archivo, detalle=type(exc).__name__)
        return None
    columnas = {c: tabla[c].tolist() for c in COLUMNAS[nombre]}
    return [{c: columnas[c][i] for c in COLUMNAS[nombre]} for i in range(len(tabla))]


def _texto(fila: dict[str, Any], columna: str, archivo: str, clave: str, registro: _Registro, obligatorio: bool = True) -> str | None:
    valor = fila[columna]
    if _es_nulo(valor):
        if obligatorio:
            registro.error("VALOR_FALTANTE", archivo, columna, clave)
        return None
    if not isinstance(valor, str):
        registro.error("TIPO_INVALIDO", archivo, columna, clave, f"se esperaba texto, no {type(valor).__name__}")
        return None
    limpio = valor.strip()
    if not limpio:
        if obligatorio:
            registro.error("VALOR_FALTANTE", archivo, columna, clave)
        return None
    return limpio


def _decimal(fila: dict[str, Any], columna: str, validacion: Validacion, archivo: str, clave: str, registro: _Registro) -> Decimal | None:
    valor = fila[columna]
    if _es_nulo(valor):
        registro.error("VALOR_FALTANTE", archivo, columna, clave)
        return None
    try:
        return a_decimal(valor, validacion, columna)
    except ValorDecimalInvalido as exc:
        registro.error("VALOR_INVALIDO", archivo, columna, clave, exc.motivo)
        return None


def _cargar_productos(filas: list[dict[str, Any]], registro: _Registro) -> dict[str, Producto]:
    archivo = "productos.parquet"
    productos: dict[str, Producto] = {}
    for i, fila in enumerate(filas):
        clave = f"fila {i}"
        sku = _texto(fila, "sku", archivo, clave, registro)
        if sku is None:
            continue
        clave = sku
        campos = {c: _texto(fila, c, archivo, clave, registro) for c in ("nombre", "marca", "categoria", "presentacion", "unidad_venta")}
        upe = _decimal(fila, "unidades_por_empaque", CANTIDAD, archivo, clave, registro)
        precio = _decimal(fila, "precio", PRECIO, archivo, clave, registro)
        disponible = fila["disponible"]
        if not isinstance(disponible, bool):
            registro.error("TIPO_INVALIDO", archivo, "disponible", clave, "se esperaba booleano")
            disponible = None
        sustituto = _texto(fila, "sustituto_sku", archivo, clave, registro, obligatorio=False)
        if sku in productos:
            registro.error("SKU_DUPLICADO", archivo, "sku", clave)
            continue
        if None in campos.values() or upe is None or precio is None or disponible is None:
            continue
        productos[sku] = Producto(
            sku=sku,
            nombre=campos["nombre"],
            marca=campos["marca"],
            categoria=campos["categoria"],
            presentacion=campos["presentacion"],
            unidad_venta=campos["unidad_venta"],
            unidades_por_empaque=upe,
            precio=precio,
            disponible=disponible,
            sustituto_sku=sustituto,
        )
    for producto in productos.values():
        if producto.sustituto_sku is None:
            continue
        if producto.sustituto_sku == producto.sku:
            registro.error("SUSTITUTO_PROPIO", archivo, "sustituto_sku", producto.sku)
        elif producto.sustituto_sku not in productos:
            registro.error("SUSTITUTO_INEXISTENTE", archivo, "sustituto_sku", producto.sku, producto.sustituto_sku)
    return productos


def _cargar_alias(filas: list[dict[str, Any]], productos: dict[str, Producto], registro: _Registro) -> tuple[Alias, ...]:
    archivo = "sinonimos.parquet"
    alias: list[Alias] = []
    for i, fila in enumerate(filas):
        sku = _texto(fila, "sku", archivo, f"fila {i}", registro, obligatorio=False)
        texto = _texto(fila, "alias", archivo, f"fila {i}", registro, obligatorio=False)
        if sku is None or texto is None:
            registro.aviso("ALIAS_INCOMPLETO", archivo, clave=f"fila {i}")
            continue
        if sku not in productos:
            registro.aviso("ALIAS_SKU_INEXISTENTE", archivo, "sku", sku)
            continue
        alias.append(Alias(sku=sku, alias=texto))
    return tuple(alias)


def _cargar_escalas(filas: list[dict[str, Any]], registro: _Registro) -> dict[str, tuple[Escala, ...]]:
    archivo = "precios_escala.parquet"
    por_categoria: dict[str, dict[Decimal, Escala]] = defaultdict(dict)
    for i, fila in enumerate(filas):
        clave = f"fila {i}"
        categoria = _texto(fila, "categoria", archivo, clave, registro)
        minimo = _decimal(fila, "cantidad_minima", CANTIDAD, archivo, clave, registro)
        pct = _decimal(fila, "descuento_pct", PORCENTAJE, archivo, clave, registro)
        if categoria is None or minimo is None or pct is None:
            continue
        existente = por_categoria[categoria].get(minimo)
        if existente is not None and existente.descuento_pct != pct:
            registro.error("ESCALA_DUPLICADA", archivo, "cantidad_minima", f"{categoria}/{minimo}")
            continue
        por_categoria[categoria][minimo] = Escala(categoria=categoria, cantidad_minima=minimo, descuento_pct=pct)
    return {c: tuple(sorted(e.values(), key=lambda x: x.cantidad_minima)) for c, e in por_categoria.items()}


def _cargar_clientes(filas: list[dict[str, Any]], registro: _Registro) -> dict[str, Cliente]:
    archivo = "clientes.parquet"
    clientes: dict[str, Cliente] = {}
    for i, fila in enumerate(filas):
        cliente_id = _texto(fila, "cliente_id", archivo, f"fila {i}", registro)
        if cliente_id is None:
            continue
        texto_dias = _texto(fila, "dias_visita", archivo, cliente_id, registro)
        dias: frozenset[int] | None = None
        if texto_dias is not None:
            try:
                dias = parsear_dias_visita(texto_dias)
            except ValueError as exc:
                registro.error("DIA_INVALIDO", archivo, "dias_visita", cliente_id, str(exc))
            else:
                if not dias:
                    registro.error("SIN_DIAS_VISITA", archivo, "dias_visita", cliente_id)
                    dias = None
        limite = _decimal(fila, "limite_credito", LIMITE, archivo, cliente_id, registro)
        saldo = _decimal(fila, "saldo_pendiente", SALDO, archivo, cliente_id, registro)
        if cliente_id in clientes:
            registro.error("CLIENTE_DUPLICADO", archivo, "cliente_id", cliente_id)
            continue
        if dias is None or limite is None or saldo is None:
            continue
        clientes[cliente_id] = Cliente(cliente_id=cliente_id, dias_visita=dias, limite_credito=limite, saldo_pendiente=saldo)
    return clientes


def _fecha(valor: Any) -> date | None:
    if _es_nulo(valor):
        return None
    if isinstance(valor, datetime):  # incluye pandas.Timestamp
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _cargar_historial(
    filas: list[dict[str, Any]], productos: dict[str, Producto], clientes: dict[str, Cliente], registro: _Registro
) -> dict[str, tuple[PedidoHistorico, ...]]:
    archivo = "historial_pedidos.parquet"
    cabeceras: dict[str, tuple[str, date, str]] = {}
    lineas: dict[str, list[LineaHistorica]] = defaultdict(list)
    for i, fila in enumerate(filas):
        clave = f"fila {i}"
        pedido_id = _texto(fila, "pedido_id", archivo, clave, registro)
        cliente_id = _texto(fila, "cliente_id", archivo, clave, registro)
        sku = _texto(fila, "sku", archivo, clave, registro)
        estado = _texto(fila, "estado", archivo, clave, registro)
        cantidad = _decimal(fila, "cantidad", CANTIDAD, archivo, clave, registro)
        fecha = _fecha(fila["fecha_entrega"])
        if fecha is None:
            registro.error("FECHA_INVALIDA", archivo, "fecha_entrega", clave)
        if estado is not None and estado not in ESTADOS_HISTORIAL:
            registro.error("ESTADO_INVALIDO", archivo, "estado", clave, estado)
            estado = None
        if None in (pedido_id, cliente_id, sku, estado, cantidad, fecha):
            continue
        cabecera = (cliente_id, fecha, estado)
        if pedido_id in cabeceras and cabeceras[pedido_id] != cabecera:
            registro.error("PEDIDO_INCOHERENTE", archivo, clave=pedido_id)
            continue
        cabeceras[pedido_id] = cabecera
        if sku not in productos:
            registro.aviso("HISTORIAL_SKU_INEXISTENTE", archivo, "sku", pedido_id, sku)
        if cliente_id not in clientes:
            registro.aviso("HISTORIAL_CLIENTE_INEXISTENTE", archivo, "cliente_id", pedido_id)
        lineas[pedido_id].append(LineaHistorica(sku=sku, cantidad=cantidad))

    por_cliente: dict[str, list[PedidoHistorico]] = defaultdict(list)
    for pedido_id, (cliente_id, fecha, estado) in cabeceras.items():
        por_cliente[cliente_id].append(
            PedidoHistorico(pedido_id=pedido_id, cliente_id=cliente_id, fecha_entrega=fecha, estado=estado, lineas=tuple(lineas[pedido_id]))
        )
    return {c: tuple(sorted(p, key=lambda x: (x.fecha_entrega, x.pedido_id))) for c, p in por_cliente.items()}


def cargar_datos(directorio: str | Path) -> Datos:
    """Carga y valida los cinco archivos. Lanza DatosInvalidos con todos los problemas."""
    base = Path(directorio)
    registro = _Registro()
    filas = {nombre: _leer(base, nombre, registro) for nombre in COLUMNAS}

    productos = _cargar_productos(filas["productos"], registro) if filas["productos"] is not None else {}
    alias = _cargar_alias(filas["sinonimos"], productos, registro) if filas["sinonimos"] is not None else ()
    escalas = _cargar_escalas(filas["precios_escala"], registro) if filas["precios_escala"] is not None else {}
    clientes = _cargar_clientes(filas["clientes"], registro) if filas["clientes"] is not None else {}
    historial = (
        _cargar_historial(filas["historial_pedidos"], productos, clientes, registro)
        if filas["historial_pedidos"] is not None
        else {}
    )
    if registro.errores:
        raise DatosInvalidos(registro.errores, registro.advertencias)
    return Datos(
        productos=MappingProxyType(productos),
        alias=alias,
        escalas=MappingProxyType(escalas),
        clientes=MappingProxyType(clientes),
        historial=MappingProxyType(historial),
        advertencias=tuple(registro.advertencias),
    )
