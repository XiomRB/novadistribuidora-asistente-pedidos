import random
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from app.datos.carga import cargar_datos
from app.dominio.cierre import cerrar_pedido
from app.dominio.errores import ClienteNoEncontrado, EntradaCierreIncoherente, ValorDecimalInvalido
from app.dominio.resultado import Estado, LineaSolicitada, Motivo, Pendiente, Sustitucion
from tests.fixtures import datos_sinteticos as ds

D = Decimal
MARTES = datetime(2026, 12, 1, 10, 0)
AMBIGUO = Pendiente(Motivo.PRODUCTO_AMBIGUO, "gaseosa", ("G01", "G02", "G03"))
NO_EXISTE = Pendiente(Motivo.PRODUCTO_NO_EXISTE, "cerveza")


def L(sku, cantidad):
    return LineaSolicitada(sku, D(cantidad))


def cerrar(datos, cliente="K01", lineas=(), pendientes=(), eventos=True, sustituciones=(), fecha_hora=MARTES):
    return cerrar_pedido(
        cliente_id=cliente,
        fecha_hora=fecha_hora,
        lineas_solicitadas=lineas,
        pendientes=pendientes,
        hay_eventos_pedido=eventos,
        datos=datos,
        sustituciones=sustituciones,
    )


def _sin_nada(r):
    return r.lineas == () and r.pendientes == () and r.motivos_revision == () and r.sustituciones == ()


class TestTransiciones:
    def test_t4_sin_eventos_fuera_de_alcance(self, datos):
        r = cerrar(datos, eventos=False)
        assert r.estado is Estado.FUERA_DE_ALCANCE and _sin_nada(r)
        assert r.total == D("0.00") and r.fecha_entrega is None

    def test_t4_consulta_pura_con_credito_excedido_no_se_revisa(self, datos):
        # K03: saldo (1200) > límite (1000). Sin eventos no se evalúa crédito.
        r = cerrar(datos, cliente="K03", eventos=False)
        assert r.estado is Estado.FUERA_DE_ALCANCE and r.motivos_revision == ()

    def test_t5_pedido_vaciado_fuera_de_alcance_sin_credito(self, datos):
        r = cerrar(datos, cliente="K03", eventos=True)
        assert r.estado is Estado.FUERA_DE_ALCANCE and _sin_nada(r)

    def test_t6_solo_pendientes(self, datos):
        r = cerrar(datos, pendientes=[AMBIGUO])
        assert r.estado is Estado.REQUIERE_REVISION
        assert r.lineas == () and r.total == D("0.00") and r.fecha_entrega is None
        assert r.motivos_revision == (Motivo.PRODUCTO_AMBIGUO,)
        assert r.pendientes == (AMBIGUO,)

    def test_t6_solo_pendientes_con_saldo_sobre_limite(self, datos):
        r = cerrar(datos, cliente="K03", pendientes=[NO_EXISTE])
        assert r.motivos_revision == (Motivo.PRODUCTO_NO_EXISTE, Motivo.CREDITO_EXCEDIDO)

    def test_t7_confirmado(self, datos):
        r = cerrar(datos, lineas=[L("G01", 2), L("C01", 5)])
        assert r.estado is Estado.CONFIRMADO
        assert [(l.sku, l.cantidad, l.precio_unitario, l.descuento_pct, l.subtotal) for l in r.lineas] == [
            ("G01", D(2), D("100.0"), D(0), D("200.00")),
            ("C01", D(5), D("6.7"), D(2), D("32.83")),  # 5 × 6.70 × 0.98 = 32.83
        ]
        assert r.total == D("232.83")
        assert r.fecha_entrega == date(2026, 12, 3)  # martes -> jueves
        assert r.motivos_revision == () and r.pendientes == ()

    def test_t7_solo_sustituciones_sigue_confirmado(self, datos):
        sust = Sustitucion("G03", "G02", D(3))
        r = cerrar(datos, lineas=[L("G02", 3)], sustituciones=[sust])
        assert r.estado is Estado.CONFIRMADO and r.sustituciones == (sust,)

    def test_t8_lineas_con_credito_excedido(self, datos):
        # K02: saldo == límite; cualquier total positivo excede.
        r = cerrar(datos, cliente="K02", lineas=[L("L01", 1)])
        assert r.estado is Estado.REQUIERE_REVISION
        assert r.motivos_revision == (Motivo.CREDITO_EXCEDIDO,)
        assert r.total == D("45.25") and r.fecha_entrega == date(2026, 12, 2)  # visita miércoles y sábado
        assert r.pendientes == ()

    def test_t9_lineas_y_pendientes(self, datos):
        r = cerrar(datos, lineas=[L("G01", 1)], pendientes=[NO_EXISTE, AMBIGUO, NO_EXISTE])
        assert r.estado is Estado.REQUIERE_REVISION
        assert r.motivos_revision == (Motivo.PRODUCTO_NO_EXISTE, Motivo.PRODUCTO_AMBIGUO)
        assert len(r.pendientes) == 3 and r.fecha_entrega is not None

    def test_t10_lineas_pendientes_y_credito(self, datos):
        r = cerrar(datos, cliente="K02", lineas=[L("G01", 1)], pendientes=[AMBIGUO])
        assert r.motivos_revision == (Motivo.PRODUCTO_AMBIGUO, Motivo.CREDITO_EXCEDIDO)

    def test_orden_de_lineas_conservado(self, datos):
        r = cerrar(datos, lineas=[L("S01", 1), L("G01", 1), L("C01", 1)])
        assert [l.sku for l in r.lineas] == ["S01", "G01", "C01"]

    def test_descuentos_por_escala_en_cierre(self, datos):
        r = cerrar(datos, cliente="K04", lineas=[L("G01", 10), L("G02", 20), L("S01", 10), L("L01", 50)])
        assert [l.descuento_pct for l in r.lineas] == [D(3), D(5), D(3), D(0)]

    def test_tipos_decimales_en_resultado(self, datos):
        r = cerrar(datos, lineas=[L("G01", 2)])
        valores = [r.total] + [v for l in r.lineas for v in (l.cantidad, l.precio_unitario, l.descuento_pct, l.subtotal)]
        assert all(isinstance(v, Decimal) for v in valores)


