"""Estado de MLflow para `/health` (hito 2). Sin importar MLflow.

- Sin `MLFLOW_TRACKING_URI`: `mlflow_no_configurado`.
- URI configurada: un hilo de fondo comprueba el servidor cada `intervalo_s` (GET `<uri>/health`
  con timeout de 2 s; para `sqlite:` o `file:` basta con que exista la carpeta). Mientras falle,
  `mlflow_no_disponible`; en cuanto responda, operativo. Tras una caída se recupera solo.
- `/health` solo lee el último estado: nunca hace llamadas de red.
- Al primer éxito ejecuta `al_conectar` (p. ej., preparar el experimento); si falla, se reintenta en
  la siguiente comprobación. El hilo es demonio y `detener()` nunca espera más de unos segundos.
"""

from __future__ import annotations

import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

MOTIVO_MLFLOW_NO_CONFIGURADO = "mlflow_no_configurado"
MOTIVO_MLFLOW_NO_DISPONIBLE = "mlflow_no_disponible"
TIMEOUT_S = 2.0


def comprobar_servidor(uri: str) -> bool:
    partes = urlparse(uri)
    if partes.scheme in ("http", "https"):
        try:
            with urllib.request.urlopen(uri.rstrip("/") + "/health", timeout=TIMEOUT_S) as respuesta:  # noqa: S310 - URI de configuración
                return respuesta.status == 200
        except Exception:  # noqa: BLE001 - cualquier fallo es "no disponible"
            return False
    if partes.scheme in ("sqlite", "file", ""):
        ruta = partes.path if partes.scheme else uri
        return Path(ruta).parent.exists() if partes.scheme == "sqlite" else Path(ruta).exists()
    return False


def uri_local(uri: str) -> bool:
    """El modo completo solo se permite con un almacén local."""
    partes = urlparse(uri)
    return partes.scheme in ("sqlite", "file") or (partes.scheme in ("http", "https") and partes.hostname in ("localhost", "127.0.0.1", "::1", "mlflow"))


class EstadoMlflow:
    def __init__(self, uri: str | None, intervalo_s: float = 10.0, comprobar: Callable[[str], bool] = comprobar_servidor,
                 al_conectar: Callable[[], None] | None = None):
        self.uri = uri or None
        self.intervalo_s = intervalo_s
        self._comprobar = comprobar
        self._al_conectar = al_conectar
        self._disponible = False
        self._conectado = False
        self._candado = threading.Lock()
        self._fin = threading.Event()
        self._hilo: threading.Thread | None = None

    @property
    def configurado(self) -> bool:
        return self.uri is not None

    @property
    def disponible(self) -> bool:
        with self._candado:
            return self._disponible and self._conectado

    def comprobar_ahora(self) -> None:
        if not self.configurado:
            return
        ok = bool(self._comprobar(self.uri))
        conectado = self._conectado
        if ok and not conectado:
            try:
                if self._al_conectar is not None:
                    self._al_conectar()
                conectado = True
            except Exception:  # noqa: BLE001 - se reintenta en la próxima comprobación
                conectado = False
        with self._candado:
            self._disponible = ok
            self._conectado = conectado

    def iniciar(self) -> None:
        if not self.configurado or self._hilo is not None:
            return
        self._hilo = threading.Thread(target=self._bucle, name="estado-mlflow", daemon=True)
        self._hilo.start()

    def _bucle(self) -> None:
        while not self._fin.is_set():
            self.comprobar_ahora()
            self._fin.wait(self.intervalo_s)

    def detener(self) -> None:
        self._fin.set()
        if self._hilo is not None:
            self._hilo.join(timeout=TIMEOUT_S + 1)

    def sonda(self) -> tuple[bool, str | None]:
        if not self.configurado:
            return False, MOTIVO_MLFLOW_NO_CONFIGURADO
        return (True, None) if self.disponible else (False, MOTIVO_MLFLOW_NO_DISPONIBLE)
