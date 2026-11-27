"""Aplicación FastAPI (E2b): factoría, arranque y ejecución.

- `crear_app(configuracion=None, datos=None, interprete=None, sondas=())`: los datos, el intérprete
  y las sondas son inyectables (pruebas). Por defecto los datos se cargan de `DATA_DIR` al
  arrancar y el intérprete se construye desde la configuración (hito 1): `InterpreteLLM` con
  OpenRouter si hay `OPENROUTER_API_KEY` y `LLM_MODELO`; si no, `InterpreteNoConfigurado` (503).
- Los registradores de `httpx` y `openai` quedan en WARNING: nunca se registran solicitudes.
- Hito 2: `observabilidad=(EstadoMlflow, Trazador)` inyectable. Por defecto se construye desde la
  configuración: el estado de MLflow se comprueba en un hilo de fondo (la API arranca sin esperar a
  MLflow) y `/health` combina las sondas del intérprete y de MLflow, independientes entre sí. Al
  cerrar, se detiene la comprobación y se vacía las trazas pendientes con un límite de tiempo.
- Arranque (`lifespan`): `cargar_datos`; si faltan o son inválidos, **la aplicación no arranca**
  (D24) y el error solo informa códigos y archivos (nunca claves ni datos). Después,
  `Recursos.construir` una sola vez (D68).
- Límite del cuerpo de 1 MiB contando los bytes recibidos (D87).
- `ejecutar()`: Uvicorn en el puerto 8000 del Anexo, **sin access log** (D88).
- `X-Request-ID` queda para E4 (D84).

Uso: `python -m app.main` (o `uvicorn app.main:app --port 8000 --no-access-log`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.limites_http import LimiteCuerpo
from app.api.rutas import registrar_manejadores, router
from app.api.salud import ResultadoSonda, Sonda, sonda_interprete
from app.config import Configuracion
from app.datos.carga import cargar_datos
from app.datos.modelos import Datos
from app.dominio.errores import DatosInvalidos
from app.dominio.pedido import Recursos
from app.interprete.base import Interprete, InterpreteNoConfigurado
from app.interprete.llm import crear_interprete_openrouter
from app.observabilidad.estado_mlflow import EstadoMlflow
from app.observabilidad.trazas import Trazador
from app.servicio import ServicioPedidos

PUERTO = 8000
HOST = "0.0.0.0"

log = logging.getLogger("novadistribuidora.api")


class ErrorArranque(RuntimeError):
    """Los datos faltan o son inválidos: la API no arranca (D24)."""


def cargar_datos_para_arranque(configuracion: Configuracion) -> Datos:
    try:
        return cargar_datos(configuracion.dir_datos)
    except DatosInvalidos as error:
        # Solo códigos y archivos: las claves de los problemas pueden ser identificadores.
        problemas = sorted({f"{p.codigo} ({p.archivo})" for p in error.errores})
        mensaje = f"No se pudieron cargar los datos de {configuracion.dir_datos}: " + ", ".join(problemas)
        log.error(mensaje)
        raise ErrorArranque(mensaje) from None


def construir_interprete(configuracion: Configuracion, datos: Datos) -> Interprete:
    """`InterpreteLLM` con OpenRouter si la configuración está completa; si no, no configurado."""
    if not configuracion.interprete_configurado:
        return InterpreteNoConfigurado()
    return crear_interprete_openrouter(configuracion, datos)


def construir_observabilidad(configuracion: Configuracion) -> tuple[EstadoMlflow, Trazador]:
    trazador_ref: list[Trazador] = []
    estado = EstadoMlflow(configuracion.mlflow_tracking_uri, configuracion.mlflow_intervalo_s, al_conectar=lambda: trazador_ref[0].preparar())
    trazador = Trazador(estado, configuracion.mlflow_experimento, configuracion.mlflow_trazas_contenido, configuracion.version,
                        configuracion.llm_modelo, configuracion.llm_instrucciones)
    trazador_ref.append(trazador)
    return estado, trazador


def sonda_mlflow(estado: EstadoMlflow) -> Sonda:
    return lambda: ResultadoSonda(*estado.sonda())


def crear_app(
    configuracion: Configuracion | None = None,
    datos: Datos | None = None,
    interprete: Interprete | None = None,
    sondas: Sequence[Sonda] = (),
    observabilidad: tuple[EstadoMlflow, Trazador] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = configuracion or Configuracion.desde_entorno()
        datos_efectivos = datos if datos is not None else cargar_datos_para_arranque(config)
        interprete_efectivo = interprete if interprete is not None else construir_interprete(config, datos_efectivos)
        app.state.interprete = interprete_efectivo
        app.state.servicio = ServicioPedidos(datos_efectivos, Recursos.construir(datos_efectivos), interprete_efectivo)
        estado_mlflow, trazador = observabilidad if observabilidad is not None else construir_observabilidad(config)
        app.state.trazador = trazador
        app.state.sondas = [sonda_interprete(interprete_efectivo), sonda_mlflow(estado_mlflow), *sondas]
        estado_mlflow.iniciar()
        try:
            yield
        finally:
            estado_mlflow.detener()
            trazador.cerrar()

    app = FastAPI(title="NovaDistribuidora: interpretación de pedidos", version="0.2.0", lifespan=lifespan)
    app.include_router(router)
    registrar_manejadores(app)
    app.add_middleware(LimiteCuerpo)
    return app


app = crear_app()


def ejecutar() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for nombre in ("httpx", "httpcore", "openai"):
        logging.getLogger(nombre).setLevel(logging.WARNING)
    uvicorn.run(app, host=HOST, port=PUERTO, access_log=False)


if __name__ == "__main__":
    ejecutar()
