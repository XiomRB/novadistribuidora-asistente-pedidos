"""Registro de las evaluaciones en MLflow (hito 2, D-M4). `evaluacion/` no depende de este paquete.

- Entrada: el **resumen público** de una ejecución del evaluador (`resumen_publico.json`). Por
  construcción, un conjunto privado (D39) solo aporta su hash y si se aprobó; ninguna métrica suya.
- Correlación (E): las trazas del servidor llevan `evaluacion.ejecucion`, `.conjunto`, `.caso` y
  `.repeticion`. Los costes se suman **solo** con las trazas de esa ejecución, nunca por ventanas de
  tiempo. Se espera a que lleguen todas las esperadas (casos x repeticiones por conjunto); si faltan
  trazas o alguna no informa el coste, `costes_completos` es falso y el coste total es `None`.
- Tokens y coste efectivo se informan por separado; nunca se estima un coste con precios publicados.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_AJUSTES = {"MLFLOW_HTTP_REQUEST_TIMEOUT": "2", "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "0", "MLFLOW_DISABLE_AGENT_HINT": "1"}
ETIQUETA = "evaluacion"


def _mlflow() -> Any:
    for clave, valor in _AJUSTES.items():
        os.environ.setdefault(clave, valor)
    import mlflow

    return mlflow


@dataclass
class Costes:
    trazas_esperadas: int
    trazas_encontradas: int = 0
    con_coste: int = 0
    coste_total_usd: float | None = None
    tokens_entrada: int = 0
    tokens_salida: int = 0
    latencia_servidor_media_ms: int | None = None
    variantes: list[str] = field(default_factory=list)
    modelos: list[str] = field(default_factory=list)

    @property
    def completos(self) -> bool:
        return self.trazas_encontradas == self.trazas_esperadas and self.con_coste == self.trazas_esperadas


def esperadas(metadatos: Mapping[str, Any]) -> set[tuple[str, str]]:
    """(conjunto, repetición) -> número de trazas esperadas, como conjunto de claves (conjunto, repetición)."""
    return {(c, str(r)) for c in metadatos["casos_por_conjunto"] for r in range(int(metadatos["repeticiones"]))}


def _atributo(traza: Any, tramo: str, clave: str) -> Any:
    for span in traza.data.spans:
        if span.name == tramo:
            return span.attributes.get(clave)
    return None


def costes_de_ejecucion(metadatos: Mapping[str, Any], experimento_trazas: str, espera_s: float = 60, intervalo_s: float = 2,
                        buscar: Callable[[str, str], list[Any]] | None = None) -> Costes:
    ejecucion = metadatos["ejecucion_id"]
    total = sum(int(n) for n in metadatos["casos_por_conjunto"].values()) * int(metadatos["repeticiones"])
    if buscar is None:
        mlflow = _mlflow()
        experimento = mlflow.get_experiment_by_name(experimento_trazas)

        def buscar(exp_id: str, filtro: str) -> list[Any]:
            return mlflow.search_traces(locations=[exp_id], filter_string=filtro, return_type="list", max_results=10_000)

        exp_id = experimento.experiment_id if experimento else None
    else:
        exp_id = experimento_trazas
    filtro = f"tags.`{ETIQUETA}.ejecucion` = '{ejecucion}'"
    limite = time.monotonic() + espera_s
    unicas: dict[tuple[str, str, str], Any] = {}
    while exp_id is not None:
        for t in buscar(exp_id, filtro):  # registro asíncrono: se espera a que lleguen todas
            e = t.info.tags
            clave = (e.get(f"{ETIQUETA}.conjunto", ""), e.get(f"{ETIQUETA}.repeticion", ""), e.get(f"{ETIQUETA}.caso", ""))
            if e.get(f"{ETIQUETA}.ejecucion") == ejecucion and (clave[0], clave[1]) in esperadas(metadatos):
                unicas[clave] = t
        if len(unicas) >= total or time.monotonic() >= limite:
            break
        time.sleep(intervalo_s)
    costes = Costes(trazas_esperadas=total, trazas_encontradas=len(unicas))
    suma, latencias = 0.0, []
    for t in unicas.values():
        coste = _atributo(t, "interprete", "coste_usd")
        if isinstance(coste, (int, float)) and not isinstance(coste, bool):
            costes.con_coste += 1
            suma += coste
        costes.tokens_entrada += int(_atributo(t, "interprete", "tokens_entrada") or 0)
        costes.tokens_salida += int(_atributo(t, "interprete", "tokens_salida") or 0)
        latencia = _atributo(t, "pedido", "latencia_ms")
        if isinstance(latencia, int):
            latencias.append(latencia)
    costes.coste_total_usd = round(suma, 8) if costes.completos else None
    costes.latencia_servidor_media_ms = round(sum(latencias) / len(latencias)) if latencias else None
    costes.variantes = sorted({t.info.tags.get("variante", "") for t in unicas.values()})
    costes.modelos = sorted({t.info.tags.get("modelo", "") for t in unicas.values()})
    return costes


def _metricas_publicas(resumen: Mapping[str, Any]) -> dict[str, float]:
    metricas: dict[str, float] = {}
    for conjunto, datos in resumen.get("conjuntos", {}).items():
        if "sha256" in datos:  # privado: solo si se aprobó
            metricas[f"{conjunto}.aprobado"] = 1.0 if datos.get("aprobado") else 0.0
            continue
        for i, r in enumerate(datos.get("resumenes", [])):
            prefijo = f"{conjunto}.r{i}"
            metricas[f"{prefijo}.exactitud"] = r["correctos"] / r["casos"] if r["casos"] else 0.0
            metricas[f"{prefijo}.casos"] = r["casos"]
            metricas[f"{prefijo}.correctos"] = r["correctos"]
            for k, v in r["k_unidades"].items():
                metricas[f"{prefijo}.{k}"] = v
            metricas[f"{prefijo}.invalidos"] = sum(r["invalidos"].values())
            for clave in ("latencia_media_ms", "latencia_p50_ms", "latencia_p95_ms"):
                if r.get(clave) is not None:
                    metricas[f"{prefijo}.{clave}"] = r[clave]
    if "veredicto" in resumen:
        metricas["e3.aprobado"] = 1.0 if resumen["veredicto"].get("aprobado") else 0.0
    return metricas


def registrar(resumen_publico: Path, experimento: str = "lab3-evaluaciones", experimento_trazas: str = "lab3-api",
              espera_s: float = 60, nombre: str | None = None) -> tuple[str, Costes]:
    resumen = json.loads(Path(resumen_publico).read_text(encoding="utf-8"))
    metadatos = resumen["metadatos"]
    costes = costes_de_ejecucion(metadatos, experimento_trazas, espera_s)
    mlflow = _mlflow()
    mlflow.set_experiment(experimento)
    with mlflow.start_run(run_name=nombre or f"{metadatos['modo']}-{metadatos['ejecucion_id'][:8]}") as run:
        mlflow.set_tags({"ejecucion_id": metadatos["ejecucion_id"], "modo": metadatos["modo"], "git": metadatos.get("git", ""),
                         "variantes": ",".join(costes.variantes), "modelos": ",".join(costes.modelos),
                         "costes_completos": str(costes.completos).lower(), "privados": ",".join(metadatos.get("privados", []))})
        mlflow.log_params({"timeout": metadatos.get("timeout"), "repeticiones": metadatos.get("repeticiones"),
                           **{f"conjunto.{c}.sha256_casos": h.get("casos", "") for c, h in metadatos.get("conjuntos", {}).items()}})
        metricas = _metricas_publicas(resumen)
        metricas.update({"trazas_esperadas": costes.trazas_esperadas, "trazas_encontradas": costes.trazas_encontradas,
                         "tokens_entrada": costes.tokens_entrada, "tokens_salida": costes.tokens_salida})
        if costes.coste_total_usd is not None:  # solo si está completo; si no, se deja constancia en la etiqueta
            metricas["coste_total_usd"] = costes.coste_total_usd
            metricas["coste_medio_usd"] = costes.coste_total_usd / costes.trazas_esperadas if costes.trazas_esperadas else 0.0
        if costes.latencia_servidor_media_ms is not None:
            metricas["latencia_servidor_media_ms"] = costes.latencia_servidor_media_ms
        mlflow.log_metrics(metricas)
        mlflow.log_artifact(str(resumen_publico))
        return run.info.run_id, costes
