"""Plegado de eventos (E1b-2a) sobre el catálogo sintético de E1b-1 y el historial de E1b-2a."""

from decimal import Decimal

import pytest

from app.dominio.plegado import Clase, EstadoItem
from tests.fixtures.historial_e1b2 import cargar_contexto, ev, lineas, pendientes, plegar_mensajes

D = Decimal


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("e1b2"))


def correr(ctx, mensajes, eventos, cliente="K04"):
    return plegar_mensajes(ctx, mensajes, eventos, cliente=cliente)


def items(rp):
    return {i.id: i for i in rp.items}


def codigos(rp):
    return {e.evento: e.codigo for e in rp.eventos}


SOL600 = ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2", unidad_texto="fardos")


# ====================================================================== agregar


class TestAgregar:
    def test_suma_por_sku(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600 y 3 de gaseosa sol 600"], [
            SOL600, ev(2, 0, "agregar", "3 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="3"),
        ])
        assert lineas(sal) == [("GS6", "5")] and len(rp.items) == 1
        assert [a.accion for a in rp.acciones] == ["CREAR", "SUMAR"]

    def test_no_convertible_se_agrega_aparte_y_la_linea_se_conserva(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600 y 36 botellas de gaseosa sol 600"], [
            SOL600,
            ev(2, 0, "agregar", "36 botellas de gaseosa sol 600", producto="gaseosa sol 600", cantidad="36", unidad="suelta", unidad_texto="botellas"),
        ])
        assert lineas(sal) == [("GS6", "2")] and pendientes(rp) == [("cantidad_no_convertible", ("GS6",))]

    def test_d62_cantidad_cero_sin_efecto(self, ctx):
        rp, sal, _ = correr(ctx, ["0 de gaseosa sol 600"], [ev(1, 0, "agregar", "0 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="0")])
        assert rp.items == [] and codigos(rp) == {"e1": "CANTIDAD_CERO"} and not rp.creo_items

    def test_d38_agotado_sin_sustituto_un_solo_pendiente(self, ctx):
        rp, _, _ = correr(ctx, ["galletas luna chocolate: 2, y 3 de galletas luna chocolate"], [
            ev(1, 0, "agregar", "galletas luna chocolate: 2", producto="galletas luna chocolate", cantidad="2"),
            ev(2, 0, "agregar", "3 de galletas luna chocolate", producto="galletas luna chocolate", cantidad="3"),
        ])
        assert [(p.motivo.value, p.texto, p.opciones) for p in rp.pendientes()] == [
            ("agotado_sin_sustituto", "Galletas Luna Chocolate", ("GC1",))
        ]

    def test_ambiguo_y_no_existe(self, ctx):
        rp, _, _ = correr(ctx, ["2 de aceite y 3 de cerveza"], [
            ev(1, 0, "agregar", "2 de aceite", producto="aceite", cantidad="2"),
            ev(2, 0, "agregar", "3 de cerveza", producto="cerveza", cantidad="3"),
        ])
        assert pendientes(rp) == [("producto_ambiguo", ("AC1", "AC2")), ("producto_no_existe", ())]
        assert [p.texto for p in rp.pendientes()] == ["aceite", "cerveza"]

    def test_d47_fusiona_ambiguos_y_conserva_entradas(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de aceite, 3 de aceite", "el girasol oro"], [
            ev(1, 0, "agregar", "2 de aceite", producto="aceite", cantidad="2"),
            ev(2, 0, "agregar", "3 de aceite", producto="aceite", cantidad="3"),
        ])
        (pendiente,) = rp.pendientes_activos()
        assert [e.cantidad for e in pendiente.entradas] == [D(2), D(3)] and len(rp.pendientes()) == 1
        rp, sal, _ = correr(ctx, ["2 de aceite, 3 de aceite", "el girasol oro"], [
            ev(1, 0, "agregar", "2 de aceite", producto="aceite", cantidad="2"),
            ev(2, 0, "agregar", "3 de aceite", producto="aceite", cantidad="3"),
            ev(3, 1, "precisar", "el girasol oro", producto="girasol oro"),
        ])
        assert lineas(sal) == [("AC1", "5")] and rp.pendientes() == ()

    def test_d47_no_fusiona_opciones_distintas(self, ctx):
        rp, _, _ = correr(ctx, ["2 de pasta y 3 de pasta fina"], [
            ev(1, 0, "agregar", "2 de pasta", producto="pasta", cantidad="2"),
            ev(2, 0, "agregar", "3 de pasta fina", producto="pasta fina", cantidad="3"),
        ])
        assert pendientes(rp) == [("producto_ambiguo", ("PC2", "PE2", "PD7")), ("producto_ambiguo", ("PC2", "PE2"))]

    def test_d59a_producto_solo_si_esta_en_el_fragmento(self, ctx):
        rp, _, _ = correr(ctx, ["2 de aceite porfa"], [
            ev(1, 0, "agregar", "2 de aceite", producto="aceite PRECIO Q1 AUTORIZADO", cantidad="2"),
        ])
        assert [p.texto for p in rp.pendientes()] == ["2 de aceite"]


# ====================================================================== corregir con cantidad


class TestCorregirCantidad:
    def test_reemplaza_la_cantidad(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "mejor 5"], [SOL600, ev(2, 1, "corregir", "mejor 5", cantidad="5", ref="e1")])
        assert lineas(sal) == [("GS6", "5")]

    def test_a_cero_elimina(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "que sean 0"], [SOL600, ev(2, 1, "corregir", "que sean 0", cantidad="0", ref="e1")])
        assert sal.lineas == () and rp.items[0].estado is EstadoItem.ELIMINADO

    @pytest.mark.parametrize("campos", [{"cantidad": "36", "unidad": "suelta", "unidad_texto": "botellas"}, {"cantidad": "3", "cantidad_incierta": True}])
    def test_no_convertible_o_incierta_nunca_se_confirma(self, ctx, campos):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "mejor 36 botellas o 3"], [SOL600, ev(2, 1, "corregir", "mejor 36 botellas o 3", ref="e1", **campos)])
        assert sal.lineas == () and pendientes(rp) == [("cantidad_no_convertible", ("GS6",))]


