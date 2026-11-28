"""Hito 4: casos propios públicos A01-A15 (`evaluacion/casos/`), en el formato de los casos de desarrollo.

Los dos archivos están aprobados y fijados por hash: cualquier cambio exige una nueva revisión. La
prueba no usa datos reales: comprueba la carga del evaluador (formato, recuentos y anotaciones), el
contrato de los esperados, los fragmentos literales de los pendientes y la forma de las anotaciones.
El recálculo de la política con los datos reales y la ausencia de solapamientos con los conjuntos
privados se verificaron fuera del repositorio antes de incorporarlos.
"""

import hashlib
import json
from pathlib import Path

from app.api.esquemas import RespuestaPedido
from evaluacion.conjuntos import Descriptor, cargar

CARPETA = Path(__file__).resolve().parents[2] / "evaluacion" / "casos"
CASOS = CARPETA / "propios.jsonl"
ANOTACIONES = CARPETA / "propios_anotaciones.json"
HASHES_APROBADOS = {
    "casos": "991c9e7f2bc52a68c54206ffc2c6dc12bacf24ab52e0451b46c6e89f37c69a0f",
    "anotaciones": "29de529f135001256fcea133e3a464decdeb7df282df3cac3be6d673fbd33158",
}


def _filas() -> list[dict]:
    return [json.loads(linea) for linea in CASOS.read_text(encoding="utf-8").splitlines()]


def test_hashes_aprobados():
    assert {"casos": hashlib.sha256(CASOS.read_bytes()).hexdigest(),
            "anotaciones": hashlib.sha256(ANOTACIONES.read_bytes()).hexdigest()} == HASHES_APROBADOS


def test_carga_del_evaluador():
    # El rol solo es necesario para construir el descriptor; la carga no depende de él.
    descriptor = Descriptor(id="PROPIOS", rol="ajuste", sha256=HASHES_APROBADOS, n_casos=15, n_mensajes=17,
                            privado=False, todos_criticos=True)
    conjunto = cargar(descriptor, {"casos": CASOS, "anotaciones": ANOTACIONES})
    assert [c.id for c in conjunto.casos] == [f"A{i:02d}" for i in range(1, 16)]
    assert {c.tipo for c in conjunto.casos} == {"propio_asistente"}
    assert all(a.critico and not a.texto_provisional and not a.consultados for a in conjunto.anotaciones.values())


def test_esperados_cumplen_el_contrato():
    for fila in _filas():
        RespuestaPedido.model_validate({"cliente_id": fila["entrada"]["cliente_id"], **fila["esperado"], "mensaje_cliente": "-"})


def test_pendientes_con_fragmento_literal_del_mensaje():
    pendientes = [(f["entrada"]["mensajes"], p["texto"]) for f in _filas() for p in f["esperado"]["pendientes"]]
    assert len(pendientes) == 5
    assert all(any(texto in m for m in mensajes) for mensajes, texto in pendientes)
