"""Fuzz del orquestador: 2.000 pedidos de principio a fin (semilla fija, catálogo sintético).

Sobre las secuencias del fuzz del plegado (E1b-2a) se agregan consultas puras con eventos
inyectados, menciones omitidas, instrucciones rechazadas y marcadores únicos.
"""

import random
from decimal import Decimal

import pytest

from app.dominio.clasificacion import Clasificacion
from app.dominio.estado import verificar_invariantes
from app.dominio.resultado import Estado
from tests.fixtures.historial_e1b2 import MARTES
from tests.fixtures.pedido_e1b2b import cargar_recursos, frag, procesar
from tests.integracion.test_plegado_fuzz import generar

MARCA = "ZQXFUZZ"
CONSULTAS = ["¿tienen gaseosa luz de 2 litros?", "¿a cómo está el aceite palma?", "¿ya llegó el cafe monte?", "¿hay frijol rojo?"]
OMITIDOS = ["y frijol rojo campo", "también 2 cajas de cafe monte molido", "- pasta fina espagueti", "y lo de siempre", "una docena de cloro claro"]
COMENTARIOS = ["la gaseosa llegó caliente", "gracias por todo", f"saludos de {MARCA}"]


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("pedido_fuzz"))[1]


def _valido(e: dict) -> bool:
    describe = bool(e.get("producto") or e.get("presentacion") or e.get("candidatos"))
    if e["tipo"] in ("corregir", "precisar", "quitar") and not (e.get("ref") or describe):
        return False
    if e["tipo"] == "precisar" and not describe:
        return False
    return not (e["tipo"] == "corregir" and not (describe or "cantidad" in e or e.get("cantidad_incierta")))


def limpiar(eventos: list[dict]) -> list[dict]:
    """Quita los eventos omitidos y las referencias colgantes, y renumera e1, e2, …"""
    while True:
        ids = {e["id"] for e in eventos}
        eventos = [{k: v for k, v in e.items() if not (k == "ref" and v not in ids)} for e in eventos]
        validos = [e for e in eventos if _valido(e)]
        if len(validos) == len(eventos):
            break
        eventos = validos
    mapa = {e["id"]: f"e{k}" for k, e in enumerate(eventos, start=1)}
    return [dict(e, id=mapa[e["id"]], **({"ref": mapa[e["ref"]]} if "ref" in e else {})) for e in eventos]


def caso(rnd: random.Random):
    mensaje, eventos = generar(rnd, rnd.randint(0, 10)) if rnd.random() < 0.9 else ("hola", [])
    eventos = limpiar([e for e in eventos if rnd.random() < 0.9 or e["tipo"] != "agregar"])  # algunos se "omiten"
    extra, consultas, rechazadas = [], [], []
    if rnd.random() < 0.4:
        pregunta = rnd.choice(CONSULTAS)
        extra.append(pregunta)
        if rnd.random() < 0.5:
            consultas.append(frag(1, pregunta))
        if rnd.random() < 0.5:  # evento erróneo dentro de la consulta: debe descartarse
            producto = pregunta.strip("¿?").split(" ", 3)[-1]
            eventos.append({"id": f"e{len(eventos) + 1}", "mensaje": 1, "tipo": "agregar", "texto": producto, "producto": producto})
    if rnd.random() < 0.4:
        extra.append(rnd.choice(OMITIDOS))
    if rnd.random() < 0.3:
        comentario = rnd.choice(COMENTARIOS)
        extra.append(comentario)
        if rnd.random() < 0.5:
            rechazadas.append(frag(1, comentario))
    mensajes = [f"{MARCA} {mensaje}"] + ([". ".join(extra)] if extra else [])
    return mensajes, eventos, consultas, rechazadas


def test_fuzz_pedido(rec):
    rnd = random.Random(20261125)
    vistos = {c: 0 for c in Clasificacion}
    for numero in range(2000):
        mensajes, eventos, consultas, rechazadas = caso(rnd)
        cliente = rnd.choice(["K01", "K02", "K03", "K04"])
        r = procesar(rec, mensajes, eventos, cliente=cliente, fecha_hora=MARTES, consultas=consultas, rechazadas=rechazadas)
        c = r.cierre
        verificar_invariantes(c)
        vistos[r.clasificacion] += 1
        if c.estado is Estado.CONFIRMADO:
            assert c.lineas and not c.pendientes, numero
        for linea in c.lineas:
            assert isinstance(linea.cantidad, Decimal) and linea.cantidad > 0 and linea.cantidad == linea.cantidad.to_integral_value(), numero
            assert rec.datos.productos[linea.sku].disponible, numero
        # Las omisiones nunca crean líneas: cada línea de salida viene de un ítem del plegado.
        assert len(r.diagnostico.salida_lineas) == len(c.lineas), numero
        if r.clasificacion is Clasificacion.CONSULTA:
            assert c.estado is Estado.FUERA_DE_ALCANCE and not c.lineas and not c.pendientes, numero
        if r.clasificacion in (Clasificacion.PEDIDO_CANCELADO, Clasificacion.SIN_EFECTO):
            assert c.estado is Estado.FUERA_DE_ALCANCE, numero
        assert MARCA not in repr(r.diagnostico) and MARCA not in r.mensaje_cliente, numero
        assert r.mensaje_cliente.startswith("¡") and r.mensaje_cliente.count("¡") >= 1
    assert all(vistos.values()), vistos  # el fuzz recorre las cuatro clasificaciones
