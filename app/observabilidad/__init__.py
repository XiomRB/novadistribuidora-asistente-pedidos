"""Observabilidad (hito 2): trazas en MLflow y estado de MLflow para `/health`.

`registro.py` y `estado_mlflow.py` no importan MLflow; `trazas.py` es el único módulo de `app/` que
lo hace. El motor (`app/dominio`, `app/datos`, `app/mensajes`) no depende de esta capa.
"""
