"""Hito 2: correlación, privacidad del contenido y estado de MLflow (sin MLflow real ni red)."""

import time

import pytest

from app.observabilidad.estado_mlflow import MOTIVO_MLFLOW_NO_CONFIGURADO, MOTIVO_MLFLOW_NO_DISPONIBLE, EstadoMlflow, uri_local
from app.observabilidad.registro import Correlacion, Registro
from app.observabilidad.trazas import CONJUNTOS_SOLO_METADATOS, contenido_permitido


def correlacion(**k):
    base = {"x-evaluacion-ejecucion": "e1", "x-evaluacion-caso": "A01", "x-evaluacion-conjunto": "PUB", "x-evaluacion-privado": "0"}
    return Correlacion.desde_encabezados({**base, **k})


def test_correlacion_solo_valores_seguros():
    c = Correlacion.desde_encabezados({"x-evaluacion-ejecucion": "abc-1.2_3", "x-evaluacion-caso": "A01; DROP", "x-evaluacion-conjunto": "x" * 65})
    assert (c.ejecucion, c.caso, c.conjunto) == ("abc-1.2_3", None, None)
    assert c.privado  # sin "0" explícito, privado
    assert Correlacion.desde_encabezados({}).etiquetas() == {}
    assert correlacion().etiquetas() == {"evaluacion.ejecucion": "e1", "evaluacion.caso": "A01", "evaluacion.conjunto": "PUB"}


@pytest.mark.parametrize(
    ("modo", "uri", "encabezados", "permitido"),
    [
        ("metadatos", "sqlite:///x.db", {}, False),
        ("completo", "sqlite:///x.db", {}, True),
        ("completo", "http://localhost:5000", {}, True),
        ("completo", "http://mlflow.ejemplo.com", {}, False),  # no local
        ("completo", None, {}, False),
        ("completo", "sqlite:///x.db", {"x-evaluacion-privado": "1"}, False),
        ("completo", "sqlite:///x.db", {"x-evaluacion-conjunto": "D39"}, False),  # D39 aunque se declare público
        ("completo", "sqlite:///x.db", {"x-evaluacion-conjunto": "D39", "x-evaluacion-privado": "1"}, False),
    ],
    ids=["metadatos", "completo_local", "completo_localhost", "completo_remoto", "sin_uri", "privado", "d39_mal_configurado", "d39"],
)
def test_contenido_solo_en_modo_completo_local_y_conjunto_publico(modo, uri, encabezados, permitido):
    assert contenido_permitido(modo, uri, correlacion(**encabezados)) is permitido


def test_sin_encabezados_nunca_hay_contenido():
    assert not contenido_permitido("completo", "sqlite:///x.db", Correlacion.desde_encabezados({}))
    assert "D39" in CONJUNTOS_SOLO_METADATOS


def test_uri_local():
    assert uri_local("sqlite:///tmp/x.db") and uri_local("http://127.0.0.1:5000") and uri_local("http://mlflow:5000")
    assert not uri_local("https://servidor.ejemplo.com") and not uri_local("databricks")


def test_estado_no_configurado():
    estado = EstadoMlflow(None)
    estado.iniciar()
    assert estado.sonda() == (False, MOTIVO_MLFLOW_NO_CONFIGURADO) and not estado.disponible


def test_estado_caida_recuperacion_y_preparacion_una_vez():
    respuestas, conexiones = [False, True, False, True], []
    estado = EstadoMlflow("http://localhost:5000", comprobar=lambda uri: respuestas.pop(0), al_conectar=lambda: conexiones.append(1))
    vistos = []
    for _ in range(4):
        estado.comprobar_ahora()
        vistos.append(estado.sonda())
    assert vistos == [(False, MOTIVO_MLFLOW_NO_DISPONIBLE), (True, None), (False, MOTIVO_MLFLOW_NO_DISPONIBLE), (True, None)]
    assert conexiones == [1]  # el experimento se prepara una sola vez


def test_si_preparar_falla_se_reintenta_y_no_queda_disponible():
    intentos = []

    def preparar():
        intentos.append(1)
        if len(intentos) == 1:
            raise RuntimeError("zqx")

    estado = EstadoMlflow("http://localhost:5000", comprobar=lambda uri: True, al_conectar=preparar)
    estado.comprobar_ahora()
    assert estado.sonda() == (False, MOTIVO_MLFLOW_NO_DISPONIBLE)
    estado.comprobar_ahora()
    assert estado.sonda() == (True, None) and len(intentos) == 2


def test_detener_no_bloquea():
    estado = EstadoMlflow("http://localhost:5000", intervalo_s=60, comprobar=lambda uri: False)
    estado.iniciar()
    inicio = time.monotonic()
    estado.detener()
    assert time.monotonic() - inicio < 3


def test_registrar_nunca_bloquea_la_solicitud_aunque_exportar_tarde():
    """El hilo de la solicitud solo encola: una exportación lenta no lo retrasa."""
    from app.observabilidad.trazas import Trazador
    from tests.fixtures.observabilidad_falsa import EstadoFalso

    lentas = []

    class TrazadorLento(Trazador):
        def _exportar(self, registro):
            time.sleep(0.5)
            lentas.append(registro)

    trazador = TrazadorLento(EstadoFalso())
    trazador.experiment_id = "1"
    inicio = time.perf_counter()
    for _ in range(5):
        trazador.registrar(Registro(correlacion()))
    assert time.perf_counter() - inicio < 0.05
    trazador.cerrar()  # drena con límite de tiempo
    assert trazador.exportadas + len(lentas) >= 1 and trazador.descartadas == 0


def test_pendientes_llenos_descarta_y_cuenta():
    from app.observabilidad import trazas as t
    from tests.fixtures.observabilidad_falsa import EstadoFalso

    bloqueo = __import__("threading").Event()

    class TrazadorBloqueado(t.Trazador):
        def _exportar(self, registro):
            bloqueo.wait(2)

    trazador = TrazadorBloqueado(EstadoFalso())
    trazador.experiment_id = "1"
    for _ in range(t.MAX_PENDIENTES + 10):
        trazador.registrar(Registro(correlacion()))
    assert trazador.descartadas >= 9
    bloqueo.set()
    trazador.cerrar()


def test_guardar_contenido_sin_autorizacion_no_conserva_nada():
    from app.observabilidad import registro as traza

    with traza.abrir(correlacion()) as r:  # por defecto, sin captura
        assert not traza.capturando()
        traza.guardar_contenido("entrada", {"mensajes": ["zqxmarca"]})
    assert r.contenido == {} and not r.captura_contenido
    with traza.abrir(correlacion(), captura_contenido=True) as r:
        assert traza.capturando()
        traza.guardar_contenido("entrada", {"mensajes": ["zqxmarca"]})
    assert r.contenido == {"entrada": {"mensajes": ["zqxmarca"]}}
    assert not traza.capturando()  # fuera de una solicitud
