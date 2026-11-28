"""Resuelve el SHA de Git del contexto de construcción sin Git ni la carpeta `.git` en la imagen (D-H4).

Se ejecuta en `docker build` con el contexto montado (`RUN --mount=type=bind`), que por el
`.dockerignore` solo expone `.git/HEAD`, `.git/refs/` y `.git/packed-refs`. Escribe el SHA completo
(40 caracteres hexadecimales) o `unknown` si no hay repositorio, si `.git` es un archivo (worktree o
submódulo) o si la referencia no se puede resolver. Nunca falla la construcción.

Uso: python version_git.py <carpeta .git> <archivo de salida>
"""

import re
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


def resolver(git: Path) -> str:
    try:
        cabeza = (git / "HEAD").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return "unknown"
    if SHA.match(cabeza):  # HEAD separado (p. ej., clon de un tag o checkout de la CI)
        return cabeza
    if not cabeza.startswith("ref: "):
        return "unknown"
    referencia = cabeza[5:].strip()
    if ".." in referencia or not referencia.startswith("refs/"):
        return "unknown"
    try:
        valor = (git / referencia).read_text(encoding="ascii").strip()
        if SHA.match(valor):
            return valor
    except (OSError, UnicodeDecodeError):
        pass
    try:
        for linea in (git / "packed-refs").read_text(encoding="ascii").splitlines():
            partes = linea.split()
            if len(partes) == 2 and partes[1] == referencia and SHA.match(partes[0]):
                return partes[0]
    except (OSError, UnicodeDecodeError):
        pass
    return "unknown"


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(resolver(Path(sys.argv[1])) + "\n", encoding="ascii")
