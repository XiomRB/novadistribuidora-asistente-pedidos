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


# --- Confirmación de la exportación (revisión del PR #14) -------------------------------------

import logging  # noqa: E402
import threading  # noqa: E402

from app.observabilidad import trazas as modulo_trazas  # noqa: E402

RAPIDO = (0.05, 0.1, 0.2)


class ErrorMlflow(Exception):
    def __init__(self, codigo, texto="zqx"):
        super().__init__(texto)
        self.error_code = codigo


def traza_con(*nombres):
    class Span:
        def __init__(self, nombre):
            self.name = nombre

    class Datos:
        spans = [Span(n) for n in nombres]

    class Traza:
        data = Datos()

    return Traza()


ENCONTRADA = traza_con("pedido")
NO_EXISTE = ErrorMlflow("RESOURCE_DOES_NOT_EXIST")
TIMEOUT = ErrorMlflow("INTERNAL_ERROR", "API request to http://mlflow:5000/api failed: timed out")


class TrazadorPrueba(modulo_trazas.Trazador):
    """Trazador real (búfer, hilos, contadores) con la exportación sustituida: devuelve un id por registro."""

    def __init__(self, respuestas=(), lector=None, esperas=RAPIDO, exportar_s=0.0, **kwargs):
        self.exportaciones, self.lecturas = [], []
        self._respuestas = list(respuestas)
        self._exportar_s = exportar_s
        super().__init__(EstadoFalsoObs(), lector=lector or self._leer_falso, esperas=esperas, **kwargs)
        self.experiment_id = "1"

    def _exportar(self, registro):
        time.sleep(self._exportar_s)
        self.exportaciones.append(registro)
        return f"tr-{len(self.exportaciones)}", frozenset({"pedido"})

    def _leer_falso(self, trace_id):
        self.lecturas.append(trace_id)
        respuesta = self._respuestas.pop(0) if len(self._respuestas) > 1 else self._respuestas[0]
        if isinstance(respuesta, BaseException):
            raise respuesta
        return respuesta


def EstadoFalsoObs():
    from tests.fixtures.observabilidad_falsa import EstadoFalso

    return EstadoFalso()


def esperar_fin(trazador, limite=5.0):
    fin = time.monotonic() + limite
    while time.monotonic() < fin and trazador.contadores()["en_curso"]:
        time.sleep(0.02)


def invariante(trazador):
    c = trazador.contadores()
    return c["registradas"] == sum(c[k] for k in modulo_trazas.CATEGORIAS) + c["en_curso"]


@pytest.mark.parametrize(
    ("respuestas", "categoria", "lecturas"),
    [
        ([NO_EXISTE, ENCONTRADA], "exportadas", 2),  # escritura tardía: confirmada en la 2.ª lectura
        ([NO_EXISTE], "no_confirmadas", 3),  # no encontrada en las 3 lecturas: no prueba que no exista
        ([NO_EXISTE, NO_EXISTE, TIMEOUT], "no_confirmadas", 3),  # indeterminada en la última
        ([TIMEOUT], "no_confirmadas", 3),
        ([traza_con("motor")], "incompletas", 3),  # encontrada sin el tramo raíz
        ([ENCONTRADA], "exportadas", 1),
    ],
    ids=["tardia", "no_encontrada", "indeterminada_final", "timeout", "incompleta", "inmediata"],
)
def test_clasificacion_solo_por_lecturas_y_nunca_reexporta(respuestas, categoria, lecturas):
    trazador = TrazadorPrueba(respuestas)
    trazador.registrar(Registro(correlacion()))
    esperar_fin(trazador)
    c = trazador.contadores()
    assert c[categoria] == 1 and sum(c[k] for k in modulo_trazas.CATEGORIAS) == 1
    assert len(trazador.exportaciones) == 1  # nunca se reexporta
    assert len(trazador.lecturas) == lecturas
    trazador.cerrar()
    assert invariante(trazador) and trazador.contadores()[categoria] == 1


