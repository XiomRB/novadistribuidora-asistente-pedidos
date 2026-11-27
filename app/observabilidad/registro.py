"""Registro de una solicitud para las trazas (hito 2). Sin MLflow: solo Python.

Cada `POST /v1/pedidos/interpretar` abre un `Registro` en una variable de contexto. El servicio y el
intérprete anotan en él tiempos y atributos; al terminar, el trazador lo convierte en una traza.
Así el motor, el servicio y el intérprete no dependen de MLflow.

Correlación de evaluaciones (no forma parte del contrato JSON): encabezados opcionales
`X-Evaluacion-Ejecucion`, `-Caso`, `-Conjunto`, `-Repeticion` y `-Privado`. Solo se aceptan valores
con caracteres seguros y longitud acotada; cualquier otro valor se ignora.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

_SEGURO = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ENCABEZADOS = {"ejecucion": "x-evaluacion-ejecucion", "caso": "x-evaluacion-caso", "conjunto": "x-evaluacion-conjunto", "repeticion": "x-evaluacion-repeticion"}
ENCABEZADO_PRIVADO = "x-evaluacion-privado"


@dataclass(frozen=True)
class Correlacion:
    ejecucion: str | None = None
    caso: str | None = None
    conjunto: str | None = None
    repeticion: str | None = None
    privado: bool = True  # sin el encabezado explícito "0", se trata como privado

    @classmethod
    def desde_encabezados(cls, encabezados: Mapping[str, str]) -> Correlacion:
        valores = {}
        for campo, nombre in ENCABEZADOS.items():
            valor = encabezados.get(nombre)
            valores[campo] = valor if valor is not None and _SEGURO.match(valor) else None
        return cls(**valores, privado=encabezados.get(ENCABEZADO_PRIVADO) != "0")

    def etiquetas(self) -> dict[str, str]:
        return {f"evaluacion.{k}": v for k, v in (("ejecucion", self.ejecucion), ("caso", self.caso), ("conjunto", self.conjunto), ("repeticion", self.repeticion)) if v}


@dataclass
class Registro:
    correlacion: Correlacion
    inicio_ns: int = field(default_factory=time.time_ns)
    fin_ns: int | None = None
    tramos: dict[str, tuple[int, int]] = field(default_factory=dict)  # nombre -> (inicio, fin) en ns
    atributos: dict[str, dict[str, Any]] = field(default_factory=lambda: {"pedido": {}, "interprete": {}, "motor": {}})
    contenido: dict[str, Any] = field(default_factory=dict)  # solo se usa en modo completo y conjunto público


_ACTUAL: ContextVar[Registro | None] = ContextVar("registro_traza", default=None)


def actual() -> Registro | None:
    return _ACTUAL.get()


@contextmanager
def abrir(correlacion: Correlacion) -> Iterator[Registro]:
    registro = Registro(correlacion)
    token = _ACTUAL.set(registro)
    try:
        yield registro
    finally:
        registro.fin_ns = time.time_ns()
        _ACTUAL.reset(token)


def anotar(tramo: str, **atributos: Any) -> None:
    registro = _ACTUAL.get()
    if registro is not None:
        registro.atributos.setdefault(tramo, {}).update(atributos)


def guardar_contenido(clave: str, valor: Any) -> None:
    """Contenido sensible (entrada o interpretación): el trazador decide si se registra."""
    registro = _ACTUAL.get()
    if registro is not None:
        registro.contenido[clave] = valor


@contextmanager
def medir(tramo: str) -> Iterator[None]:
    inicio = time.time_ns()
    try:
        yield
    finally:
        registro = _ACTUAL.get()
        if registro is not None:
            registro.tramos[tramo] = (inicio, time.time_ns())
