"""Cálculo a partir de líneas YA INTERPRETADAS (las esperadas de cada caso de desarrollo).

Mide únicamente el motor de cálculo de E1a (precios, descuentos, subtotales, total, crédito,
fecha, estado y motivos). No mide la interpretación de mensajes.
"""

from datetime import datetime
from decimal import Decimal

from app.dominio.cierre import cerrar_pedido
from app.dominio.resultado import Estado, LineaSolicitada, Motivo, Pendiente, Sustitucion


def _entrada_desde_esperado(caso):
    esperado = caso["esperado"]
    return dict(
        cliente_id=caso["entrada"]["cliente_id"],
        fecha_hora=datetime.fromisoformat(caso["entrada"]["fecha_hora"]),
        lineas_solicitadas=[LineaSolicitada(l["sku"], Decimal(str(l["cantidad"]))) for l in esperado["lineas"]],
        pendientes=[Pendiente(Motivo(p["motivo"]), p["texto"], tuple(p["opciones"])) for p in esperado["pendientes"]],
        sustituciones=[
            Sustitucion(s["sku_solicitado"], s["sku_entregado"], Decimal(str(s["cantidad"])))
            for s in esperado["sustituciones"]
        ],
        hay_eventos_pedido=esperado["estado"] != Estado.FUERA_DE_ALCANCE.value,
    )


def _diferencias(caso, resultado):
    esperado = caso["esperado"]
    obtenido_lineas = [
        (l.sku, l.cantidad, l.precio_unitario, l.descuento_pct, l.subtotal) for l in resultado.lineas
    ]
    esperado_lineas = [
        (l["sku"], Decimal(str(l["cantidad"])), l["precio_unitario"], Decimal(str(l["descuento_pct"])), l["subtotal"])
        for l in esperado["lineas"]
    ]
    comparaciones = {
        "estado": (resultado.estado.value, esperado["estado"]),
        "lineas": (obtenido_lineas, esperado_lineas),
        "total": (resultado.total, esperado["total"]),
        "fecha_entrega": (
            resultado.fecha_entrega.isoformat() if resultado.fecha_entrega else None,
            esperado["fecha_entrega"],
        ),
        "motivos_revision": ([m.value for m in resultado.motivos_revision], esperado["motivos_revision"]),
    }
    return {k: v for k, v in comparaciones.items() if v[0] != v[1]}


def test_calculo_reproduce_todos_los_casos(casos_dev, datos_reales):
    discrepancias = {}
    for caso in casos_dev:
        resultado = cerrar_pedido(datos=datos_reales, **_entrada_desde_esperado(caso))
        diferencias = _diferencias(caso, resultado)
        if diferencias:
            discrepancias[caso["id"]] = diferencias
    print(f"\nCálculo a partir de líneas ya interpretadas: {len(casos_dev) - len(discrepancias)}/{len(casos_dev)}")
    assert casos_dev, "el archivo de casos está vacío"
    assert discrepancias == {}
