"""Agregados, veredictos de E3 y E6 y reportes sin contenido privado.

- E3 (D33): exactitud ponderada por casos = (correctos de Desarrollo + correctos de Ajuste) /
  (casos de Desarrollo + casos de Ajuste), nunca un promedio de porcentajes. Condiciones:
  A1 exactitud >= 90 %; A2 K5 = 0 en todos los casos; A3 ningún K1-K4 en un caso crítico.
- E6 (alternativa A): Validación pública y privada por separado, sin cifra conjunta; 3
  repeticiones; cada una con exactitud >= 90 %, K5 = 0 y ningún K1-K4 en un caso crítico; se
  informan la media y el mínimo. Un error crítico no se compensa con aciertos de otros casos.
- Umbral: correctos·10 >= 9·casos, con enteros exactos (sin float).
- Reportes: solo identificadores, códigos fijos, nombres de campos, indicadores, agregados, hashes y
  configuración. Para Validación privada, el resumen público solo lleva el hash y si se aprobó.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from evaluacion.criticos import ResultadoCaso

REPETICIONES_E6 = 3
UMBRAL = Fraction(9, 10)


class ErrorSalida(Exception):
    def __str__(self) -> str:
        return "SALIDA_EN_REPOSITORIO"


@dataclass(frozen=True)
class Resumen:
    casos: int
    correctos: int
    invalidos: Mapping[str, int]
    k_unidades: Mapping[str, int]
    k_casos: Mapping[str, int]
    criticos_con_error: int
    sobrantes: int
    mixtos: int
    clasificacion_coincide: int
    texto_coincide: int
    texto_denominador: int  # sin los casos con texto provisional
    texto_provisional_coincide: int
    texto_provisional_total: int
    latencia_media_ms: int | None = None
    latencia_p50_ms: int | None = None
    latencia_p95_ms: int | None = None

    @property
    def exactitud(self) -> Fraction:
        return Fraction(self.correctos, self.casos) if self.casos else Fraction(0)


def resumir(resultados: Sequence[ResultadoCaso]) -> Resumen:
    validos = [r for r in resultados if r.valido]
    estables = [r for r in validos if not r.texto_provisional]
    provisionales = [r for r in validos if r.texto_provisional]
    return Resumen(
        casos=len(resultados),
        correctos=sum(r.correcto for r in resultados),
        invalidos=dict(Counter(r.codigo for r in resultados if r.codigo != "OK")),
        k_unidades={k: sum(getattr(r, k) for r in resultados) for k in ("k1", "k2", "k3", "k4", "k5")},
        k_casos={k: sum(1 for r in resultados if getattr(r, k)) for k in ("k1", "k2", "k3", "k4", "k5")},
        criticos_con_error=sum(r.critico_con_error for r in resultados),
        sobrantes=sum(r.sobrantes for r in resultados),
        mixtos=sum(r.mixtos for r in resultados),
        clasificacion_coincide=sum(bool(r.clasificacion_coincide) for r in validos),
        texto_coincide=sum(bool(r.texto_coincide) for r in estables),
        texto_denominador=len(estables),
        texto_provisional_coincide=sum(bool(r.texto_coincide) for r in provisionales),
        texto_provisional_total=len(provisionales),
        **_latencias([r.latencia_ms for r in resultados if r.latencia_ms is not None]),
    )


def _percentil(ordenados: Sequence[int], p: int) -> int:
    """Percentil por el método del rango más cercano (enteros, sin interpolación)."""
    rango = max(1, -(-p * len(ordenados) // 100))
    return ordenados[rango - 1]


def _latencias(valores: Sequence[int]) -> dict[str, int | None]:
    if not valores:
        return {"latencia_media_ms": None, "latencia_p50_ms": None, "latencia_p95_ms": None}
    ordenados = sorted(valores)
    return {"latencia_media_ms": round(sum(ordenados) / len(ordenados)), "latencia_p50_ms": _percentil(ordenados, 50),
            "latencia_p95_ms": _percentil(ordenados, 95)}


def supera_umbral(correctos: int, casos: int) -> bool:
    return casos > 0 and correctos * UMBRAL.denominator >= UMBRAL.numerator * casos


def veredicto_e3(desarrollo: Resumen, ajuste: Resumen) -> dict[str, Any]:
    correctos, casos = desarrollo.correctos + ajuste.correctos, desarrollo.casos + ajuste.casos
    a1 = supera_umbral(correctos, casos)
    a2 = desarrollo.k_casos["k5"] + ajuste.k_casos["k5"] == 0
    a3 = desarrollo.criticos_con_error + ajuste.criticos_con_error == 0
    return {
        "exactitud": _texto(Fraction(correctos, casos) if casos else Fraction(0)),
        "correctos": correctos, "casos": casos,
        "A1_exactitud": a1, "A2_k5_cero": a2, "A3_sin_criticos": a3, "aprobado": a1 and a2 and a3,
    }


def veredicto_e6(repeticiones: Sequence[Resumen]) -> dict[str, Any]:
    """Un conjunto de validación (pública o privada) en sus 3 repeticiones."""
    detalle = [
        {"exactitud": _texto(r.exactitud), "umbral": supera_umbral(r.correctos, r.casos),
         "k5_cero": r.k_casos["k5"] == 0, "sin_criticos": r.criticos_con_error == 0}
        for r in repeticiones
    ]
    for d in detalle:
        d["aprobada"] = d["umbral"] and d["k5_cero"] and d["sin_criticos"]
    exactitudes = [r.exactitud for r in repeticiones]
    return {
        "repeticiones": detalle,
        "media": _texto(sum(exactitudes, Fraction(0)) / len(exactitudes)) if exactitudes else None,
        "minimo": _texto(min(exactitudes)) if exactitudes else None,
        "aprobado": len(repeticiones) == REPETICIONES_E6 and all(d["aprobada"] for d in detalle),
    }


def _texto(valor: Fraction) -> str:
    """Porcentaje con 2 decimales (exacto hasta el redondeo final; solo para mostrar)."""
    centesimas = (valor * 10000 + Fraction(1, 2)).__floor__()
    return f"{centesimas // 100}.{centesimas % 100:02d} %"


def resumen_dict(r: Resumen) -> dict[str, Any]:
    datos = asdict(r)
    datos["exactitud"] = _texto(r.exactitud)
    return datos


def caso_dict(r: ResultadoCaso) -> dict[str, Any]:
    datos = asdict(r)
    datos["correcto"] = r.correcto
    return datos


# ====================================================================== escritura


def _dentro(ruta: Path, raiz: Path) -> bool:
    ruta, raiz = ruta.resolve(), raiz.resolve()
    return ruta == raiz or raiz in ruta.parents


def escribir(salida: Path, raiz_repositorio: Path, nombre: str, privado: Mapping[str, Any], publico: Mapping[str, Any]) -> Path:
    """Escribe los dos reportes en `salida/<nombre>/` (700 y 400). Nunca dentro del repositorio."""
    if _dentro(Path(salida), raiz_repositorio):
        raise ErrorSalida()
    carpeta = Path(salida) / nombre
    carpeta.mkdir(parents=True, exist_ok=False, mode=0o700)
    for archivo, contenido in (("reporte_privado.json", privado), ("resumen_publico.json", publico)):
        ruta = carpeta / archivo
        ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(ruta, 0o400)
    return carpeta
