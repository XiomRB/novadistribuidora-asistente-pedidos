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

# API (puerto 8000, sin access log). Sin OPENROUTER_API_KEY y LLM_MODELO los pedidos responden 503.
DATA_DIR=datos .venv/bin/python -m app.main

# Prueba real con OpenRouter (coste por token; lee la clave del entorno o de .env sin mostrarla)
OPENROUTER_PRUEBA_REAL=1 .venv/bin/python -m pytest -q -m openrouter

# API y MLflow en contenedores (hito 3; requiere .env y datos/ con los cinco parquet)
docker compose up -d --build

# Humo con Docker Compose: contenedores reales, datos sintéticos, sin clave, proyecto y puertos propios
DOCKER_PRUEBAS=1 .venv/bin/python -m pytest -q -m docker tests/docker
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
    D92 (R-E3-09), antes de la resolución por texto: cada token se clasifica como ancla (grupo,
    marca o primer token de un nombre o alias), conocido o desconocido. R1-a (prioridad sobre
    R1-b): sin ancla y con un token conocido -> `producto_no_existe`, con o sin candidatos del LLM
    ("levadura en polvo"). R1-b: jerga pura -> D45 sin cambios ("cocas"). R1-c: sin ancla ni
    candidatos -> `producto_no_existe`. R2: ancla y token desconocido (marca o variante que no
    vendemos) -> ambiguo **sin opciones**, salvo medidas explícitas contradictorias
    (`MEDIDA_SIN_PRODUCTO`), que conservan `producto_no_existe`. Una mención sin ancla nunca
    produce una línea. `CANDIDATOS_LLM_IGNORADOS` es interno de `Resolucion.codigos`. No
    agregar listas de marcas ni excepciones por número de palabras.
    D93 (dimensión de la cantidad total): con `dimensiones`, `resolver` descarta las opciones cuya
    dimensión física (volumen o masa, según su presentación) no coincide; ninguna ->
    `producto_no_existe` (código interno `DIMENSION_CANTIDAD_INCOMPATIBLE`, que R2 conserva);
    algunas -> solo esas, sin confirmar nunca un producto. Solo la dimensión, nunca el valor.
    Sin `dimensiones`, el comportamiento es exactamente el anterior.
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
      D93: cada `Entrada` guarda la dimensión física solo si `dimension_cantidad_total` demuestra
      que la unidad física es la de la cantidad total (E1-E3; T2 `Decimal` sin formatos ambiguos;
      T3 una sola expresión numérica; T4 gramática cerrada Q1/Q2 con el producto exacto). Ante
      cualquier duda no se registra. Se usa al resolver en agregar, reagregar, D48 y D69; las
      correcciones de solo cantidad no vuelven a resolver (D63; decisiones A y B). No ampliar las
      listas de prefijos, sufijos ni números sin autorización.
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
- `app/api/` (E2a): contrato HTTP del Anexo, sin rutas todavía (las rutas, el servicio, la salud
  y el arranque son de E2b).
  - `esquemas.py`: `SolicitudPedido` (validación estricta D15; límites de D56; campos adicionales
    ignorados, D77) y `RespuestaPedido` (exactamente los **9 campos** de primer nivel del Anexo,
    sin claves adicionales en ningún nivel). `cliente_id` admite **como máximo 64 caracteres**
    (D90), contados como caracteres (`len()`, puntos de código), no como bytes UTF-8: es una
    restricción del contrato de la API. `fecha_hora` solo con dígitos ASCII.
  - Montos (D03, D91 opción A): `Decimal` en todo el cálculo; se convierten a número JSON solo
    al serializar (`PlainSerializer(float, when_used="json")`). Se garantiza la igualdad
    numérica exacta, no un texto concreto (`1164.00` se escribe `1164.0`). No escribir un
    serializador JSON propio.
  - `errores.py`: 422 en español sin eco del valor recibido (D78), 404 sin `cliente_id` (D79),
    500 genérico (D82) y `RETRY_AFTER_SEGUNDOS = 10` en **todos** los 503 (D18).
  - E2b: `rutas.py` (`POST /v1/pedidos/interpretar` y `GET /health`; orden 422 -> 404 -> 503,
    D83), `salud.py` (sondas inyectables, siempre 200, D81) y `limites_http.py` (middleware de
    1 MiB que cuenta los bytes recibidos, sin confiar en `Content-Length`; 422, D87).
    Fuera del contrato (revisión del PR #7, opción A): ruta inexistente -> 404
    `{"detail": "Ruta no encontrada"}`; método no permitido -> 405
    `{"detail": "Método no permitido"}` con `Allow`; sin la ruta, los parámetros ni los valores.
    No confundir con el 404 de negocio (D79): `{"detail": "Cliente no encontrado"}`.
- `app/servicio.py` (E2b): cliente (404 sin llamar al intérprete) -> intérprete (503) ->
  `validar_interpretacion` (503 si es inválida) -> `procesar_pedido` (500 genérico ante cualquier
  error) -> `RespuestaPedido`. Nunca expone el `cliente_id` ni detalles internos.
- `app/interprete/` (E2b, hito 1): interfaz `Interprete` (`interpretar`, `estado`).
  - `llm.py`: `InterpreteLLM` (LangChain + OpenRouter). Es el **único** archivo de `app/` que usa
    LangChain u OpenAI (`test_capas.py`). `ChatOpenAI` con la URL de OpenRouter, `temperature=0`,
    timeout y reintentos acotados (`LLM_TIMEOUT_S`, `LLM_REINTENTOS` <= 2) y salida estructurada
    `Interpretacion` por llamada a función. Su salida pasa **en todos los casos** por `validar_interpretacion`
    (D72): una salida inválida o con un índice de mensaje inexistente se rechaza completa (503, nunca
    500 ni procesamiento parcial). Los errores no conservan el mensaje del proveedor ni la clave.
  - `instrucciones.py`: variantes `base` y `catalogo` (nombres y alias del catálogo, sin precios).
    Los mensajes van aparte, como datos delimitados (`<mensajes_cliente>`, con `<`/`>` escapados);
    nunca el `cliente_id` ni la fecha. Las órdenes del cliente sobre precios, descuentos, crédito,
    fechas o reglas van a `instrucciones_rechazadas` y no tienen efecto.
  - Estados de `/health` (motivos fijos): `interprete_no_configurado` (falta clave o modelo; 503),
    `conectividad_no_verificada` (sin invocación exitosa aún), `error_al_invocar_modelo` (la
    última falló) y `ok` (la última produjo una interpretación válida; se recupera solo).
    `/health` **nunca** llama al proveedor.
  - Los intérpretes falsos y el de referencia existen **solo en las pruebas**
    (`tests/fixtures/interprete_falso.py`, `tests/fixtures/modelo_falso.py`,
    `tests/referencia/test_api_dev.py`). Prueba real opcional: `OPENROUTER_PRUEBA_REAL=1` con el
    marcador `openrouter` (con coste; nunca en la CI).
- `app/main.py` (E2b): `crear_app(configuracion, datos, interprete, sondas)`; carga los datos de
  `DATA_DIR` al arrancar y **no arranca** si faltan o son inválidos (D24; el error solo muestra
  códigos y archivos); `Recursos` una sola vez (D68); `ejecutar()` en el puerto 8000 sin access
  log (D88). `X-Request-ID` queda para E4 (D84). `app/config.py`: `DATA_DIR` y el intérprete
  (`OPENROUTER_API_KEY`, `LLM_MODELO`, `LLM_TIMEOUT_S`, `LLM_REINTENTOS`, `LLM_INSTRUCCIONES`); la
  clave nunca aparece en `repr`. El intérprete se construye en el arranque (`construir_interprete`).
- Logs de la API: solo método, ruta, código, duración y estado del pedido (o el tipo de un error
  interno). Nunca el cuerpo, los mensajes, el `cliente_id` ni el texto de los pendientes.
- `app/observabilidad/` (hito 2): trazas en MLflow y su estado para `/health`.
  - `registro.py` (sin MLflow): un `Registro` por solicitud en una variable de contexto; el servicio y
    el intérprete anotan tiempos y atributos (`medir`, `anotar`). Correlación de evaluaciones por
    encabezados `X-Evaluacion-{Ejecucion,Caso,Conjunto,Repeticion,Privado}` (no son parte del contrato
    JSON; valores seguros y acotados; sin `Privado: 0` explícito se trata como privado).
  - `trazas.py`: el **único** archivo de `app/` que usa MLflow. Traza con tramos `pedido`,
    `interprete` y `motor`. Modo `metadatos` (por defecto): recuentos, estados, códigos, latencias,
    tokens, coste efectivo de OpenRouter (`None` si no se informa; nunca estimado), modelo, variante
    y versión; nunca mensajes, `cliente_id`, instrucciones, texto de pendientes, SKU, cantidades,
    importes, claves ni errores. Modo `completo` solo con almacén local, configuración explícita y un
    conjunto público declarado; `CONJUNTOS_SOLO_METADATOS` (D39) lo impide en todos los casos. La
    política (`contenido_permitido`, en `registro.py`) se aplica **al capturar**: sin autorización, el
    contenido nunca entra en el `Registro` ni en el búfer; al exportar se comprueba otra vez. El hilo de
    la solicitud solo encola en un búfer propio acotado; un único hilo propio exporta a MLflow (timeout
    HTTP 2 s, reintentos 0, envío asíncrono de MLflow desactivado). Con MLflow no disponible o el búfer
    lleno, la traza se descarta y se cuenta; el cierre drena el búfer con un límite de tiempo.
  - `estado_mlflow.py` (sin MLflow): hilo de fondo que comprueba el servidor; `/health` solo lee el
    estado: `mlflow_no_configurado`, `mlflow_no_disponible` u operativo, independiente del intérprete.
- `evaluacion_mlflow/` (hito 2): `python -m evaluacion_mlflow --resumen <resumen_publico.json>`
  registra un run con las métricas del **resumen público** (de un conjunto privado solo si se aprobó)
  y suma tokens y coste solo con las trazas de esa ejecución (`evaluacion.ejecucion`). Si faltan
  trazas o algún coste, `costes_completos=false` y no hay total. `evaluacion/` no usa MLflow
  (`test_capas.py`); el evaluador envía la correlación y mide la latencia de cada petición.
- Contenedores (hito 3): `Dockerfile`, `compose.yaml`, `.dockerignore`, `docker/version_git.py`.
  - Imagen de la API: `python:3.12-slim` fijada por digest; `requirements.txt` con `--no-deps` y
    `pip check`; solo `COPY app/`; usuario 10001; sin `# syntax=` (frontend integrado de BuildKit).
    `.dockerignore` es una lista blanca: nunca datos, `.env`, pruebas, evaluador ni material del curso.
  - Versión (D-H4): el SHA de Git se lee de `.git/HEAD`, `.git/refs/` y `.git/packed-refs` con un
    montaje temporal durante la construcción (`/app/VERSION`); `.git` no entra en la imagen. Sin
    repositorio, `unknown`. Un `APP_VERSION` no vacío en el entorno prevalece.
  - Compose: `api` (credenciales por `env_file` en tiempo de ejecución, datos montados `:ro`,
    `DATA_DIR` y `MLFLOW_TRACKING_URI` fijados en `environment`) y `mlflow` (imagen oficial v3.18.0
    fijada por digest, la misma versión que el cliente; sqlite y artefactos en el volumen
    `mlflow_datos`; solo en `127.0.0.1`; `--allowed-hosts`). La API depende de MLflow con
    `service_started` y `required: false`: **nunca** `service_healthy` (D-M3).
  - Sin datos, la API no arranca (D24) y Docker la reinicia con espera creciente; se recupera sola
    al colocarlos (probado en `tests/docker`).
  - `tests/integracion/test_contenedores.py` valida los archivos sin Docker (CI). `tests/docker/`
    (marcador `docker`, `DOCKER_PRUEBAS=1`) levanta la pila real; corre en el trabajo `docker` de la CI.
- `tests/unit/`, `tests/integracion/`: con datos sintéticos inventados (`tests/fixtures/`).
- `tests/referencia/`: con datos reales y casos de desarrollo locales (marcador `referencia`).
  Los resultados esperados se leen siempre desde `EVAL_DEV_PATH`; nunca se copian al repositorio.
  - `eventos_dev.json` (D51, D66): interpretaciones de referencia de los 84 casos **solo con
    posiciones**, enumeraciones, SKU y cantidades en dígitos. `formato_eventos_dev.py` lo valida
    con lista blanca (D61-a, contención en `texto`, límite combinado de 20) y reconstruye los
    textos desde `EVAL_DEV_PATH`. Nunca agregar campos de texto a este archivo.
- `datos/`: archivos `.parquet` colocados localmente (ignorados por Git).
- `evaluacion/` (E2c-1): evaluador por HTTP (D33, D91). No es parte de la aplicación: `app/` nunca depende
  de él y él tampoco depende de LLM ni de MLflow (`test_capas.py`). `python -m evaluacion --modo {e3,e6}
  --registro R --base-url U --timeout S --salida-privada D` (códigos: 0 aprobado, 1 no aprobado,
  2 integridad/formato/registro/datos/salida, 3 árbol de Git no limpio). El registro real de
  conjuntos autorizados llega en E2c-2.
  - Fase 1 (`conjuntos.py`): antes de cualquier petición verifica los SHA-256 de todos los archivos
    (casos, esperadas y anotaciones), el formato, los recuentos, la coherencia y las anotaciones;
    cualquier fallo es `ErrorIntegridad` con un código fijo (código 2 y 0 peticiones). Los ids del
    registro son únicos y sus entradas solo admiten los campos documentados.
  - Excepción de clave genérica (revisión del PR #10): `EXCEPCIONES_CLAVE_GENERICA` admite solo el par
    (`D39`, `U03`). La entrada del registro debe declararla, ser `validacion_privada` con `privado: true`
    y tener sus tres hashes idénticos a los autorizados, cuya única fuente en producción será
    `evaluacion/autorizados.json` (E2c-2); hasta entonces se rechaza en todos los casos. Nunca por `--registro`,
    entorno ni CLI. `ejecutar()` obtiene la fuente una sola vez y la pasa explícitamente a
    `leer_registro()` y a `cargar()`; las dos aplican la misma regla (`excepcion_autorizada`) y, sin
    autorización, la rechazan. El literal de la clave vive solo en las anotaciones privadas; nunca en el
    repositorio. No modifica `genericas.py`, G-0 ni la validación de las claves normales.
  - Comparación (`comparacion.py`): estado, total, fecha, líneas, sustituciones, pendientes (motivo y
    opciones) y motivos como multiconjuntos y `Decimal`; `mensaje_cliente` solo por contrato; texto
    de los pendientes y clasificación aparte (U10 provisional, fuera del denominador del texto).
  - Correspondencia (`correspondencia.py`): orden canónico de los ítems; representación por SKU o,
    en pendientes sin opciones, por claves de palabras completas; prioridades lexicográficas
    (emparejados, tipo, pureza, menor K4, desempate) con Kuhn-Munkres, nodos ficticios y pesos
    enteros (`bases`). `genericas.py`: lista cerrada de 198 palabras (hash fijado en G-0).
  - K1-K5 (`criticos.py`): K1 SKU distinto; K2 como máximo 1 por producto (líneas y sustituciones
    por SKU solicitado); K3 solo en críticos; K4 por ítem libre que representa a un solo consultado;
    K5 contrato o recálculo con E1a. Inválidos (HTTP, timeout, conexión, JSON) no son K5.
  - Veredictos (`reporte.py`): E3 con la fórmula ponderada por casos (nunca promedio de porcentajes),
    A1 >= 90 %, A2 K5 = 0, A3 sin K1-K4 en críticos; E6 alternativa A (3 repeticiones, cada una con
    >= 90 %, K5 = 0 y sin K1-K4 en críticos; media y mínimo). Reportes solo con códigos, nombres
    de campos, indicadores y agregados, fuera del repositorio (700 / 400); la Validación privada
    solo publica su hash y si se aprobó. Nunca guardar cuerpos, mensajes, textos ni esperadas.

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
- **Reglas autorizadas en la revisión del PR #5** (`omisiones.py`, sin tocar `consultas.py`):
  - S1 aproximada (>= 80 %, grupos de 5 letras o más): un número solo es evidencia si es una
    presentación compatible con el grupo; un signo de puntuación entre la palabra y la evidencia
    la anula. No ampliar la tolerancia ni reducir los requisitos de evidencia.
  - Renglón S4 válido (opción B, `renglones_validos`): contiene una señal S1, o en su mismo
    mensaje hay al menos dos renglones S4 **sin** S1 (los que tienen S1 no cuentan para ese
    umbral; las viñetas no son excepción; los mensajes no se cuentan juntos). El mismo criterio
    vale para las señales S4 (pendientes de omisión), C2 y C3 (precisión de D61). C2 lo aplica
    cuando el único marcador de compra de la oración es el patrón de lista de E1b-1. C4 y los
    demás marcadores siguen funcionando por su cuenta.
  - **Limitación aceptada (listas mixtas):** en "- frijol rojo: 3\n- recargas: 3", el renglón
    de un producto fuera del catálogo no alcanza el umbral y no se detecta como omisión.
  - **Consecuencia deliberada:** con al menos dos renglones S4 sin S1 en un mensaje, todos son
    válidos, incluidos los administrativos ("recargas: 3\nvelas: 2\nentrega: 10" genera tres
    pendientes). No agregar listas de palabras administrativas ni excepciones por viñetas.
  - Fin de renglón S4: un punto solo es parte de un número cuando está entre dos dígitos.
  - Agrupación: un salto de línea separa menciones independientes, salvo que un conector o
    una señal que abarque los dos renglones indique que la descripción continúa; la
    presentación no cruza un salto de línea hacia una cantidad nueva (S2).
