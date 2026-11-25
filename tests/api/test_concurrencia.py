"""E2b: solicitudes concurrentes. `Recursos` se comparte entre solicitudes y debe dar los mismos
resultados en paralelo que en serie."""

from concurrent.futures import ThreadPoolExecutor

from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpretePorFuncion

CASOS = [
    (["2 fardos de gaseosa sol 600 y 3 de frijol negro"], "K04", [
        ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
        ev(2, 0, "agregar", "3 de frijol negro", producto="frijol negro", cantidad="3")]),
    (["lo de siempre"], "K01", [ev(1, 0, "habitual", "lo de siempre")]),
    (["mándeme 2 cajas de aceite y gaseosa"], "K04", [ev(1, 0, "agregar", "2 cajas de aceite", producto="aceite", cantidad="2")]),
    (["¿Tienen gaseosa sol de 600?"], "K03", []),
    (["1 de cloro claro"], "K02", [ev(1, 0, "agregar", "1 de cloro claro", producto="cloro claro", cantidad="1")]),
]


def test_50_solicitudes_en_paralelo_igual_que_en_serie(cliente_con):
    por_mensaje = {tuple(m): {"eventos": e} for m, _, e in CASOS}
    interprete = InterpretePorFuncion(lambda entrada: por_mensaje[entrada.mensajes])
    solicitudes = [solicitud(m, cliente=c) for m, c, _ in CASOS] * 10
    with cliente_con(interprete) as cliente:
        en_serie = [cliente.post(RUTA, json=s).json() for s in solicitudes]
        with ThreadPoolExecutor(max_workers=16) as hilos:
            en_paralelo = list(hilos.map(lambda s: cliente.post(RUTA, json=s).json(), solicitudes))
    assert en_paralelo == en_serie
    assert {r["estado"] for r in en_serie} == {"confirmado", "requiere_revision", "fuera_de_alcance"}
