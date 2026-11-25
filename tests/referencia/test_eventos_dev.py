"""D66: los 84 casos de desarrollo, con eventos de referencia, reproducen la respuesta esperada.

Los eventos se reconstruyen desde `eventos_dev.json` (solo posiciones) y los mensajes y las
respuestas esperadas se leen únicamente de `EVAL_DEV_PATH`. Se compara la respuesta completa:
estado, líneas (sku, cantidad, precio, descuento y subtotal), total, fecha de entrega,
sustituciones, pendientes (motivo, opciones y texto normalizado) y motivos de revisión.

Mide el motor determinista con interpretaciones escritas a mano (nivel N1): no mide la
interpretación del LLM.
"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from app.datos.normalizacion import normalizar_texto
from app.dominio.entrada import EntradaPedido
from app.dominio.estado import verificar_invariantes
from app.dominio.pedido import Recursos, procesar_pedido
from tests.referencia.formato_eventos_dev import cargar, reconstruir


@pytest.fixture(scope="module")
def recursos(datos_reales):
    return Recursos.construir(datos_reales)


def obtenido(cierre):
    return {
        "estado": cierre.estado.value,
        "lineas": [(l.sku, l.cantidad, l.precio_unitario, l.descuento_pct, l.subtotal) for l in cierre.lineas],
        "total": cierre.total,
        "fecha_entrega": cierre.fecha_entrega.isoformat() if cierre.fecha_entrega else None,
        "sustituciones": [(s.sku_solicitado, s.sku_entregado, s.cantidad) for s in cierre.sustituciones],
        "pendientes": [(p.motivo.value, normalizar_texto(p.texto), list(p.opciones)) for p in cierre.pendientes],
        "motivos_revision": [m.value for m in cierre.motivos_revision],
    }


def esperado(caso):
    e = caso["esperado"]
    return {
        "estado": e["estado"],
        "lineas": [
            (l["sku"], Decimal(str(l["cantidad"])), l["precio_unitario"], Decimal(str(l["descuento_pct"])), l["subtotal"])
            for l in e["lineas"]
        ],
        "total": e["total"],
        "fecha_entrega": e["fecha_entrega"],
        "sustituciones": [(s["sku_solicitado"], s["sku_entregado"], Decimal(str(s["cantidad"]))) for s in e["sustituciones"]],
        "pendientes": [(p["motivo"], normalizar_texto(p["texto"]), list(p["opciones"])) for p in e["pendientes"]],
        "motivos_revision": list(e["motivos_revision"]),
    }


def procesar_caso(caso, documento, datos, recursos):
    en = caso["entrada"]
    entrada = EntradaPedido(en["cliente_id"], datetime.fromisoformat(en["fecha_hora"]), tuple(en["mensajes"]))
    return procesar_pedido(entrada, reconstruir(documento["casos"][caso["id"]], en["mensajes"]), datos, recursos=recursos)


def test_los_84_casos_reproducen_la_respuesta_esperada(casos_dev, datos_reales, recursos):
    documento = cargar()
    assert len(casos_dev) == 84
    discrepancias = {}
    for caso in casos_dev:
        resultado = procesar_caso(caso, documento, datos_reales, recursos)
        verificar_invariantes(resultado.cierre)
        o, e = obtenido(resultado.cierre), esperado(caso)
        diferencias = sorted(k for k in e if o[k] != e[k])  # solo los nombres de campo, nunca los valores
        if diferencias:
            discrepancias[caso["id"]] = diferencias
    print(f"\nRespuesta completa con eventos de referencia: {len(casos_dev) - len(discrepancias)}/{len(casos_dev)}")
    assert discrepancias == {}


def test_mensaje_al_cliente_coherente_y_sin_texto_del_cliente(casos_dev, datos_reales, recursos):
    documento = cargar()
    for caso in casos_dev:
        resultado = procesar_caso(caso, documento, datos_reales, recursos)
        mensaje = resultado.mensaje_cliente
        assert mensaje.startswith("¡Buen") and mensaje.endswith(("!", "."))
        # El mensaje no depende del texto de los pendientes: con otro texto sale idéntico.
        marcados = tuple(replace(p, texto=f"ZQX{k}") for k, p in enumerate(resultado.cierre.pendientes))
        en = caso["entrada"]
        otro = recursos.redactor.redactar(
            replace(resultado.cierre, pendientes=marcados), resultado.clasificacion, datetime.fromisoformat(en["fecha_hora"])
        )
        assert otro == mensaje and "ZQX" not in otro, caso["id"]
        if resultado.cierre.estado.value == "requiere_revision":
            assert "Un asesor confirmará su pedido." in mensaje, caso["id"]
        for linea in resultado.cierre.lineas:
            assert datos_reales.productos[linea.sku].nombre in mensaje, caso["id"]
        assert f"{resultado.cierre.total}" not in mensaje or resultado.cierre.total == 0
