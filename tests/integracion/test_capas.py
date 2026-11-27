"""E2b: dependencias entre capas.

- `app/datos`, `app/dominio` y `app/mensajes` no importan la API, el servicio, la aplicación, el
  intérprete ni la configuración.
- La API, el servicio, la aplicación, la configuración y el intérprete no importan LangChain,
  OpenAI ni MLflow (llegan en E3 y E4, en sus módulos propios).
- `float` solo aparece en `app/api/esquemas.py`, en el serializador de los montos (D03).
- E2c: la aplicación (`app/`) nunca depende del evaluador (`evaluacion/`); el evaluador tampoco depende
  de LangChain, OpenAI ni MLflow, y su correspondencia y sus veredictos no usan `float`.
"""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
NUCLEO = ["app/datos", "app/dominio", "app/mensajes"]
BORDE = ["app/api", "app/interprete", "app/servicio.py", "app/main.py", "app/config.py"]
CAPAS_EXTERNAS = ("app.api", "app.servicio", "app.main", "app.interprete", "app.config")
PROHIBIDOS_EN_E2 = {"langchain", "langchain_core", "langchain_openai", "openai", "mlflow"}
LLM = {"langchain", "langchain_core", "langchain_openai", "openai"}
UNICO_CON_LLM = "app/interprete/llm.py"  # hito 1: LangChain y OpenRouter solo aquí
EVALUADOR = ["evaluacion"]
SIN_FLOAT_EN_EVALUADOR = ["evaluacion/correspondencia.py", "evaluacion/criticos.py", "evaluacion/reporte.py", "evaluacion/comparacion.py", "evaluacion/conjuntos.py"]


def _archivos(rutas):
    resultado = []
    for ruta in rutas:
        p = RAIZ / ruta
        resultado += sorted(p.rglob("*.py")) if p.is_dir() else [p]
    return resultado


def _imports(ruta):
    nombres = []
    for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres += [a.name for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            nombres.append(nodo.module or "")
    return nombres


@pytest.mark.parametrize("ruta", _archivos(NUCLEO), ids=lambda p: str(p.relative_to(RAIZ)))
def test_el_nucleo_no_importa_las_capas_externas(ruta):
    assert not [n for n in _imports(ruta) if n.startswith(CAPAS_EXTERNAS)]


@pytest.mark.parametrize("ruta", _archivos(BORDE), ids=lambda p: str(p.relative_to(RAIZ)))
def test_el_borde_no_importa_llm_ni_mlflow_en_e2(ruta):
    """Hito 1: LangChain/OpenAI solo en `app/interprete/llm.py`; MLflow en ningún archivo del borde."""
    prohibidos = {"mlflow"} if ruta.relative_to(RAIZ).as_posix() == UNICO_CON_LLM else PROHIBIDOS_EN_E2
    assert not [n for n in _imports(ruta) if n.split(".")[0] in prohibidos]


def test_langchain_solo_en_el_interprete_llm():
    """En toda la aplicación, el único archivo que usa LangChain u OpenAI es el intérprete LLM."""
    con_llm = sorted(p.relative_to(RAIZ).as_posix() for p in _archivos(["app"]) if any(n.split(".")[0] in LLM for n in _imports(p)))
    assert con_llm == [UNICO_CON_LLM]


def _usos_de_float(arbol):
    """Usos de `float` fuera de las anotaciones de tipo (una anotación no convierte nada)."""
    en_anotaciones = set()
    for nodo in ast.walk(arbol):
        anotaciones = []
        if isinstance(nodo, ast.arg) and nodo.annotation is not None:
            anotaciones.append(nodo.annotation)
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.returns is not None:
            anotaciones.append(nodo.returns)
        if isinstance(nodo, ast.AnnAssign):
            anotaciones.append(nodo.annotation)
        for anotacion in anotaciones:
            en_anotaciones |= {id(n) for n in ast.walk(anotacion)}
    return [n for n in ast.walk(arbol) if isinstance(n, ast.Name) and n.id == "float" and id(n) not in en_anotaciones]


@pytest.mark.parametrize("ruta", _archivos(BORDE), ids=lambda p: str(p.relative_to(RAIZ)))
def test_float_solo_en_el_serializador_de_montos(ruta):
    usos = _usos_de_float(ast.parse(ruta.read_text(encoding="utf-8")))
    if ruta.relative_to(RAIZ).as_posix() == "app/api/esquemas.py":
        assert len(usos) == 2  # PlainSerializer(float, return_type=float)
    else:
        assert usos == []


@pytest.mark.parametrize("ruta", _archivos(["app"]), ids=lambda p: str(p.relative_to(RAIZ)))
def test_la_aplicacion_nunca_depende_del_evaluador(ruta):
    assert not [n for n in _imports(ruta) if n == "evaluacion" or n.startswith("evaluacion.")]


@pytest.mark.parametrize("ruta", _archivos(EVALUADOR), ids=lambda p: str(p.relative_to(RAIZ)))
def test_el_evaluador_sin_llm_ni_mlflow(ruta):
    assert not [n for n in _imports(ruta) if n.split(".")[0] in PROHIBIDOS_EN_E2]


@pytest.mark.parametrize("ruta", _archivos(SIN_FLOAT_EN_EVALUADOR), ids=lambda p: str(p.relative_to(RAIZ)))
def test_el_evaluador_compara_y_pondera_sin_float(ruta):
    assert _usos_de_float(ast.parse(ruta.read_text(encoding="utf-8"))) == []


def test_hay_archivos_en_cada_capa():
    assert len(_archivos(NUCLEO)) >= 20 and len(_archivos(BORDE)) >= 8 and len(_archivos(EVALUADOR)) >= 9
