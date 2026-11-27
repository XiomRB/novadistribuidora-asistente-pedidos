"""Servicio de pedidos (E2b): solicitud validada (E2a) -> intérprete -> motor (E1b) -> respuesta.

Orden (D83), después de que el esquema ya validó la solicitud (422):
1. Cliente: si no existe, `ClienteNoEncontrado` (404) **sin llamar al intérprete**.
2. Intérprete: cualquier fallo -> `InterpreteNoDisponible` (503).
3. Interpretación: se valida con el punto de entrada único `validar_interpretacion` (D72); si es
   inválida -> `InterpreteNoDisponible` (503). Así una interpretación mala no se confunde con un
   error interno del motor.
4. Motor: `procesar_pedido` (E1b, sin cambios). Cualquier error aquí es interno (500).
5. Respuesta: `RespuestaPedido.desde_resultado` (E2a), traducción uno a uno.

El diagnóstico del dominio no sale de aquí (se usará en E4).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.api.esquemas import RespuestaPedido, SolicitudPedido
from app.datos.modelos import Datos
from app.dominio.errores import ClienteNoEncontrado
from app.dominio.limites import validar_interpretacion
from app.dominio.pedido import Recursos, ResultadoPedido, procesar_pedido
from app.interprete.base import Interprete, InterpreteNoDisponible
from app.observabilidad import registro as traza


class ErrorInterno(Exception):
    """Error inesperado al procesar un pedido (500). Solo conserva el tipo del error original."""

    def __init__(self, tipo: str):
        self.tipo = tipo
        super().__init__("error interno")


@dataclass(frozen=True)
class Atencion:
    respuesta: RespuestaPedido
    resultado: ResultadoPedido


class ServicioPedidos:
    def __init__(self, datos: Datos, recursos: Recursos, interprete: Interprete):
        self.datos = datos
        self.recursos = recursos
        self.interprete = interprete

    def atender(self, solicitud: SolicitudPedido) -> Atencion:
        entrada = solicitud.a_entrada()
        # 1. Cliente (404) antes del intérprete. El mensaje de ClienteNoEncontrado (E1a) incluye el
        #    cliente_id: la API nunca lo muestra ni lo registra.
        if entrada.cliente_id not in self.datos.clientes:
            raise ClienteNoEncontrado(entrada.cliente_id)
        # 2. Intérprete (503). Hito 2: el tramo se mide para la traza (sin cambiar la lógica).
        with traza.medir("interprete"):
            try:
                bruto = self.interprete.interpretar(entrada)
            except InterpreteNoDisponible as error:
                traza.anotar("interprete", resultado=str(error) or "no_disponible")
                raise
            except Exception:  # noqa: BLE001 - cualquier fallo del intérprete es un 503
                traza.anotar("interprete", resultado="error_al_invocar_modelo")
                raise InterpreteNoDisponible("el intérprete falló") from None
            # 3. Interpretación (503 si es inválida), por el punto de entrada único (D72).
            try:
                interpretacion = validar_interpretacion(
                    bruto.model_dump() if hasattr(bruto, "model_dump") else bruto, len(entrada.mensajes)
                )
            except Exception:  # noqa: BLE001 - ValidationError, LimitesExcedidos u otro formato
                traza.anotar("interprete", resultado="interpretacion_invalida")
                raise InterpreteNoDisponible("interpretación inválida") from None
        traza.anotar("interprete", resultado="ok", n_eventos=len(interpretacion.eventos), n_consultas=len(interpretacion.consultas),
                     n_instrucciones_rechazadas=len(interpretacion.instrucciones_rechazadas))
        if traza.capturando():  # solo si la política lo autorizó al abrir el registro (D-M1)
            traza.guardar_contenido("interpretacion", interpretacion.model_dump(mode="json"))
        # 4. Motor (500 ante cualquier error).
        with traza.medir("motor"):
            try:
                resultado = procesar_pedido(entrada, interpretacion, self.datos, recursos=self.recursos)
                atencion = Atencion(RespuestaPedido.desde_resultado(resultado), resultado)
            except Exception as error:  # noqa: BLE001 - HistorialInconsistente, invariantes, etc.
                traza.anotar("motor", error=type(error).__name__)
                raise ErrorInterno(type(error).__name__) from None
        r = atencion.respuesta
        traza.anotar("motor", estado=r.estado, n_lineas=len(r.lineas), n_pendientes=len(r.pendientes),
                     n_sustituciones=len(r.sustituciones), motivos_revision=",".join(sorted(str(m) for m in r.motivos_revision)))
        return atencion
