"""Q-N1 pasando por el orquestador, con el catálogo real (mensajes propios, no publicados).

- Consultas genuinas, incluso con un evento `agregar` erróneo inyectado sobre el producto:
  clasificación `CONSULTA`, `fuera_de_alcance`, sin líneas ni pendientes (0 falsos positivos).
- Pedidos en forma de pregunta: el evento no se descarta y el mensaje es un pedido (0 descartados).
- D60 con el catálogo real: "doña Rosa" no activa el jabón Rosa y "te mando" no activa el té.
"""

from datetime import datetime

import pytest

from app.dominio.clasificacion import Clasificacion
from app.dominio.entrada import EntradaPedido
from app.dominio.pedido import Recursos, procesar_pedido
from tests.referencia.test_consultas_qn1 import CONSULTAS, PEDIDOS

FECHA = datetime(2026, 11, 24, 10, 0)


@pytest.fixture(scope="module")
def recursos(datos_reales):
    return Recursos.construir(datos_reales)


def _evento(caso):
    indice = next(i for i, m in enumerate(caso["mensajes"]) if caso["fragmento"] in m)
    return {"id": "e1", "mensaje": indice, "tipo": "agregar", "texto": caso["fragmento"], "producto": caso["fragmento"]}


def _procesar(recursos, mensajes, eventos):
    cliente = sorted(recursos.datos.clientes)[0]
    return procesar_pedido(EntradaPedido(cliente, FECHA, tuple(mensajes)), {"eventos": eventos}, recursos.datos, recursos=recursos)


@pytest.mark.parametrize("caso", CONSULTAS, ids=[c["id"] for c in CONSULTAS])
@pytest.mark.parametrize("con_evento", [False, True], ids=["sin_evento", "evento_inyectado"])
def test_consultas_qn1_por_el_orquestador(recursos, caso, con_evento):
    r = _procesar(recursos, caso["mensajes"], [_evento(caso)] if con_evento else [])
    assert r.clasificacion is Clasificacion.CONSULTA
    assert r.cierre.estado.value == "fuera_de_alcance" and r.cierre.lineas == () and r.cierre.pendientes == ()
    if con_evento:
        assert [d.codigo for d in r.diagnostico.eventos_descartados] == ["DESCARTADO_CONSULTA"]


@pytest.mark.parametrize("caso", PEDIDOS, ids=[c["id"] for c in PEDIDOS])
def test_pedidos_interrogativos_por_el_orquestador(recursos, caso):
    r = _procesar(recursos, caso["mensajes"], [_evento(caso)])
    assert r.diagnostico.eventos_descartados == ()
    assert r.clasificacion is Clasificacion.PEDIDO


@pytest.mark.parametrize("mensaje", ["doña Rosa le manda saludos", "te mando el dinero mañana", "Claro que sí, gracias", "la Finca está lejos"])
def test_d60_nombres_y_palabras_comunes_no_son_senal(recursos, mensaje):
    assert recursos.detector.senales([mensaje]) == []