def test_lecturas_lentas_no_retrasan_solicitudes_ni_exportaciones():
    liberar = threading.Event()

    def lector_lento(trace_id):
        liberar.wait(3)
        return ENCONTRADA

    trazador = TrazadorPrueba(lector=lector_lento, esperas=(0.0, 0.0, 0.0))
    inicio = time.perf_counter()
    for _ in range(5):
        trazador.registrar(Registro(correlacion()))
    assert time.perf_counter() - inicio < 0.05  # la solicitud solo encola
    fin = time.monotonic() + 2
    while time.monotonic() < fin and len(trazador.exportaciones) < 5:
        time.sleep(0.01)
    assert len(trazador.exportaciones) == 5  # exportadas mientras la primera lectura sigue bloqueada
    assert trazador.contadores()["exportadas"] == 0
    liberar.set()
    esperar_fin(trazador)
    assert trazador.contadores()["exportadas"] == 5
    trazador.cerrar()


def test_cierre_acotado_con_pendientes_cuenta_todo_y_nada_como_exportada():
    trazador = TrazadorPrueba([ENCONTRADA], esperas=(30.0, 30.0, 30.0), exportar_s=0.4)
    for _ in range(30):  # 30 x 0.4 s de exportación no caben en el cierre
        trazador.registrar(Registro(correlacion()))
    time.sleep(0.5)
    inicio = time.monotonic()
    trazador.cerrar()
    assert time.monotonic() - inicio <= modulo_trazas.ESPERA_CIERRE_S + 0.3
    c = trazador.contadores()
    assert c["en_curso"] == 0 and invariante(trazador)
    assert c["registradas"] == 30 and c["descartadas"] > 0 and c["no_confirmadas"] > 0
    assert c["exportadas"] == len(trazador.lecturas)  # solo lo confirmado con una lectura al cerrar
    trazador.registrar(Registro(correlacion()))  # después del cierre no se cuenta nada
    assert trazador.contadores() == c


def test_tras_el_cierre_una_actualizacion_tardia_se_ignora(monkeypatch):
    monkeypatch.setattr(modulo_trazas, "ESPERA_CIERRE_S", 0.5)
    liberar = threading.Event()

    def lector_bloqueado(trace_id):
        liberar.wait(5)
        return ENCONTRADA

    trazador = TrazadorPrueba(lector=lector_bloqueado, esperas=(0.0, 0.0, 0.0))
    trazador.registrar(Registro(correlacion()))
    time.sleep(0.2)  # la lectura está en curso
    trazador.cerrar()
    congelados = trazador.contadores()
    assert congelados["no_confirmadas"] == 1 and congelados["exportadas"] == 0 and invariante(trazador)
    liberar.set()
    time.sleep(0.3)
    assert trazador.contadores() == congelados  # la lectura tardía no la convierte en exportada


def test_mlflow_no_disponible_durante_la_verificacion_no_lee_y_no_confirma():
    trazador = TrazadorPrueba([ENCONTRADA], esperas=(0.2, 0.2, 0.2))
    trazador.registrar(Registro(correlacion()))
    time.sleep(0.05)
    trazador.estado.poner(False)
    esperar_fin(trazador)
    assert trazador.contadores()["no_confirmadas"] == 1 and trazador.lecturas == []
    trazador.cerrar()


def test_excepcion_propia_es_fallida_y_el_aviso_no_expone_detalles(caplog):
    class Falla(TrazadorPrueba):
        def _exportar(self, registro):
            raise RuntimeError("http://mlflow:5000/api zqxmarca K04 sk-or-zqxsecreto")

    trazador = Falla([ENCONTRADA])
    with caplog.at_level(logging.WARNING, logger="novadistribuidora.observabilidad"):
        trazador.registrar(Registro(correlacion()))
        esperar_fin(trazador)
        trazador.cerrar()
    assert trazador.contadores()["fallidas"] == 1 and invariante(trazador)
    texto = caplog.text
    assert "RuntimeError" in texto and "fallidas=1" in texto
    for prohibido in ("http://", "mlflow:5000", "zqxmarca", "K04", "sk-or"):
        assert prohibido not in texto


def test_aviso_de_no_confirmada_sin_url_ni_detalles(caplog):
    trazador = TrazadorPrueba([TIMEOUT])
    with caplog.at_level(logging.WARNING, logger="novadistribuidora.observabilidad"):
        trazador.registrar(Registro(correlacion()))
        esperar_fin(trazador)
    assert "traza no confirmada (indeterminada tras 3 lecturas)" in caplog.text and "no_confirmadas=1" in caplog.text
    assert "http://" not in caplog.text and "timed out" not in caplog.text
    trazador.cerrar()


