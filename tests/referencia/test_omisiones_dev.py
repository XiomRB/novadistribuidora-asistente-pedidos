"""Detector de omisiones sobre los 84 casos de desarrollo con eventos de referencia (local).

- 0 señales falsas: con los eventos de referencia, ninguna señal queda sin cubrir (ni siquiera
  las que no generarían pendiente por falta de contexto).
- Control de sensibilidad: si se quita cada evento `agregar` o `habitual` (sin referencias que
  dependan de él), el detector marca la mención como omisión en al menos el 90 % de los casos.
  Los fallos conocidos (jerga, productos fuera del catálogo, errores en marcas) están en el
  informe de E1b-2b y como riesgos para E3.
"""

import copy
from datetime import datetime

import pytest

from app.dominio.entrada import EntradaPedido
from app.dominio.pedido import Recursos, procesar_pedido
from tests.referencia.formato_eventos_dev import cargar, reconstruir

MIN_SENSIBILIDAD_PCT = 90


@pytest.fixture(scope="module")
def recursos(datos_reales):
    return Recursos.construir(datos_reales)


def _procesar(caso, definicion, datos, recursos):
    en = caso["entrada"]
    entrada = EntradaPedido(en["cliente_id"], datetime.fromisoformat(en["fecha_hora"]), tuple(en["mensajes"]))
    return procesar_pedido(entrada, reconstruir(definicion, en["mensajes"]), datos, recursos=recursos)


def test_cero_senales_falsas_en_los_84_casos(casos_dev, datos_reales, recursos):
    documento = cargar()
    con_senal = {}
    total = 0
    for caso in casos_dev:
        resultado = _procesar(caso, documento["casos"][caso["id"]], datos_reales, recursos)
        total += len(recursos.detector.senales(caso["entrada"]["mensajes"]))
        if resultado.diagnostico.omisiones:
            con_senal[caso["id"]] = [o.senal for o in resultado.diagnostico.omisiones]
    print(f"\nSeñales detectadas: {total}; sin cubrir: {sum(len(v) for v in con_senal.values())}")
    assert total > 0 and con_senal == {}


def _sin_evento(definicion, evento_id):
    nuevo = copy.deepcopy(definicion)
    nuevo["eventos"] = [e for e in nuevo["eventos"] if e["id"] != evento_id]
    mapa = {e["id"]: f"e{k}" for k, e in enumerate(nuevo["eventos"], start=1)}
    for e in nuevo["eventos"]:
        e["id"] = mapa[e["id"]]
        e["ref"] = mapa.get(e["ref"]) if e["ref"] else None
    return nuevo


def test_sensibilidad_al_quitar_cada_evento(casos_dev, datos_reales, recursos):
    documento = cargar()
    probados = detectados = 0
    for caso in casos_dev:
        definicion = documento["casos"][caso["id"]]
        for evento in definicion["eventos"]:
            if evento["tipo"] not in ("agregar", "habitual") or any(e["ref"] == evento["id"] for e in definicion["eventos"]):
                continue
            resultado = _procesar(caso, _sin_evento(definicion, evento["id"]), datos_reales, recursos)
            i, f = evento["texto"]
            probados += 1
            detectados += any(
                o.codigo == "OMISION" and o.posicion[0] == evento["m"] and o.posicion[1] < f and i < o.posicion[2]
                for o in resultado.diagnostico.omisiones
            )
            # Una omisión nunca crea líneas: nada de lo quitado aparece como línea nueva.
            assert len(resultado.diagnostico.salida_lineas) == len(resultado.cierre.lineas)
    print(f"\nMenciones quitadas detectadas como omisión: {detectados}/{probados}")
    assert probados > 100 and detectados * 100 >= MIN_SENSIBILIDAD_PCT * probados
