"""Pruebas de humo con Docker Compose (marcador `docker`): solo con `DOCKER_PRUEBAS=1` y Docker disponible."""

import os
import shutil
import subprocess

import pytest


def pytest_collection_modifyitems(config, items):
    motivo = None
    if os.environ.get("DOCKER_PRUEBAS") != "1":
        motivo = "pruebas de humo con Docker: requieren DOCKER_PRUEBAS=1"
    elif shutil.which("docker") is None or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        motivo = "Docker Compose no disponible"
    for item in items:
        if "tests/docker/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(pytest.mark.docker)
            if motivo:
                item.add_marker(pytest.mark.skip(reason=motivo))
