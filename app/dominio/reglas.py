"""Reglas comerciales deterministas: descuentos, subtotales, total, crédito y fecha de entrega."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.datos.modelos import Escala
from app.dominio.dinero import CERO, CIEN, exigir_decimal, redondear_centavos

HORA_CORTE = time(14, 0)


def descuento_pct(categoria: str, cantidad: Decimal, escalas: Mapping[str, tuple[Escala, ...]]) -> Decimal:
    """Mayor porcentaje de la categoría cuyo mínimo se alcance; 0 si no hay escala aplicable."""
    exigir_decimal(cantidad)
    aplicables = [e.descuento_pct for e in escalas.get(categoria, ()) if e.cantidad_minima <= cantidad]
    return max(aplicables, default=CERO)


def subtotal(cantidad: Decimal, precio: Decimal, descuento: Decimal) -> Decimal:
    """cantidad × precio × (1 − descuento/100), redondeado a centavos (mitad hacia arriba)."""
    exigir_decimal(cantidad, precio, descuento)
    return redondear_centavos(cantidad * precio * (CIEN - descuento) / CIEN)


def total(subtotales: Iterable[Decimal]) -> Decimal:
    """Suma de subtotales ya redondeados (nunca se redondea la suma)."""
    acumulado = Decimal("0.00")
    for valor in subtotales:
        exigir_decimal(valor)
        if redondear_centavos(valor) != valor:
            raise ValueError("El subtotal debe estar redondeado a centavos antes de sumarse")
        acumulado += valor
    return redondear_centavos(acumulado)


def credito_excedido(saldo: Decimal, limite: Decimal, total_pedido: Decimal) -> bool:
    """True si saldo pendiente + total supera (estrictamente) el límite de crédito."""
    exigir_decimal(saldo, limite, total_pedido)
    return saldo + total_pedido > limite


def fecha_efectiva(fecha_hora: datetime) -> date:
    """Fecha de recepción; a partir de las 14:00 se considera recibido al día siguiente."""
    dia = fecha_hora.date()
    return dia + timedelta(days=1) if fecha_hora.time() >= HORA_CORTE else dia


def fecha_entrega(fecha_hora: datetime, dias_visita: frozenset[int]) -> date:
    """Primer día de visita (0=lunes … 6=domingo) estrictamente posterior a la fecha efectiva."""
    if not dias_visita or not all(isinstance(d, int) and 0 <= d <= 6 for d in dias_visita):
        raise ValueError("dias_visita debe contener días válidos entre 0 y 6")
    base = fecha_efectiva(fecha_hora)
    for desplazamiento in range(1, 8):
        candidato = base + timedelta(days=desplazamiento)
        if candidato.weekday() in dias_visita:
            return candidato
    raise AssertionError("inalcanzable: siempre hay un día de visita en 7 días")
