"""`GET /health` con sondas inyectables (D81).

Responde **siempre 200**: `{"estado": "ok"}` si todas las sondas están bien, o
`{"estado": "degradado", "motivo": "..."}` si alguna no lo está (Anexo). En E2 la única sonda es
la del intérprete (no configurado hasta E3, D80); la de MLflow se agrega en E4.

Una sonda que falla con una excepción cuenta como degradada con un motivo genérico: su mensaje
nunca se muestra.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.interprete.base import Interprete

MOTIVO_SONDA_FALLIDA = "una dependencia no respondió"


@dataclass(frozen=True)
class ResultadoSonda:
    ok: bool
    motivo: str | None = None


Sonda = Callable[[], ResultadoSonda]


def sonda_interprete(interprete: Interprete) -> Sonda:
    def sonda() -> ResultadoSonda:
        disponible, motivo = interprete.estado()
        return ResultadoSonda(bool(disponible), None if disponible else (motivo or MOTIVO_SONDA_FALLIDA))

    return sonda


def estado_de_salud(sondas: Sequence[Sonda]) -> dict[str, str]:
    motivos: list[str] = []
    for sonda in sondas:
        try:
            resultado = sonda()
        except Exception:  # noqa: BLE001 - una sonda rota no tumba /health
            resultado = ResultadoSonda(False, MOTIVO_SONDA_FALLIDA)
        if not resultado.ok:
            motivo = resultado.motivo or MOTIVO_SONDA_FALLIDA
            if motivo not in motivos:
                motivos.append(motivo)
    if motivos:
        return {"estado": "degradado", "motivo": "; ".join(motivos)}
    return {"estado": "ok"}
