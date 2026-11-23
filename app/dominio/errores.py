"""Errores del dominio. Los mensajes nunca incluyen datos personales."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProblemaDatos:
    """Un problema detectado al cargar los datos.

    `clave` identifica el registro con un código técnico (sku, cliente_id, pedido_id o fila),
    nunca con nombres de tiendas o personas.
    """

    codigo: str
    archivo: str
    columna: str | None = None
    clave: str | None = None
    detalle: str = ""

    def __str__(self) -> str:
        partes = [self.codigo, self.archivo]
        if self.columna:
            partes.append(f"columna={self.columna}")
        if self.clave:
            partes.append(f"clave={self.clave}")
        if self.detalle:
            partes.append(self.detalle)
        return " | ".join(partes)


class DatosInvalidos(Exception):
    """Los datos no cumplen el formato o las reglas mínimas; el servicio no debe arrancar."""

    def __init__(self, errores: list[ProblemaDatos], advertencias: list[ProblemaDatos] | None = None):
        self.errores = tuple(errores)
        self.advertencias = tuple(advertencias or ())
        resumen = "; ".join(str(e) for e in self.errores[:10])
        extra = f" (+{len(self.errores) - 10} más)" if len(self.errores) > 10 else ""
        super().__init__(f"{len(self.errores)} problema(s) en los datos: {resumen}{extra}")


class ClienteNoEncontrado(LookupError):
    """El cliente no existe en los datos (la API lo traduce a 404)."""

    def __init__(self, cliente_id: str):
        self.cliente_id = cliente_id
        super().__init__(f"Cliente inexistente: {cliente_id}")


class ValorDecimalInvalido(ValueError):
    """Un valor numérico no cumple la validación de su campo."""

    def __init__(self, campo: str, motivo: str):
        self.campo = campo
        self.motivo = motivo
        super().__init__(f"{campo}: {motivo}")


class EntradaCierreIncoherente(ValueError):
    """La entrada al cierre del pedido viola su contrato (error del llamador, no del cliente)."""


class InvarianteViolada(AssertionError):
    """El resultado del pedido no cumple un invariante del contrato."""
