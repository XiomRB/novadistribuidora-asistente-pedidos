from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import combinations

import pytest

from app.datos.modelos import Escala
from app.dominio.reglas import credito_excedido, descuento_pct, fecha_efectiva, fecha_entrega, subtotal, total

D = Decimal

ESCALAS = {
    # Desordenadas a propósito.
    "bebidas": (Escala("bebidas", D(20), D(5)), Escala("bebidas", D(10), D(3))),
    "abarrotes": (Escala("abarrotes", D(5), D(2)), Escala("abarrotes", D(10), D(4))),
}


class TestDescuento:
    @pytest.mark.parametrize(
        ("cantidad", "esperado"),
        [(1, 0), (9, 0), (10, 3), (11, 3), (19, 3), (20, 5), (500, 5)],
    )
    def test_bebidas_limites(self, cantidad, esperado):
        assert descuento_pct("bebidas", D(cantidad), ESCALAS) == D(esperado)

    @pytest.mark.parametrize(("cantidad", "esperado"), [(4, 0), (5, 2), (9, 2), (10, 4)])
    def test_abarrotes_limites(self, cantidad, esperado):
        assert descuento_pct("abarrotes", D(cantidad), ESCALAS) == D(esperado)

    def test_categoria_sin_escalas(self):
        assert descuento_pct("limpieza", D(1000), ESCALAS) == D(0)

    def test_resultado_es_decimal(self):
        assert isinstance(descuento_pct("bebidas", D(20), ESCALAS), Decimal)

    def test_rechaza_cantidad_float(self):
        with pytest.raises(TypeError):
            descuento_pct("bebidas", 20.0, ESCALAS)


class TestSubtotalYTotal:
    @pytest.mark.parametrize(
        ("cantidad", "precio", "pct", "esperado"),
        [
            (2, "120.0", 0, "240.00"),
            (10, "156.0", 4, "1497.60"),
            (24, "120.0", 5, "2736.00"),
            (1, "6.70", 5, "6.37"),  # 6.365 -> mitad hacia arriba
            (3, "0.11", 50, "0.17"),  # 0.165 -> 0.17
            (7, "45.25", 3, "307.25"),  # 307.2475 -> 307.25
        ],
    )
    def test_subtotal(self, cantidad, precio, pct, esperado):
        resultado = subtotal(D(cantidad), D(precio), D(pct))
        assert resultado == D(esperado)
        assert resultado.as_tuple().exponent == -2

    def test_redondea_cada_subtotal_antes_de_sumar(self):
        # Tres líneas de 0.335: redondeando cada una da 0.34 × 3 = 1.02;
        # sumando primero daría 1.005 -> 1.01.
        sub = subtotal(D(1), D("0.67"), D(50))
        assert sub == D("0.34")
        assert total([sub, sub, sub]) == D("1.02")

    def test_total_rechaza_subtotal_sin_redondear(self):
        with pytest.raises(ValueError, match="redondeado"):
            total([D("0.335")])

    def test_total_vacio(self):
        assert total([]) == D("0.00")

    @pytest.mark.parametrize("argumentos", [(2.0, D("1"), D("0")), (D("2"), 1.5, D("0")), (D("2"), D("1"), 0.0)])
    def test_subtotal_rechaza_float(self, argumentos):
        with pytest.raises(TypeError):
            subtotal(*argumentos)

    def test_total_rechaza_float(self):
        with pytest.raises(TypeError):
            total([1.0])


class TestCredito:
    def test_igual_al_limite_no_excede(self):
        assert credito_excedido(D("7500"), D("8000"), D("500.00")) is False

    def test_un_centavo_por_encima_excede(self):
        assert credito_excedido(D("7500"), D("8000"), D("500.01")) is True

    def test_total_cero_con_saldo_mayor_que_limite_excede(self):
        assert credito_excedido(D("1200"), D("1000"), D("0.00")) is True

    def test_total_cero_con_saldo_igual_al_limite_no_excede(self):
        assert credito_excedido(D("2000"), D("2000"), D("0.00")) is False

    def test_rechaza_float(self):
        with pytest.raises(TypeError):
            credito_excedido(7500.0, D("8000"), D("1"))


LUNES = date(2026, 11, 23)  # lunes


class TestFechaEntrega:
    @pytest.mark.parametrize(
        ("recibido", "dias", "esperado"),
        [
            (datetime(2026, 11, 23, 9, 12), {0, 3}, date(2026, 11, 26)),   # lunes mañana -> jueves (no el mismo lunes)
            (datetime(2026, 11, 23, 15, 20), {0, 3}, date(2026, 11, 26)),  # Anexo: lunes tarde -> jueves
            (datetime(2026, 12, 2, 13, 59), {0, 3}, date(2026, 12, 3)),    # miércoles 13:59 -> jueves
            (datetime(2026, 12, 2, 14, 0), {0, 3}, date(2026, 12, 7)),     # miércoles 14:00 = jueves -> lunes
            (datetime(2026, 12, 2, 23, 59), {0, 3}, date(2026, 12, 7)),
            (datetime(2026, 12, 3, 0, 0), {0, 3}, date(2026, 12, 7)),      # jueves 00:00 -> lunes
            (datetime(2026, 11, 29, 20, 40), {0, 3}, date(2026, 12, 3)),   # domingo noche = lunes -> jueves
            (datetime(2026, 11, 28, 10, 0), {5}, date(2026, 12, 5)),       # sábado, visita solo sábado -> 7 días
            (datetime(2026, 11, 27, 14, 0), {5}, date(2026, 12, 5)),       # viernes 14:00 = sábado -> sábado siguiente
            (datetime(2026, 12, 31, 9, 0), {4}, date(2027, 1, 1)),         # cambio de año
            (datetime(2026, 12, 31, 15, 0), {0}, date(2027, 1, 4)),
            (datetime(2026, 11, 30, 16, 0), {1, 4}, date(2026, 12, 4)),    # cambio de mes
        ],
    )
    def test_casos(self, recibido, dias, esperado):
        assert fecha_entrega(recibido, frozenset(dias)) == esperado

    def test_hora_de_corte(self):
        assert fecha_efectiva(datetime(2026, 12, 2, 13, 59, 59)) == date(2026, 12, 2)
        assert fecha_efectiva(datetime(2026, 12, 2, 14, 0)) == date(2026, 12, 3)

    @pytest.mark.parametrize("dias", [frozenset(), frozenset({7}), frozenset({-1})])
    def test_dias_invalidos(self, dias):
        with pytest.raises(ValueError):
            fecha_entrega(datetime(2026, 12, 1, 9, 0), dias)

    def test_exhaustivo_contra_referencia_independiente(self):
        """127 combinaciones de días × 7 días de recepción × 2 horarios contra un oráculo."""

        def oraculo(recibido: datetime, dias: frozenset[int]) -> date:
            limite = recibido.date() + (timedelta(days=1) if (recibido.hour, recibido.minute) >= (14, 0) else timedelta())
            candidato = recibido.date()
            while True:
                candidato += timedelta(days=1)
                if candidato > limite and candidato.weekday() in dias:
                    return candidato

        discrepancias = []
        for n in range(1, 8):
            for combinacion in combinations(range(7), n):
                dias = frozenset(combinacion)
                for desplazamiento in range(7):
                    for hora, minuto in ((13, 59), (14, 0)):
                        dia = LUNES + timedelta(days=desplazamiento)
                        recibido = datetime(dia.year, dia.month, dia.day, hora, minuto)
                        if fecha_entrega(recibido, dias) != oraculo(recibido, dias):
                            discrepancias.append((recibido, sorted(dias)))
        assert discrepancias == []
