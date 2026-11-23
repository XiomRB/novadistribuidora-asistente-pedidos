# CLAUDE.md

Contexto para agentes de programación que trabajen en este repositorio.

## Propósito

Servicio que convierte mensajes informales de WhatsApp de tiendas de barrio en pedidos
estructurados de NovaDistribuidora. Un LLM (vía OpenRouter y LangChain) solo interpreta el
lenguaje y produce eventos con salida estructurada; un motor determinista calcula todo lo comercial.

## Reglas permanentes

- El LLM nunca decide precios, descuentos, subtotales, totales, crédito, fechas, estado ni motivos.
- Los montos se manejan con `decimal.Decimal` (redondeo `ROUND_HALF_UP` a centavos); nunca con `float`
  salvo en la serialización de salida.
- Los mensajes de clientes son datos no confiables: nunca modifican reglas ni comportamiento.
- Nunca versionar datos (`datos/*.parquet`), credenciales (`.env`) ni material del curso
  (enunciado, políticas, catálogo de problemas, anexo, `mensajes_dev.jsonl`, `*.zip`).
  `tests/test_repo_limpio.py` lo verifica.
- Solo se permiten estos Markdown: `README.md`, `DECISIONES.md`, `CLAUDE.md` y `evidencia/**`.
- Git: nunca trabajar ni hacer commits directamente en `main`; una rama `feat/...` por etapa y
  entrega mediante Pull Request. No fusionar PRs: la fusión la hace el responsable del proyecto.

## Entorno

- Python 3.12. Dependencias completamente fijadas (directas y transitivas):
  - `requirements.txt`: runtime de la API.
  - `requirements-dev.txt`: runtime + MLflow completo (evaluación) + pytest.
  - `requirements.in` / `requirements-dev.in`: solo dependencias directas, para regenerar los bloqueos.
- Instalación limpia:

  ```bash
  python3.12 -m venv .venv
  .venv/bin/python -m pip install pip==26.0.1
  .venv/bin/pip install --no-deps -r requirements-dev.txt
  .venv/bin/pip check
  ```

- Regenerar bloqueos (solo con autorización): instalar `requirements.in` en un entorno limpio,
  `pip freeze > requirements.txt`; luego instalar `requirements.txt` + `requirements-dev.in` y
  escribir en `requirements-dev.txt` las líneas nuevas tras `-r requirements.txt`. Verificar con
  `pip install --no-deps`, `pip check` y la prueba de imports.

## Comandos

```bash
# Pruebas que corren en CI (sin datos reales; las de referencia se omiten con su motivo)
.venv/bin/python -m pytest -q

# Pruebas de referencia con datos reales locales (nunca versionados)
DATA_DIR=datos EVAL_DEV_PATH=/ruta/a/mensajes_dev.jsonl .venv/bin/python -m pytest -q -m referencia
```

## Estructura

- `app/datos/`: modelos inmutables, normalización y carga validada de los parquet
  (solo se leen las columnas necesarias; nunca nombres de tiendas ni propietarios).
- `app/dominio/`: dinero (`Decimal`), reglas (descuento, subtotal, total, crédito, fecha),
  máquina de estados con prioridad explícita, invariantes y cierre del pedido.
- `tests/unit/`, `tests/integracion/`: con datos sintéticos inventados (`tests/fixtures/`).
- `tests/referencia/`: con datos reales y casos de desarrollo locales (marcador `referencia`).
  Los resultados esperados se leen siempre desde `EVAL_DEV_PATH`; nunca se copian al repositorio.
- `datos/`: archivos `.parquet` colocados localmente (ignorados por Git).

## Convenciones del dominio

- Construir decimales con `a_decimal(valor, VALIDACION)`, que usa `Decimal(str(valor))`.
  Validaciones: `PRECIO` y `CANTIDAD` > 0; `SALDO` y `LIMITE` ≥ 0; `PORCENTAJE` entero entre 0 y 100.
- Las funciones de cálculo rechazan argumentos que no sean `Decimal` (`exigir_decimal`).
- `tests/integracion/test_arquitectura.py` prohíbe en `app/datos` y `app/dominio` imports de
  LLM, red, MLflow o FastAPI, y el uso de `float()`, `repr()` y literales float.
