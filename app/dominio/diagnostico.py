"""Diagnóstico técnico del procesamiento de un pedido.

Contiene solo códigos, posiciones `(mensaje, inicio, fin)`, SKU, cantidades y medidas
normalizadas. Nunca contiene texto de los mensajes, el texto de los pendientes, nombres,
`cliente_id` ni `pedido_id` (D59, D73, D74). El uso del pedido habitual se registra como
indicador booleano (`habitual_usado`).

La estructura es completa desde E1b-2a; los apartados de omisiones y clasificación los
llena el orquestador en E1b-2b.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Posicion = tuple[int, int, int]  # (mensaje, inicio, fin)


@dataclass(frozen=True)
class DiagEvento:
    evento: str
    tipo: str
    codigo: str
    posicion: Posicion | None
    candidatos_llm: tuple[str, ...] = ()
    sku: str | None = None
    opciones: tuple[str, ...] = ()
    cantidad: str | None = None
    codigo_unidad: str | None = None
    item: str | None = None


@dataclass(frozen=True)
class DiagAccion:
    item: str
    evento: str | None
    accion: str
    sku_antes: str | None = None
    sku_despues: str | None = None
    cantidad_antes: str | None = None
    cantidad_despues: str | None = None


@dataclass(frozen=True)
class DiagItem:
    item: str
    clase: str
    estado: str
    sku: str | None
    motivo: str | None
    opciones: tuple[str, ...]
    origen: tuple[str, ...]  # ids de eventos o "habitual" (nunca el pedido_id)
    sucesor: str | None


@dataclass(frozen=True)
class DiagMedidas:
    """D67: medidas explícitas normalizadas que provocaron un rechazo por contradicción."""

    evento: str
    posicion: Posicion | None
    medidas: tuple[str, ...]
    codigo: str


@dataclass(frozen=True)
class DiagDesacuerdo:
    evento: str
    codigo: str


@dataclass(frozen=True)
class DiagOmision:
    """Señal de omisión (E1b-2b): solo su posición y tipo."""

    posicion: Posicion
    senal: str
    codigo: str


@dataclass(frozen=True)
class DiagSustitucion:
    item: str
    sku_solicitado: str
    sku_entregado: str
    cantidad: str


@dataclass(frozen=True)
class Diagnostico:
    eventos: tuple[DiagEvento, ...] = ()
    items: tuple[DiagItem, ...] = ()
    acciones: tuple[DiagAccion, ...] = ()
    medidas_rechazo: tuple[DiagMedidas, ...] = ()
    desacuerdos: tuple[DiagDesacuerdo, ...] = ()
    sustituciones: tuple[DiagSustitucion, ...] = ()
    salida_lineas: tuple[str, ...] = ()  # id del ítem que originó cada línea de salida
    salida_pendientes: tuple[str, ...] = ()  # id del ítem de cada pendiente de salida
    habitual_usado: bool = False
    # Apartados que llena el orquestador (E1b-2b).
    omisiones: tuple[DiagOmision, ...] = ()
    clasificacion: str | None = None
    consultas: int = 0
    instrucciones_rechazadas: int = 0
    eventos_descartados: tuple[DiagEvento, ...] = field(default_factory=tuple)


def posicion(span) -> Posicion | None:
    return None if span is None else (span.mensaje, span.inicio, span.fin)
