"""Esquema estructurado que produce la interpretación (LLM en E3; pruebas en E1).

No existe ningún campo para precios, descuentos, subtotales, totales, crédito, fechas,
estado ni motivos: esos valores solo los calcula el motor determinista.

Los patrones (id, sku, cantidad) se validan en código y no como `pattern` del esquema JSON,
porque no todos los proveedores lo admiten en salida estructurada estricta.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator, model_validator

TipoEvento = Literal["agregar", "corregir", "quitar", "precisar", "habitual"]
UnidadDeclarada = Literal["venta", "suelta", "docena", "no_indicada", "otra"]

MAX_EVENTOS = 40
MAX_FRAGMENTOS = 20

_ID = re.compile(r"^e[1-9][0-9]{0,2}$")
_SKU = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
_CANTIDAD = re.compile(r"^\d{1,5}([.,]\d{1,3})?$")

Texto200 = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Texto300 = Annotated[str, StringConstraints(min_length=1, max_length=300)]
Texto100 = Annotated[str, StringConstraints(min_length=1, max_length=100)]
Texto50 = Annotated[str, StringConstraints(min_length=1, max_length=50)]
Texto30 = Annotated[str, StringConstraints(min_length=1, max_length=30)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _no_vacio(valor: str | None) -> str | None:
    if valor is not None and not valor.strip():
        raise ValueError("no puede estar vacío")
    return valor


class Fragmento(_Base):
    """Fragmento literal de un mensaje (consulta o instrucción rechazada)."""

    mensaje: int = Field(ge=0)
    texto: Texto300

    @field_validator("texto")
    @classmethod
    def _validar_texto(cls, valor: str) -> str:
        return _no_vacio(valor)


class Evento(_Base):
    id: str
    mensaje: int = Field(ge=0)
    tipo: TipoEvento
    texto: Texto200
    producto: Texto100 | None = None
    presentacion: Texto50 | None = None
    candidatos: list[str] = Field(default_factory=list, max_length=10)
    cantidad: str | None = None
    cantidad_incierta: bool = False
    unidad: UnidadDeclarada = "no_indicada"
    unidad_texto: Texto30 | None = None
    ref: str | None = None

    @field_validator("id")
    @classmethod
    def _validar_id(cls, valor: str) -> str:
        if not _ID.match(valor):
            raise ValueError("id debe tener la forma e1, e2, …")
        return valor

    @field_validator("ref")
    @classmethod
    def _validar_ref(cls, valor: str | None) -> str | None:
        if valor is not None and not _ID.match(valor):
            raise ValueError("ref debe tener la forma e1, e2, …")
        return valor

    @field_validator("texto", "producto", "presentacion", "unidad_texto")
    @classmethod
    def _validar_no_vacio(cls, valor: str | None) -> str | None:
        return _no_vacio(valor)

    @field_validator("candidatos")
    @classmethod
    def _validar_candidatos(cls, valor: list[str]) -> list[str]:
        for sku in valor:
            if not _SKU.match(sku):
                raise ValueError(f"sku con formato inválido: {sku!s}")
        if len(set(valor)) != len(valor):
            raise ValueError("candidatos repetidos")
        return valor

    @field_validator("cantidad")
    @classmethod
    def _validar_cantidad(cls, valor: str | None) -> str | None:
        if valor is not None and not _CANTIDAD.match(valor.strip()):
            raise ValueError("cantidad debe ser un número decimal no negativo (p. ej. 2, 48, 0.5)")
        return valor.strip() if valor is not None else None

    @model_validator(mode="after")
    def _reglas_por_tipo(self) -> Evento:
        describe = bool(self.producto or self.presentacion or self.candidatos)
        if self.tipo == "habitual":
            if self.candidatos or self.cantidad is not None or self.cantidad_incierta or self.ref is not None:
                raise ValueError("habitual no lleva candidatos, cantidad ni ref")
        if self.tipo == "quitar" and (self.cantidad is not None or self.cantidad_incierta):
            raise ValueError("quitar no lleva cantidad (las reducciones se expresan con corregir)")
        if self.tipo == "agregar" and self.ref is not None:
            raise ValueError("agregar no lleva ref")
        if self.tipo in ("corregir", "precisar", "quitar") and self.ref is None and not describe:
            raise ValueError(f"{self.tipo} requiere ref o una descripción del producto")
        if self.tipo == "corregir" and not (describe or self.cantidad is not None or self.cantidad_incierta):
            raise ValueError("corregir debe indicar una cantidad o un producto")
        if self.tipo == "precisar" and not describe:
            raise ValueError("precisar requiere una descripción del producto")
        return self

    def cantidad_decimal(self) -> Decimal | None:
        """Cantidad como `Decimal` construido desde su texto (nunca desde float)."""
        return None if self.cantidad is None else Decimal(self.cantidad.replace(",", "."))

    def descripcion(self) -> str:
        """Descripción del producto para la resolución (producto y presentación)."""
        return " ".join(p for p in (self.producto, self.presentacion) if p)


class Interpretacion(_Base):
    eventos: list[Evento] = Field(default_factory=list, max_length=MAX_EVENTOS)
    consultas: list[Fragmento] = Field(default_factory=list, max_length=MAX_FRAGMENTOS)
    instrucciones_rechazadas: list[Fragmento] = Field(default_factory=list, max_length=MAX_FRAGMENTOS)

    @model_validator(mode="after")
    def _coherencia(self, info: ValidationInfo) -> Interpretacion:
        n_mensajes = (info.context or {}).get("n_mensajes")
        vistos: list[str] = []
        mensaje_previo = 0
        for posicion, evento in enumerate(self.eventos, start=1):
            if evento.id != f"e{posicion}":
                raise ValueError(f"los ids deben ser consecutivos: se esperaba e{posicion} y llegó {evento.id}")
            if evento.ref is not None and evento.ref not in vistos:
                raise ValueError(f"{evento.id}: ref {evento.ref} no apunta a un evento anterior")
            if evento.mensaje < mensaje_previo:
                raise ValueError(f"{evento.id}: el índice de mensaje no puede retroceder")
            mensaje_previo = evento.mensaje
            vistos.append(evento.id)
        if n_mensajes is not None:
            indices = [e.mensaje for e in self.eventos] + [f.mensaje for f in self.consultas + self.instrucciones_rechazadas]
            fuera = [i for i in indices if i >= n_mensajes]
            if fuera:
                raise ValueError(f"índice de mensaje fuera de rango: {fuera[0]} (hay {n_mensajes})")
        return self

    @classmethod
    def validar(cls, datos: Any, n_mensajes: int) -> Interpretacion:
        """Valida un dict o un JSON con el número de mensajes como contexto."""
        contexto = {"n_mensajes": n_mensajes}
        if isinstance(datos, (str, bytes)):
            return cls.model_validate_json(datos, context=contexto)
        return cls.model_validate(datos, context=contexto)
