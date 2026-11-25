"""Rutas y manejadores de errores de la API (E2b).

- `POST /v1/pedidos/interpretar`: 200 con los 9 campos del Anexo; 422 (D78), 404 (D79), 503 con
  `Retry-After: 10` (D18, D80) o 500 genérico (D82), en el orden 422 -> 404 -> 503 (D83).
- `GET /health`: siempre 200, `ok` o `degradado` con motivo (D81).

Los errores están en español y nunca incluyen el valor recibido, el texto de los mensajes, el
`cliente_id` ni detalles internos. El log propio solo registra método, ruta, código, duración y
estado del pedido (nunca el cuerpo ni el cliente); el access log de Uvicorn se desactiva (D88).
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import errores
from app.api.esquemas import SolicitudPedido
from app.api.salud import estado_de_salud
from app.dominio.entrada import EntradaInvalida
from app.dominio.errores import ClienteNoEncontrado
from app.interprete.base import InterpreteNoDisponible
from app.servicio import ErrorInterno

RUTA_PEDIDOS = "/v1/pedidos/interpretar"
RUTA_SALUD = "/health"

log = logging.getLogger("novadistribuidora.api")
router = APIRouter()


def _registrar(codigo: int, inicio: float, detalle: str = "") -> None:
    milisegundos = round((time.perf_counter() - inicio) * 1000)
    log.info("POST %s -> %s en %s ms%s", RUTA_PEDIDOS, codigo, milisegundos, f" ({detalle})" if detalle else "")


@router.post(RUTA_PEDIDOS)
def interpretar_pedido(solicitud: SolicitudPedido, request: Request) -> JSONResponse:
    inicio = time.perf_counter()
    servicio = request.app.state.servicio
    try:
        atencion = servicio.atender(solicitud)
    except ClienteNoEncontrado:
        _registrar(404, inicio)
        return JSONResponse(status_code=404, content=errores.cuerpo_404())
    except InterpreteNoDisponible:
        _registrar(503, inicio)
        return JSONResponse(status_code=503, content=errores.cuerpo_503(), headers=errores.encabezados_503())
    except EntradaInvalida:
        # No debería ocurrir: el esquema aplica los mismos límites que EntradaPedido.
        _registrar(422, inicio)
        return JSONResponse(status_code=422, content=errores.cuerpo_422([]))
    except ErrorInterno as error:
        _registrar(500, inicio, error.tipo)
        return JSONResponse(status_code=500, content=errores.cuerpo_500())
    except Exception as error:  # noqa: BLE001 - nunca se exponen detalles internos
        _registrar(500, inicio, type(error).__name__)
        return JSONResponse(status_code=500, content=errores.cuerpo_500())
    _registrar(200, inicio, f"estado={atencion.respuesta.estado}")
    return JSONResponse(status_code=200, content=atencion.respuesta.model_dump(mode="json"))


@router.get(RUTA_SALUD)
def salud(request: Request) -> JSONResponse:
    return JSONResponse(status_code=200, content=estado_de_salud(request.app.state.sondas))


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validacion(_request: Request, error: RequestValidationError) -> JSONResponse:
        log.info("%s -> 422", _request.url.path)
        return JSONResponse(status_code=422, content=errores.cuerpo_422(error.errors()))
