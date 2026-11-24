"""D53 (fecha de corte), D70 (desempate determinista) y D73 (duplicados) del pedido habitual."""

import random
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest

from app.datos.carga import cargar_datos
from app.datos.modelos import Datos, LineaHistorica, PedidoHistorico
from app.dominio.errores import DatosInvalidos
from app.dominio.habitual import (
    MENSAJE_INCONSISTENTE,
    HistorialInconsistente,
    clave_natural,
    normalizar_identificador,
    ultimo_entregado,
)
from tests.fixtures import catalogo_e1b, historial_e1b2

DIA = date(2026, 12, 1)


def pedido(pid, fecha=date(2026, 11, 10), estado="entregado", cliente="K01", sku="GS6"):
    return PedidoHistorico(pid, cliente, fecha, estado, (LineaHistorica(sku, Decimal(1)),))


def datos_con(pedidos, cliente="K01") -> Datos:
    return Datos(
        productos=MappingProxyType({}), alias=(), escalas=MappingProxyType({}), clientes=MappingProxyType({}),
        historial=MappingProxyType({cliente: tuple(pedidos)}),
    )


def gana(*pids, fecha_recepcion=DIA, **kw):
    return ultimo_entregado(datos_con([pedido(p, **kw) for p in pids]), "K01", fecha_recepcion).pedido_id


class TestNormalizacion:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("PÉD-10", "ped-10"),  # É precompuesta (U+00C9)
            ("PÉD-10", "ped-10"),  # E + tilde combinante (U+0301)
            ("PED-１０", "ped-10"),  # dígitos de ancho completo
            ("straße-1", "strasse-1"),
            ("  PED   10  ", "ped 10"),
        ],
    )
    def test_nfkd_sin_marcas_casefold_espacios(self, texto, esperado):
        assert normalizar_identificador(texto) == esperado

    def test_clave_natural(self):
        assert clave_natural("PED-007") == ((1, "ped-"), (0, 7))
        assert clave_natural("A-2-10") == ((1, "a-"), (0, 2), (1, "-"), (0, 10))


class TestDesempateD70:
    @pytest.mark.parametrize(
        ("a", "b", "ganador"),
        [
            ("PED-10", "PED-9", "PED-10"),
            ("A-2-10", "A-2-9", "A-2-10"),
            ("A-3-1", "A-2-99", "A-3-1"),
            ("PED-007", "PED-7", "PED-7"),  # empate natural; desempate por el original ('7' > '0')
            ("ped-10", "PED-10", "ped-10"),  # empate sin mayúsculas; 'p' > 'P'
            ("PÉD-10", "PED-10", "PÉD-10"),  # empate sin tildes; 'É' > 'E'
            ("PÉD-10", "PÉD-10", "PÉD-10"),  # combinante frente a precompuesta: mismo natural
            ("PED-１０", "PED-10", "PED-１０"),  # ancho completo frente a ASCII
            ("STRASSE-1", "straße-1", "straße-1"),
            ("PED  10", "PED 10", "PED 10"),
            ("PED-10", "PED-10-1", "PED-10-1"),  # el más largo es mayor
            ("PED-10", "PEDX-1", "PEDX-1"),
        ],
    )
    def test_misma_fecha(self, a, b, ganador):
        assert gana(a, b) == ganador
        assert gana(b, a) == ganador  # el orden de entrada no influye

    def test_fecha_mayor_gana_antes_que_el_identificador(self):
        datos = datos_con([pedido("PED-99", date(2026, 11, 1)), pedido("PED-1", date(2026, 11, 20))])
        assert ultimo_entregado(datos, "K01", DIA).pedido_id == "PED-1"

    def test_mismo_dia_de_recepcion_se_incluye_posterior_no(self):
        datos = datos_con([pedido("P-1", date(2026, 11, 30)), pedido("P-2", DIA), pedido("P-3", date(2026, 12, 2))])
        assert ultimo_entregado(datos, "K01", DIA).pedido_id == "P-2"

    def test_cancelado_con_identificador_mayor_se_ignora(self):
        datos = datos_con([pedido("P-9"), pedido("P-10", estado="cancelado")])
        assert ultimo_entregado(datos, "K01", DIA).pedido_id == "P-9"

    def test_solo_cancelados_es_sin_historial(self):
        assert ultimo_entregado(datos_con([pedido("P-1", estado="cancelado")]), "K01", DIA) is None
        assert ultimo_entregado(datos_con([]), "K01", DIA) is None

    def test_independiente_del_orden_de_carga(self, tmp_path):
        base = historial_e1b2.historial()
        resultados = set()
        for semilla in range(10):
            mezclado = base.sample(frac=1, random_state=semilla).reset_index(drop=True)
            directorio = historial_e1b2.escribir(tmp_path / f"d{semilla}", mezclado)
            datos = cargar_datos(directorio)
            resultados.add(tuple(
                (c, (ultimo_entregado(datos, c, DIA) or pedido("ninguno")).pedido_id) for c in ("K01", "K02", "K03", "K04")
            ))
        assert resultados == {(("K01", "P-0010"), ("K02", "P-10"), ("K03", "ninguno"), ("K04", "P-20"))}

    def test_independiente_del_orden_del_objeto_datos(self):
        pedidos = [pedido("P-9"), pedido("P-10"), pedido("P-8"), pedido("P-11", estado="cancelado")]
        for orden in (pedidos, list(reversed(pedidos)), random.Random(3).sample(pedidos, len(pedidos))):
            assert ultimo_entregado(datos_con(orden), "K01", DIA).pedido_id == "P-10"


