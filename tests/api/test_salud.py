"""E2b: `GET /health` (D81, D80): siempre 200, `ok` o `degradado` con motivo."""

import pytest

from app.api.salud import MOTIVO_SONDA_FALLIDA, ResultadoSonda, estado_de_salud, sonda_interprete
from app.interprete.base import MOTIVO_NO_CONFIGURADO, InterpreteNoConfigurado
from tests.fixtures.interprete_falso import InterpreteFijo

MARCA = "ZQXSALUD"


def test_produccion_en_e2_esta_degradada_por_el_interprete(cliente_con):
    with cliente_con() as cliente:
        respuesta = cliente.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "degradado", "motivo": "intérprete no configurado"}


def test_ok_con_un_interprete_disponible(cliente_con):
    with cliente_con(InterpreteFijo({"eventos": []})) as cliente:
        respuesta = cliente.get("/health")
    assert respuesta.status_code == 200 and respuesta.json() == {"estado": "ok"}


def test_degradado_con_un_interprete_no_disponible(cliente_con):
    with cliente_con(InterpreteFijo({}, disponible=False)) as cliente:
        assert cliente.get("/health").json() == {"estado": "degradado", "motivo": "intérprete de prueba no disponible"}


def test_sondas_adicionales_inyectables(cliente_con):
    caida = lambda: ResultadoSonda(False, "mlflow no disponible")  # noqa: E731
    with cliente_con(InterpreteFijo({}), sondas=[caida]) as cliente:
        respuesta = cliente.get("/health")
    assert respuesta.status_code == 200 and respuesta.json() == {"estado": "degradado", "motivo": "mlflow no disponible"}


def test_una_sonda_que_lanza_no_rompe_health_ni_muestra_su_mensaje(cliente_con):
    def rota():
        raise RuntimeError(f"detalle interno {MARCA}")

    with cliente_con(InterpreteFijo({}), sondas=[rota]) as cliente:
        respuesta = cliente.get("/health")
    assert respuesta.status_code == 200 and respuesta.json() == {"estado": "degradado", "motivo": MOTIVO_SONDA_FALLIDA}
    assert MARCA not in respuesta.text


@pytest.mark.parametrize(
    ("resultados", "esperado"),
    [
        ([], {"estado": "ok"}),
        ([ResultadoSonda(True)], {"estado": "ok"}),
        ([ResultadoSonda(False, "a"), ResultadoSonda(True), ResultadoSonda(False, "b")], {"estado": "degradado", "motivo": "a; b"}),
        ([ResultadoSonda(False, "a"), ResultadoSonda(False, "a")], {"estado": "degradado", "motivo": "a"}),
        ([ResultadoSonda(False)], {"estado": "degradado", "motivo": MOTIVO_SONDA_FALLIDA}),
    ],
)
def test_agregacion_de_sondas(resultados, esperado):
    assert estado_de_salud([lambda r=r: r for r in resultados]) == esperado


def test_sonda_del_interprete_no_configurado():
    assert sonda_interprete(InterpreteNoConfigurado())() == ResultadoSonda(False, MOTIVO_NO_CONFIGURADO)


def test_health_no_depende_del_cuerpo_ni_del_metodo_de_pedidos(cliente_con):
    with cliente_con() as cliente:
        assert cliente.get("/health").status_code == 200
        assert cliente.post("/health").status_code == 405  # solo GET
