"""Conversión y validación de valores decimales (montos, cantidades y porcentajes).

Regla: todo valor numérico que interviene en cálculos se construye con
`Decimal(str(valor))`. Nunca `Decimal(float)` ni `repr()`.
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.dominio.errores import ValorDecimalInvalido

CERO = Decimal("0")
CIEN = Decimal("100")
CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class Validacion:
    """Reglas de validación de un campo numérico."""

    nombre: str
    permite_cero: bool
    entero: bool = False
    max_decimales: int | None = None
    maximo: Decimal | None = None


# Validaciones por tipo de campo.
PRECIO = Validacion("precio", permite_cero=False, max_decimales=2)
SALDO = Validacion("saldo", permite_cero=True, max_decimales=2)
LIMITE = Validacion("limite", permite_cero=True, max_decimales=2)
CANTIDAD = Validacion("cantidad", permite_cero=False, entero=True)
PORCENTAJE = Validacion("porcentaje", permite_cero=True, entero=True, maximo=CIEN)


def _decimales(valor: Decimal) -> int:
    exponente = valor.normalize().as_tuple().exponent
    return -exponente if isinstance(exponente, int) and exponente < 0 else 0


def a_decimal(valor: object, validacion: Validacion, campo: str | None = None) -> Decimal:
    """Convierte `valor` a `Decimal` mediante su representación textual y lo valida.

    Acepta `Decimal`, enteros (incluidos los de numpy), reales (incluido `numpy.float64`,
    que se convierte con `str`) y cadenas. Rechaza booleanos, no finitos, negativos,
    cero si el campo no lo permite, no enteros si el campo lo exige, exceso de decimales
    y valores sobre el máximo.
    """
    etiqueta = campo or validacion.nombre
    if isinstance(valor, bool) or valor is None:
        raise ValorDecimalInvalido(etiqueta, "tipo no numérico")
    if isinstance(valor, Decimal):
        resultado = valor
    elif isinstance(valor, (numbers.Real, str)):
        texto = str(valor).strip()
        try:
            resultado = Decimal(texto)
        except InvalidOperation:
            raise ValorDecimalInvalido(etiqueta, "no es un número") from None
    else:
        raise ValorDecimalInvalido(etiqueta, f"tipo no admitido: {type(valor).__name__}")

    if not resultado.is_finite():
        raise ValorDecimalInvalido(etiqueta, "no es finito")
    if resultado < CERO:
        raise ValorDecimalInvalido(etiqueta, "negativo")
    if resultado == CERO and not validacion.permite_cero:
        raise ValorDecimalInvalido(etiqueta, "debe ser mayor que cero")
    if validacion.entero and resultado != resultado.to_integral_value():
        raise ValorDecimalInvalido(etiqueta, "debe ser entero")
    if validacion.max_decimales is not None and _decimales(resultado) > validacion.max_decimales:
        raise ValorDecimalInvalido(etiqueta, f"más de {validacion.max_decimales} decimales")
    if validacion.maximo is not None and resultado > validacion.maximo:
        raise ValorDecimalInvalido(etiqueta, f"mayor que {validacion.maximo}")
    return resultado


def exigir_decimal(*valores: object) -> None:
    """Garantiza que los argumentos de un cálculo sean `Decimal` (nunca `float`)."""
    for valor in valores:
        if not isinstance(valor, Decimal):
            raise TypeError(f"Se esperaba Decimal y se recibió {type(valor).__name__}")


def redondear_centavos(valor: Decimal) -> Decimal:
    """Redondea a dos decimales con ROUND_HALF_UP."""
    exigir_decimal(valor)
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