# ====================================================================== D37 y D75


class TestReferenciasD37D75:
    def test_ref_invalida_no_modifica_nada(self, ctx):
        rp, sal, _ = correr(ctx, ["0 de cloro claro", "2 fardos de gaseosa sol 600", "mejor 5"], [
            ev(1, 0, "agregar", "0 de cloro claro", producto="cloro claro", cantidad="0"),
            ev(2, 1, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
            ev(3, 2, "corregir", "mejor 5", cantidad="5", ref="e1"),
        ])
        assert lineas(sal) == [("GS6", "2")] and codigos(rp)["e3"] == "REF_INVALIDA"
        assert pendientes(rp)[0][0] == "producto_ambiguo"

    def test_d75_regla1_producto_activo_en_otro_item(self, ctx):
        mensajes = ["2 de frijol negro y 3 fardos de gaseosa sol 600", "del frijol negro que sean 10"]
        rp, sal, _ = correr(ctx, mensajes, [
            ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2"),
            ev(2, 0, "agregar", "3 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="3"),
            ev(3, 1, "corregir", "del frijol negro que sean 10", producto="frijol negro", cantidad="10", ref="e2"),
        ])
        assert lineas(sal) == [("FN1", "2"), ("GS6", "3")]
        assert codigos(rp)["e3"] == "REF_CONFLICTO" and pendientes(rp) == [("producto_ambiguo", ("GS6", "FN1"))]

    def test_d75_regla2_producto_nuevo_permite_reemplazo(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "no, mejor arroz sierra de libra"], [
            SOL600, ev(2, 1, "corregir", "no, mejor arroz sierra de libra", producto="arroz sierra de libra", ref="e1"),
        ])
        assert lineas(sal) == [("AR1", "2")] and rp.pendientes() == ()

    def test_d75_regla2_mismo_caso_con_arroz_ya_activo(self, ctx):
        mensajes = ["2 fardos de gaseosa sol 600 y 1 de arroz sierra de libra", "no, mejor arroz sierra de libra"]
        rp, sal, _ = correr(ctx, mensajes, [
            SOL600,
            ev(2, 0, "agregar", "1 de arroz sierra de libra", producto="arroz sierra de libra", cantidad="1"),
            ev(3, 1, "corregir", "no, mejor arroz sierra de libra", producto="arroz sierra de libra", ref="e1"),
        ])
        assert lineas(sal) == [("GS6", "2"), ("AR1", "1")] and codigos(rp)["e3"] == "REF_CONFLICTO"

    def test_d75_regla3_ambiguo_con_una_opcion_activa(self, ctx):
        mensajes = ["2 de aceite girasol oro y 3 fardos de gaseosa sol 600", "de esa mejor aceite"]
        rp, sal, _ = correr(ctx, mensajes, [
            ev(1, 0, "agregar", "2 de aceite girasol oro", producto="aceite girasol oro", cantidad="2"),
            ev(2, 0, "agregar", "3 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="3"),
            ev(3, 1, "corregir", "de esa mejor aceite", producto="aceite", ref="e2"),
        ])
        assert lineas(sal) == [("AC1", "2"), ("GS6", "3")] and codigos(rp)["e3"] == "REF_CONFLICTO"

    def test_d75_regla5_el_destino_no_cuenta_como_otro(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "de la gaseosa sol 600 que sean 4"], [
            SOL600, ev(2, 1, "corregir", "de la gaseosa sol 600 que sean 4", producto="gaseosa sol 600", cantidad="4", ref="e1"),
        ])
        assert lineas(sal) == [("GS6", "4")]

    def test_d75_quitar_con_ref_no_elimina_si_la_descripcion_es_otro_item(self, ctx):
        mensajes = ["2 de frijol negro y 3 fardos de gaseosa sol 600", "quite el frijol negro"]
        rp, sal, _ = correr(ctx, mensajes, [
            ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2"),
            ev(2, 0, "agregar", "3 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="3"),
            ev(3, 1, "quitar", "quite el frijol negro", producto="frijol negro", ref="e2"),
        ])
        assert lineas(sal) == [("FN1", "2"), ("GS6", "3")] and codigos(rp)["e3"] == "REF_CONFLICTO"


# ====================================================================== D10, D13 y D76 (sin ref)


class TestSinRefD76:
    def test_un_unico_item_compatible(self, ctx):
        mensajes = ["2 fardos de gaseosa sol 600 y 1 fardo de gaseosa sol de 2 litros", "no, mejor 4 de la de 2 litros"]
        rp, sal, _ = correr(ctx, mensajes, [
            SOL600,
            ev(2, 0, "agregar", "1 fardo de gaseosa sol de 2 litros", producto="gaseosa sol", presentacion="2 litros", cantidad="1", unidad_texto="fardo"),
            ev(3, 1, "corregir", "no, mejor 4 de la de 2 litros", presentacion="2 litros", cantidad="4"),
        ])
        assert lineas(sal) == [("GS6", "2"), ("GS2", "4")]

    def test_varios_compatibles_d13(self, ctx):
        mensajes = ["1 de gaseosa sol de 2 litros y 1 de gaseosa luz de 2 litros", "de la de 2 litros que sean 4"]
        rp, sal, _ = correr(ctx, mensajes, [
            ev(1, 0, "agregar", "1 de gaseosa sol de 2 litros", producto="gaseosa sol", presentacion="2 litros", cantidad="1"),
            ev(2, 0, "agregar", "1 de gaseosa luz de 2 litros", producto="gaseosa luz", presentacion="2 litros", cantidad="1"),
            ev(3, 1, "corregir", "de la de 2 litros que sean 4", presentacion="2 litros", cantidad="4"),
        ])
        assert lineas(sal) == [("GS2", "1"), ("GL2", "1")] and codigos(rp)["e3"] == "DESTINO_AMBIGUO"
        assert pendientes(rp) == [("producto_ambiguo", ("GS2", "GL2"))]

    def test_ninguno_compatible_se_trata_como_agregar(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "y gaseosa luz de 2 litros, 3"], [
            SOL600, ev(2, 1, "corregir", "gaseosa luz de 2 litros, 3", producto="gaseosa luz", presentacion="2 litros", cantidad="3"),
        ])
        assert lineas(sal) == [("GS6", "2"), ("GL2", "3")]

    def test_falta_de_informacion_no_es_compatibilidad(self, ctx):
        # "la grande" no aporta atributos: no hay coincidencia positiva con ningún ítem.
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "que sean 5 de la grande"], [
            SOL600, ev(2, 1, "corregir", "que sean 5 de la grande", producto="la grande", cantidad="5"),
        ])
        assert ("GS6", "2") in lineas(sal) and codigos(rp)["e2"] != "CORREGIR_CANTIDAD"


