"""Hito 3: prueba de humo con la API y MLflow **en contenedores reales** (Docker Compose).

Usa datos sintéticos generados en la prueba (nunca parquet versionados), un `.env` de prueba **sin
clave** (sin coste de OpenRouter), un proyecto de Compose, una imagen y unos puertos propios: no toca
la pila ni el `.env` del usuario. Comprueba:

- La imagen: sin datos ni credenciales, con todos los módulos de `app/` y el SHA de Git como versión.
- La API arranca y responde (503 del intérprete no configurado) y `/health` refleja cada estado.
- Las trazas generadas en el contenedor llevan el SHA de Git y no contienen el mensaje.
- MLflow detenido: la API sigue respondiendo y `/health` informa `mlflow_no_disponible`; se recupera.
- Persistencia de MLflow tras `restart` y `down` + `up` (sin `-v`).
- Sin datos: la API no arranca, Docker la reinicia y se recupera sola al colocar los datos.

Ejecutar: DOCKER_PRUEBAS=1 python -m pytest -q -m docker tests/docker
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from tests.fixtures.historial_e1b2 import escribir
from tests.test_repo_limpio import HASHES_MATERIAL

RAIZ = Path(__file__).resolve().parents[2]
MARCA = "zqxmarcahumo"
SERVICIOS = ("api", "mlflow")


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha_git() -> str:
    resultado = subprocess.run(["git", "-C", str(RAIZ), "rev-parse", "HEAD"], capture_output=True, text=True)
    return resultado.stdout.strip() if resultado.returncode == 0 else "unknown"


def escribir_datos(carpeta: Path) -> None:
    escribir(carpeta)
    for archivo in carpeta.iterdir():
        archivo.chmod(0o644)  # legibles por el usuario no root del contenedor


class Pila:
    """Un proyecto de Compose aislado (nombre, imagen, puertos, `.env` y datos propios)."""

    def __init__(self, base: Path, nombre: str, imagen: str, con_datos: bool = True):
        self.nombre, self.imagen = nombre, imagen
        self.api_puerto, self.mlflow_puerto = puerto_libre(), puerto_libre()
        self.datos = base / f"datos-{nombre}"
        self.datos.mkdir(mode=0o755)
        self.datos.chmod(0o755)
        if con_datos:
            escribir_datos(self.datos)
        self.api_env = base / f"api-{nombre}.env"  # sin clave: nunca usa el .env del usuario
        self.api_env.write_text("OPENROUTER_API_KEY=\nLLM_MODELO=zqx/modelo-humo\nMLFLOW_INTERVALO_S=2\n", encoding="utf-8")
        self.compose_env = base / f"compose-{nombre}.env"
        self._escribir_env()

    def _escribir_env(self) -> None:
        self.compose_env.write_text(
            f"API_ENV_FILE={self.api_env}\nDATOS_HOST={self.datos}\nAPI_PUERTO={self.api_puerto}\n"
            f"MLFLOW_PUERTO={self.mlflow_puerto}\nAPI_IMAGEN={self.imagen}\n", encoding="utf-8")

    def levantar(self, *args: str, timeout: float = 1800) -> None:
        """`up -d`; si el reenvío de puertos de Docker Desktop rechaza los puertos elegidos (error del
        entorno, no del proyecto), baja la pila sin borrar el volumen y reintenta con otros puertos."""
        for intento in range(3):
            resultado = self.compose("up", "-d", *args, timeout=timeout, check=False)
            if resultado.returncode == 0:
                return
            if "ports are not available" not in resultado.stderr or intento == 2:
                raise AssertionError(f"up -d {' '.join(args)} falló: {resultado.stderr[-1500:]}")
            self.compose("down", check=False, timeout=300)
            self.api_puerto, self.mlflow_puerto = puerto_libre(), puerto_libre()
            self._escribir_env()

    def compose(self, *args: str, timeout: float = 900, check: bool = True) -> subprocess.CompletedProcess:
        orden = ["docker", "compose", "-p", self.nombre, "--env-file", str(self.compose_env), "-f", str(RAIZ / "compose.yaml"), *args]
        resultado = subprocess.run(orden, cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
        if check and resultado.returncode != 0:
            raise AssertionError(f"{' '.join(args)} falló: {resultado.stderr[-1500:]}")
        return resultado

    def contenedor(self, servicio: str) -> str:
        return f"{self.nombre}-{servicio}-1"

    def inspeccionar(self, servicio: str, formato: str) -> str:
        return subprocess.run(["docker", "inspect", self.contenedor(servicio), "--format", formato], capture_output=True, text=True).stdout.strip()

    # --- HTTP --------------------------------------------------------------------------------
    def salud(self, timeout: float = 3) -> tuple[dict | None, float]:
        inicio = time.perf_counter()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.api_puerto}/health", timeout=timeout) as r:
                assert r.status == 200
                return json.loads(r.read()), time.perf_counter() - inicio
        except (urllib.error.URLError, ConnectionError, OSError):
            return None, time.perf_counter() - inicio

    def esperar_salud(self, condicion, limite: float = 240) -> dict:
        fin = time.monotonic() + limite
        while time.monotonic() < fin:
            cuerpo, _ = self.salud()
            if cuerpo is not None and condicion(cuerpo):
                return cuerpo
            time.sleep(1)
        raise AssertionError(f"/health no alcanzó la condición en {limite} s (último: {self.salud()[0]})")

    def pedir(self, ejecucion: str, caso: str) -> tuple[int, dict, float]:
        cuerpo = json.dumps({"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": [f"{MARCA} 2 fardos de frijol negro"]}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.api_puerto}/v1/pedidos/interpretar", data=cuerpo, method="POST",
            headers={"Content-Type": "application/json", "X-Evaluacion-Ejecucion": ejecucion, "X-Evaluacion-Caso": caso,
                     "X-Evaluacion-Conjunto": "HUMO", "X-Evaluacion-Repeticion": "0", "X-Evaluacion-Privado": "0"})
        inicio = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, time.perf_counter() - inicio
        except urllib.error.HTTPError as error:
            return error.code, {k.lower(): v for k, v in error.headers.items()}, time.perf_counter() - inicio

    # --- MLflow desde el equipo ----------------------------------------------------------------
    def trazas(self, ejecucion: str) -> list:
        os.environ.update(MLFLOW_HTTP_REQUEST_TIMEOUT="5", MLFLOW_HTTP_REQUEST_MAX_RETRIES="0", MLFLOW_DISABLE_AGENT_HINT="1")
        import mlflow

        mlflow.set_tracking_uri(f"http://127.0.0.1:{self.mlflow_puerto}")
        experimento = mlflow.get_experiment_by_name("lab3-api")
        if experimento is None:
            return []
        return mlflow.search_traces(locations=[experimento.experiment_id], filter_string=f"tags.`evaluacion.ejecucion` = '{ejecucion}'",
                                    return_type="list")

    def esperar_trazas(self, ejecucion: str, n: int, limite: float = 60) -> list:
        """Consulta desde el equipo; reintenta mientras MLflow arranca o responde lento."""
        fin, encontradas = time.monotonic() + limite, []
        while time.monotonic() < fin:
            try:
                encontradas = self.trazas(ejecucion)
            except Exception:  # noqa: BLE001 - timeout o conexión del cliente de la prueba
                encontradas = []
            if len(encontradas) >= n:
                return encontradas
            time.sleep(2)
        return encontradas

    def pedir_con_traza(self, ejecucion: str, intentos: int = 3) -> list:
        """Con timeout de 2 s y 0 reintentos (hito 2), MLflow recién arrancado puede perder una traza:
        se repite el pedido hasta que llegue alguna (cada caso con su propio identificador)."""
        for i in range(intentos):
            assert self.pedir(ejecucion, f"T{i}")[0] == 503
            encontradas = self.esperar_trazas(ejecucion, 1, limite=20)
            if encontradas:
                return encontradas
        return []

    def esperar_mlflow(self, limite: float = 240) -> None:
        fin = time.monotonic() + limite
        while time.monotonic() < fin:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.mlflow_puerto}/health", timeout=3) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(2)
        raise AssertionError("MLflow no respondió")


@pytest.fixture(autouse=True)
def _aislar_uri_de_mlflow():
    """`mlflow.set_tracking_uri()` (consultas desde el equipo) escribe MLFLOW_TRACKING_URI en el entorno del
    proceso de pytest: se restaura al terminar cada prueba para no afectar a otras."""
    original = os.environ.get("MLFLOW_TRACKING_URI")
    yield
    if original is None:
        os.environ.pop("MLFLOW_TRACKING_URI", None)
    else:
        os.environ["MLFLOW_TRACKING_URI"] = original


@pytest.fixture(scope="module")
def base():
    carpeta = Path(tempfile.mkdtemp(prefix="lab3humo-"))
    carpeta.chmod(0o755)
    yield carpeta
    shutil.rmtree(carpeta, ignore_errors=True)


@pytest.fixture(scope="module")
def imagen():
    nombre = f"lab3humo-api:{uuid.uuid4().hex[:8]}"
    yield nombre
    subprocess.run(["docker", "image", "rm", "-f", nombre], capture_output=True)


@pytest.fixture(scope="module")
def pila(base, imagen):
    p = Pila(base, f"lab3humo{uuid.uuid4().hex[:6]}", imagen)
    inicio = time.monotonic()
    p.levantar("--build")
    p.arranque_s = time.monotonic() - inicio
    yield p
    p.compose("logs", "--no-color", check=False)  # disponible en la salida si algo falla
    p.compose("down", "-v", "--remove-orphans", check=False, timeout=300)


def docker_run(imagen: str, *orden: str, usuario: str | None = None) -> str:
    args = ["docker", "run", "--rm", "--network", "none", "--entrypoint", orden[0]]
    if usuario:
        args += ["--user", usuario]
    return subprocess.run([*args, imagen, *orden[1:]], capture_output=True, text=True, timeout=300, check=True).stdout


# --- 1. La imagen ---------------------------------------------------------------------------------


def test_imagen_sin_datos_ni_credenciales(pila):
    assert sorted(docker_run(pila.imagen, "ls", "-A", "/app").split()) == ["VERSION", "app", "datos"]
    assert docker_run(pila.imagen, "ls", "-A", "/app/datos").strip() == ""  # solo el punto de montaje
    assert docker_run(pila.imagen, "id", "-u").strip() == "10001"
    prohibidos = docker_run(pila.imagen, "sh", "-c", "find / -xdev \\( -name .env -o -name '*.env' -o -name mensajes_dev.jsonl "
                            "-o -name .git -o -name '*.zip' -o -name politicas.md -o -name catalogo_problemas.md "
                            "-o -name 'instrucciones*.md' \\) -print 2>/dev/null", usuario="0")
    assert prohibidos.strip() == ""
    # Los únicos .parquet de la imagen son de terceros (pyarrow): ninguno coincide con los datos del curso.
    salida = docker_run(pila.imagen, "sh", "-c", "find / -xdev -name '*.parquet' -exec sha256sum {} + 2>/dev/null", usuario="0")
    for linea in salida.splitlines():
        digest, ruta = linea.split(maxsplit=1)
        assert digest not in HASHES_MATERIAL and ruta.startswith("/opt/venv/lib/python3.12/site-packages/pyarrow/tests/"), ruta
    configuracion = json.loads(subprocess.run(["docker", "image", "inspect", pila.imagen], capture_output=True, text=True, check=True).stdout)[0]
    entorno = " ".join(configuracion["Config"]["Env"])
    historia = subprocess.run(["docker", "history", "--no-trunc", pila.imagen], capture_output=True, text=True, check=True).stdout
    for texto in (entorno, historia):
        assert "OPENROUTER_API_KEY" not in texto and "sk-or" not in texto


def test_imagen_importa_todos_los_modulos_de_app(pila):
    salida = docker_run(pila.imagen, "python", "-c",
                        "import importlib, pkgutil, app; m=[i.name for i in pkgutil.walk_packages(app.__path__, 'app.')]; "
                        "[importlib.import_module(n) for n in m]; print(len(m))")
    assert int(salida) >= 40


def test_version_de_la_imagen_es_el_sha_de_git(pila):
    assert docker_run(pila.imagen, "cat", "/app/VERSION").strip() == sha_git()


# --- 2. La API y MLflow en contenedores -----------------------------------------------------------


def test_api_arranca_y_responde_sin_esperar_a_mlflow(pila):
    cuerpo = pila.esperar_salud(lambda c: True, limite=120)
    assert cuerpo["estado"] == "degradado" and "interprete_no_configurado" in cuerpo["motivo"]
    codigo, encabezados, _ = pila.pedir("humo-arranque", "A0")
    assert codigo == 503 and encabezados.get("retry-after") == "10"


def test_servicios_sanos_y_mlflow_reflejado_en_health(pila):
    pila.esperar_salud(lambda c: c.get("motivo") == "interprete_no_configurado")  # MLflow operativo
    fin = time.monotonic() + 180
    while time.monotonic() < fin and any(pila.inspeccionar(s, "{{.State.Health.Status}}") != "healthy" for s in SERVICIOS):
        time.sleep(2)
    assert [pila.inspeccionar(s, "{{.State.Health.Status}}") for s in SERVICIOS] == ["healthy", "healthy"]
    latencias = [pila.salud()[1] for _ in range(20)]
    assert max(latencias) < 1.0  # /health nunca hace llamadas de red


def avisos_exportador(pila) -> list[str]:
    """Avisos propios del exportador (solo categorías y recuentos; nunca textos ni URL)."""
    lineas = pila.compose("logs", "--no-color", "api", check=False).stdout.splitlines()
    return [l.split("novadistribuidora.observabilidad:", 1)[-1].strip() for l in lineas if "traza no " in l]


def resumen_al_cerrar(pila) -> dict[str, int]:
    lineas = [l for l in pila.compose("logs", "--no-color", "api", check=False).stdout.splitlines() if "trazas al cerrar:" in l]
    assert lineas, "la API no registró el resumen de trazas al cerrar"
    return {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", lineas[-1])}


def test_trazas_en_el_contenedor_con_sha_de_git_y_sin_contenido(pila):
    # MLflow recién arrancado puede tardar en sus primeras escrituras: un pedido de calentamiento, no evaluado.
    pila.pedir_con_traza("humo-calentamiento")
    for caso in ("C0", "C1"):
        assert pila.pedir("humo-trazas", caso)[0] == 503
    trazas = pila.esperar_trazas("humo-trazas", 2, limite=60)
    if len(trazas) != 2:
        pytest.fail(f"{len(trazas)} de 2 trazas confirmadas; avisos del exportador: {avisos_exportador(pila)[-3:]}")
    for traza in trazas:
        assert traza.info.tags["version"] == sha_git() and traza.info.tags["contenido"] == "metadatos"
        assert traza.info.tags["modelo"] == "zqx/modelo-humo"
        texto = traza.to_json()
        assert MARCA not in texto and "K04" not in texto


def test_mlflow_detenido_la_api_responde_y_health_se_degrada_y_recupera(pila):
    pila.compose("stop", "mlflow", timeout=120)
    cuerpo = pila.esperar_salud(lambda c: "mlflow_no_disponible" in c.get("motivo", ""), limite=30)
    assert cuerpo["estado"] == "degradado"
    codigo, _, duracion = pila.pedir("humo-caido", "X0")
    assert codigo == 503 and duracion < 3  # misma respuesta que con MLflow operativo, sin esperas
    assert pila.inspeccionar("api", "{{.State.Status}}") == "running"
    pila.compose("start", "mlflow", timeout=120)
    pila.esperar_salud(lambda c: c.get("motivo") == "interprete_no_configurado", limite=240)
    assert pila.pedir_con_traza("humo-recuperado")  # tras la recuperación vuelven a llegar trazas
    assert pila.esperar_trazas("humo-caido", 1, limite=5) == []  # descartada mientras MLflow no estaba disponible


def test_persistencia_de_mlflow_tras_restart_y_down_up(pila):
    antes = {t.info.trace_id for t in pila.esperar_trazas("humo-trazas", 1)}
    assert antes
    pila.compose("restart", "mlflow", timeout=120)
    pila.esperar_mlflow()
    assert {t.info.trace_id for t in pila.esperar_trazas("humo-trazas", len(antes))} == antes
    # Cierre ordenado de la API: el resumen cumple el invariante y nada quedó como fallida.
    pila.compose("stop", "api", timeout=120)
    resumen = resumen_al_cerrar(pila)
    categorias = ("exportadas", "incompletas", "no_confirmadas", "fallidas", "descartadas")
    assert resumen["registradas"] == sum(resumen[c] for c in categorias), resumen
    assert resumen["fallidas"] == 0 and resumen["exportadas"] >= 3, resumen  # 2 medidas y la de recuperación, como mínimo
    pila.compose("down", timeout=300)  # sin -v: el volumen se conserva
    volumenes = subprocess.run(["docker", "volume", "ls", "--format", "{{.Name}}"], capture_output=True, text=True).stdout.split()
    assert f"{pila.nombre}_mlflow_datos" in volumenes
    pila.levantar(timeout=600)
    pila.esperar_mlflow()
    assert {t.info.trace_id for t in pila.esperar_trazas("humo-trazas", len(antes))} == antes


# --- 3. Sin datos ---------------------------------------------------------------------------------


def test_sin_datos_la_api_no_arranca_docker_reinicia_y_se_recupera_al_colocarlos(base, imagen, pila):
    sin_datos = Pila(base, f"lab3sindatos{uuid.uuid4().hex[:6]}", imagen, con_datos=False)
    try:
        sin_datos.levantar("--no-deps", "api", timeout=600)
        fin = time.monotonic() + 60
        while time.monotonic() < fin and int(sin_datos.inspeccionar("api", "{{.RestartCount}}") or 0) < 2:
            time.sleep(1)
        assert int(sin_datos.inspeccionar("api", "{{.RestartCount}}")) >= 2  # Docker sí la reinicia
        assert sin_datos.salud()[0] is None  # nunca llega a responder
        registro = sin_datos.compose("logs", "--no-color", "api").stdout
        assert "ARCHIVO_FALTANTE" in registro and "clientes.parquet" in registro
        escribir_datos(sin_datos.datos)  # se colocan los datos: sin intervención adicional
        cuerpo = sin_datos.esperar_salud(lambda c: True, limite=180)
        assert "interprete_no_configurado" in cuerpo["motivo"]
    finally:
        sin_datos.compose("down", "-v", "--remove-orphans", check=False, timeout=300)
