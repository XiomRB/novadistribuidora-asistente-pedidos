"""Hito 3: Dockerfile, compose.yaml, .dockerignore y .env.example (sin Docker; corre en la CI).

La prueba de humo con contenedores reales está en `tests/docker/` (marcador `docker`).
"""

import re
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
DOCKERFILE = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load((RAIZ / "compose.yaml").read_text(encoding="utf-8"))
TEXTO_COMPOSE = (RAIZ / "compose.yaml").read_text(encoding="utf-8")
DOCKERIGNORE = [l.strip() for l in (RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
ENV_EJEMPLO = (RAIZ / ".env.example").read_text(encoding="utf-8")
SECRETOS = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|OPENROUTER)", re.IGNORECASE)

sys.path.insert(0, str(RAIZ / "docker"))
from version_git import resolver  # noqa: E402


def instrucciones(nombre):
    return [l.strip() for l in DOCKERFILE.splitlines() if l.strip().upper().startswith(nombre + " ")]


# --- Dockerfile ---------------------------------------------------------------------------------


def test_base_python_312_fijada_por_digest_igual_que_la_ci():
    bases = instrucciones("FROM")
    assert bases and all(re.match(r"FROM python:3\.12-slim@sha256:[0-9a-f]{64}( AS \w+)?$", b) for b in bases)
    assert len({b.split()[1] for b in bases}) == 1  # la misma base en las dos etapas
    assert 'python-version: "3.12"' in (RAIZ / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_dependencias_del_bloqueo_con_no_deps_y_pip_check():
    assert "pip install pip==26.0.1" in DOCKERFILE
    assert "pip install --no-deps -r /tmp/requirements.txt" in DOCKERFILE and "pip check" in DOCKERFILE
    assert "requirements-dev" not in DOCKERFILE
    assert "# syntax=" not in DOCKERFILE  # sin frontend externo sin fijar: el integrado de BuildKit basta


def test_solo_copia_la_aplicacion_y_el_bloqueo():
    copias = instrucciones("COPY") + instrucciones("ADD")
    assert not instrucciones("ADD")
    origenes = sorted(c.split()[1] for c in copias if not c.startswith("COPY --from="))
    assert origenes == ["app/", "requirements.txt"]
    for prohibido in ("datos", ".env", "tests", "evaluacion", ".git", "*.parquet"):
        assert not any(prohibido in c.split()[1] for c in copias if not c.startswith("COPY --from="))


def test_sin_credenciales_en_args_ni_env_y_usuario_no_root():
    for linea in instrucciones("ARG") + instrucciones("ENV"):
        assert not SECRETOS.search(linea), linea
    assert instrucciones("USER") == ["USER app"] and "--uid 10001" in DOCKERFILE


def test_version_desde_git_sin_copiar_git():
    assert "--mount=type=bind,source=.,target=/contexto" in DOCKERFILE and "version_git.py" in DOCKERFILE
    assert '${APP_VERSION:-$(cat /app/VERSION)}' in DOCKERFILE


def test_healthcheck_y_arranque_de_la_api():
    assert instrucciones("HEALTHCHECK") and "http://127.0.0.1:8000/health" in DOCKERFILE
    assert "python -m app.main" in instrucciones("CMD")[-1] and "EXPOSE 8000" in DOCKERFILE


# --- compose.yaml -------------------------------------------------------------------------------


def test_servicios_api_y_mlflow_en_una_red_propia():
    assert set(COMPOSE["services"]) == {"api", "mlflow"}
    assert all(s["networks"] == ["lab3"] for s in COMPOSE["services"].values())
    assert all(s["restart"] == "unless-stopped" for s in COMPOSE["services"].values())


def test_api_credenciales_por_env_file_y_datos_en_solo_lectura():
    api = COMPOSE["services"]["api"]
    assert api["env_file"] == [{"path": "${API_ENV_FILE:-.env}", "required": True}]
    assert api["environment"] == {"DATA_DIR": "/app/datos", "MLFLOW_TRACKING_URI": "http://mlflow:5000"}
    assert api["volumes"] == ["${DATOS_HOST:-./datos}:/app/datos:ro"]
    assert api["ports"] == ["${API_PUERTO:-8000}:8000"]
    assert not SECRETOS.search(TEXTO_COMPOSE.replace("API_ENV_FILE", ""))  # ningún nombre ni valor de clave


def test_la_api_no_espera_a_que_mlflow_este_sano():
    dependencia = COMPOSE["services"]["api"]["depends_on"]["mlflow"]
    assert dependencia == {"condition": "service_started", "required": False}
    assert "service_healthy" not in TEXTO_COMPOSE


def test_mlflow_imagen_oficial_fijada_misma_version_que_el_cliente():
    imagen = COMPOSE["services"]["mlflow"]["image"]
    version = re.search(r"^mlflow-skinny==(\S+)$", (RAIZ / "requirements.txt").read_text(encoding="utf-8"), re.M).group(1)
    assert re.fullmatch(rf"ghcr\.io/mlflow/mlflow:v{re.escape(version)}@sha256:[0-9a-f]{{64}}", imagen)


def test_mlflow_persistente_solo_en_127_0_0_1_y_con_healthcheck():
    mlflow = COMPOSE["services"]["mlflow"]
    assert mlflow["volumes"] == ["mlflow_datos:/mlflow"] and "mlflow_datos" in COMPOSE["volumes"]
    comando = mlflow["command"]
    assert "--backend-store-uri=sqlite:////mlflow/mlflow.db" in comando and "--artifacts-destination=/mlflow/artefactos" in comando
    assert any(c.startswith("--allowed-hosts=mlflow:5000,") for c in comando)
    assert mlflow["ports"] == ["127.0.0.1:${MLFLOW_PUERTO:-5000}:5000"]
    assert "http://127.0.0.1:5000/health" in " ".join(mlflow["healthcheck"]["test"]) and mlflow["healthcheck"]["start_period"] == "120s"


# --- .dockerignore y .env.example ---------------------------------------------------------------


def test_dockerignore_es_lista_blanca_sin_datos_ni_secretos():
    assert DOCKERIGNORE[0] == "*"
    permitidos = [l[1:] for l in DOCKERIGNORE if l.startswith("!")]
    assert permitidos == ["app/", "requirements.txt", "docker/version_git.py", ".git/HEAD", ".git/refs/", ".git/packed-refs"]


def test_env_example_cubre_la_configuracion_sin_secretos():
    variables = set(re.findall(r'"([A-Z][A-Z0-9_]{3,})"', (RAIZ / "app/config.py").read_text(encoding="utf-8")))
    assert variables and all(re.search(rf"^#? ?{v}=", ENV_EJEMPLO, re.M) for v in variables), variables
    assert re.search(r"^OPENROUTER_API_KEY=$", ENV_EJEMPLO, re.M)
    assert not re.search(r"sk-[A-Za-z0-9-]{10,}", ENV_EJEMPLO)


# --- Resolución del SHA de Git (D-H4) -----------------------------------------------------------

SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize(
    ("archivos", "esperado"),
    [
        ({"HEAD": SHA + "\n"}, SHA),  # HEAD separado (clon de un tag, checkout de la CI)
        ({"HEAD": "ref: refs/heads/main\n", "refs/heads/main": SHA + "\n"}, SHA),
        ({"HEAD": "ref: refs/heads/main\n", "packed-refs": f"# pack-refs\n{SHA} refs/heads/main\n"}, SHA),
        ({"HEAD": "ref: refs/heads/main\n"}, "unknown"),
        ({"HEAD": "ref: ../../etc/passwd\n"}, "unknown"),
        ({"HEAD": "basura\n"}, "unknown"),
        ({}, "unknown"),
    ],
    ids=["separado", "rama", "packed_refs", "sin_referencia", "fuera_de_refs", "invalido", "sin_git"],
)
def test_resolver_sha(tmp_path, archivos, esperado):
    git = tmp_path / ".git"
    for ruta, contenido in archivos.items():
        (git / ruta).parent.mkdir(parents=True, exist_ok=True)
        (git / ruta).write_text(contenido, encoding="ascii")
    assert resolver(git) == esperado


def test_git_como_archivo_worktree_da_unknown(tmp_path):
    (tmp_path / ".git").write_text("gitdir: /otro/lugar\n", encoding="ascii")
    assert resolver(tmp_path / ".git") == "unknown"
