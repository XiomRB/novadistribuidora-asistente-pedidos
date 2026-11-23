"""Límites de arquitectura: el dominio no depende de LLM, red, MLflow ni FastAPI y no usa float."""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PAQUETES = ["app/datos", "app/dominio"]
IMPORTS_PROHIBIDOS = {
    "langchain",
    "langchain_core",
    "langchain_openai",
    "openai",
    "httpx",
    "mlflow",
    "fastapi",
    "requests",
    "urllib",
    "socket",
    "http",
    "aiohttp",
}
LLAMADAS_PROHIBIDAS = {"float", "repr"}


def _archivos():
    return sorted(p for paquete in PAQUETES for p in (RAIZ / paquete).rglob("*.py"))


def _arbol(ruta: Path) -> ast.AST:
    return ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))


def test_hay_archivos_que_revisar():
    assert len(_archivos()) >= 8


@pytest.mark.parametrize("ruta", _archivos(), ids=lambda p: str(p.relative_to(RAIZ)))
def test_sin_imports_prohibidos(ruta):
    prohibidos = []
    for nodo in ast.walk(_arbol(ruta)):
        if isinstance(nodo, ast.Import):
            nombres = [a.name for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            nombres = [nodo.module or ""]
        else:
            continue
        prohibidos += [n for n in nombres if n.split(".")[0] in IMPORTS_PROHIBIDOS]
    assert not prohibidos, prohibidos


@pytest.mark.parametrize("ruta", _archivos(), ids=lambda p: str(p.relative_to(RAIZ)))
def test_sin_float_ni_repr_ni_decimal_desde_float(ruta):
    infracciones = []
    for nodo in ast.walk(_arbol(ruta)):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            if nodo.func.id in LLAMADAS_PROHIBIDAS:
                infracciones.append(f"{nodo.func.id}() en línea {nodo.lineno}")
            if nodo.func.id == "Decimal" and nodo.args:
                argumento = nodo.args[0]
                if isinstance(argumento, ast.Constant) and isinstance(argumento.value, float):
                    infracciones.append(f"Decimal(float literal) en línea {nodo.lineno}")
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, float):
            infracciones.append(f"literal float {nodo.value} en línea {nodo.lineno}")
    assert not infracciones, infracciones


RELOJ_ATRIBUTOS = {"now", "today", "utcnow", "fromtimestamp", "utcfromtimestamp"}
RELOJ_TIME = {"time", "time_ns", "localtime", "gmtime", "monotonic", "perf_counter"}


@pytest.mark.parametrize("ruta", _archivos(), ids=lambda p: str(p.relative_to(RAIZ)))
def test_sin_reloj_del_sistema(ruta):
    """El dominio nunca consulta la hora actual: solo usa la fecha_hora de la entrada."""
    infracciones = []
    for nodo in ast.walk(_arbol(ruta)):
        if isinstance(nodo, ast.Attribute):
            if nodo.attr in RELOJ_ATRIBUTOS:
                infracciones.append(f".{nodo.attr} en línea {nodo.lineno}")
            if isinstance(nodo.value, ast.Name) and nodo.value.id == "time" and nodo.attr in RELOJ_TIME:
                infracciones.append(f"time.{nodo.attr} en línea {nodo.lineno}")
        if isinstance(nodo, ast.ImportFrom) and nodo.module == "time":
            infracciones.append(f"from time import … en línea {nodo.lineno}")
    assert not infracciones, infracciones
