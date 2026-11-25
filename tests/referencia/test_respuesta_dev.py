"""E2a con los 84 casos de desarrollo (local): motor (E1b) -> RespuestaPedido -> JSON.

- La respuesta serializada tiene exactamente las claves del Anexo en cada nivel.
- Todos los campos y valores coinciden con lo esperado en `EVAL_DEV_PATH`, con los montos
  **numéricamente** iguales (JSON leído como `Decimal`). D91 (opción A): la igualdad textual de
  los montos con el jsonl publicado solo se informa, no es un criterio.
- La comparación por HTTP de los 84 casos corresponde a E2b.
"""

import json
import re
from datetime import datetime
from decimal import Decimal

import pytest

from app.api.esquemas import RespuestaPedido
from app.datos.normalizacion import normalizar_texto
from app.dominio.entrada import EntradaPedido
from app.dominio.pedido import Recursos, procesar_pedido
from tests.referencia.formato_eventos_dev import cargar, reconstruir

CLAVES = {"cliente_id", "estado", "lineas", "total", "fecha_entrega", "sustituciones", "pendientes", "motivos_revision", "mensaje_cliente"}
_MONTO = re.compile(r'"(total|subtotal|precio_unitario)":\s*(-?\d+(?:\.\d+)?)')


@pytest.fixture(scope="module")
def recursos(datos_reales):
    return Recursos.construir(datos_reales)


def _normalizado(cuerpo):
    return {
        "estado": cuerpo["estado"],
        "lineas": [(l["sku"], Decimal(l["cantidad"]), l["precio_unitario"], Decimal(l["descuento_pct"]), l["subtotal"]) for l in cuerpo["lineas"]],
        "total": cuerpo["total"],
        "fecha_entrega": cuerpo["fecha_entrega"],
        "sustituciones": [(s["sku_solicitado"], s["sku_entregado"], Decimal(s["cantidad"])) for s in cuerpo["sustituciones"]],
        "pendientes": [(p["motivo"], normalizar_texto(p["texto"]), list(p["opciones"])) for p in cuerpo["pendientes"]],
        "motivos_revision": list(cuerpo["motivos_revision"]),
    }


def test_los_84_casos_por_el_esquema_de_respuesta(casos_dev, lineas_crudas_dev, datos_reales, recursos):
    documento = cargar()
    discrepancias, textuales, montos = {}, 0, 0
    publicado = {json.loads(l)["id"]: l for l in lineas_crudas_dev}
    for caso in casos_dev:
        en = caso["entrada"]
        entrada = EntradaPedido(en["cliente_id"], datetime.fromisoformat(en["fecha_hora"]), tuple(en["mensajes"]))
        resultado = procesar_pedido(entrada, reconstruir(documento["casos"][caso["id"]], en["mensajes"]), datos_reales, recursos=recursos)
        texto = RespuestaPedido.desde_resultado(resultado).model_dump_json()
        cuerpo = json.loads(texto, parse_float=Decimal)
        assert set(cuerpo) == CLAVES, caso["id"]
        assert cuerpo["cliente_id"] == en["cliente_id"] and cuerpo["mensaje_cliente"] == resultado.mensaje_cliente
        o, e = _normalizado(cuerpo), _normalizado(caso["esperado"])
        diferencias = sorted(k for k in e if o[k] != e[k])  # solo nombres de campo
        if diferencias:
            discrepancias[caso["id"]] = diferencias
        # Informativo (D91): ¿el texto de cada monto coincide con el del jsonl publicado?
        propios = _MONTO.findall(texto)
        ajenos = _MONTO.findall(publicado[caso["id"]])
        montos += len(propios)
        textuales += sum(1 for a, b in zip(sorted(propios), sorted(ajenos)) if a == b)
    print(f"\nRespuesta por el esquema: {len(casos_dev) - len(discrepancias)}/{len(casos_dev)}; "
          f"montos con el mismo texto que el jsonl (informativo): {textuales}/{montos}")
    assert len(casos_dev) == 84 and discrepancias == {}