# ====================================================================== D48 (corregir y precisar)


@pytest.mark.parametrize("tipo", ["corregir", "precisar"])
class TestD48:
    def evento(self, tipo, texto, **campos):
        return ev(2, 1, tipo, texto, ref="e1", **campos)

    def test_atributo_incompatible_un_producto_reemplaza(self, ctx, tipo):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "no, mejor la de 2 litros"], [SOL600, self.evento(tipo, "no, mejor la de 2 litros", presentacion="2 litros")])
        assert lineas(sal) == [("GS2", "2")] and rp.items[0].estado is EstadoItem.REEMPLAZADO

    def test_informacion_compatible_conserva(self, ctx, tipo):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "la gaseosa sol"], [SOL600, self.evento(tipo, "la gaseosa sol", producto="gaseosa sol")])
        assert lineas(sal) == [("GS6", "2")] and codigos(rp)["e2"] == "PRECISION_COMPATIBLE"

    def test_no_degrada_a_un_producto_menos_especifico(self, ctx, tipo):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "la gaseosa"], [SOL600, self.evento(tipo, "la gaseosa", producto="gaseosa")])
        assert lineas(sal) == [("GS6", "2")] and rp.pendientes() == ()

    def test_varios_productos_conserva_y_crea_pendiente(self, ctx, tipo):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa de 600", "mejor la de 2 litros"], [
            ev(1, 0, "agregar", "2 fardos de gaseosa de 600", producto="gaseosa de 600", cantidad="2"),
            self.evento(tipo, "mejor la de 2 litros", presentacion="2 litros"),
        ])
        assert lineas(sal) == [("GS6", "2")] and pendientes(rp) == [("producto_ambiguo", ("GS2", "GL2"))]

    def test_d48a_sin_producto_conserva_y_no_existe(self, ctx, tipo):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "mejor la de 5 litros"], [SOL600, self.evento(tipo, "mejor la de 5 litros", presentacion="5 litros")])
        assert lineas(sal) == [("GS6", "2")] and pendientes(rp) == [("producto_no_existe", ())]
        assert [m.medidas for m in rp.medidas] == [("5000ml",)]

    def test_sin_evidencia_util_sin_cambios(self, ctx, tipo):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "no, mejor esa"], [SOL600, self.evento(tipo, "no, mejor esa", producto="esa")])
        assert lineas(sal) == [("GS6", "2")] and rp.pendientes() == ()

    def test_cambio_de_grupo(self, ctx, tipo):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "no, mejor arroz sierra de libra"], [SOL600, self.evento(tipo, "no, mejor arroz sierra de libra", producto="arroz sierra de libra")])
        assert lineas(sal) == [("AR1", "2")]

    def test_d48b_reconvierte_la_cantidad_expresada(self, ctx, tipo):
        # 48 botellas: 2 fardos de GS6 (UPE 24) -> 8 fardos de GS2 (UPE 6).
        rp, sal, _ = correr(ctx, ["48 botellas de gaseosa sol 600", "mejor la de 2 litros"], [
            ev(1, 0, "agregar", "48 botellas de gaseosa sol 600", producto="gaseosa sol 600", cantidad="48", unidad="suelta", unidad_texto="botellas"),
            self.evento(tipo, "mejor la de 2 litros", presentacion="2 litros"),
        ])
        assert lineas(sal) == [("GS2", "8")]

    def test_d48c_reconversion_no_exacta_es_atomica(self, ctx, tipo):
        # 12 botellas: 2 fardos de GS2 (UPE 6); en GS6 (UPE 24) no es exacto.
        rp, sal, _ = correr(ctx, ["12 botellas de gaseosa sol de 2 litros", "mejor la de 600"], [
            ev(1, 0, "agregar", "12 botellas de gaseosa sol de 2 litros", producto="gaseosa sol", presentacion="2 litros", cantidad="12", unidad="suelta", unidad_texto="botellas"),
            self.evento(tipo, "mejor la de 600", presentacion="600 ml"),
        ])
        linea = rp.items[0]
        assert (linea.estado, linea.clase, linea.sku, linea.cantidad) == (EstadoItem.ACTIVO, Clase.LINEA, "GS2", D(2))
        assert lineas(sal) == [("GS2", "2")] and pendientes(rp) == [("cantidad_no_convertible", ("GS6",))]
        pendiente = rp.pendientes_activos()[0]
        assert pendiente.origen == ["e2"] and codigos(rp)["e2"] == "REEMPLAZO_NO_CONVERTIBLE"
        assert "REEMPLAZO_RECHAZADO" in [a.accion for a in rp.acciones if a.item == linea.id]


