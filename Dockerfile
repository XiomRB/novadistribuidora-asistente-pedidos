# Imagen de la API (hito 3). Reproducible: base fijada por digest y dependencias del bloqueo
# (`requirements.txt`, con `--no-deps` y `pip check`). Sin datos, credenciales, pruebas ni `.git`.

FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS dependencias
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv && /opt/venv/bin/python -m pip install pip==26.0.1
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-deps -r /tmp/requirements.txt && /opt/venv/bin/pip check

FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANGSMITH_TRACING=false \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    DATA_DIR=/app/datos
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin app
COPY --from=dependencias /opt/venv /opt/venv
WORKDIR /app
COPY app/ /app/app/
# D-H4: SHA de Git leído del contexto montado solo durante este paso; `.git` no queda en la imagen.
RUN --mount=type=bind,source=.,target=/contexto \
    python /contexto/docker/version_git.py /contexto/.git /app/VERSION && mkdir -p /app/datos
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
# APP_VERSION del entorno solo si no está vacío; si no, el SHA de la construcción.
CMD ["sh", "-c", "APP_VERSION=\"${APP_VERSION:-$(cat /app/VERSION)}\" exec python -m app.main"]
