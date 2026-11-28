"""Hito 2: integración con un MLflow real local (`sqlite` en una carpeta temporal; sin red ni servidor).

- Una solicitud deja una traza con tres tramos, correlación, tokens y coste efectivo.
- Modo metadatos: ni mensajes, ni `cliente_id`, ni SKU, cantidades o importes.
- Modo completo: contenido solo para un conjunto público; nunca para D39, aunque se configure mal.
- Dos evaluaciones simultáneas no mezclan trazas ni costes; con trazas faltantes o sin coste, los
  costes no se presentan como completos.
- MLflow caído no cambia la respuesta ni su tiempo de forma significativa, y `/health` lo refleja;
  la recuperación también se refleja. El cierre no se bloquea.
- `evaluacion_mlflow` registra el run desde el resumen público; de D39 solo si se aprobó.
"""

import json
import os
import logging
import statistics
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.interprete.llm import InterpreteLLM
from app.main import crear_app
from app.observabilidad.estado_mlflow import MOTIVO_MLFLOW_NO_DISPONIBLE, EstadoMlflow
from app.observabilidad.trazas import Trazador
from evaluacion_mlflow.registro import costes_de_ejecucion, registrar
from tests.fixtures.historial_e1b2 import cargar_contexto
from tests.fixtures.modelo_falso import Cadena
from tests.fixtures.observabilidad_falsa import observabilidad_ok

mlflow = pytest.importorskip("mlflow")
RUTA = "/v1/pedidos/interpretar"
MARCA = "zqxmarcamensaje"
EVENTO = {"id": "e1", "mensaje": 0, "tipo": "agregar", "texto": "2 fardos de frijol negro", "producto": "frijol negro",
          "cantidad": "2", "unidad": "venta", "unidad_texto": "fardos"}


class Crudo:
    """Mensaje crudo de LangChain con el uso que informa OpenRouter."""

    def __init__(self, coste=0.00025):
        self.usage_metadata = {"input_tokens": 1200, "output_tokens": 80}
        self.response_metadata = {"token_usage": {"cost": coste} if coste is not None else {}, "model_name": "zqx/modelo"}


def con_uso(coste=0.00025):
    from app.dominio.esquema_eventos import Interpretacion

    return {"raw": Crudo(coste), "parsed": Interpretacion.validar({"eventos": [EVENTO]}, 1), "parsing_error": None}


@pytest.fixture(autouse=True)
def _aislar_uri_de_mlflow():
    """`mlflow.set_tracking_uri()` escribe MLFLOW_TRACKING_URI en el entorno del proceso: sin esto, la URI
    temporal se filtraría a las pruebas siguientes (p. ej., a las de referencia, que leen la configuración).
    Restauración explícita: `monkeypatch.delenv(raising=False)` no deshace nada si la variable no existía."""
    original = os.environ.get("MLFLOW_TRACKING_URI")
    yield
    if original is None:
        os.environ.pop("MLFLOW_TRACKING_URI", None)
    else:
        os.environ["MLFLOW_TRACKING_URI"] = original


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("mlflow_datos")).datos


@pytest.fixture
def almacen(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # los artefactos de MLflow quedan en la carpeta temporal
    return f"sqlite:///{tmp_path / 'mlflow.db'}"


def observabilidad(uri, modo="metadatos", experimento="lab3-api", esperas=(0.2, 0.5, 1.0)):
    referencia = []
    estado = EstadoMlflow(uri, intervalo_s=60, al_conectar=lambda: referencia[0].preparar())
    trazador = Trazador(estado, experimento, modo, "zqxversion", "zqx/modelo", "base", esperas=esperas)
    referencia.append(trazador)
    estado.comprobar_ahora()
    return estado, trazador


def pedir(cliente, mensaje=f"{MARCA} 2 fardos de frijol negro", **correlacion):
    encabezados = {f"X-Evaluacion-{k.capitalize()}": v for k, v in correlacion.items()}
    return cliente.post(RUTA, json={"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": [mensaje]}, headers=encabezados)


def trazas(experimento="lab3-api", filtro=None):
    mlflow.flush_trace_async_logging()
    exp = mlflow.get_experiment_by_name(experimento)
    return mlflow.search_traces(locations=[exp.experiment_id], filter_string=filtro, return_type="list")


def test_traza_con_tramos_correlacion_tokens_y_coste(datos, almacen):
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso()), "x"), observabilidad=observabilidad(almacen))) as cliente:
        r = pedir(cliente, ejecucion="run1", caso="A01", conjunto="PUB", repeticion="0", privado="0")
        assert r.status_code == 200 and cliente.get("/health").json() == {"estado": "ok"}
    (t,) = trazas(filtro="tags.`evaluacion.ejecucion` = 'run1'")
    assert {s.name for s in t.data.spans} == {"pedido", "interprete", "motor"}
    assert t.info.tags["evaluacion.caso"] == "A01" and t.info.tags["variante"] == "base" and t.info.tags["contenido"] == "metadatos"
    por_tramo = {s.name: s.attributes for s in t.data.spans}
    assert por_tramo["interprete"]["coste_usd"] == 0.00025 and por_tramo["interprete"]["tokens_entrada"] == 1200
    assert por_tramo["pedido"]["codigo_http"] == 200 and por_tramo["motor"]["n_lineas"] == 1 and por_tramo["motor"]["estado"]