def test_d48_con_cantidad_nueva(ctx):
    rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "mejor 4 de la de 2 litros"], [
        SOL600, ev(2, 1, "corregir", "mejor 4 de la de 2 litros", presentacion="2 litros", cantidad="4", ref="e1"),
    ])
    assert lineas(sal) == [("GS2", "4")]


# ====================================================================== atomicidad sobre pendientes ambiguos


class TestAtomicidadPendiente:
    def base(self, texto="2 de aceite", producto="aceite", cantidad="2", **k):
        return ev(1, 0, "agregar", texto, producto=producto, cantidad=cantidad, **k)

    def test_d63_solo_cantidad(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de aceite", "mejor 5"], [self.base(), ev(2, 1, "corregir", "mejor 5", cantidad="5", ref="e1")])
        (p,) = rp.pendientes_activos()
        assert p.motivo.value == "producto_ambiguo" and [e.cantidad for e in p.entradas] == [D(5)]

    def test_d69_solo_producto_resuelve(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de aceite", "el girasol oro"], [self.base(), ev(2, 1, "precisar", "el girasol oro", producto="girasol oro", ref="e1")])
        assert lineas(sal) == [("AC1", "2")] and rp.pendientes() == ()

    def test_d69_producto_unico_con_entrada_no_convertible(self, ctx):
        rp, sal, _ = correr(ctx, ["30 botellas de aceite", "el girasol oro"], [
            self.base("30 botellas de aceite", cantidad="30", unidad="suelta", unidad_texto="botellas"),
            ev(2, 1, "precisar", "el girasol oro", producto="girasol oro", ref="e1"),
        ])
        assert sal.lineas == () and pendientes(rp) == [("cantidad_no_convertible", ("AC1",))]

    def test_d69_sigue_ambiguo_con_opciones_reducidas(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de pasta", "la pasta fina"], [
            self.base("2 de pasta", producto="pasta"), ev(2, 1, "precisar", "la pasta fina", producto="pasta fina", ref="e1"),
        ])
        assert pendientes(rp) == [("producto_ambiguo", ("PC2", "PE2"))]

    def test_d69_sin_producto(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de aceite", "el aceite de 5 litros"], [self.base(), ev(2, 1, "precisar", "el aceite de 5 litros", producto="aceite", presentacion="5 litros", ref="e1")])
        assert pendientes(rp) == [("producto_no_existe", ())]

    def test_producto_y_cantidad_convertible(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de aceite", "mejor 4 del girasol oro"], [self.base(), ev(2, 1, "corregir", "mejor 4 del girasol oro", producto="girasol oro", cantidad="4", ref="e1")])
        assert lineas(sal) == [("AC1", "4")]

    def test_producto_y_cantidad_no_convertible(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de aceite", "30 botellas del girasol oro"], [
            self.base(), ev(2, 1, "corregir", "30 botellas del girasol oro", producto="girasol oro", cantidad="30", unidad="suelta", unidad_texto="botellas", ref="e1"),
        ])
        (p,) = rp.pendientes_activos()
        assert sal.lineas == () and (p.motivo.value, p.opciones) == ("cantidad_no_convertible", ("AC1",))
        assert [e.cantidad for e in p.entradas] == [D(30)] and "e2" in p.origen

    def test_producto_y_cantidad_varios(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de galletas", "3 de las galletas luna"], [
            self.base("2 de galletas", producto="galletas"), ev(2, 1, "corregir", "3 de las galletas luna", producto="galletas luna", cantidad="3", ref="e1"),
        ])
        (p,) = rp.pendientes_activos()
        assert (p.motivo.value, p.opciones, [e.cantidad for e in p.entradas]) == ("producto_ambiguo", ("GV1", "GC1"), [D(3)])

    def test_producto_y_cantidad_ninguno(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de aceite", "3 del aceite de 5 litros"], [
            self.base(), ev(2, 1, "corregir", "3 del aceite de 5 litros", producto="aceite", presentacion="5 litros", cantidad="3", ref="e1"),
        ])
        (p,) = rp.pendientes_activos()
        assert (p.motivo.value, [e.cantidad for e in p.entradas]) == ("producto_no_existe", [D(3)])


