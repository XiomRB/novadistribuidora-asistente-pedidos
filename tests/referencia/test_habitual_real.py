"""D53 y D70 sobre el historial real (local; se omite sin DATA_DIR).

Compara `ultimo_entregado` con un cálculo independiente (ordenar con `sorted` por la misma
clave) para los 40 clientes en varias fechas, y comprueba que no hay duplicados (D73).
"""

from datetime import date

from app.dominio.habitual import clave_natural, ultimo_entregado

FECHAS = [date(2026, 10, 1), date(2026, 11, 1), date(2026, 11, 15), date(2026, 11, 20), date(2026, 11, 25), date(2026, 12, 15)]


def independiente(datos, cliente, fecha):
    candidatos = [p for p in datos.historial.get(cliente, ()) if p.estado == "entregado" and p.fecha_entrega <= fecha]
    ordenados = sorted(candidatos, key=lambda p: (p.fecha_entrega, clave_natural(p.pedido_id), p.pedido_id))
    return ordenados[-1].pedido_id if ordenados else None


def test_coincide_con_calculo_independiente(datos_reales):
    clientes = sorted(datos_reales.clientes)
    assert len(clientes) == 40
    diferencias = []
    for cliente in clientes:
        for fecha in FECHAS:
            obtenido = ultimo_entregado(datos_reales, cliente, fecha)
            if (obtenido.pedido_id if obtenido else None) != independiente(datos_reales, cliente, fecha):
                diferencias.append((cliente, fecha))
    assert diferencias == []


def test_nunca_elige_un_cancelado_ni_un_pedido_posterior(datos_reales):
    for cliente in datos_reales.clientes:
        for fecha in FECHAS:
            obtenido = ultimo_entregado(datos_reales, cliente, fecha)
            if obtenido is not None:
                assert obtenido.estado == "entregado" and obtenido.fecha_entrega <= fecha
