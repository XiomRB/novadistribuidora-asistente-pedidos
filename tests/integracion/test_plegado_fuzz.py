"""Fuzz del plegado: 2.000 secuencias aleatorias de eventos (semilla fija) sobre el catálogo sintético."""

import random
from decimal import Decimal

import pytest

from app.dominio.cierre import cerrar_pedido
from app.dominio.estado import verificar_invariantes
from app.dominio.plegado import Clase, EstadoItem
from app.dominio.resultado import Estado
from tests.fixtures.historial_e1b2 import MARTES, cargar_contexto, plegar_mensajes

DESCRIPCIONES = [
    ("gaseosa sol 600", None), ("gaseosa", "2 litros"), ("gaseosa luz", "2 litros"), ("gaseosa sol", "3 L"),
    ("frijol negro", None), ("frijol", None), ("aceite", None), ("aceite girasol oro", None), ("aceite palma", None),
    ("pasta", None), ("pasta fina coditos", None), ("galletas luna chocolate", None), ("galletas", None),
    ("papel nube 12", None), ("cerveza", None), ("arroz sierra de libra", None), (None, "2 litros"), (None, "5 litros"),
    ("cafe monte instantaneo", None), ("cloro claro", None),
]
UNIDADES = [(None, "no_indicada"), ("fardos", "venta"), ("botellas", "suelta"), ("cajas", "venta"), ("docena", "docena"), ("pacas", "otra")]


def generar(rnd: random.Random, n: int):
    eventos, textos = [], []
    for i in range(1, n + 1):
        tipo = rnd.choices(["agregar", "corregir", "precisar", "quitar", "habitual"], [5, 3, 2, 2, 1])[0]
        producto, presentacion = rnd.choice(DESCRIPCIONES)
        texto = f"frase{i} {producto or ''} {presentacion or ''}".strip()
        e = {"id": f"e{i}", "mensaje": 0, "tipo": tipo, "texto": texto}
        ref = f"e{rnd.randint(1, i - 1)}" if i > 1 and rnd.random() < 0.6 else None
        if tipo == "habitual":
            pass
        elif tipo == "quitar":
            if ref:
                e["ref"] = ref
            if not ref or rnd.random() < 0.4:
                e["producto"], e["presentacion"] = producto, presentacion
            if not (e.get("ref") or e.get("producto") or e.get("presentacion")):
                e["producto"] = "gaseosa"
        else:
            if tipo != "agregar" and ref:
                e["ref"] = ref
            if tipo in ("agregar", "precisar") or rnd.random() < 0.6:
                e["producto"], e["presentacion"] = producto, presentacion
            if tipo != "precisar" and (tipo == "agregar" or rnd.random() < 0.7):
                cantidad = rnd.choice(["0", "1", "2", "3", "6", "12", "24", "36", "48", "0.5", None])
                if cantidad is not None:
                    e["cantidad"] = cantidad
                unidad_texto, unidad = rnd.choice(UNIDADES)
                e["unidad"], e["unidad_texto"] = unidad, unidad_texto
                e["cantidad_incierta"] = rnd.random() < 0.05
            if tipo == "precisar" and not (e.get("producto") or e.get("presentacion")):
                e["producto"] = "gaseosa"
            if tipo == "corregir" and not (e.get("producto") or e.get("presentacion") or "cantidad" in e or e.get("cantidad_incierta")):
                e["cantidad"] = "2"
            if tipo == "corregir" and not e.get("ref") and not (e.get("producto") or e.get("presentacion")):
                e["producto"] = "gaseosa"
            if rnd.random() < 0.2:
                e["candidatos"] = rnd.sample(["GS6", "GS2", "GL2", "AC1", "FN1", "ZZZ"], 2)
        e = {k: v for k, v in e.items() if v is not None}
        eventos.append(e)
        textos.append(texto)
    return ". ".join(textos), eventos


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("fuzz"))


def test_fuzz_plegado(ctx):
    rnd = random.Random(20261124)
    clientes = ["K01", "K02", "K03", "K04"]
    for caso in range(2000):
        mensaje, eventos = generar(rnd, rnd.randint(1, 12))
        cliente = rnd.choice(clientes)
        rp, sal, _ = plegar_mensajes(ctx, [mensaje], eventos, cliente=cliente)

        ids = [i.id for i in rp.items]
        assert len(ids) == len(set(ids)) == sum(1 for a in rp.acciones if a.accion == "CREAR"), caso
        for item in rp.items:
            if item.estado in (EstadoItem.REEMPLAZADO, EstadoItem.FUSIONADO):
                assert item.sucesor in ids, caso
        activas = rp.lineas_activas()
        assert len({l.sku for l in activas}) == len(activas), caso  # una línea activa por SKU solicitado
        for linea in activas:
            assert linea.cantidad > 0 and linea.cantidad == linea.cantidad.to_integral_value(), caso
            assert not any(e.incierta for e in linea.entradas), caso  # nunca se confirma una cantidad incierta
            producto = ctx.datos.productos[linea.sku]
            assert producto.disponible or (producto.sustituto_sku and ctx.datos.productos[producto.sustituto_sku].disponible), caso
        for pendiente in rp.pendientes_activos():
            assert pendiente.clase is Clase.PENDIENTE and pendiente.motivo is not None, caso

        r = cerrar_pedido(
            cliente_id=cliente, fecha_hora=MARTES, lineas_solicitadas=sal.lineas, pendientes=rp.pendientes(),
            sustituciones=sal.sustituciones, hay_eventos_pedido=True, datos=ctx.datos,
        )
        verificar_invariantes(r)
        if r.estado is Estado.CONFIRMADO:
            assert not r.pendientes and r.lineas, caso
        assert all(isinstance(l.cantidad, Decimal) for l in r.lineas)
