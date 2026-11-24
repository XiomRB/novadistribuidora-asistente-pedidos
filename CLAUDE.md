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
  máquina de estados con prioridad explícita, invariantes y cierre del pedido (E1a), y la
  interpretación determinista (E1b-1):
  - `entrada.py`: `EntradaPedido` (fecha_hora sin zona horaria = hora local de Guatemala).
  - `esquema_eventos.py`: `Interpretacion`, `Evento`, `Fragmento` (sin campos comerciales;
    patrones validados en código, no en el esquema JSON). Lo reutiliza el intérprete LLM (E3).
  - `texto.py`: presentaciones, tokens, similitud, `Span` (posiciones sobre el texto original),
    `localizar` y `anclar`.
  - `catalogo.py`: índice (grupo, hermanos, alias, medidas) y `resolver()`: nunca acepta un SKU
    sin evidencia textual (D45); agotado sin sustituto antes que la unidad (D38).
  - `unidades.py`: cantidades (`Decimal` desde texto), compatibilidad por presentación y UPE,
    `convertir()`; cantidades inciertas y sueltas sin número nunca se convierten (D46).
  - `consultas.py`: oraciones con posición y consulta pura = interrogativa sin marcador de compra (D36).
  - E1b-2a:
    - `limites.py`: `validar_interpretacion(datos, n_mensajes)` es el **punto de entrada único**
      para validar una interpretación: aplica el esquema de E1b-1 y el límite combinado
      `consultas + instrucciones_rechazadas <= 20` (D72). El orquestador (E1b-2b) y el
      intérprete LLM (E3) deben usarlo; nunca omitir `validar_limites`.
    - `habitual.py`: último pedido entregado con fecha <= recepción (D53); desempate por
      `pedido_id` en orden natural y luego por el original (D70); duplicados ->
      `HistorialInconsistente`, sin identificadores en el mensaje (D73).
    - `atributos.py`: grupo, marcas, variantes y medidas (D48); compatibilidad = al menos una
      coincidencia positiva y ninguna contradicción (D76).
    - `plegado.py`: ítems con identidad y bitácora (nunca se borran), referencias por cadena de
      sucesores, D37/D75, D10/D13/D76, D47, D48-a/b/c (atómico), D57, D58, D62, D63, D69.
    - `sustitucion.py`: sustituciones después del plegado, fusionadas en la primera posición.
    - `diagnostico.py`: solo códigos, posiciones, SKU, cantidades y medidas normalizadas; nunca
      textos, `cliente_id` ni `pedido_id` (el habitual se registra como `habitual_usado`, D74).
  - E1b-2b:
    - `omisiones.py`: señales S1 (grupo, alias o nombre completo; nunca marca o variante
      suelta, D60), S2 (número + unidad), S3 (habitual) y S4 (renglón de lista). Cobertura por
      posición (`|S∩E| >= ceil(|S|/2)` con un evento efectivo, o S dentro de una consulta pura
      del código); las rechazadas y los descartados nunca cubren. Contexto D61 (C1–C5). Pendiente
      `producto_ambiguo` con el tramo exacto de la señal (D59); nunca crea líneas (D05).
    - `clasificacion.py`: `CONSULTA`, `PEDIDO_CANCELADO`, `SIN_EFECTO`, `PEDIDO`, de la que sale
      `hay_eventos_pedido` para el cierre de E1a.
    - `pedido.py`: `procesar_pedido(entrada, interpretacion, datos, indice=None, lexico=None,
      recursos=None)`. Orden obligatorio: cliente (`ClienteNoEncontrado`), luego
      `validar_interpretacion` (D72) **antes** del anclaje, anclaje y descartes (`SIN_ANCLA`,
      `DESCARTADO_CONSULTA`), plegado, sustituciones, omisiones, clasificación, cierre de E1a,
      mensaje y diagnóstico. Pendientes en el orden D64. `Recursos` precomputa índice, léxico,
      vocabulario, detector y redactor (D68).
- `app/mensajes/confirmacion.py`: mensaje al cliente con plantillas (D16 sin montos, D49, D65,
  saludo y fecha según 3.6). Nunca usa texto del cliente ni el texto de los pendientes.
- `tests/unit/`, `tests/integracion/`: con datos sintéticos inventados (`tests/fixtures/`).
- `tests/referencia/`: con datos reales y casos de desarrollo locales (marcador `referencia`).
  Los resultados esperados se leen siempre desde `EVAL_DEV_PATH`; nunca se copian al repositorio.
  - `eventos_dev.json` (D51, D66): interpretaciones de referencia de los 84 casos **solo con
    posiciones**, enumeraciones, SKU y cantidades en dígitos. `formato_eventos_dev.py` lo valida
    con lista blanca (D61-a, contención en `texto`, límite combinado de 20) y reconstruye los
    textos desde `EVAL_DEV_PATH`. Nunca agregar campos de texto a este archivo.
- `datos/`: archivos `.parquet` colocados localmente (ignorados por Git).

## Convenciones del dominio

- Construir decimales con `a_decimal(valor, VALIDACION)`, que usa `Decimal(str(valor))`.
  Validaciones: `PRECIO` y `CANTIDAD` > 0; `SALDO` y `LIMITE` ≥ 0; `PORCENTAJE` entero entre 0 y 100.
- Las funciones de cálculo rechazan argumentos que no sean `Decimal` (`exigir_decimal`).
- `tests/integracion/test_arquitectura.py` prohíbe en `app/datos`, `app/dominio` y `app/mensajes` imports de
  LLM, red, MLflow o FastAPI, el uso de `float()`, `repr()` y literales float, y el reloj del
  sistema (`datetime.now`, `date.today`, `time.time`, …). Los umbrales de similitud son
  porcentajes enteros.
- El código de E1a (`app/datos/*`, `cierre.py`, `reglas.py`, `estado.py`, `dinero.py`,
  `resultado.py`, `errores.py`) y sus fixtures no se modifican desde E1b.
- Los fixtures de E1b están en `tests/fixtures/catalogo_e1b.py` (catálogo inventado).
- E1b-2a agrega `tests/fixtures/historial_e1b2.py` (historial sintético y utilidades para armar
  eventos). No modifica los fixtures de E1a ni de E1b-1, ni sus módulos (incluido
  `esquema_eventos.py`).
- E1b-2b agrega `tests/fixtures/pedido_e1b2b.py` (utilidades para el orquestador) y no modifica
  la implementación de E1a, E1b-1 ni E1b-2a.

## Requisitos y riesgos para etapas posteriores

- **E2:** `ClienteNoEncontrado` (E1a) incluye el `cliente_id` en su mensaje. La API debe
  traducirlo a HTTP 404 **sin exponer** el `cliente_id` (ni en la respuesta ni en logs). No
  modificar E1a para esto.
- **E2:** `HistorialInconsistente` debe responderse como error interno genérico, sin identificadores.
- **R-E3-08:** el detector de omisiones no marca la jerga sin el sustantivo del grupo ("cocas",
  "juguitos"), los productos fuera del catálogo ("recargas", "gas propano") ni los errores en
  marcas ("bellla", "qutezal"): 7 de 166 menciones quitadas en los casos de desarrollo. Medirlo
  en E3 (tasa de omisiones no detectadas con el LLM real).
- **Pendiente de decisión (revisión del PR #5):** pruebas `xfail(strict=True)` en
  `tests/unit/test_omisiones.py` y `tests/referencia/test_pedido_qn1.py` documentan dos falsos
  positivos del detector (S1 aproximada con un número que no es presentación; C2 activado por
  una línea "x: n" sin producto). No quitar las marcas sin la decisión correspondiente.
