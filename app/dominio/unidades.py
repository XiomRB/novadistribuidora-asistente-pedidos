"""Unidades y cantidades: clasificación de la palabra de unidad, compatibilidad y conversión.

Reglas (decisiones aprobadas):
- La palabra literal (`unidad_texto`) manda sobre la clasificación declarada por el LLM.
- Empaque igual a la unidad de venta del producto: unidad de venta (entero > 0).
- Empaque que es unidad de venta de otro producto: no convertible (no se asume).
- Palabra suelta: solo si es compatible con la presentación y las unidades por empaque (UPE)
  del producto, y la división es exacta.
- Docena: x12 y luego la regla de unidades sueltas.
- `cantidad_incierta`: nunca se convierte (no convertible).
- Sin número y con unidad suelta ("unas latas"): no convertible (D46).
- Sin número y con unidad de venta o sin unidad: 1 unidad de venta.
- La conversión usa siempre la UPE del producto solicitado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.datos.modelos import Datos, Producto
from app.datos.normalizacion import normalizar_texto
from app.dominio.texto import CONTENEDORES, UNIDADES_MEDIDA, extraer_medidas, peso_coincidencia, singular, variantes

DOCE = Decimal(12)
_CANTIDAD = re.compile(r"^\d{1,5}([.,]\d{1,3})?$")

# Palabras sueltas (unidad interior) -> lema. 'unidad' es genérica.
SUELTAS: dict[str, str] = {
    "botella": "botella", "botellita": "botella", "lata": "lata", "latita": "lata",
    "bolsa": "bolsa", "bolsita": "bolsa", "sobre": "sobre", "sobrecito": "sobre",
    "paquete": "paquete", "paquetito": "paquete", "unidad": "unidad", "rollo": "rollo",
}
DOCENAS = frozenset({"docena", "docenas"})
PESO = frozenset({"g", "lb"})
VOLUMEN = frozenset({"ml"})


class CantidadInvalida(ValueError):
    """La cantidad no tiene el formato decimal esperado."""


class ClaseUnidad(StrEnum):
    NO_INDICADA = "no_indicada"
    VENTA_PROPIA = "venta_propia"
    VENTA_AJENA = "venta_ajena"
    SUELTA = "suelta"
    DOCENA = "docena"
    DESCONOCIDA = "desconocida"


class CodigoConversion(StrEnum):
    OK = "OK"
    INCIERTA = "INCIERTA"
    SUELTA_SIN_NUMERO = "SUELTA_SIN_NUMERO"
    SIN_PALABRA = "SIN_PALABRA"
    NO_ENTERA = "NO_ENTERA"
    NO_EXACTA = "NO_EXACTA"
    UNIDAD_INCOMPATIBLE = "UNIDAD_INCOMPATIBLE"
    UNIDAD_DESCONOCIDA = "UNIDAD_DESCONOCIDA"
    CANTIDAD_CERO = "CANTIDAD_CERO"


@dataclass(frozen=True)
class Conversion:
    codigo: CodigoConversion
    cantidad_venta: Decimal | None = None
    clase: ClaseUnidad = ClaseUnidad.NO_INDICADA
    desacuerdo_llm: bool = False

    @property
    def convertible(self) -> bool:
        return self.codigo is CodigoConversion.OK


def parsear_cantidad(texto: str | None) -> Decimal | None:
    """'2' -> 2; '0,5' -> 0.5; None -> None. Siempre `Decimal(str)`, nunca float."""
    if texto is None:
        return None
    limpio = texto.strip()
    if not _CANTIDAD.match(limpio):
        raise CantidadInvalida(f"cantidad con formato inválido: {limpio!s}")
    return Decimal(limpio.replace(",", "."))


def _lema(palabra: str, lexico: dict[str, str]) -> str | None:
    for variante in variantes(palabra):
        if variante in lexico:
            return lexico[variante]
    return None


class LexicoUnidades:
    """Léxico de unidades de venta derivado de los datos (`unidad_venta`)."""

    def __init__(self, datos: Datos):
        self.venta: frozenset[str] = frozenset(normalizar_texto(p.unidad_venta) for p in datos.productos.values())

    def palabras_cantidad(self) -> frozenset[str]:
        """Palabras que acompañan a una cantidad (para no confundirlas con presentaciones)."""
        formas = set(self.venta) | {singular(v) + "s" for v in self.venta} | {v + "es" for v in self.venta}
        return frozenset(formas | set(SUELTAS) | {s + "s" for s in SUELTAS} | DOCENAS)

    def lema_venta(self, palabra: str) -> str | None:
        for variante in variantes(palabra):
            if variante in self.venta:
                return variante
        for variante in variantes(palabra):
            for venta in self.venta:
                if peso_coincidencia(variante, venta) >= 7 and len(variante) >= 5:
                    return venta
        return None

    def clasificar(self, unidad_texto: str | None, producto: Producto) -> tuple[ClaseUnidad, str | None]:
        if unidad_texto is None:
            return ClaseUnidad.NO_INDICADA, None
        palabra = normalizar_texto(unidad_texto)
        if not palabra:
            return ClaseUnidad.NO_INDICADA, None
        ultima = palabra.split()[-1]
        if ultima in DOCENAS:
            return ClaseUnidad.DOCENA, "docena"
        venta = self.lema_venta(ultima)
        if venta is not None:
            propia = normalizar_texto(producto.unidad_venta)
            return (ClaseUnidad.VENTA_PROPIA if venta == propia else ClaseUnidad.VENTA_AJENA), venta
        suelta = _lema(ultima, SUELTAS) or _lema(ultima, CONTENEDORES)
        if suelta is not None:
            return ClaseUnidad.SUELTA, suelta
        return ClaseUnidad.DESCONOCIDA, ultima


def contenedor_declarado(producto: Producto) -> tuple[Decimal, str] | None:
    """('12', 'paquete') para presentaciones como '12 paquetes'."""
    for medida in extraer_medidas(producto.presentacion):
        if medida.unidad in set(CONTENEDORES.values()):
            return medida.valor, medida.unidad
    return None


def sueltas_compatibles(producto: Producto) -> frozenset[str]:
    """Palabras sueltas válidas para el producto según su presentación y su UPE."""
    if producto.unidades_por_empaque == 1:
        return frozenset()
    declarado = contenedor_declarado(producto)
    if declarado is not None:
        numero, lema = declarado
        return frozenset({lema, "unidad"}) if numero == producto.unidades_por_empaque else frozenset()
    unidades = {m.unidad for m in extraer_medidas(producto.presentacion) if m.unidad in set(u for u, _ in UNIDADES_MEDIDA.values())}
    if unidades & PESO:
        return frozenset({"bolsa", "unidad"})
    if unidades & VOLUMEN:
        return frozenset({"botella", "lata", "unidad"})
    return frozenset()


def convertir(
    *,
    cantidad: Decimal | None,
    cantidad_incierta: bool,
    unidad_declarada: str,
    unidad_texto: str | None,
    producto: Producto,
    lexico: LexicoUnidades,
) -> Conversion:
    """Convierte una cantidad expresada por el cliente a unidades de venta del producto."""
    clase, lema = lexico.clasificar(unidad_texto, producto)
    if clase is ClaseUnidad.NO_INDICADA and unidad_declarada == "docena":
        clase, lema = ClaseUnidad.DOCENA, "docena"
    declarada_venta = unidad_declarada in ("venta", "no_indicada")
    desacuerdo = (clase in (ClaseUnidad.VENTA_PROPIA, ClaseUnidad.VENTA_AJENA) and unidad_declarada not in ("venta", "no_indicada")) or (
        clase in (ClaseUnidad.SUELTA, ClaseUnidad.DOCENA) and declarada_venta
    )

    def resultado(codigo: CodigoConversion, valor: Decimal | None = None) -> Conversion:
        return Conversion(codigo, valor, clase, desacuerdo)

    if cantidad_incierta:
        return resultado(CodigoConversion.INCIERTA)
    if clase is ClaseUnidad.NO_INDICADA and not declarada_venta:
        return resultado(CodigoConversion.SIN_PALABRA)
    if clase is ClaseUnidad.VENTA_AJENA:
        return resultado(CodigoConversion.UNIDAD_INCOMPATIBLE)
    if clase is ClaseUnidad.DESCONOCIDA:
        return resultado(CodigoConversion.UNIDAD_DESCONOCIDA)

    if clase in (ClaseUnidad.NO_INDICADA, ClaseUnidad.VENTA_PROPIA):
        valor = Decimal(1) if cantidad is None else cantidad
        if valor == 0:
            return resultado(CodigoConversion.CANTIDAD_CERO)
        if valor != valor.to_integral_value():
            return resultado(CodigoConversion.NO_ENTERA)
        return resultado(CodigoConversion.OK, valor)

    # Unidades sueltas o docenas.
    if cantidad is None:
        return resultado(CodigoConversion.SUELTA_SIN_NUMERO)
    if cantidad == 0:
        return resultado(CodigoConversion.CANTIDAD_CERO)
    compatibles = sueltas_compatibles(producto)
    if clase is ClaseUnidad.DOCENA:
        if not compatibles:
            return resultado(CodigoConversion.UNIDAD_INCOMPATIBLE)
        unidades = cantidad * DOCE
    else:
        declarado = contenedor_declarado(producto)
        if declarado is not None and declarado[1] == lema and declarado[0] == cantidad and declarado[0] != producto.unidades_por_empaque:
            # "papel 12 rollos": el número y la palabra describen la presentación, no la cantidad.
            return resultado(CodigoConversion.OK, Decimal(1))
        if lema not in compatibles:
            return resultado(CodigoConversion.UNIDAD_INCOMPATIBLE)
        unidades = cantidad
    if unidades != unidades.to_integral_value() or unidades % producto.unidades_por_empaque != 0:
        return resultado(CodigoConversion.NO_EXACTA)
    return resultado(CodigoConversion.OK, unidades / producto.unidades_por_empaque)