class TestLimitesDeCredito:
    @pytest.fixture
    def datos_credito(self, tmp_path):
        clientes = pd.concat(
            [
                ds.clientes(),
                pd.DataFrame(
                    [
                        ("K09", "T", "P", "M", "lunes", 3000, 2800),
                        ("K10", "T", "P", "M", "lunes", 2999.99, 2800),
                    ],
                    columns=ds.clientes().columns,
                ),
            ],
            ignore_index=True,
        )
        return cargar_datos(ds.escribir(tmp_path / "d", {"clientes": clientes}))

    def test_total_justo_en_el_limite_confirma(self, datos_credito):
        r = cerrar(datos_credito, cliente="K09", lineas=[L("G01", 2)])  # 2800 + 200 = 3000
        assert r.estado is Estado.CONFIRMADO

    def test_un_centavo_sobre_el_limite_requiere_revision(self, datos_credito):
        r = cerrar(datos_credito, cliente="K10", lineas=[L("G01", 2)])  # 3000 > 2999.99
        assert r.estado is Estado.REQUIERE_REVISION and r.motivos_revision == (Motivo.CREDITO_EXCEDIDO,)


class TestCoherenciaDeSustituciones:
    @pytest.fixture
    def datos_dos_agotados(self, tmp_path):
        """Agrega G04 (agotado, sustituto G02) para que dos productos sustituyan hacia la misma línea."""
        productos = pd.concat(
            [
                ds.productos(),
                pd.DataFrame(
                    [("G04", "Gaseosa Sol 1 L", "Sol", "bebidas", "1 L", "fardo", 12, 80.0, False, "G02")],
                    columns=ds.productos().columns,
                ),
            ],
            ignore_index=True,
        )
        return cargar_datos(ds.escribir(tmp_path / "d", {"productos": productos}))

    def test_sustitucion_igual_a_la_linea(self, datos):
        r = cerrar(datos, lineas=[L("G02", 3)], sustituciones=[Sustitucion("G03", "G02", D(3))])
        assert r.estado is Estado.CONFIRMADO and r.lineas[0].cantidad == D(3)

    def test_linea_combina_unidades_directas_y_sustituidas(self, datos):
        # 2 fardos de G02 pedidos directamente + 3 que sustituyen a G03.
        r = cerrar(datos, lineas=[L("G02", 5)], sustituciones=[Sustitucion("G03", "G02", D(3))])
        assert r.estado is Estado.CONFIRMADO and r.lineas[0].cantidad == D(5)

    def test_varias_sustituciones_acumuladas_en_la_misma_linea(self, datos_dos_agotados):
        sustituciones = [Sustitucion("G03", "G02", D(3)), Sustitucion("G04", "G02", D(4))]
        r = cerrar(datos_dos_agotados, lineas=[L("G02", 7)], sustituciones=sustituciones)
        assert r.estado is Estado.CONFIRMADO and r.sustituciones == tuple(sustituciones)

    def test_varias_sustituciones_mas_unidades_directas(self, datos_dos_agotados):
        sustituciones = [Sustitucion("G03", "G02", D(3)), Sustitucion("G04", "G02", D(4))]
        r = cerrar(datos_dos_agotados, lineas=[L("G02", 10)], sustituciones=sustituciones)
        assert r.estado is Estado.CONFIRMADO

    def test_suma_sustituida_superior_a_la_linea_se_rechaza(self, datos_dos_agotados):
        sustituciones = [Sustitucion("G03", "G02", D(3)), Sustitucion("G04", "G02", D(4))]
        with pytest.raises(EntradaCierreIncoherente, match="superan la cantidad de la línea"):
            cerrar(datos_dos_agotados, lineas=[L("G02", 6)], sustituciones=sustituciones)

    def test_sustitucion_unica_superior_a_la_linea_se_rechaza(self, datos):
        with pytest.raises(EntradaCierreIncoherente, match="superan la cantidad de la línea"):
            cerrar(datos, lineas=[L("G02", 2)], sustituciones=[Sustitucion("G03", "G02", D(3))])