class TestDuplicadosD73:
    MARCA_CLIENTE = "KMARCA-77"
    MARCA_PEDIDO = "PMARCA-55"

    @pytest.mark.parametrize(
        "estados", [("entregado", "entregado"), ("entregado", "cancelado"), ("cancelado", "cancelado"), ("entregado", "entregado", "cancelado")]
    )
    def test_duplicado_lanza_error_sin_identificadores_en_el_mensaje(self, estados):
        pedidos = [pedido(self.MARCA_PEDIDO, estado=e, cliente=self.MARCA_CLIENTE) for e in estados]
        with pytest.raises(HistorialInconsistente) as info:
            ultimo_entregado(datos_con(pedidos, self.MARCA_CLIENTE), self.MARCA_CLIENTE, DIA)
        error = info.value
        assert error.cliente_id == self.MARCA_CLIENTE and error.pedido_id == self.MARCA_PEDIDO
        for texto in (str(error), repr(error), " ".join(map(str, error.args))):
            assert self.MARCA_CLIENTE not in texto and self.MARCA_PEDIDO not in texto
        assert error.args == (MENSAJE_INCONSISTENTE,)

    def test_mismo_identificador_en_clientes_distintos_no_es_error(self):
        datos = Datos(
            productos=MappingProxyType({}), alias=(), escalas=MappingProxyType({}), clientes=MappingProxyType({}),
            historial=MappingProxyType({"K01": (pedido("P-1"),), "K02": (pedido("P-1", cliente="K02"),)}),
        )
        assert ultimo_entregado(datos, "K01", DIA).pedido_id == "P-1"

    def test_cargador_e1a_agrupa_misma_cabecera(self, tmp_path):
        tabla = historial_e1b2.historial()
        extra = pd.DataFrame([("P-10", "K02", pd.Timestamp(2026, 11, 10), "CL1", 3, "entregado")], columns=tabla.columns)
        extra["fecha_entrega"] = extra["fecha_entrega"].astype("datetime64[ms]")
        datos = cargar_datos(historial_e1b2.escribir(tmp_path / "d", pd.concat([tabla, extra], ignore_index=True)))
        p10 = ultimo_entregado(datos, "K02", DIA)
        assert p10.pedido_id == "P-10" and [l.sku for l in p10.lineas] == ["DT5", "CL1"]

    def test_cargador_e1a_rechaza_cabecera_distinta(self, tmp_path):
        tabla = historial_e1b2.historial()
        extra = pd.DataFrame([("P-10", "K02", pd.Timestamp(2026, 11, 11), "CL1", 3, "entregado")], columns=tabla.columns)
        extra["fecha_entrega"] = extra["fecha_entrega"].astype("datetime64[ms]")
        with pytest.raises(DatosInvalidos) as info:
            cargar_datos(historial_e1b2.escribir(tmp_path / "d", pd.concat([tabla, extra], ignore_index=True)))
        assert "PEDIDO_INCOHERENTE" in {e.codigo for e in info.value.errores}


class TestFixture:
    def test_historial_sintetico_coherente(self, tmp_path):
        datos = cargar_datos(historial_e1b2.escribir(tmp_path / "d"))
        assert {a.codigo for a in datos.advertencias} == {"HISTORIAL_SKU_INEXISTENTE"}
        assert set(datos.productos) == {f[0] for f in catalogo_e1b.PRODUCTOS}
