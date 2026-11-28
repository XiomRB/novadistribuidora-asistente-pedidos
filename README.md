# NovaDistribuidora: asistente de pedidos

Servicio que convierte los mensajes informales de WhatsApp de las tiendas de barrio en pedidos
estructurados. Un modelo de lenguaje (LangChain + OpenRouter) solo interpreta el lenguaje; un motor
determinista calcula precios, descuentos, totales, crédito, fecha de entrega, estado y motivos de
revisión. Las trazas y las evaluaciones se registran en MLflow.

Este README cubre el arranque con Docker Compose, la configuración, la comprobación, la persistencia,
la parada y la ejecución del evaluador contra el contenedor. La comparación de alternativas y la
evidencia se documentarán en el hito de evaluación.

## Requisitos

- Docker Engine 23 o posterior (o Docker Desktop) con Docker Compose v2.24 o posterior.
- Conexión a Internet: OpenRouter para el modelo y, la primera vez, las imágenes base y las
  dependencias de Python.
- Los puertos `8000` (API) y `5000` (MLflow, solo en `127.0.0.1`) libres, o configure otros (ver más abajo).
- Una clave propia de OpenRouter.
- Los cinco archivos de datos del laboratorio (no forman parte del repositorio ni de las imágenes).

Las imágenes funcionan en `linux/amd64` y `linux/arm64`. Las dependencias están fijadas en
`requirements.txt` y las imágenes base, por digest.

## Configuración

1. **Credenciales.** Copie el ejemplo y complete la clave:

   ```bash
   cp .env.example .env
   ```

   - `OPENROUTER_API_KEY`: obligatoria.
   - `LLM_MODELO`: el modelo indicado en `.env.example`.

   El archivo `.env` está ignorado por Git y por Docker. Compose lo inyecta en el contenedor de la API
   al arrancar; nunca se copia en la imagen.

2. **Datos.** Coloque en la carpeta `datos/` del repositorio estos cinco archivos:

   ```text
   datos/
   ├── clientes.parquet
   ├── historial_pedidos.parquet
   ├── precios_escala.parquet
   ├── productos.parquet
   └── sinonimos.parquet
   ```

   La carpeta se monta en el contenedor en solo lectura. Los archivos deben ser legibles por cualquier
   usuario (`chmod 644 datos/*.parquet`), porque la API se ejecuta con un usuario sin privilegios.

3. **Opcionales.** Pueden agregarse a `.env`:

   | Variable | Para qué sirve | Valor por defecto |
   |---|---|---|
   | `DATOS_HOST` | otra carpeta de datos | `./datos` |
   | `API_PUERTO` | otro puerto para la API | `8000` |
   | `MLFLOW_PUERTO` | otro puerto para MLflow | `5000` |

   En `.env.example` están además las opciones del intérprete y de MLflow.

## Arranque

```bash
docker compose up -d --build
```

- La primera construcción descarga la imagen base y las dependencias; puede tardar varios minutos.
- La API arranca **sin esperar a MLflow** y responde en pocos segundos.
- MLflow tarda más la primera vez, porque crea su base de datos (hasta unos 2 minutos).
- Mientras tanto, `/health` informa `mlflow_no_disponible`.

## Comprobación

```bash
docker compose ps                     # api y mlflow: "healthy"
curl -s http://localhost:8000/health
```

`/health` responde 200 en todos los casos. El campo `estado` vale `ok`, o `degradado` con el `motivo`:

| Motivo | Significado |
|---|---|
| `conectividad_no_verificada` | Aún no hubo ninguna llamada al modelo. Es el estado normal justo después de arrancar: `/health` nunca llama al proveedor, para no generar coste. Pasa a `ok` con el primer pedido interpretado correctamente. |
| `interprete_no_configurado` | Falta `OPENROUTER_API_KEY` o `LLM_MODELO`. Los pedidos responden 503. |
| `error_al_invocar_modelo` | La última llamada al modelo falló; se recupera sola con la siguiente que funcione. |
| `mlflow_no_disponible` | MLflow no responde. La API sigue atendiendo pedidos; las trazas de ese periodo se descartan. |

Si hay varios problemas a la vez, los motivos aparecen juntos, separados por `; `.

Ejemplo de pedido (use un `cliente_id` de sus datos):

