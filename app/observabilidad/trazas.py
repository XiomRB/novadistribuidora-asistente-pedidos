"""Trazas de las solicitudes en MLflow (hito 2).

Es el único módulo de `app/` que usa MLflow (`test_capas.py`). Convierte cada `Registro` en una
traza con tres tramos (`pedido`, `interprete`, `motor`) con sus tiempos reales.

Privacidad (D-M1):
- Modo `metadatos` (por defecto): solo recuentos, estados, códigos, latencias, tokens, coste, modelo,
  variante y versión. Nunca mensajes, `cliente_id`, instrucciones, texto de pendientes, SKU,
  cantidades, importes, claves ni mensajes de error.
- Modo `completo`: además la entrada y la interpretación, SOLO si (1) está configurado
  explícitamente, (2) el almacén es local y (3) la solicitud declara un conjunto público
  (`X-Evaluacion-Conjunto` y `X-Evaluacion-Privado: 0`) que no sea privado por código
  (`CONJUNTOS_SOLO_METADATOS`, que incluye D39). Si falta cualquiera, metadatos.

Disponibilidad: antes de importar MLflow se fijan timeout HTTP de 2 s, reintentos 0 y un reintento
asíncrono acotado. El hilo de la solicitud **nunca** llama a MLflow: solo deja el registro en un búfer
propia acotada (`MAX_PENDIENTES`) y un único hilo de fondo lo exporta. Si MLflow no está disponible o la
búfer está lleno, la traza se descarta y se cuenta. Ningún error de aquí cambia la respuesta.
`cerrar()` drena el búfer y vacía el de MLflow con un límite total de tiempo (`ESPERA_CIERRE_S`).
(En la demostración con Uvicorn, la primera exportación desde el hilo de la solicitud llegó a tardar
unos 20 s: por eso la exportación no ocurre nunca en ese hilo. El envío asíncrono de MLflow se
desactiva: agrupaba spans hasta 5 s y perdía trazas pendientes si el servidor caía.)
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any

from app.observabilidad.estado_mlflow import EstadoMlflow, uri_local
from app.observabilidad.registro import Registro

CONJUNTOS_SOLO_METADATOS = frozenset({"D39"})
ESPERA_CIERRE_S = 5.0
MAX_PENDIENTES = 1000
_AJUSTES_MLFLOW = {
    "MLFLOW_HTTP_REQUEST_TIMEOUT": "2",
    "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "0",
    "MLFLOW_ASYNC_TRACE_LOGGING_RETRY_TIMEOUT": "5",
    # La exportación ya ocurre en el hilo propio de fondo: sin el envío asíncrono de MLflow, que agrupa spans
    # (hasta 5 o 5 s) y perdía trazas pendientes si el servidor caía antes de enviarlas.
    "MLFLOW_ENABLE_ASYNC_TRACE_LOGGING": "false",
    "MLFLOW_DISABLE_AGENT_HINT": "1",
}

log = logging.getLogger("novadistribuidora.observabilidad")


_AJUSTADO = False


def _mlflow() -> Any:
    global _AJUSTADO
    if not _AJUSTADO:  # antes del primer import: fija los límites de tiempo y reintentos (F)
        os.environ.update(_AJUSTES_MLFLOW)
        _AJUSTADO = True
    import mlflow

    return mlflow


def contenido_permitido(modo: str, uri: str | None, registro: Registro) -> bool:
    c = registro.correlacion
    return (
        modo == "completo" and uri is not None and uri_local(uri)
        and c.conjunto is not None and not c.privado and c.conjunto not in CONJUNTOS_SOLO_METADATOS
    )


class Trazador:
    def __init__(self, estado: EstadoMlflow, experimento: str = "lab3-api", modo: str = "metadatos", version: str = "desconocida",
                 modelo: str = "", variante: str = ""):
        self.estado = estado
        self.experimento = experimento
        self.modo = modo
        self.version = version
        self.modelo = modelo
        self.variante = variante
        self.experiment_id: str | None = None
        self.descartadas = 0
        self.fallidas = 0
        self.exportadas = 0
        self._candado = threading.Lock()
        self._pendientes: queue.Queue[Registro] = queue.Queue(maxsize=MAX_PENDIENTES)
        self._fin = threading.Event()
        self._hilo: threading.Thread | None = None

    def preparar(self) -> None:
        """Se ejecuta en el hilo de `EstadoMlflow` al conectar: fija la URI y el experimento."""
        mlflow = _mlflow()
        mlflow.set_tracking_uri(self.estado.uri)
        self.experiment_id = mlflow.set_experiment(self.experimento).experiment_id

    def _descartar(self) -> None:
        with self._candado:
            self.descartadas += 1

    def registrar(self, registro: Registro) -> None:
        """En el hilo de la solicitud: solo encola (sin MLflow, sin red, sin esperas)."""
        if not self.estado.disponible or self.experiment_id is None or self._fin.is_set():
            self._descartar()
            return
        self._asegurar_hilo()
        try:
            self._pendientes.put_nowait(registro)
        except queue.Full:
            self._descartar()

    def _asegurar_hilo(self) -> None:
        with self._candado:
            if self._hilo is None:
                self._hilo = threading.Thread(target=self._exportador, name="exportar-trazas", daemon=True)
                self._hilo.start()

    def _exportador(self) -> None:
        while not (self._fin.is_set() and self._pendientes.empty()):
            try:
                registro = self._pendientes.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self.estado.disponible:
                    self._exportar(registro)
                    with self._candado:
                        self.exportadas += 1
                else:
                    self._descartar()
            except Exception as error:  # noqa: BLE001 - una traza nunca afecta a la API
                with self._candado:
                    self.fallidas += 1
                log.warning("traza no registrada (%s)", type(error).__name__)
            finally:
                self._pendientes.task_done()

    def _exportar(self, registro: Registro) -> None:
        mlflow = _mlflow()
        completo = contenido_permitido(self.modo, self.estado.uri, registro)
        etiquetas = {**registro.correlacion.etiquetas(), "modelo": self.modelo, "variante": self.variante, "version": self.version,
                     "contenido": "completo" if completo else "metadatos"}
        raiz = mlflow.start_span_no_context(
            "pedido", span_type="CHAIN", tags=etiquetas, experiment_id=self.experiment_id, start_time_ns=registro.inicio_ns,
            attributes=dict(registro.atributos.get("pedido", {})), inputs=registro.contenido.get("entrada") if completo else None,
        )
        for tramo, tipo in (("interprete", "LLM"), ("motor", "CHAIN")):
            if tramo in registro.tramos:
                inicio, fin = registro.tramos[tramo]
                hijo = mlflow.start_span_no_context(tramo, span_type=tipo, parent_span=raiz, start_time_ns=inicio,
                                                    attributes=dict(registro.atributos.get(tramo, {})))
                salida = registro.contenido.get("interpretacion") if completo and tramo == "interprete" else None
                hijo.end(outputs=salida, end_time_ns=fin)
        codigo = registro.atributos.get("pedido", {}).get("codigo_http")
        raiz.end(status="OK" if codigo == 200 else "ERROR", end_time_ns=registro.fin_ns)

    def cerrar(self) -> None:
        """Drena los pendientes propios y vacía el de MLflow sin bloquear más de `ESPERA_CIERRE_S` en total."""
        limite = time.monotonic() + ESPERA_CIERRE_S
        self._fin.set()
        if self._hilo is not None:
            self._hilo.join(timeout=max(0.0, limite - time.monotonic()))
        if self.experiment_id is None:
            return

        def vaciar() -> None:
            try:
                _mlflow().flush_trace_async_logging(terminate=True)
            except Exception:  # noqa: BLE001
                pass

        hilo = threading.Thread(target=vaciar, name="vaciar-trazas", daemon=True)
        hilo.start()
        hilo.join(timeout=max(0.1, limite - time.monotonic()))
