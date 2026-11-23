from decimal import Decimal

import numpy as np
import pytest

from app.dominio.dinero import (
    CANTIDAD,
    LIMITE,
    PORCENTAJE,
    PRECIO,
    SALDO,
    a_decimal,
    exigir_decimal,
    redondear_centavos,
)
from app.dominio.errores import ValorDecimalInvalido


class TestConversion:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (120.0, Decimal("120.0")),
            (np.float64(96.0), Decimal("96.0")),
            (np.float64(1497.6), Decimal("1497.6")),
            (np.int64(24), Decimal("24")),
            (45, Decimal("45")),
            ("45.25", Decimal("45.25")),
            (" 7.5 ", Decimal("7.5")),
            (Decimal("6.70"), Decimal("6.70")),
        ],
    )
    def test_convierte_con_representacion_textual(self, valor, esperado):
        resultado = a_decimal(valor, PRECIO)
        assert resultado == esperado
        assert isinstance(resultado, Decimal)

    def test_numpy_float_no_usa_repr(self):
        # En numpy 2, repr(np.float64(96.0)) == 'np.float64(96.0)'; str() devuelve '96.0'.
        assert str(a_decimal(np.float64(96.0), PRECIO)) == "96.0"

    def test_float_binario_con_decimales_espurios_se_rechaza(self):
        with pytest.raises(ValorDecimalInvalido, match="más de 2 decimales"):
            a_decimal(0.1 + 0.2, PRECIO)

    @pytest.mark.parametrize("valor", [True, False, None, [1], object()])
    def test_tipos_no_admitidos(self, valor):
        with pytest.raises(ValorDecimalInvalido):
            a_decimal(valor, PRECIO)

    @pytest.mark.parametrize("valor", ["abc", "", float("nan"), float("inf"), "NaN", "-Infinity", np.float64("nan")])
    def test_no_numericos_o_no_finitos(self, valor):
        with pytest.raises(ValorDecimalInvalido):
            a_decimal(valor, SALDO)


class TestValidacionPorCampo:
    @pytest.mark.parametrize("validacion", [PRECIO, CANTIDAD])
    def test_precio_y_cantidad_estrictamente_positivos(self, validacion):
        with pytest.raises(ValorDecimalInvalido, match="mayor que cero"):
            a_decimal(0, validacion)
        with pytest.raises(ValorDecimalInvalido, match="negativo"):
            a_decimal(-1, validacion)

    @pytest.mark.parametrize("validacion", [SALDO, LIMITE])
    def test_saldo_y_limite_admiten_cero(self, validacion):
        assert a_decimal(0, validacion) == Decimal("0")
        with pytest.raises(ValorDecimalInvalido, match="negativo"):
            a_decimal("-0.01", validacion)

    @pytest.mark.parametrize("valor", ["12.345", 12.345, "0.001"])
    def test_precio_mas_de_dos_decimales(self, valor):
        with pytest.raises(ValorDecimalInvalido, match="más de 2 decimales"):
            a_decimal(valor, PRECIO)

    def test_ceros_finales_no_cuentan_como_decimales(self):
        assert a_decimal("120.000", PRECIO) == Decimal("120")

    def test_saldo_mas_de_dos_decimales(self):
        with pytest.raises(ValorDecimalInvalido):
            a_decimal("10.005", SALDO)

    def test_cantidad_debe_ser_entera(self):
        assert a_decimal(3.0, CANTIDAD) == Decimal("3")
        with pytest.raises(ValorDecimalInvalido, match="entero"):
            a_decimal("2.5", CANTIDAD)

    @pytest.mark.parametrize("valor", [0, 3, 100])
    def test_porcentaje_en_rango(self, valor):
        assert a_decimal(valor, PORCENTAJE) == Decimal(valor)

    @pytest.mark.parametrize("valor", [101, -1, "2.5"])
    def test_porcentaje_fuera_de_rango_o_no_entero(self, valor):
        with pytest.raises(ValorDecimalInvalido):
            a_decimal(valor, PORCENTAJE)

    def test_el_error_nombra_el_campo(self):
        with pytest.raises(ValorDecimalInvalido) as info:
            a_decimal(-5, PRECIO, "precio[G01]")
        assert info.value.campo == "precio[G01]"


class TestRedondeo:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("0.005", "0.01"),
            ("0.015", "0.02"),
            ("0.025", "0.03"),  # con redondeo bancario daría 0.02
            ("2.675", "2.68"),  # con float daría 2.67
            ("6.365", "6.37"),
            ("1.0049999", "1.00"),
            ("1.004", "1.00"),
            ("1.995", "2.00"),
            ("0", "0.00"),
            ("1164", "1164.00"),
        ],
    )
    def test_mitad_hacia_arriba_a_centavos(self, valor, esperado):
        resultado = redondear_centavos(Decimal(valor))
        assert resultado == Decimal(esperado)
        assert str(resultado) == esperado

    def test_rechaza_float(self):
        with pytest.raises(TypeError):
            redondear_centavos(2.675)

    def test_exigir_decimal(self):
        exigir_decimal(Decimal("1"), Decimal("2"))
        with pytest.raises(TypeError):
            exigir_decimal(Decimal("1"), 2.0)
        with pytest.raises(TypeError):
            exigir_decimal(3)
