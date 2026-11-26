"""Evaluador de E2c (D33, D91): mide la API por HTTP sin exponer contenido privado.

No forma parte de la aplicación: `app/` nunca depende de `evaluacion`, y `evaluacion` tampoco depende
de LLM ni de MLflow (ver `tests/integracion/test_capas.py`).
"""

VERSION = "E2c-1"