```bash
curl -s -X POST http://localhost:8000/v1/pedidos/interpretar \
  -H 'Content-Type: application/json' \
  -d '{"cliente_id": "<cliente_id>", "fecha_hora": "2026-12-07T10:00", "mensajes": ["Buenas, le encargo 2 fardos de frijol negro"]}'
```

### MLflow

- **Interfaz:** `http://localhost:5000`. Solo es accesible desde este equipo.
- **Trazas** (experimento `lab3-api`):
  - Cada pedido deja una traza con los tramos `pedido`, `interprete` y `motor`.
  - Incluye latencias, tokens, el coste informado por OpenRouter, el modelo, la variante y la versión
    del código (el SHA de Git de la construcción).
  - Por defecto solo contiene metadatos: nunca mensajes, `cliente_id`, SKU, cantidades ni importes.
- **Evaluaciones:** experimento `lab3-evaluaciones` (ver más abajo).

### Si MLflow se detiene

```bash
docker compose stop mlflow    # la API sigue respondiendo; /health: mlflow_no_disponible
docker compose start mlflow   # /health se recupera solo en unos segundos
```

### Versión registrada

- La construcción guarda el SHA de Git del repositorio (sin copiar `.git` a la imagen), y las trazas lo
  registran como `version`.
- Si el código no proviene de un clon de Git (por ejemplo, una descarga en `.zip`) o `.git` es un
  archivo (worktree o submódulo), la versión es `unknown`.
- Un `APP_VERSION` no vacío en `.env` prevalece sobre el SHA.

### Si faltan los datos

- La API no arranca y el log indica qué archivos faltan: `docker compose logs api`.
- Docker la reinicia con esperas cada vez más largas (hasta un minuto) y `docker compose ps` la
  muestra como `restarting`.
- Basta con colocar los archivos en `datos/`: el siguiente reinicio arranca sin más intervención.

## Persistencia

- Las trazas, los runs y los artefactos de MLflow se guardan en el volumen `novadistribuidora_mlflow_datos`.
- Sobreviven a `docker compose restart`, `stop`/`start`, `down`/`up` y a una nueva construcción.
- **Solo** `docker compose down -v` borra el volumen.

## Parada

```bash
docker compose down        # detiene y elimina los contenedores; conserva MLflow
docker compose down -v     # además borra el volumen de MLflow (trazas y evaluaciones)
```

## Evaluador contra el contenedor

El evaluador se ejecuta en el equipo, fuera de los contenedores, y envía los casos por HTTP a la API.

1. **Entorno de Python 3.12 con las dependencias fijadas:**

   ```bash
   python3.12 -m venv .venv
   .venv/bin/python -m pip install pip==26.0.1
   .venv/bin/pip install --no-deps -r requirements-dev.txt
   ```

2. **Evaluación.** Requiere el árbol de Git limpio. El registro de conjuntos y la carpeta de salida van
   fuera del repositorio:

   ```bash
   .venv/bin/python -m evaluacion --modo e3 --registro /ruta/registro.json \
     --base-url http://localhost:8000 --timeout 30 --salida-privada /ruta/salida
   ```

   - Escribe `reporte_privado.json` y `resumen_publico.json` en una subcarpeta de `--salida-privada`.
   - Termina con el código 0 (aprobado), 1 (no aprobado), 2 (integridad, formato, registro, datos o
     salida) o 3 (árbol de Git no limpio).

3. **Registro en MLflow.** Registra el run con las métricas del resumen público y los costes de las
   trazas de esa ejecución:

   ```bash
   MLFLOW_TRACKING_URI=http://localhost:5000 .venv/bin/python -m evaluacion_mlflow \
     --resumen /ruta/salida/<ejecucion>/resumen_publico.json
   ```

   Si falta alguna traza o algún coste (por ejemplo, porque MLflow estuvo detenido), el resultado indica
   `COSTES_INCOMPLETOS` y no se informa un total.

## Desarrollo y pruebas

```bash
.venv/bin/python -m pytest -q                                      # suite de la CI
DOCKER_PRUEBAS=1 .venv/bin/python -m pytest -q -m docker tests/docker  # humo con Docker Compose
```

La prueba de humo construye la imagen y levanta la API y MLflow en contenedores reales:
- usa datos sintéticos generados en la prueba y no la clave de OpenRouter;
- usa un proyecto de Compose, una imagen y unos puertos propios;
- no toca la pila ni el `.env` del usuario.

`CLAUDE.md` describe la arquitectura y las reglas del repositorio.