def _sin_contenido(texto, datos):
    linea_sku = [s for s in datos.productos if s in texto]  # ningún SKU del catálogo
    return MARCA not in texto and "K04" not in texto and "frijol" not in texto and not linea_sku


def test_metadatos_sin_mensajes_cliente_sku_cantidades_ni_importes(datos, almacen):
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso()), "x"), observabilidad=observabilidad(almacen))) as cliente:
        assert pedir(cliente, ejecucion="m1", caso="A01", conjunto="PUB", repeticion="0", privado="0").status_code == 200
    (t,) = trazas(filtro="tags.`evaluacion.ejecucion` = 'm1'")
    assert _sin_contenido(t.to_json(), datos)


@pytest.mark.parametrize(
    ("correlacion", "con_contenido"),
    [({"conjunto": "PUB", "privado": "0"}, True), ({"conjunto": "D39", "privado": "0"}, False),
     ({"conjunto": "D39", "privado": "1"}, False), ({"conjunto": "PUB", "privado": "1"}, False), ({}, False)],
    ids=["publico", "d39_mal_configurado", "d39", "privado", "sin_correlacion"],
)
def test_modo_completo_nunca_registra_contenido_de_d39(datos, almacen, correlacion, con_contenido):
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso()), "x"), observabilidad=observabilidad(almacen, "completo"))) as cliente:
        assert pedir(cliente, ejecucion="c1", caso="U03", repeticion="0", **correlacion).status_code == 200
    (t,) = trazas(filtro="tags.`evaluacion.ejecucion` = 'c1'")
    texto = t.to_json()
    assert (MARCA in texto) is con_contenido and (t.info.tags["contenido"] == "completo") is con_contenido


def _metadatos(ejecucion, casos_por_conjunto, repeticiones=1):
    return {"ejecucion_id": ejecucion, "casos_por_conjunto": casos_por_conjunto, "repeticiones": repeticiones, "modo": "e3"}


def test_dos_evaluaciones_simultaneas_no_mezclan_trazas_ni_costes(datos, almacen):
    obs = observabilidad(almacen)
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso(0.001)), "x"), observabilidad=obs)) as cliente:
        def evaluar(ejecucion, n):
            for i in range(n):
                assert pedir(cliente, ejecucion=ejecucion, caso=f"C{i}", conjunto="PUB", repeticion="0", privado="0").status_code == 200

        hilos = [threading.Thread(target=evaluar, args=("ejA", 4)), threading.Thread(target=evaluar, args=("ejB", 3))]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
    mlflow.flush_trace_async_logging()
    a = costes_de_ejecucion(_metadatos("ejA", {"PUB": 4}), "lab3-api", espera_s=5, intervalo_s=0.2)
    b = costes_de_ejecucion(_metadatos("ejB", {"PUB": 3}), "lab3-api", espera_s=5, intervalo_s=0.2)
    assert (a.trazas_encontradas, a.completos, a.coste_total_usd, a.tokens_entrada) == (4, True, 0.004, 4800)
    assert (b.trazas_encontradas, b.completos, b.coste_total_usd, b.tokens_entrada) == (3, True, 0.003, 3600)


def test_trazas_faltantes_o_sin_coste_no_dan_costes_completos(datos, almacen):
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso(0.001), con_uso(None)), "x"), observabilidad=observabilidad(almacen))) as cliente:
        pedir(cliente, ejecucion="f1", caso="C0", conjunto="PUB", repeticion="0", privado="0")
        pedir(cliente, ejecucion="f2", caso="C0", conjunto="PUB", repeticion="0", privado="0")  # sin coste informado
    faltan = costes_de_ejecucion(_metadatos("f1", {"PUB": 3}), "lab3-api", espera_s=1, intervalo_s=0.2)
    assert (faltan.trazas_encontradas, faltan.completos, faltan.coste_total_usd) == (1, False, None)
    sin_coste = costes_de_ejecucion(_metadatos("f2", {"PUB": 1}), "lab3-api", espera_s=1, intervalo_s=0.2)
    assert (sin_coste.trazas_encontradas, sin_coste.con_coste, sin_coste.completos, sin_coste.coste_total_usd) == (1, 0, False, None)


