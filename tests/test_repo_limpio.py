"""Garantiza que ningún material del curso, dato o secreto pueda entrar al repositorio.

Revisa los archivos rastreados y los que `git add -A` incorporaría (no ignorados).
"""

import fnmatch
import hashlib
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

PATRONES_PROHIBIDOS = [
    "*.parquet",
    "*.zip",
    "instrucciones*.md",
    "politicas.md",
    "catalogo_problemas.md",
    "anexo*",
    "Anexo*",
    "mensajes_dev.jsonl",
    ".env",
    "*.db",
]
DIRECTORIOS_PROHIBIDOS = ["datos/", "ejemplos/", "mlruns/", "mlartifacts/", ".venv/"]
MARKDOWN_PERMITIDOS = {"README.md", "DECISIONES.md", "CLAUDE.md"}

# SHA-256 del material del curso (enunciado, zip y su contenido): detecta copias renombradas.
HASHES_MATERIAL = {
    "e69161cda19f8a6487f69027111e61532d8350c6513ac3db9d7e5290daa0a2a6",  # instrucciones_lab3.md
    "2ecf12c7b63f39e40d32ffa0d1fee3a9359cb09cd82a5433b685e10e7cb32799",  # lab3.zip
    "d5e0128d530864d114b2d0665a1d94209b35640bfa6f343055da087370549940",  # catalogo_problemas.md
    "49fcc9b429c67033849be10a781d53ba12f64ff46bcb6528e17311980bcbd32e",  # politicas.md
    "0726c2d4a8391b436f3a3dd4993484548f7d764ec42cd23569090ead8920a45f",  # mensajes_dev.jsonl
    "0f7acb71d875fecca2b8fc7379ebffb85895d7ca0b9c5d4f3ffc2ce7e0c7c4d6",  # clientes.parquet
    "d7a3db589e7ab6d0151df97ffef838779908f664c25db5acd18540fe6063b402",  # historial_pedidos.parquet
    "8262682fb127434467c9c80daf34b7266dbfc1967b5a65a9043c0229f6227c10",  # precios_escala.parquet
    "08aa4d74b8528655e3fca2708b0cbdafaac2117669e2a6510743f7c5ead1f96e",  # productos.parquet
    "94dfc743d03f974d526deb78b7a60080685bc38ae09aab9591f39f3a6c1565a5",  # sinonimos.parquet
}


def _git(*args: str) -> list[str]:
    salida = subprocess.run(
        ["git", "-C", str(RAIZ), *args], check=True, capture_output=True, text=True
    ).stdout
    return [linea for linea in salida.splitlines() if linea]


def _candidatos() -> list[str]:
    rastreados = _git("ls-files")
    no_ignorados = _git("ls-files", "--others", "--exclude-standard")
    return sorted(set(rastreados) | set(no_ignorados))


def test_es_repositorio_git():
    assert _git("rev-parse", "--is-inside-work-tree") == ["true"]


def test_sin_archivos_prohibidos():
    infracciones = []
    for ruta in _candidatos():
        nombre = Path(ruta).name
        if any(fnmatch.fnmatch(nombre, p) for p in PATRONES_PROHIBIDOS):
            infracciones.append(ruta)
        elif any(ruta.startswith(d) for d in DIRECTORIOS_PROHIBIDOS) and ruta != "datos/.gitkeep":
            infracciones.append(ruta)
    assert not infracciones, infracciones


def test_solo_markdown_permitido():
    otros = [
        ruta
        for ruta in _candidatos()
        if ruta.lower().endswith(".md")
        and ruta not in MARKDOWN_PERMITIDOS
        and not ruta.startswith("evidencia/")
    ]
    assert not otros, f"Markdown no permitido (posible documento de planificación): {otros}"


def test_sin_copias_del_material_por_contenido():
    copias = []
    for ruta in _candidatos():
        archivo = RAIZ / ruta
        if archivo.is_file() and hashlib.sha256(archivo.read_bytes()).hexdigest() in HASHES_MATERIAL:
            copias.append(ruta)
    assert not copias, copias


def test_datos_y_secretos_ignorados():
    rutas = ["datos/productos.parquet", ".env", "lab3.zip", "politicas.md", "ejemplos/mensajes_dev.jsonl"]
    resultado = subprocess.run(
        ["git", "-C", str(RAIZ), "check-ignore", "--no-index", *rutas], capture_output=True, text=True
    )
    ignorados = set(resultado.stdout.split())
    assert ignorados == set(rutas), f"No ignorados: {set(rutas) - ignorados}"
