"""Q-N1 con nombres del catálogo real (mensajes propios, no publicados).

El reconocedor de consultas no necesita datos, así que estas pruebas también corren en CI.
- Consultas genuinas: 0 falsos positivos (el producto queda dentro de una consulta pura).
- Pedidos en forma de pregunta: 0 descartados (el producto queda fuera de las consultas puras).
"""

import json
from pathlib import Path

import pytest

from app.dominio.consultas import consultas_puras, dentro_de_consulta
from app.dominio.texto import localizar

AQUI = Path(__file__).parent


def _cargar(nombre):
    return [json.loads(l) for l in (AQUI / nombre).read_text(encoding="utf-8").splitlines() if l.strip()]


CONSULTAS = _cargar("consultas_qn1.jsonl")
PEDIDOS = _cargar("pedidos_interrogativos.jsonl")


def _span(caso):
    for indice, mensaje in enumerate(caso["mensajes"]):
        span = localizar(caso["fragmento"], mensaje, indice)
        if span is not None:
            return span
    raise AssertionError(f"{caso['id']}: fragmento no encontrado")


@pytest.mark.parametrize("caso", CONSULTAS, ids=[c["id"] for c in CONSULTAS])
def test_consultas_qn1_sin_falsos_positivos(caso):
    assert dentro_de_consulta(_span(caso), consultas_puras(caso["mensajes"]))


@pytest.mark.parametrize("caso", PEDIDOS, ids=[c["id"] for c in PEDIDOS])
def test_pedidos_interrogativos_no_descartados(caso):
    assert not dentro_de_consulta(_span(caso), consultas_puras(caso["mensajes"]))


def test_incluye_los_ejemplos_pedidos_y_tamano_minimo():
    textos = {c["mensajes"][0] for c in CONSULTAS}
    assert {"¿Tienen kola de 600?", "¿Cuánto cuesta el aceite?", "¿La próxima semana tendrán jabón?"} <= textos
    assert len(CONSULTAS) >= 25 and len(PEDIDOS) >= 15