def test_mlflow_caido_no_cambia_la_respuesta_ni_su_tiempo(datos):
    def medir(obs):
        with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso()), "x"), observabilidad=obs)) as cliente:
            pedir(cliente)
            tiempos, cuerpos = [], []
            for _ in range(5):
                inicio = time.perf_counter()
                r = pedir(cliente, ejecucion="d1", caso="C0", conjunto="PUB", repeticion="0", privado="0")
                tiempos.append(time.perf_counter() - inicio)
                cuerpos.append((r.status_code, r.json()))
            salud = cliente.get("/health").json()
        return statistics.median(tiempos), cuerpos, salud

    base, cuerpos_ok, _ = medir(observabilidad_ok())
    caido = EstadoMlflow("http://127.0.0.1:9", intervalo_s=60)  # puerto cerrado
    caido.comprobar_ahora()
    inicio_cierre = time.monotonic()
    t_caido, cuerpos_caido, salud = medir((caido, Trazador(caido)))
    assert time.monotonic() - inicio_cierre < 10  # arranque y cierre sin bloquearse
    assert cuerpos_caido == cuerpos_ok
    assert t_caido - base < 0.1
    assert salud["estado"] == "degradado" and MOTIVO_MLFLOW_NO_DISPONIBLE in salud["motivo"]


def test_health_independiente_y_recuperacion(datos):
    respuesta = {"ok": False}
    estado = EstadoMlflow("http://localhost:5000", intervalo_s=60, comprobar=lambda uri: respuesta["ok"])
    interprete = InterpreteLLM(Cadena(con_uso(), RuntimeError("zqx"), con_uso()), "x")
    with TestClient(crear_app(datos=datos, interprete=interprete, observabilidad=(estado, Trazador(estado))), raise_server_exceptions=False) as cliente:
        estado.comprobar_ahora()
        assert pedir(cliente).status_code == 200  # intérprete operativo, MLflow caído
        assert cliente.get("/health").json() == {"estado": "degradado", "motivo": MOTIVO_MLFLOW_NO_DISPONIBLE}
        respuesta["ok"] = True
        estado.comprobar_ahora()
        assert cliente.get("/health").json() == {"estado": "ok"}  # recuperación de MLflow
        assert pedir(cliente).status_code == 503  # ahora falla el intérprete
        assert cliente.get("/health").json() == {"estado": "degradado", "motivo": "error_al_invocar_modelo"}
        respuesta["ok"] = False
        estado.comprobar_ahora()
        assert cliente.get("/health").json() == {"estado": "degradado", "motivo": f"error_al_invocar_modelo; {MOTIVO_MLFLOW_NO_DISPONIBLE}"}


def test_evaluacion_mlflow_registra_el_run_y_de_d39_solo_si_se_aprobo(datos, almacen, tmp_path):
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso(0.002)), "x"), observabilidad=observabilidad(almacen))) as cliente:
        for caso in ("C0", "C1"):
            pedir(cliente, ejecucion="r1", caso=caso, conjunto="PUB", repeticion="0", privado="0")
        pedir(cliente, ejecucion="r1", caso="U01", conjunto="D39", repeticion="0", privado="1")
    resumen = {"metadatos": {**_metadatos("r1", {"PUB": 2, "D39": 1}), "git": "zqx", "timeout": 5, "privados": ["D39"],
                             "conjuntos": {"PUB": {"casos": "a" * 64}, "D39": {"casos": "b" * 64}}},
               "conjuntos": {"PUB": {"resumenes": [{"casos": 2, "correctos": 2, "k_unidades": {"k1": 0, "k2": 0, "k3": 0, "k4": 0, "k5": 0},
                                                    "invalidos": {}, "latencia_p50_ms": 12, "latencia_p95_ms": 20, "latencia_media_ms": 14}]},
                             "D39": {"sha256": "b" * 64, "aprobado": True}}}
    ruta = tmp_path / "resumen_publico.json"
    ruta.write_text(json.dumps(resumen), encoding="utf-8")
    run_id, costes = registrar(ruta, espera_s=5)
    assert costes.completos and costes.coste_total_usd == 0.006
    run = mlflow.get_run(run_id)
    assert run.data.metrics["PUB.r0.exactitud"] == 1.0 and run.data.metrics["coste_total_usd"] == 0.006
    assert [k for k in run.data.metrics if k.startswith("D39.")] == ["D39.aprobado"]
    assert run.data.tags["costes_completos"] == "true" and run.data.tags["ejecucion_id"] == "r1"


# --- Confirmación de la exportación (revisión del PR #14) -------------------------------------


def _esperar_resueltas(trazador, limite=10.0):
    fin = time.monotonic() + limite
    while time.monotonic() < fin and trazador.contadores()["en_curso"]:
        time.sleep(0.05)


