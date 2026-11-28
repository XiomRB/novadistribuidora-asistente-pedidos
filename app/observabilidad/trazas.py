"""Trazas de las solicitudes en MLflow (hito 2).

Es el único módulo de `app/` que usa MLflow (`test_capas.py`). Convierte cada `Registro` en una
traza con tres tramos (`pedido`, `interprete`, `motor`) con sus tiempos reales.

Privacidad (D-M1):
- Modo `metadatos` (por defecto): solo recuentos, estados, códigos, latencias, tokens, coste, modelo,
  variante y versión. Nunca mensajes, `cliente_id`, instrucciones, texto de pendientes, SKU,
  cantidades, importes, claves ni mensajes de error.
- Modo `completo`: además la entrada y la interpretación, SOLO si `contenido_permitido`
  (`registro.py`) lo autoriza: configuración explícita, almacén local y un conjunto declarado público
  que no esté en `CONJUNTOS_SOLO_METADATOS` (D39). La política se aplica al **capturar**
  (`permite_contenido`, al abrir el registro): sin autorización el contenido nunca entra en el registro
  ni en el búfer. Al exportar se comprueba otra vez, como defensa adicional.

Disponibilidad: antes de importar MLflow se fijan timeout HTTP de 2 s y 0 reintentos, y se desactiva
el envío asíncrono de MLflow (agrupaba spans hasta 5 s y perdía trazas pendientes si el servidor caía).
El hilo de la solicitud **nunca** llama a MLflow: solo deja el registro en un búfer propio acotado
(`MAX_PENDIENTES`). Un hilo propio (`exportar-trazas`) lo exporta de forma síncrona y otro
(`verificar-trazas`) confirma después que MLflow la guardó. Ningún error de aquí cambia la respuesta.
(En la demostración con Uvicorn, la primera exportación desde el hilo de la solicitud llegó a tardar
unos 20 s: por eso la exportación no ocurre nunca en ese hilo.)

Confirmación (revisión del PR #14): el exportador de MLflow captura sus propios errores (`start_trace`
solo emite un aviso y `log_spans` lo registra en DEBUG), así que una traza puede perderse sin
excepción. Por eso cada traza exportada se **lee** con la API pública (`MlflowClient.get_trace`) a
+1, +3 y +7 s (`ESPERAS_VERIFICACION_S`); **nunca se reexporta**, porque la API pública no permite
reenviar con el mismo `trace_id` y un reenvío podría duplicarla. Cada registro cuenta en una sola
categoría:

- `exportadas`: encontrada con todos sus tramos y sus etiquetas (correlación, modelo, variante, versión).
- `incompletas`: encontrada, pero sin alguno de sus tramos o etiquetas en la última lectura (p. ej., si
  `start_trace` falla y `log_spans` no: el almacén crea la traza con los spans, pero sin etiquetas, y
  la evaluación no puede correlacionarla).
- `no_confirmadas`: no se pudo confirmar dentro de la ventana (no encontrada, error de lectura,
  MLflow no disponible, verificaciones pendientes al límite o cierre). **No significa necesariamente que la
  traza nunca se guardó**: el servidor pudo terminar de guardarla después de la última lectura.
- `fallidas`: excepción propia del exportador.
- `descartadas`: no llegó a exportarse (MLflow no disponible, búfer lleno o cierre).

Invariante: `registradas = exportadas + incompletas + no_confirmadas + fallidas + descartadas + en curso`;
tras `cerrar()` no queda nada en curso y los contadores se congelan. `cerrar()` termina en
`ESPERA_CIERRE_S` como máximo; lo pendiente al vencer el plazo nunca cuenta como exportada.

Logs: se filtran solo los avisos de exportación de MLflow que incluyen la URL interna y el texto de la
excepción (`_FiltroAvisosExportacion`); los sustituyen avisos propios con categorías y recuentos.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from app.observabilidad.estado_mlflow import EstadoMlflow
from app.observabilidad.registro import CONJUNTOS_SOLO_METADATOS, Correlacion, Registro, contenido_permitido

__all__ = ["CONJUNTOS_SOLO_METADATOS", "Trazador", "contenido_permitido"]
ESPERA_CIERRE_S = 5.0
MAX_PENDIENTES = 1000
MAX_VERIFICACIONES = 1000
ESPERAS_VERIFICACION_S = (1.0, 3.0, 7.0)  # lecturas a +1, +3 y +7 s de la exportación
CATEGORIAS = ("exportadas", "incompletas", "no_confirmadas", "fallidas", "descartadas")
# Avisos de exportación de MLflow que interpolan la excepción (URL interna y detalles): se filtran.
PREFIJOS_AVISOS_EXPORTACION = (
    "Failed to send trace to MLflow backend",
    "Failed to log span to MLflow backend",
    "Failed to upload attachments of remote trace",
    "Failed to upload trace attachments",
    "Failed to link prompts to trace",
)
LOGGER_EXPORTADOR_MLFLOW = "mlflow.tracing.export.mlflow_v3"
_AJUSTES_MLFLOW = {
    "MLFLOW_HTTP_REQUEST_TIMEOUT": "2",
    "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "0",
    "MLFLOW_ASYNC_TRACE_LOGGING_RETRY_TIMEOUT": "5",  # solo aplicaría si se reactivara el envío asíncrono
    # La exportación ocurre en el hilo propio de fondo: sin el envío asíncrono de MLflow, que agrupa spans
    # (hasta 5 o 5 s) y perdía trazas pendientes si el servidor caía antes de enviarlas.
    "MLFLOW_ENABLE_ASYNC_TRACE_LOGGING": "false",
    "MLFLOW_DISABLE_AGENT_HINT": "1",
}

log = logging.getLogger("novadistribuidora.observabilidad")


_AJUSTADO = False


class _FiltroAvisosExportacion(logging.Filter):
    """Descarta solo los avisos de exportación de MLflow con detalles de la excepción; el resto pasa."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            mensaje = record.getMessage()
        except Exception:  # noqa: BLE001 - un registro mal formado no se filtra
            return True
        return not mensaje.startswith(PREFIJOS_AVISOS_EXPORTACION)