# ====================================================================== quitar


class TestQuitar:
    def test_por_descripcion(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600 y 2 de frijol negro", "sin el frijol"], [
            SOL600, ev(2, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2"), ev(3, 1, "quitar", "sin el frijol", producto="frijol"),
        ])
        assert lineas(sal) == [("GS6", "2")]

    def test_d13_varios_compatibles(self, ctx):
        rp, sal, _ = correr(ctx, ["2 de frijol negro y 2 de frijol rojo", "sin el frijol"], [
            ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2"),
            ev(2, 0, "agregar", "2 de frijol rojo", producto="frijol rojo", cantidad="2"),
            ev(3, 1, "quitar", "sin el frijol", producto="frijol"),
        ])
        assert lineas(sal) == [("FN1", "2"), ("FR1", "2")] and pendientes(rp) == [("producto_ambiguo", ("FN1", "FR1"))]

    def test_d58_quitar_ya_eliminado_sin_efecto(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "quitela", "quitela de nuevo"], [
            SOL600, ev(2, 1, "quitar", "quitela", ref="e1"), ev(3, 2, "quitar", "quitela de nuevo", ref="e1"),
        ])
        assert sal.lineas == () and rp.pendientes() == () and codigos(rp)["e3"] == "QUITAR_YA_ELIMINADO"

    def test_agregar_despues_de_quitar_crea_item_nuevo(self, ctx):
        rp, sal, _ = correr(ctx, ["2 fardos de gaseosa sol 600", "no, quite la gaseosa", "bueno si, 4 de gaseosa sol 600"], [
            SOL600, ev(2, 1, "quitar", "quite la gaseosa", ref="e1"),
            ev(3, 2, "agregar", "4 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="4"),
        ])
        assert lineas(sal) == [("GS6", "4")] and [i.id for i in rp.items] == ["i1", "i2"]

    def test_sin_destino(self, ctx):
        rp, sal, _ = correr(ctx, ["quiteme la gaseosa del pedido de ayer"], [ev(1, 0, "quitar", "quiteme la gaseosa del pedido de ayer", producto="gaseosa")])
        assert rp.items == [] and codigos(rp)["e1"] == "QUITAR_SIN_DESTINO" and not rp.creo_items

    def test_d57_exclusion_anticipada_mismo_mensaje(self, ctx):
        rp, sal, _ = plegar_mensajes(ctx, ["sin la pasta, mándeme lo de siempre"], [
            ev(1, 0, "quitar", "sin la pasta", producto="pasta"), ev(2, 0, "habitual", "lo de siempre"),
        ], cliente="K01")
        assert "PC2" not in [s for s, _ in lineas(sal)] and codigos(rp)["e1"] == "QUITAR_DIFERIDO_APLICADO"

    def test_d57_otro_mensaje_no_se_aplica(self, ctx):
        rp, sal, _ = plegar_mensajes(ctx, ["sin la pasta", "mándeme lo de siempre"], [
            ev(1, 0, "quitar", "sin la pasta", producto="pasta"), ev(2, 1, "habitual", "lo de siempre"),
        ], cliente="K01")
        assert "PC2" in [s for s, _ in lineas(sal)] and codigos(rp)["e1"] == "QUITAR_SIN_DESTINO"


# ====================================================================== habitual


class TestHabitual:
    def test_expansion_k01(self, ctx):
        rp, sal, _ = plegar_mensajes(ctx, ["lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K01")
        assert [(i.sku, i.cantidad) for i in rp.lineas_activas()] == [("GS3", D(3)), ("AC2", D(1)), ("PC2", D(2))]
        assert [(p.motivo.value, p.texto, p.opciones) for p in rp.pendientes()] == [
            ("agotado_sin_sustituto", "Galletas Luna Chocolate", ("GC1",)),
            ("producto_no_existe", "ZZ9", ()),
        ]
        assert rp.habitual_usado is True

    def test_repetido_se_expande_una_vez(self, ctx):
        rp, _, _ = plegar_mensajes(ctx, ["lo de siempre, lo de siempre"], [ev(1, 0, "habitual", "lo de siempre"), ev(2, 0, "habitual", "lo de siempre")], cliente="K01")
        assert len(rp.lineas_activas()) == 3 and codigos(rp)["e2"] == "HABITUAL_REPETIDO"

    def test_d07_sin_historial(self, ctx):
        rp, sal, _ = plegar_mensajes(ctx, ["lo de siempre porfa"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K03")
        assert [(p.motivo.value, p.texto, p.opciones) for p in rp.pendientes()] == [("producto_ambiguo", "lo de siempre", ())]
        assert rp.habitual_usado is False

    def test_suma_con_agregado_del_mismo_sku(self, ctx):
        rp, sal, _ = plegar_mensajes(ctx, ["lo de siempre y 2 de pasta fina coditos"], [
            ev(1, 0, "habitual", "lo de siempre"), ev(2, 0, "agregar", "2 de pasta fina coditos", producto="pasta fina coditos", cantidad="2"),
        ], cliente="K01")
        assert ("PC2", D(4)) in [(i.sku, i.cantidad) for i in rp.lineas_activas()]

    def test_exclusion_de_un_agotado_elimina_su_pendiente(self, ctx):
        rp, _, _ = plegar_mensajes(ctx, ["lo de siempre pero sin las galletas"], [
            ev(1, 0, "habitual", "lo de siempre"), ev(2, 0, "quitar", "sin las galletas", producto="galletas"),
        ], cliente="K01")
        assert [p.motivo.value for p in rp.pendientes()] == ["producto_no_existe"]

    def test_ref_al_evento_habitual_con_descripcion(self, ctx):
        rp, _, _ = plegar_mensajes(ctx, ["lo de siempre", "de la pasta que sean 5"], [
            ev(1, 0, "habitual", "lo de siempre"), ev(2, 1, "corregir", "de la pasta que sean 5", producto="pasta", cantidad="5", ref="e1"),
        ], cliente="K01")
        assert ("PC2", D(5)) in [(i.sku, i.cantidad) for i in rp.lineas_activas()]

    def test_d53_mismo_dia_incluido(self, ctx):
        rp, _, _ = plegar_mensajes(ctx, ["lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K04")
        assert [(i.sku, i.cantidad) for i in rp.lineas_activas()] == [("LP3", D(1))]


# ====================================================================== prueba B (trazabilidad)


class TestPruebaB:
    MENSAJES = ["2 fardos de gaseosa sol 600", "4 de frijol negro", "3 de gaseosa sol 600", "no, mejor la de 2 litros", "quitela", "otra vez"]

    def base(self):
        return [
            SOL600,
            ev(2, 1, "agregar", "4 de frijol negro", producto="frijol negro", cantidad="4"),
            ev(3, 2, "agregar", "3 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="3"),
            ev(4, 3, "corregir", "no, mejor la de 2 litros", presentacion="2 litros", ref="e1"),
            ev(5, 4, "quitar", "quitela", ref="e4"),
        ]

    def comprobar_cadena(self, rp):
        i = items(rp)
        assert (i["i1"].estado, i["i1"].sucesor, i["i1"].origen) == (EstadoItem.REEMPLAZADO, "i3", ["e1", "e3"])
        assert (i["i3"].estado, i["i3"].sku, i["i3"].cantidad, i["i3"].origen) == (EstadoItem.ELIMINADO, "GS2", D(5), ["e1", "e3", "e4"])
        testigo = i["i2"]
        assert (testigo.estado, testigo.sku, testigo.cantidad) == (EstadoItem.ACTIVO, "FN1", D(4))
        assert [a.accion for a in rp.acciones if a.item == "i2"] == ["CREAR"]
        assert len({x.id for x in rp.items}) == len(rp.items)

    def test_a_corregir_crea_item_nuevo(self, ctx):
        rp, sal, _ = correr(ctx, self.MENSAJES, self.base() + [ev(6, 5, "corregir", "otra vez", cantidad="7", ref="e1")])
        self.comprobar_cadena(rp)
        assert items(rp)["i4"].sku == "GS2" and lineas(sal) == [("FN1", "4"), ("GS2", "7")]

    def test_b_quitar_sin_efecto(self, ctx):
        rp, sal, _ = correr(ctx, self.MENSAJES, self.base() + [ev(6, 5, "quitar", "otra vez", ref="e1")])
        self.comprobar_cadena(rp)
        assert lineas(sal) == [("FN1", "4")] and codigos(rp)["e6"] == "QUITAR_YA_ELIMINADO" and len(rp.items) == 3

    def test_c_precisar_crea_pendiente(self, ctx):
        rp, sal, _ = correr(ctx, self.MENSAJES, self.base() + [ev(6, 5, "precisar", "otra vez", producto="gaseosa", ref="e1")])
        self.comprobar_cadena(rp)
        assert lineas(sal) == [("FN1", "4")] and pendientes(rp) == [("producto_ambiguo", ("GS2",))]

    def test_sin_ref_con_dos_lineas_compatibles(self, ctx):
        mensajes = ["2 fardos de gaseosa sol 600 y 1 de gaseosa sol 3 L", "mejor 5 de la gaseosa sol"]
        rp, sal, _ = correr(ctx, mensajes, [
            SOL600,
            ev(2, 0, "agregar", "1 de gaseosa sol 3 L", producto="gaseosa sol", presentacion="3 L", cantidad="1"),
            ev(3, 1, "corregir", "mejor 5 de la gaseosa sol", producto="gaseosa sol", cantidad="5"),
        ])
        assert [(i.sku, i.cantidad) for i in rp.lineas_activas()] == [("GS6", D(2)), ("GS3", D(1))]
        assert codigos(rp)["e3"] == "DESTINO_AMBIGUO"


@pytest.mark.parametrize("ref", [None, "e1"])
def test_precisar_pendiente_agotado_al_mismo_sku_no_forma_ciclo(ctx, ref):
    # Regresión (fuzz, caso 156): el pendiente que se reemplaza no puede absorber a su reemplazo.
    extra = {"ref": ref} if ref else {}
    rp, _, _ = correr(ctx, ["galletas luna chocolate y galletas, mejor 2"], [
        ev(1, 0, "agregar", "galletas luna chocolate", producto="galletas luna chocolate"),
        ev(2, 0, "precisar", "galletas", producto="galletas", **extra),
        ev(3, 0, "corregir", "mejor 2", cantidad="2", ref="e1"),  # recorre la cadena de sucesores
    ])
    todos = items(rp)
    assert all(i.sucesor != i.id for i in rp.items)
    assert (todos["i1"].estado, todos["i1"].sucesor) == (EstadoItem.REEMPLAZADO, "i2")
    (activo,) = rp.pendientes_activos()
    assert activo.id == "i2" and activo.sku == "GC1" and activo.entradas[0].cantidad == D(2)
