"""Verifica que el entorno instalado desde los bloqueos importe y tenga las versiones fijadas."""

import importlib
import sys
from importlib.metadata import version

MODULOS = [
    "fastapi",
    "fastapi.testclient",
    "uvicorn",
    "pydantic",
    "langchain_core",
    "langchain_openai",
    "openai",
    "mlflow",
    "mlflow.langchain",
    "mlflow.tracing",
    "pandas",
    "pyarrow",
    "pyarrow.parquet",
    "httpx",
    "pytest",
]

VERSIONES_DIRECTAS = {
    "fastapi": "0.165.0",
    "uvicorn": "0.54.0",
    "pydantic": "2.14.4",
    "langchain-core": "1.8.4",
    "langchain-openai": "1.8.5",
    "mlflow-skinny": "3.18.0",
    "pandas": "3.1.1",
    "pyarrow": "26.0.1",
}


def test_python_312():
    assert sys.version_info[:2] == (3, 12)


def test_imports_componentes_principales():
    fallos = []
    for modulo in MODULOS:
        try:
            importlib.import_module(modulo)
        except Exception as exc:  # noqa: BLE001 - se reporta cualquier fallo de import
            fallos.append(f"{modulo}: {type(exc).__name__}: {exc}")
    assert not fallos, fallos


def test_versiones_fijadas():
    instaladas = {paquete: version(paquete) for paquete in VERSIONES_DIRECTAS}
    assert instaladas == VERSIONES_DIRECTAS


def test_lectura_parquet(tmp_path):
    import pandas as pd

    ruta = tmp_path / "x.parquet"
    pd.DataFrame({"a": [1, 2]}).to_parquet(ruta)
    assert pd.read_parquet(ruta)["a"].tolist() == [1, 2]
