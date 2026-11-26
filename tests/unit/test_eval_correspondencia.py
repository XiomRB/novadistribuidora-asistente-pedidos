"""E2c-1: correspondencia determinista (K1-K4, sobrantes, mixtos), con los valores de las tablas
aprobadas. Datos sintéticos: SKU del catálogo sintético y claves con la marca «zqx»."""

import itertools
import random

import pytest

from evaluacion.correspondencia import bases
from tests.fixtures.evaluacion_e2c import AM, CN, NE, L, P, anot, co, cuerpo, esperado, exhaustiva, medir


def K(**valores):
    base = {"K1": 0, "K2": 0, "K3": 0, "K4": 0, "sobrantes": 0, "mixtos": 0}
    base.update(valores)
    return base


def caso_(e_lineas=(), e_pend=(), o_lineas=(), o_pend=(), claves=None, consultados=()):
    esp = esperado(e_lineas, e_pend)
    cue = cuerpo(esperado(o_lineas, o_pend))
    n = len(e_lineas) + len(e_pend)
    claves = claves or [[f"zqxp{i}"] for i in range(n)]
    return esp, cue, anot(*claves, consultados=consultados)


# (nombre, esperado, obtenido, anotación, resultado). Cada caso se prueba además en todas las permutaciones.
TABLA = {
    # ------------------------------------------------ K3
    "K3-1": (caso_(e_pend=[P("GS6", "GS2"), P("GS6", "GS2")], o_pend=[P("GS6", "GS2")]), K(K3=1)),
    "K3-2": (caso_(e_pend=[P("GS6", "GS2"), P("GS6", "GS2")], o_pend=[P("GS6", "GS2"), P("GS6", "GS2")]), K()),
    "K3-3": (caso_(e_pend=[P("GS6", "GS2"), P("GS2", "GL2")], o_pend=[P("GS2")]), K(K3=1)),
    "K3-4": (caso_(e_pend=[P("GS6", "GS2"), P("GS2", "GL2")], o_pend=[P("GS2"), P("GS6")]), K()),
    "K3-5": (caso_(e_lineas=[L("GS6", 2)], e_pend=[P("GS6", "GS2")], o_lineas=[L("GS6", 2)]), K(K3=1)),
    "K3-6": (caso_(e_pend=[P(motivo=NE), P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqxkiwi"), P(motivo=NE, texto="otra cosa")],
                   claves=[["zqxkiwi"], ["zqxtortas"]]), K(K3=1, sobrantes=1)),
    "K3-7": (caso_(e_pend=[P(motivo=NE), P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqxkiwi y zqxtortas")], claves=[["zqxkiwi"], ["zqxtortas"]]), K(K3=1)),
    "K3-9": (caso_(e_lineas=[L("GS6")], o_pend=[P(motivo=NE, texto="gaseosa sol 600")], claves=[["gaseosa sol"]]), K()),
    "K3-10": (caso_(e_lineas=[L("GS6")], o_pend=[P(motivo=NE, texto="gaseosa")], claves=[["gaseosa sol"]]), K(K3=1, sobrantes=1)),
    "K3-11": (caso_(e_lineas=[L("GS6")], o_pend=[P("PH4", texto="gaseosa sol")], claves=[["gaseosa sol"]]), K(K3=1, sobrantes=1)),
    "K3-12": (caso_(e_lineas=[L("GS6")], o_lineas=[L("CL1")], claves=[["gaseosa sol"]]), K(K1=1, K3=1)),
    "K3-13": (caso_(e_lineas=[L("GS6")], o_pend=[P(motivo=NE, texto="gaseosas sol")], claves=[["gaseosa sol"]]), K(K3=1, sobrantes=1)),
    "K3-14": (caso_(e_lineas=[L("GS6")], e_pend=[P(motivo=NE)], o_pend=[P(motivo=NE, texto="gaseosa sol y zqxkiwi")], claves=[["gaseosa sol"], ["zqxkiwi"]]), K(K3=1)),
    # ------------------------------------------------ K4
    "K4-1": (caso_(e_lineas=[L("FN1", 2)], o_lineas=[L("FN1", 2)], o_pend=[P(motivo=NE, texto="zqxtortas")], consultados=[co(claves=["zqxtortas"])]), K(K4=1)),
    "K4-2": (caso_(e_lineas=[L("GS6", 2)], o_lineas=[L("GS6", 2)], consultados=[co(pedido_como=0)]), K()),
    "K4-3": (caso_(e_lineas=[L("FN1", 2)], o_lineas=[L("FN1", 2), L("CL1")], consultados=[co("CL1")]), K(K4=1)),
    "K4-4": (caso_(e_lineas=[L("FN1"), L("GS6")], o_lineas=[L("CL1"), L("FN1")], consultados=[co("CL1")]), K(K3=1, K4=1)),
    "K4-5": (caso_(e_lineas=[L("FN1", 2)], o_lineas=[L("FN1", 2)], o_pend=[P(motivo=NE, texto="zqxtortas")]), K(sobrantes=1)),
    "K4-6": (caso_(e_lineas=[L("GS6")], o_lineas=[L("GS6")], o_pend=[P("GS6")], consultados=[co(pedido_como=0)]), K(sobrantes=1)),
    "K4-7": (caso_(o_lineas=[L("CL1")], o_pend=[P("CL1")], consultados=[co("CL1")]), K(K4=2)),
    "K4-8": (caso_(e_lineas=[L("FN1"), L("GS6")], o_lineas=[L("FN1"), L("GS6"), L("CL1")], consultados=[co("CL1"), co(pedido_como=1)]), K(K4=1)),
    "K4-10": (caso_(e_lineas=[L("GS6")], o_lineas=[L("GS6")], o_pend=[P("GS6", "GS2")], consultados=[co("GS2")]), K(K4=1)),
    "K4-11": (caso_(e_lineas=[L("GS6")], o_lineas=[L("GS2")], o_pend=[P("GS6", "GS2")], consultados=[co("GS2")]), K(K4=1, mixtos=1)),
    "K4-12": (caso_(o_pend=[P("GS2", "CL1")], consultados=[co("GS2"), co("CL1")]), K(K4=1)),
    "K4-15": (caso_(e_lineas=[L("FN1"), L("FR1")], e_pend=[P("PC2", "PE2")], o_lineas=[L("FN1"), L("FR1")], o_pend=[P("PC2", "PE2"), P("PC2", "PE2")],
                    consultados=[co(pedido_como=2)]), K(sobrantes=1)),
    "K4-16": (caso_(e_pend=[P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqxkiwi zqxtortas")], claves=[["zqxkiwi"]], consultados=[co(claves=["zqxtortas"])]), K(mixtos=1)),
    "K4-18": (caso_(e_lineas=[L("GS6")], o_pend=[P("GS6", "GS2")], consultados=[co("GS2")]), K(mixtos=1)),
    "K4-19": (caso_(e_lineas=[L("GS6")], e_pend=[P("PC2", "PE2")], o_lineas=[L("GS6")], o_pend=[P("GS6", "GS2"), P("PC2", "PE2")], consultados=[co("GS2")]), K(K4=1)),
    "K4-20": (caso_(e_lineas=[L("GS6")], o_pend=[P("GS6", "GS2"), P("GS6")], consultados=[co("GS2")]), K(K4=1)),
    "K4-21": (caso_(e_lineas=[L("GS6")], o_pend=[P("GS6"), P("GS6")]), K(sobrantes=1)),
    "K4-22": (caso_(e_lineas=[L("GS6"), L("FR1")], o_lineas=[L("GS6")], o_pend=[P("GS6", "GS2")], consultados=[co("GS2")]), K(K3=1, K4=1)),
    # ------------------------------------------------ prioridades lexicográficas, texto y nodos ficticios
    "LEX-1": (caso_(e_pend=[P("A", "B"), P("B", "C"), P("C", "D")], o_lineas=[L("D")], o_pend=[P("A", "Z"), P("A", "B"), P("B", "C")]), K(sobrantes=1)),
    "TX-1": (caso_(e_pend=[P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqxkiwi")], claves=[["zqxkiwi"]], consultados=[co(claves=["zqxtortas"])]), K()),
    "TX-3": (caso_(e_pend=[P(motivo=NE), P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqxkiwi zqxpan")], claves=[["zqxkiwi"], ["zqxpan"]]), K(K3=1)),
    "TX-4": (caso_(e_pend=[P(motivo=NE), P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqxkiwi zqxpan"), P(motivo=NE, texto="zqxpan zqxkiwi")],
                   claves=[["zqxkiwi"], ["zqxpan"]]), K()),
    "TX-5": (caso_(e_pend=[P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqxkiwi zqxtortas"), P(motivo=NE, texto="zqxkiwi")], claves=[["zqxkiwi"]],
                   consultados=[co(claves=["zqxtortas"])]), K(K4=1)),
    "TX-6": (caso_(e_lineas=[L("GS6")], o_pend=[P(motivo=NE, texto="gaseosa sol 600")], claves=[["gaseosa sol"]]), K()),
    "TX-7a": (caso_(e_pend=[P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqx kiwi fresco")], claves=[["zqx kiwi"]], consultados=[co(claves=["kiwi fresco"])]), K(mixtos=1)),
    "TX-7b": (caso_(e_pend=[P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqx kiwi fresco"), P(motivo=NE, texto="zqx kiwi")], claves=[["zqx kiwi"]],
                    consultados=[co(claves=["kiwi fresco"])]), K(K4=1)),
    "TX-7c": (caso_(e_pend=[P(motivo=NE)], o_pend=[P(motivo=NE, texto="zqx kiwi fresco")], claves=[["zqx kiwi"]]), K()),
    "DUM-1": (caso_(e_lineas=[L("GS6"), L("GS6"), L("FN1")], o_lineas=[L("GS6")]), K(K3=2)),
    "DUM-2": (caso_(e_lineas=[L("GS6")], o_lineas=[L("GS6"), L("FN1"), L("CL1")], o_pend=[P("GS6")], consultados=[co("CL1")]), K(K1=1, K4=1, sobrantes=1)),
    "DUM-3": (caso_(o_lineas=[L("GS6")], o_pend=[P("GS6")]), K(K1=1, sobrantes=1)),
    "DUM-4": (caso_(e_lineas=[L("GS6")], e_pend=[P("PC2", "PE2")]), K(K3=2)),
    "DUM-5": (caso_(e_pend=[P("GS6", "GS2"), P("GS6", "GS2")], o_pend=[P("GS6")]), K(K3=1)),
    "W-2": (caso_(e_lineas=[L("GS6")], e_pend=[P("GS6", "GS2")], o_lineas=[L("GS2")], o_pend=[P("GS6", "GS2", "PC2")]), K()),
    "W-4": (caso_(e_lineas=[L("GS6")], o_lineas=[L("FN1")]), K(K1=1, K3=1)),
}


@pytest.mark.parametrize("nombre", sorted(TABLA))
def test_tabla_aprobada(nombre):
    (esp, cue, anotacion), esperado_k = TABLA[nombre]
    assert medir(esp, cue, anotacion)[0] == esperado_k


@pytest.mark.parametrize("nombre", sorted(TABLA))
def test_asignacion_y_recuentos_invariantes_ante_permutaciones(nombre):  # T-1, K4-17, C-4
    (esp, cue, anotacion), _ = TABLA[nombre]
    referencia = medir(esp, cue, anotacion)
    for lineas in itertools.permutations(cue["lineas"]):
        for pendientes in itertools.permutations(cue["pendientes"]):
            assert medir(esp, {**cue, "lineas": list(lineas), "pendientes": list(pendientes)}, anotacion) == referencia


@pytest.mark.parametrize("nombre", sorted(TABLA))
def test_kuhn_munkres_igual_a_la_busqueda_exhaustiva(nombre):  # T-3 (casos de la tabla)
    (esp, cue, anotacion), _ = TABLA[nombre]
    assert medir(esp, cue, anotacion)[1] == exhaustiva(esp, cue, anotacion)


def test_lex1_elige_tres_coincidencias_de_tipo_y_no_la_suma_ponderada():
    (esp, cue, anotacion), _ = TABLA["LEX-1"]
    trazabilidad = medir(esp, cue, anotacion)[1]
    opciones = [None if t[1] is None else __import__("json").loads(t[1])[3] for t in trazabilidad]
    assert opciones == [["A", "Z"], ["A", "B"], ["B", "C"]]  # 3 coincidencias de tipo, pureza 0


def test_items_identicos_se_asignan_por_rango_estable():  # T-2
    (esp, cue, anotacion), _ = TABLA["K4-21"]
    trazabilidad = medir(esp, cue, anotacion)[1]
    assert trazabilidad[0][2] == 0  # rango 0; el otro ítem idéntico queda libre


def test_empate_con_producto_sin_pareja_elige_el_menor_vector():  # T-4, DUM-5
    (esp, cue, anotacion), _ = TABLA["DUM-5"]
    trazabilidad = medir(esp, cue, anotacion)[1]
    assert trazabilidad[0][1] is not None and trazabilidad[1] == (1, None)


def test_dum1_el_producto_cero_recibe_el_unico_item():
    (esp, cue, anotacion), _ = TABLA["DUM-1"]
    trazabilidad = medir(esp, cue, anotacion)[1]
    assert trazabilidad[0][1] is not None and trazabilidad[1] == (1, None) and trazabilidad[2] == (2, None)


def test_w2_mas_emparejados_domina_a_tipo_pureza_y_desempate():
    (esp, cue, anotacion), _ = TABLA["W-2"]
    assert all(t[1] is not None for t in medir(esp, cue, anotacion)[1])  # 2 emparejados aunque la otra opción tenga más tipo


@pytest.mark.parametrize(("n", "m"), [(n, m) for n in range(9) for m in range(9)])
def test_w1_desigualdades_de_las_bases_y_big(n, m):
    b, big, t_max = bases(n, m)
    for k in range(4):
        assert b[k] > sum(n * b[l] for l in range(k + 1, 4)) + t_max
    assert big > sum(n * b[l] for l in range(4)) + t_max
    assert all(isinstance(x, int) for x in [*b, big, t_max])


def test_k2_por_cantidad_y_cnc_resuelto_como_linea():
    assert medir(esperado([L("FN1", 2)]), cuerpo(esperado([L("FN1", 3)])), anot(["zqxa"]))[0]["K2"] == 1
    assert medir(esperado(pendientes=[P("FN1", motivo=CN)]), cuerpo(esperado([L("FN1", 2)])), anot(["zqxa"]))[0]["K2"] == 1
    assert medir(esperado([L("FN1", 2)]), cuerpo(esperado(pendientes=[P("FN1", motivo=CN)])), anot(["zqxa"]))[0]["K2"] == 0


def test_k3_solo_en_casos_criticos():
    esp, cue = esperado([L("GS6")]), cuerpo(esperado())
    assert medir(esp, cue, anot(["zqxa"]))[0]["K3"] == 1
    assert medir(esp, cue, anot(["zqxa"], critico=False))[0]["K3"] == 0


def test_diferencial_2000_instancias_contra_la_busqueda_exhaustiva():  # T-3 / W-5
    rnd = random.Random(20261126)
    skus = ["A", "B", "C", "D", "E"]
    comparadas = 0
    for _ in range(2000):
        e_lineas = [L(rnd.choice(skus)) for _ in range(rnd.randint(0, 2))]
        e_pend = [P(*rnd.sample(skus, rnd.randint(0, 2)), motivo=rnd.choice([AM, NE, CN])) for _ in range(rnd.randint(0, 2))]
        o_lineas = [L(rnd.choice(skus)) for _ in range(rnd.randint(0, 2))]
        o_pend = [P(*rnd.sample(skus, rnd.randint(0, 2)), texto=" ".join(rnd.sample(["zqxk1", "zqxk2", "zqxk3", "zqxk4"], rnd.randint(0, 2))))
                  for _ in range(rnd.randint(0, 2))]
        n = len(e_lineas) + len(e_pend)
        claves = [[c] for c in rnd.sample(["zqxk1", "zqxk2", "zqxk3", "zqxu0", "zqxu1", "zqxu2", "zqxu3"], n)]  # distintas entre productos
        usados = {s for l in e_lineas for s in [l["sku"]]} | {s for p in e_pend for s in p["opciones"]}
        libres = [s for s in skus if s not in usados]
        consultados = [co(*([rnd.choice(libres)] if libres else []), claves=["zqxk4"])] if rnd.random() < 0.5 else []
        esp, cue, anotacion = esperado(e_lineas, e_pend), cuerpo(esperado(o_lineas, o_pend)), anot(*claves, consultados=consultados)
        referencia = medir(esp, cue, anotacion)
        assert referencia[1] == exhaustiva(esp, cue, anotacion)
        mezclado = {**cue, "lineas": rnd.sample(cue["lineas"], len(cue["lineas"])), "pendientes": rnd.sample(cue["pendientes"], len(cue["pendientes"]))}
        assert medir(esp, mezclado, anotacion) == referencia
        comparadas += 1
    assert comparadas == 2000
