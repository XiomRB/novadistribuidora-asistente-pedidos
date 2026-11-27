"""`python -m evaluacion_mlflow --resumen <resumen_publico.json>`: registra la ejecución en MLflow.

Usa `MLFLOW_TRACKING_URI`. Imprime el id del run, las trazas encontradas frente a las esperadas y si
los costes están completos (`COSTES_INCOMPLETOS` en caso contrario). Nunca imprime contenido.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evaluacion_mlflow.registro import registrar


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evaluacion_mlflow")
    p.add_argument("--resumen", type=Path, required=True, help="resumen_publico.json de una ejecución del evaluador")
    p.add_argument("--experimento", default="lab3-evaluaciones")
    p.add_argument("--experimento-trazas", default="lab3-api")
    p.add_argument("--espera-s", type=float, default=60)
    p.add_argument("--nombre")
    a = p.parse_args(argv)
    run_id, costes = registrar(a.resumen, a.experimento, a.experimento_trazas, a.espera_s, a.nombre)
    estado = "COSTES_COMPLETOS" if costes.completos else "COSTES_INCOMPLETOS"
    print(f"run={run_id} trazas={costes.trazas_encontradas}/{costes.trazas_esperadas} {estado} coste_total_usd={costes.coste_total_usd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