FILTRO_AVISOS_EXPORTACION = _FiltroAvisosExportacion()


def _mlflow() -> Any:
    global _AJUSTADO
    if not _AJUSTADO:  # antes del primer import: fija los límites de tiempo y reintentos (F)
        os.environ.update(_AJUSTES_MLFLOW)
        logging.getLogger(LOGGER_EXPORTADOR_MLFLOW).addFilter(FILTRO_AVISOS_EXPORTACION)
        _AJUSTADO = True
    import mlflow

    return mlflow


def _codigo_error(error: BaseException) -> str | None:
    codigo = getattr(error, "error_code", None)
    return codigo if isinstance(codigo, str) else None


def leer_traza_mlflow(uri: str | None) -> Callable[[str], Any]:
    """Lector por la API pública: `MlflowClient.get_trace` contra el servidor configurado."""
    cliente = _mlflow().MlflowClient(uri)

    def leer(trace_id: str) -> Any:
        return cliente.get_trace(trace_id, display=False)

    return leer


class Trazador:
    def __init__(self, estado: EstadoMlflow, experimento: str = "lab3-api", modo: str = "metadatos", version: str = "desconocida",
                 modelo: str = "", variante: str = "", lector: Callable[[str], Any] | None = None,
                 esperas: tuple[float, ...] = ESPERAS_VERIFICACION_S):
        self.estado = estado
        self.experimento = experimento
        self.modo = modo
        self.version = version
        self.modelo = modelo
        self.variante = variante
        self.experiment_id: str | None = None
        self.esperas = tuple(esperas)
        self._lector = lector
        self.registradas = 0
        self.exportadas = self.incompletas = self.no_confirmadas = self.fallidas = self.descartadas = 0
        self._candado = threading.Lock()
        self._aviso = threading.Condition(self._candado)
        self._pendientes: deque[Registro] = deque()
        self._exportando = 0
        self._verificaciones: list[tuple[float, int, str, tuple, int]] = []  # (vence, orden, id, esperado, lecturas)
        self._verificando = 0
        self._orden = itertools.count()
        self._congelado = False
        self._limite: float | None = None
        self._fin = threading.Event()
        self._hilo: threading.Thread | None = None
        self._hilo_verificador: threading.Thread | None = None

    # --- Contadores ---------------------------------------------------------------------------

    def contadores(self) -> dict[str, int]:
        with self._candado:
            return {"registradas": self.registradas, **{c: getattr(self, c) for c in CATEGORIAS},
                    "en_curso": len(self._pendientes) + self._exportando + len(self._verificaciones) + self._verificando}

    def _resumen(self) -> str:  # se llama con el candado tomado; solo recuentos
        return " ".join(f"{c}={getattr(self, c)}" for c in ("registradas", *CATEGORIAS))

    def _sumar(self, categoria: str) -> None:  # con el candado tomado
        if not self._congelado:
            setattr(self, categoria, getattr(self, categoria) + 1)

    def _descartar(self) -> None:
        with self._candado:
            self._sumar("descartadas")

    # --- Preparación y política ---------------------------------------------------------------

    def preparar(self) -> None:
        """Se ejecuta en el hilo de `EstadoMlflow` al conectar: fija la URI y el experimento."""
        mlflow = _mlflow()
        mlflow.set_tracking_uri(self.estado.uri)
        self.experiment_id = mlflow.set_experiment(self.experimento).experiment_id
        if self._lector is None:
            self._lector = leer_traza_mlflow(self.estado.uri)

    def permite_contenido(self, correlacion: Correlacion) -> bool:
        """Se consulta al abrir el registro: decide si la solicitud puede capturar contenido."""
        return contenido_permitido(self.modo, self.estado.uri, correlacion)

    # --- Hilo de la solicitud: solo encola ----------------------------------------------------

    def registrar(self, registro: Registro) -> None:
        """En el hilo de la solicitud: solo encola (sin MLflow, sin red, sin esperas)."""
        with self._aviso:
            if self._congelado:
                return
            self.registradas += 1
            if (not self.estado.disponible or self.experiment_id is None or self._fin.is_set()
                    or len(self._pendientes) >= MAX_PENDIENTES):
                self._sumar("descartadas")
                return
            self._pendientes.append(registro)
            if self._hilo is None:
                self._hilo = threading.Thread(target=self._exportador, name="exportar-trazas", daemon=True)
                self._hilo.start()
            self._aviso.notify_all()

    # --- Exportador ---------------------------------------------------------------------------

    def _vencido(self) -> bool:
        return self._limite is not None and time.monotonic() >= self._limite

    def _exportador(self) -> None:
        while True:
            with self._aviso:
                while not self._pendientes and not self._fin.is_set():
                    self._aviso.wait(timeout=0.2)
                if not self._pendientes or self._congelado or self._vencido():
                    return
                registro = self._pendientes.popleft()
                self._exportando += 1
            resultado, error = None, None
            if self.estado.disponible:
                try:
                    resultado = self._exportar(registro)
                except Exception as e:  # noqa: BLE001 - una traza nunca afecta a la API
                    error = e
            with self._aviso:
                if self._congelado:  # el cierre ya lo contó como pendiente
                    return
                self._exportando -= 1
                if not self.estado.disponible and error is None and resultado is None:
                    self._sumar("descartadas")
                elif error is not None:
                    self._sumar("fallidas")
                    if not self._congelado:
                        log.warning("traza no registrada (%s); %s", type(error).__name__, self._resumen())
                elif not resultado:
                    self._sumar("no_confirmadas")  # sin identificador no hay forma de confirmarla
                else:
                    esperado = (frozenset(resultado[1]), frozenset(resultado[2].items()) if len(resultado) > 2 else frozenset())
                    self._programar(resultado[0], esperado, 0)

    def _programar(self, trace_id: str, esperado: tuple, lecturas: int) -> None:  # con el candado tomado
        if self._congelado:
            return
        if len(self._verificaciones) >= MAX_VERIFICACIONES:
            self._sumar("no_confirmadas")
            return
        espera = self.esperas[lecturas] if lecturas < len(self.esperas) else 0.0
        heapq.heappush(self._verificaciones, (time.monotonic() + espera, next(self._orden), trace_id, esperado, lecturas))
        if self._hilo_verificador is None:
            self._hilo_verificador = threading.Thread(target=self._verificador, name="verificar-trazas", daemon=True)
            self._hilo_verificador.start()
        self._aviso.notify_all()

    def _exportar(self, registro: Registro) -> tuple[str, frozenset[str], dict[str, str]]:
        mlflow = _mlflow()
        completo = registro.captura_contenido and self.permite_contenido(registro.correlacion)  # defensa adicional
        etiquetas = {**registro.correlacion.etiquetas(), "modelo": self.modelo, "variante": self.variante, "version": self.version,
                     "contenido": "completo" if completo else "metadatos"}
        raiz = mlflow.start_span_no_context(
            "pedido", span_type="CHAIN", tags=etiquetas, experiment_id=self.experiment_id, start_time_ns=registro.inicio_ns,
            attributes=dict(registro.atributos.get("pedido", {})), inputs=registro.contenido.get("entrada") if completo else None,
        )
        tramos = {"pedido"}
        for tramo, tipo in (("interprete", "LLM"), ("motor", "CHAIN")):
            if tramo in registro.tramos:
                inicio, fin = registro.tramos[tramo]
                hijo = mlflow.start_span_no_context(tramo, span_type=tipo, parent_span=raiz, start_time_ns=inicio,
                                                    attributes=dict(registro.atributos.get(tramo, {})))
                salida = registro.contenido.get("interpretacion") if completo and tramo == "interprete" else None
                hijo.end(outputs=salida, end_time_ns=fin)
                tramos.add(tramo)
        codigo = registro.atributos.get("pedido", {}).get("codigo_http")
        raiz.end(status="OK" if codigo == 200 else "ERROR", end_time_ns=registro.fin_ns)
        return raiz.trace_id, frozenset(tramos), etiquetas

    # --- Verificador (solo lecturas; nunca reexporta) -----------------------------------------

    def _leer(self, trace_id: str, esperado: tuple) -> str:
        """Una lectura: `exportada`, `incompleta`, `no_encontrada` o `indeterminada`."""
        tramos, etiquetas = esperado
        if not self.estado.disponible or self._lector is None:
            return "indeterminada"
        try:
            traza = self._lector(trace_id)
        except Exception as error:  # noqa: BLE001 - solo cuenta el código del servidor
            return "no_encontrada" if _codigo_error(error) == "RESOURCE_DOES_NOT_EXIST" else "indeterminada"
        try:
            nombres = {s.name for s in traza.data.spans}
            guardadas = dict(getattr(getattr(traza, "info", None), "tags", None) or {})
        except Exception:  # noqa: BLE001
            return "indeterminada"
        completa = tramos <= nombres and all(guardadas.get(k) == v for k, v in etiquetas)
        return "exportada" if completa else "incompleta"

    def _verificador(self) -> None:
        while True:
            with self._aviso:
                while True:
                    if self._congelado or self._vencido() or (self._fin.is_set() and not self._verificaciones
                                                             and not self._pendientes and not self._exportando):
                        return
                    if self._verificaciones and (self._fin.is_set() or self._verificaciones[0][0] <= time.monotonic()):
                        break  # al cerrar, una lectura inmediata por traza, sin esperas
                    espera = self._verificaciones[0][0] - time.monotonic() if self._verificaciones else 0.2
                    self._aviso.wait(timeout=max(0.01, min(espera, 0.2)))
                _, _, trace_id, esperado, lecturas = heapq.heappop(self._verificaciones)
                self._verificando += 1
                cerrando = self._fin.is_set()
            resultado = self._leer(trace_id, esperado)
            with self._aviso:
                if self._congelado:  # el cierre ya la contó como no confirmada
                    return
                self._verificando -= 1
                if resultado == "exportada":
                    self._sumar("exportadas")
                elif lecturas + 1 < len(self.esperas) and not cerrando:
                    self._programar(trace_id, esperado, lecturas + 1)
                else:
                    categoria = "incompletas" if resultado == "incompleta" else "no_confirmadas"
                    self._sumar(categoria)
                    if not self._congelado:
                        log.warning("traza no confirmada (%s tras %d lecturas); %s", resultado, lecturas + 1, self._resumen())

    # --- Cierre -------------------------------------------------------------------------------

    def cerrar(self) -> None:
        """Termina en `ESPERA_CIERRE_S` como máximo; lo pendiente se cuenta y nunca como exportada."""
        limite = time.monotonic() + ESPERA_CIERRE_S
        with self._aviso:
            self._limite = limite
            self._fin.set()
            self._aviso.notify_all()
        for hilo in (self._hilo, self._hilo_verificador):
            if hilo is not None:
                hilo.join(timeout=max(0.0, limite - time.monotonic()))
        hilo = self._hilo_verificador  # pudo crearse durante el cierre
        if hilo is not None and hilo.is_alive():
            hilo.join(timeout=max(0.0, limite - time.monotonic()))
        with self._aviso:
            if not self._congelado:
                self.descartadas += len(self._pendientes)
                self.no_confirmadas += self._exportando + len(self._verificaciones) + self._verificando
                self._pendientes.clear()
                self._verificaciones.clear()
                self._exportando = self._verificando = 0
                self._congelado = True
                self._aviso.notify_all()
                if self.registradas:
                    log.info("trazas al cerrar: %s", self._resumen())