def test_exportaciones_normales_quedan_confirmadas_con_la_api_publica(datos, almacen):
    estado, trazador = observabilidad(almacen)
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso()), "x"), observabilidad=(estado, trazador))) as cliente:
        for i in range(2):
            assert pedir(cliente, ejecucion="v1", caso=f"C{i}", conjunto="PUB", repeticion="0", privado="0").status_code == 200
        _esperar_resueltas(trazador)
        c = trazador.contadores()
        assert c["exportadas"] == 2 and c["registradas"] == 2 and c["en_curso"] == 0
    assert len(trazas(filtro="tags.`evaluacion.ejecucion` = 'v1'")) == 2


def test_fallo_tragado_por_mlflow_no_confirmada_sin_duplicado_ni_costes_completos(datos, almacen, monkeypatch, caplog):
    from mlflow.tracing.client import TracingClient

    original, llamadas = TracingClient.start_trace, []

    def falla_la_primera(self, info, *args, **kwargs):  # MLflow captura esta excepción y solo emite un aviso
        llamadas.append(1)
        if len(llamadas) == 1:
            raise TimeoutError("API request to http://mlflow:5000/api/3.0/mlflow/traces timed out")
        return original(self, info, *args, **kwargs)

    monkeypatch.setattr(TracingClient, "start_trace", falla_la_primera)
    estado, trazador = observabilidad(almacen)
    with caplog.at_level(logging.DEBUG):
        with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso(0.001)), "x"), observabilidad=(estado, trazador))) as cliente:
            for i in range(2):
                assert pedir(cliente, ejecucion="v2", caso=f"C{i}", conjunto="PUB", repeticion="0", privado="0").status_code == 200
            _esperar_resueltas(trazador)
            c = trazador.contadores()
    # La primera: `log_spans` guardó los spans y el almacén creó la traza **sin etiquetas** (las pone
    # `start_trace`): existe, pero no se puede correlacionar -> incompleta, nunca exportada.
    assert c["exportadas"] == 1 and c["incompletas"] == 1 and c["registradas"] == 2 and c["en_curso"] == 0
    assert len(llamadas) == 2  # una exportación por solicitud: nunca se reexporta
    assert len(trazas(filtro="tags.`evaluacion.ejecucion` = 'v2'")) == 1  # sin duplicados
    costes = costes_de_ejecucion(_metadatos("v2", {"PUB": 2}), "lab3-api", espera_s=0)
    assert not costes.completos and costes.coste_total_usd is None
    # El aviso de MLflow (URL interna y excepción) no llega a ningún handler; el propio, saneado, sí.
    textos = [r.getMessage() for r in caplog.records]
    assert not any(m.startswith("Failed to send trace") for m in textos)
    propios = [m for m in textos if m.startswith("traza no confirmada")]  # incompleta tras 3 lecturas
    assert propios and all("http" not in m and "timed out" not in m and "K04" not in m for m in propios)


def test_traza_ausente_en_el_servidor_queda_no_confirmada(datos, almacen, monkeypatch):
    from mlflow.tracing.client import TracingClient

    iniciadas = []
    original_inicio, original_spans = TracingClient.start_trace, TracingClient.log_spans

    def inicio(self, info, *args, **kwargs):
        iniciadas.append(1)
        if len(iniciadas) == 1:
            raise TimeoutError("zqx")
        return original_inicio(self, info, *args, **kwargs)

    def spans(self, *args, **kwargs):  # fallan todos los spans de la primera traza
        if not iniciadas:
            raise TimeoutError("zqx")
        return original_spans(self, *args, **kwargs)

    monkeypatch.setattr(TracingClient, "start_trace", inicio)
    monkeypatch.setattr(TracingClient, "log_spans", spans)
    estado, trazador = observabilidad(almacen)
    with TestClient(crear_app(datos=datos, interprete=InterpreteLLM(Cadena(con_uso()), "x"), observabilidad=(estado, trazador))) as cliente:
        assert pedir(cliente, ejecucion="v3", caso="C0", conjunto="PUB", repeticion="0", privado="0").status_code == 200
        _esperar_resueltas(trazador)
        assert pedir(cliente, ejecucion="v3", caso="C1", conjunto="PUB", repeticion="0", privado="0").status_code == 200
        _esperar_resueltas(trazador)
        c = trazador.contadores()
    assert c["no_confirmadas"] == 1 and c["exportadas"] == 1 and c["incompletas"] == 0 and c["en_curso"] == 0
    assert len(iniciadas) == 2  # nunca se reexporta
    assert [t.info.tags["evaluacion.caso"] for t in trazas(filtro="tags.`evaluacion.ejecucion` = 'v3'")] == ["C1"]
