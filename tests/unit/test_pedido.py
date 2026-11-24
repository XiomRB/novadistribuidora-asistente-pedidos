"""Orquestador `procesar_pedido`: orden de los pasos, D56/D72, D64, D68, descartes y clasificación."""

import json

import pytest

from app.dominio import pedido as modulo_pedido
from app.dominio.catalogo import IndiceCatalogo
from app.dominio.clasificacion import Clasificacion, clasificar
from app.dominio.entrada import EntradaPedido
from app.dominio.errores import ClienteNoEncontrado
from app.dominio.esquema_eventos import Interpretacion
from app.dominio.limites import LimitesExcedidos
from app.dominio.pedido import Recursos, procesar_pedido
from tests.fixtures.historial_e1b2 import MARTES, ev
from tests.fixtures.pedido_e1b2b import cargar_recursos, frag, lineas, pendientes, procesar


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("pedido"))


@pytest.fixture(scope="module")
def rec(base):
    return base[1]


def fragmentos(n, mensaje=0):
    return [frag(mensaje, "hola") for _ in range(n)]


# ====================================================================== orden de los pasos


class TestOrden:
    def test_cliente_inexistente_antes_que_cualquier_validacion(self, rec):
        invalida = {"eventos": [{"id": "e7", "mensaje": 5, "tipo": "agregar", "texto": "x"}]}
        with pytest.raises(ClienteNoEncontrado):
            procesar_pedido(EntradaPedido("NO-EXISTE", MARTES, ("hola",)), invalida, rec.datos, recursos=rec)

    @pytest.mark.parametrize(("consultas", "rechazadas"), [(11, 10), (20, 1), (1, 20)])
    def test_d72_21_fragmentos_se_rechazan_antes_del_anclaje(self, rec, monkeypatch, consultas, rechazadas):
        def anclar_prohibido(*args, **kwargs):
            raise AssertionError("no debe anclarse una interpretación que supera los límites")

        monkeypatch.setattr(modulo_pedido, "anclar", anclar_prohibido)
        with pytest.raises(LimitesExcedidos):
            procesar(rec, ["hola"], consultas=fragmentos(consultas), rechazadas=fragmentos(rechazadas))

    @pytest.mark.parametrize(("consultas", "rechazadas"), [(0, 0), (10, 10), (20, 0), (0, 20)])
    def test_d72_hasta_20_fragmentos_combinados_es_valido(self, rec, consultas, rechazadas):
        r = procesar(rec, ["hola"], consultas=fragmentos(consultas), rechazadas=fragmentos(rechazadas))
        assert (r.diagnostico.consultas, r.diagnostico.instrucciones_rechazadas) == (consultas, rechazadas)

    def test_indice_de_mensaje_fuera_de_rango(self, rec):
        with pytest.raises(ValueError):
            procesar(rec, ["hola"], [ev(1, 1, "agregar", "2 de frijol negro", producto="frijol negro")])

    def test_una_interpretacion_ya_validada_se_vuelve_a_validar_con_la_entrada(self, rec):
        # Validada con 2 mensajes, pero la entrada solo tiene 1.
        interp = Interpretacion.validar({"eventos": [ev(1, 1, "agregar", "frijol negro", producto="frijol negro")]}, 2)
        with pytest.raises(ValueError):
            procesar_pedido(EntradaPedido("K04", MARTES, ("hola",)), interp, rec.datos, recursos=rec)

    @pytest.mark.parametrize("forma", ["dict", "json", "modelo"])
    def test_acepta_dict_json_o_modelo(self, rec, forma):
        datos = {"eventos": [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")]}
        interp = {"dict": datos, "json": json.dumps(datos), "modelo": Interpretacion.validar(datos, 1)}[forma]
        r = procesar_pedido(EntradaPedido("K04", MARTES, ("2 de frijol negro",)), interp, rec.datos, recursos=rec)
        assert lineas(r) == [("FN1", "2")]


# ====================================================================== D68


class TestRecursos:
    def test_usa_el_indice_y_el_lexico_dados(self, base):
        ctx, _ = base
        recursos = Recursos.construir(ctx.datos, ctx.indice, ctx.lexico)
        assert recursos.indice is ctx.indice and recursos.lexico is ctx.lexico

    def test_con_recursos_no_reconstruye_el_indice(self, rec, monkeypatch):
        def prohibido(*args, **kwargs):
            raise AssertionError("no debe reconstruirse el índice")

        monkeypatch.setattr(IndiceCatalogo, "__init__", prohibido)
        r = procesar(rec, ["2 de frijol negro"], [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")])
        assert lineas(r) == [("FN1", "2")]

    def test_sin_recursos_los_construye(self, base):
        ctx, _ = base
        r = procesar_pedido(
            EntradaPedido("K04", MARTES, ("2 de frijol negro",)),
            {"eventos": [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")]},
            ctx.datos, indice=ctx.indice, lexico=ctx.lexico,
        )
        assert lineas(r) == [("FN1", "2")]


# ====================================================================== D64


def test_d64_pendientes_de_eventos_primero_y_omisiones_por_posicion(rec):
    mensaje = "mándeme aceite, 2 de cerveza, gaseosa y 3 de frijol negro"
    r = procesar(rec, [mensaje], [
        ev(1, 0, "agregar", "3 de frijol negro", producto="frijol negro", cantidad="3"),
        ev(2, 0, "agregar", "2 de cerveza", producto="cerveza", cantidad="2"),
    ])
    assert [(m, t) for m, t, _ in pendientes(r)] == [
        ("producto_no_existe", "cerveza"),  # de un evento (aunque aparece después de "aceite")
        ("producto_ambiguo", "aceite"),  # omisiones, por posición
        ("producto_ambiguo", "gaseosa"),
    ]
    assert lineas(r) == [("FN1", "3")]


def test_d64_habitual_antes_que_omisiones(rec):
    r = procesar(rec, ["gaseosa y lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K01")
    motivos = [m for m, _, _ in pendientes(r)]
    assert motivos[-1] == "producto_ambiguo" and pendientes(r)[-1][1] == "gaseosa"
    assert motivos[:-1] == ["agotado_sin_sustituto", "producto_no_existe"]


# ====================================================================== descartes (D36)


class TestDescartes:
    def test_sin_ancla(self, rec):
        r = procesar(rec, ["hola"], [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")])
        ((d,),) = [r.diagnostico.eventos_descartados]
        assert (d.evento, d.codigo, d.posicion) == ("e1", "SIN_ANCLA", None)
        assert r.cierre.lineas == () and r.clasificacion is Clasificacion.CONSULTA

    def test_evento_dentro_de_consulta_pura(self, rec):
        r = procesar(rec, ["¿Cuánto cuesta el aceite girasol?"], [ev(1, 0, "agregar", "aceite girasol", producto="aceite girasol")])
        ((d,),) = [r.diagnostico.eventos_descartados]
        assert (d.codigo, d.posicion) == ("DESCARTADO_CONSULTA", (0, 18, 32))
        assert r.cierre.estado.value == "fuera_de_alcance" and r.clasificacion is Clasificacion.CONSULTA

    def test_referencia_a_un_evento_descartado_es_invalida(self, rec):
        r = procesar(rec, ["¿tienen frijol negro? mándeme 2 de gaseosa sol 600", "mejor 5"], [
            ev(1, 0, "agregar", "frijol negro", producto="frijol negro"),
            ev(2, 0, "agregar", "2 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
            ev(3, 1, "corregir", "mejor 5", cantidad="5", ref="e1"),
        ])
        assert lineas(r) == [("GS6", "2")]
        assert {e.evento: e.codigo for e in r.diagnostico.eventos}["e3"] == "REF_INVALIDA"


# ====================================================================== clasificación


@pytest.mark.parametrize(
    ("efectivos", "creo", "quedan", "omision", "esperado"),
    [
        (0, False, False, 0, Clasificacion.CONSULTA),
        (0, False, False, 1, Clasificacion.PEDIDO),
        (1, True, True, 0, Clasificacion.PEDIDO),
        (1, True, False, 0, Clasificacion.PEDIDO_CANCELADO),
        (1, True, False, 1, Clasificacion.PEDIDO),
        (1, False, False, 0, Clasificacion.SIN_EFECTO),
    ],
)
def test_tabla_de_clasificacion(efectivos, creo, quedan, omision, esperado):
    c = clasificar(eventos_efectivos=efectivos, creo_items=creo, quedan_items=quedan, pendientes_omision=omision)
    assert c is esperado and c.hay_eventos_pedido is (esperado is not Clasificacion.CONSULTA)


def test_diagnostico_completo(rec):
    r = procesar(rec, ["2 de frijol negro. ¿tienen cafe?"], [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")],
                 consultas=[frag(0, "¿tienen cafe?")], rechazadas=[frag(0, "2 de frijol negro")])
    d = r.diagnostico
    assert (d.clasificacion, d.consultas, d.instrucciones_rechazadas, d.omisiones, d.habitual_usado) == ("PEDIDO", 1, 1, (), False)
    assert d.salida_lineas == ("i1",) and d.eventos[0].codigo == "RESUELTO"
