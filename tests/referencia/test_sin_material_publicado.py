"""D43: ningún archivo versionable contiene mensajes publicados ni respuestas esperadas.

Revisa los archivos rastreados (incluido el staging) y los que `git add -A` incorporaría.
"""

import json
import subprocess
from pathlib import Path

from app.datos.normalizacion import normalizar_texto

RAIZ = Path(__file__).resolve().parents[2]
MIN_CARACTERES_MENSAJE = 20
MIN_CARACTERES_RESPUESTA = 40


def _candidatos() -> dict[str, str]:
    def git(*args):
        salida = subprocess.run(["git", "-C", str(RAIZ), *args], check=True, capture_output=True, text=True).stdout
        return [l for l in salida.splitlines() if l]

    contenidos = {}
    for ruta in sorted(set(git("ls-files")) | set(git("ls-files", "--others", "--exclude-standard"))):
        archivo = RAIZ / ruta
        if not archivo.is_file():
            continue
        try:
            contenidos[ruta] = archivo.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binario
    return contenidos


def test_sin_mensajes_publicados(casos_dev):
    archivos = {ruta: normalizar_texto(texto) for ruta, texto in _candidatos().items()}
    hallazgos = []
    for caso in casos_dev:
        for mensaje in caso["entrada"]["mensajes"]:
            huella = normalizar_texto(mensaje)
            if len(huella) < MIN_CARACTERES_MENSAJE:
                continue
            hallazgos += [(caso["id"], ruta) for ruta, texto in archivos.items() if huella in texto]
    assert hallazgos == []


def test_sin_respuestas_esperadas(lineas_crudas_dev):
    archivos = _candidatos()
    hallazgos = []
    for linea in lineas_crudas_dev:
        caso = json.loads(linea)
        esperado = caso["esperado"]
        huellas = [json.dumps(esperado, ensure_ascii=False)]
        if esperado["lineas"]:
            huellas.append(json.dumps(esperado["lineas"], ensure_ascii=False))
        for huella in huellas:
            if len(huella) < MIN_CARACTERES_RESPUESTA:
                continue
            assert huella in linea, "la huella debe existir en el archivo publicado"
            hallazgos += [(caso["id"], ruta) for ruta, texto in archivos.items() if huella in texto]
    assert hallazgos == []
