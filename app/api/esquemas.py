"""Esquemas del contrato HTTP (Anexo): solicitud y respuesta de `POST /v1/pedidos/interpretar`.

Solicitud (`SolicitudPedido`):
- `cliente_id`: texto no vacío (sin contar espacios), de **64 caracteres como máximo** (D90).
  Se cuentan caracteres (puntos de código, `len()` de Python), no bytes UTF-8. No se normaliza:
  "c001" no es "C001" (D15). Es una restricción del contrato de la API.
- `fecha_hora`: exactamente `AAAA-MM-DDTHH:MM` y una fecha y hora válidas; sin segundos ni zona
  horaria (hora local de Guatemala) (D15).
- `mensajes`: lista de 1 a 20 textos, de 2.000 caracteres como máximo cada uno, con al menos uno
  no vacío (D15, D56; los mismos límites que `EntradaPedido`).
- Campos adicionales: se ignoran (D77).
Los errores usan el formato de D78 (`app/api/errores.py`) y nunca incluyen el valor recibido.

Respuesta (`RespuestaPedido`): exactamente los 9 campos de primer nivel del Anexo. Los montos
(`precio_unitario`, `subtotal`, `total`) se calculan con `Decimal` en el dominio y se convierten
a número JSON **solo al serializar** (D03, D91 opción A): se garantiza la igualdad numérica
exacta, no un texto concreto (no se conservan los ceros finales). `cantidad` y `descuento_pct`
son enteros.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, PlainSerializer, StrictStr, field_validator
from pydantic_core import PydanticCustomError

from app.api.errores import PREFIJO_CONTRATO
from app.dominio.entrada import MAX_CARACTERES_MENSAJE, MAX_MENSAJES, EntradaPedido
from app.dominio.pedido import ResultadoPedido
from app.dominio.resultado import Estado, Motivo

MAX_CARACTERES_CLIENTE_ID = 64  # D90: caracteres (puntos de código), no bytes
FORMATO_FECHA_HORA = "%Y-%m-%dT%H:%M"
# Solo dígitos ASCII: `\d` aceptaría dígitos Unicode como "２０２６" (y `strptime` también).
_PATRON_FECHA_HORA = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$")

MOTIVO_CLIENTE_ID = f"debe tener entre 1 y {MAX_CARACTERES_CLIENTE_ID} caracteres"
MOTIVO_FECHA_HORA = "debe tener el formato AAAA-MM-DDTHH:MM y ser una fecha y hora válidas"
MOTIVO_MENSAJES_CANTIDAD = f"debe contener entre 1 y {MAX_MENSAJES} mensajes"
MOTIVO_MENSAJE_LARGO = f"supera {MAX_CARACTERES_MENSAJE} caracteres"
MOTIVO_MENSAJES_VACIOS = "al menos un mensaje debe tener texto"


def _error(codigo: str, motivo: str) -> PydanticCustomError:
    return PydanticCustomError(PREFIJO_CONTRATO + codigo, motivo)


class SolicitudPedido(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    cliente_id: StrictStr
    fecha_hora: StrictStr
    mensajes: list[StrictStr]

    @field_validator("cliente_id")
    @classmethod
    def _validar_cliente_id(cls, valor: str) -> str:
        if not valor.strip() or len(valor) > MAX_CARACTERES_CLIENTE_ID:
            raise _error("cliente_id", MOTIVO_CLIENTE_ID)
        return valor

    @field_validator("fecha_hora")
    @classmethod
    def _validar_fecha_hora(cls, valor: str) -> str:
        if not _PATRON_FECHA_HORA.match(valor):
            raise _error("fecha_hora", MOTIVO_FECHA_HORA)
        try:
            datetime.strptime(valor, FORMATO_FECHA_HORA)
        except ValueError:
            raise _error("fecha_hora", MOTIVO_FECHA_HORA) from None
        return valor

    @field_validator("mensajes")
    @classmethod
    def _validar_mensajes(cls, valor: list[str]) -> list[str]:
        if not 1 <= len(valor) <= MAX_MENSAJES:
            raise _error("mensajes", MOTIVO_MENSAJES_CANTIDAD)
        if any(len(m) > MAX_CARACTERES_MENSAJE for m in valor):
            raise _error("mensajes", MOTIVO_MENSAJE_LARGO)
        if not any(m.strip() for m in valor):
            raise _error("mensajes", MOTIVO_MENSAJES_VACIOS)
        return valor

    def a_entrada(self) -> EntradaPedido:
        """Entrada del dominio (E1b-1). `fecha_hora` sin zona horaria = hora de Guatemala."""
        return EntradaPedido(
            cliente_id=self.cliente_id,
            fecha_hora=datetime.strptime(self.fecha_hora, FORMATO_FECHA_HORA),
            mensajes=tuple(self.mensajes),
        )


# ---------------------------------------------------------------- respuesta

# D03 / D91 (opción A): Decimal -> número JSON solo al serializar. Igualdad numérica exacta.
Monto = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

EstadoContrato = Literal["confirmado", "requiere_revision", "fuera_de_alcance"]
MotivoPendiente = Literal["producto_ambiguo", "producto_no_existe", "agotado_sin_sustituto", "cantidad_no_convertible"]
MotivoRevision = Literal[
    "producto_ambiguo", "producto_no_existe", "agotado_sin_sustituto", "cantidad_no_convertible", "credito_excedido"
]


class _Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LineaRespuesta(_Contrato):
    sku: str
    cantidad: int
    precio_unitario: Monto
    descuento_pct: int
    subtotal: Monto


class SustitucionRespuesta(_Contrato):
    sku_solicitado: str
    sku_entregado: str
    cantidad: int


class PendienteRespuesta(_Contrato):
    motivo: MotivoPendiente
    texto: str
    opciones: list[str]


class RespuestaPedido(_Contrato):
    """Los 9 campos de primer nivel del Anexo (ni más ni menos)."""

    cliente_id: str
    estado: EstadoContrato
    lineas: list[LineaRespuesta]
    total: Monto
    fecha_entrega: date | None
    sustituciones: list[SustitucionRespuesta]
    pendientes: list[PendienteRespuesta]
    motivos_revision: list[MotivoRevision]
    mensaje_cliente: str

    @classmethod
    def desde_resultado(cls, resultado: ResultadoPedido) -> RespuestaPedido:
        """Traducción uno a uno del resultado del dominio; no recalcula nada."""
        cierre = resultado.cierre
        return cls(
            cliente_id=cierre.cliente_id,
            estado=_estado(cierre.estado),
            lineas=[
                LineaRespuesta(
                    sku=l.sku,
                    cantidad=_entero(l.cantidad),
                    precio_unitario=l.precio_unitario,
                    descuento_pct=_entero(l.descuento_pct),
                    subtotal=l.subtotal,
                )
                for l in cierre.lineas
            ],
            total=cierre.total,
            fecha_entrega=cierre.fecha_entrega,
            sustituciones=[
                SustitucionRespuesta(sku_solicitado=s.sku_solicitado, sku_entregado=s.sku_entregado, cantidad=_entero(s.cantidad))
                for s in cierre.sustituciones
            ],
            pendientes=[PendienteRespuesta(motivo=p.motivo.value, texto=p.texto, opciones=list(p.opciones)) for p in cierre.pendientes],
            motivos_revision=[_motivo(m) for m in cierre.motivos_revision],
            mensaje_cliente=resultado.mensaje_cliente,
        )


def _estado(estado: Estado) -> str:
    return Estado(estado).value


def _motivo(motivo: Motivo) -> str:
    return Motivo(motivo).value


def _entero(valor: Decimal) -> int:
    """Cantidades y porcentajes: `Decimal` entero -> `int` exacto (nunca se redondea)."""
    if not isinstance(valor, Decimal) or valor != valor.to_integral_value():
        raise ValueError("se esperaba un entero exacto")
    return int(valor)