class TestEntradasIncoherentes:
    def test_cliente_inexistente(self, datos):
        with pytest.raises(ClienteNoEncontrado):
            cerrar(datos, cliente="K99", lineas=[L("G01", 1)])

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"eventos": False, "lineas": [L("G01", 1)]},
            {"eventos": False, "pendientes": [AMBIGUO]},
            {"lineas": [L("ZZ1", 1)]},
            {"lineas": [L("G03", 1)]},  # agotado: la sustitución corresponde a E1b
            {"lineas": [L("G01", 1), L("G01", 2)]},
            {"lineas": [L("G01", 1)], "sustituciones": [Sustitucion("G03", "G02", D(1))]},  # sin línea G02
            {"lineas": [L("G02", 1)], "sustituciones": [Sustitucion("G01", "G02", D(1))]},  # G01 está disponible
            {"lineas": [L("G02", 1)], "sustituciones": [Sustitucion("C02", "G02", D(1))]},  # C02 no tiene ese sustituto
        ],
    )
    def test_rechazadas(self, datos, kwargs):
        with pytest.raises(EntradaCierreIncoherente):
            cerrar(datos, **kwargs)

    @pytest.mark.parametrize("cantidad", [D(0), D("2.5"), D(-1)])
    def test_cantidad_invalida(self, datos, cantidad):
        with pytest.raises(ValorDecimalInvalido):
            cerrar(datos, lineas=[LineaSolicitada("G01", cantidad)])

    @pytest.mark.parametrize("cantidad", [2.0, 2])
    def test_cantidad_no_decimal_rechazada(self, datos, cantidad):
        with pytest.raises(TypeError):
            cerrar(datos, lineas=[LineaSolicitada("G01", cantidad)])  # type: ignore[arg-type]


class TestPropiedadesAleatorias:
    def test_estado_respeta_prioridad_e_invariantes(self, datos):
        """2.000 combinaciones aleatorias (semilla fija): prioridad de estados e invariantes."""
        rnd = random.Random(20261122)
        disponibles = [s for s, p in datos.productos.items() if p.disponible]
        pendientes_posibles = [AMBIGUO, NO_EXISTE, Pendiente(Motivo.CANTIDAD_NO_CONVERTIBLE, "x", ("C01",))]
        for _ in range(2000):
            cliente = rnd.choice(list(datos.clientes))
            eventos = rnd.random() < 0.85
            lineas = [L(s, rnd.randint(1, 60)) for s in rnd.sample(disponibles, rnd.randint(0, 4))] if eventos else []
            pendientes = rnd.sample(pendientes_posibles, rnd.randint(0, 2)) if eventos else []
            r = cerrar(datos, cliente=cliente, lineas=lineas, pendientes=pendientes, eventos=eventos)
            if not eventos or (not lineas and not pendientes):
                assert r.estado is Estado.FUERA_DE_ALCANCE
            elif pendientes:
                assert r.estado is Estado.REQUIERE_REVISION
            if r.estado is Estado.CONFIRMADO:
                assert r.lineas and not r.pendientes and not r.motivos_revision