def test_filtro_solo_descarta_avisos_de_exportacion_de_mlflow():
    modulo_trazas._mlflow()  # instala el filtro
    exportador = logging.getLogger(modulo_trazas.LOGGER_EXPORTADOR_MLFLOW)
    assert modulo_trazas.FILTRO_AVISOS_EXPORTACION in exportador.filters

    def registro(nombre, mensaje, nivel=logging.WARNING):
        return logging.LogRecord(nombre, nivel, __file__, 1, mensaje, None, None)

    for prefijo in modulo_trazas.PREFIJOS_AVISOS_EXPORTACION:
        assert not exportador.filter(registro(exportador.name, f"{prefijo}: API request to http://mlflow:5000 failed"))
    assert exportador.filter(registro(exportador.name, "Current MLflow server does not support ingesting the span x"))
    assert exportador.filter(registro(exportador.name, "No trace or trace info provided, unable to export"))
    otro = logging.getLogger("mlflow.tracking.fluent")
    assert modulo_trazas.FILTRO_AVISOS_EXPORTACION not in otro.filters  # el resto de MLflow no cambia


def test_etiquetas_distintas_o_ausentes_es_incompleta():
    class ConEtiquetas(TrazadorPrueba):
        def _exportar(self, registro):
            self.exportaciones.append(registro)
            return "tr-1", frozenset({"pedido"}), {"evaluacion.ejecucion": "e1", "version": "v1"}

    sin_etiquetas = traza_con("pedido")
    sin_etiquetas.info = type("Info", (), {"tags": {"evaluacion.ejecucion": "e1"}})()  # falta la versión
    trazador = ConEtiquetas([sin_etiquetas])
    trazador.registrar(Registro(correlacion()))
    esperar_fin(trazador)
    assert trazador.contadores()["incompletas"] == 1 and trazador.contadores()["exportadas"] == 0
    trazador.cerrar()
    completa = traza_con("pedido")
    completa.info = type("Info", (), {"tags": {"evaluacion.ejecucion": "e1", "version": "v1", "otra": "x"}})()
    trazador = ConEtiquetas([completa])
    trazador.registrar(Registro(correlacion()))
    esperar_fin(trazador)
    assert trazador.contadores()["exportadas"] == 1
    trazador.cerrar()


class RelojSimulado:
    """Reloj del calendario de lecturas, controlado por la prueba (sin esperas reales largas)."""

    def __init__(self, inicio=100.0):
        self.ahora = inicio
        self._candado = threading.Lock()

    def __call__(self):
        with self._candado:
            return self.ahora

    def poner(self, valor):
        with self._candado:
            self.ahora = valor


def _esperar(condicion, limite=2.0):
    fin = time.monotonic() + limite
    while time.monotonic() < fin and not condicion():
        time.sleep(0.01)
    return condicion()


def _vencimientos(trazador):
    with trazador._candado:
        return [v[0] for v in trazador._verificaciones]


def test_calendario_absoluto_lecturas_a_1_3_y_7_s_desde_la_exportacion():
    """Cada lectura vence en exportación + 1, + 3 y + 7 s, aunque una lectura tarde (no son intervalos)."""
    reloj = RelojSimulado(100.0)
    instantes = []

    def lector_lento(trace_id):  # cada lectura consume 1,5 s del reloj simulado
        instantes.append(reloj())
        reloj.poner(reloj() + 1.5)
        raise NO_EXISTE

    trazador = TrazadorPrueba(lector=lector_lento, esperas=modulo_trazas.ESPERAS_VERIFICACION_S, reloj=reloj)
    trazador.registrar(Registro(correlacion()))  # la exportación termina con el reloj en 100,0
    assert _esperar(lambda: _vencimientos(trazador) == [101.0])
    reloj.poner(100.9)
    time.sleep(0.3)
    assert instantes == []  # ninguna lectura antes de su vencimiento
    reloj.poner(101.0)
    assert _esperar(lambda: _vencimientos(trazador) == [103.0])  # 100 + 3, no 102,5 + 3
    reloj.poner(103.0)
    assert _esperar(lambda: _vencimientos(trazador) == [107.0])  # 100 + 7, no 104,5 + 7
    reloj.poner(107.0)
    assert _esperar(lambda: trazador.contadores()["no_confirmadas"] == 1)
    assert instantes == [101.0, 103.0, 107.0] and len(trazador.exportaciones) == 1  # 3 lecturas, sin reexportar
    trazador.cerrar()
    assert invariante(trazador)
