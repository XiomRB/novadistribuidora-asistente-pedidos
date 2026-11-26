"""Línea de comandos: `python -m evaluacion --modo {e3,e6} --registro R --base-url U --timeout S --salida-privada D`.

Códigos de salida: 0 aprobado; 1 no aprobado; 2 integridad, formato, registro, datos o salida
inválidos (antes de cualquier petición); 3 árbol de Git no limpio.

Registro (JSON): lista de conjuntos con `id`, `rol`, `n_casos`, `n_mensajes` (opcional),
`privado`, `todos_criticos` y `archivos` (`casos`, `anotaciones` y, opcional, `esperadas`), cada uno
con `sha256` y una ubicación: `variable` (variable de entorno), `ruta` (relativa al repositorio) o
`junto_a` + `nombre` (en la misma carpeta que otro archivo del conjunto).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.datos.carga import cargar_datos
from evaluacion import VERSION, reporte
from evaluacion.cliente import ClienteEvaluacion
from evaluacion.conjuntos import Conjunto, Descriptor, ErrorIntegridad, cargar_todos
from evaluacion.criticos import evaluar_caso

RAIZ = Path(__file__).resolve().parents[1]
ROLES_POR_MODO = {"e3": ("desarrollo", "ajuste"), "e6": ("validacion_publica", "validacion_privada")}


def _ruta(archivo: Mapping[str, Any], resueltas: Mapping[str, Path], entorno: Mapping[str, str], raiz: Path) -> Path:
    if "variable" in archivo:
        valor = entorno.get(archivo["variable"])
        if not valor:
            raise ErrorIntegridad("ARCHIVO_FALTANTE")
        return Path(valor)
    if "ruta" in archivo:
        return raiz / archivo["ruta"]
    if "junto_a" in archivo and archivo["junto_a"] in resueltas:
        return resueltas[archivo["junto_a"]].parent / archivo["nombre"]
    raise ErrorIntegridad("REGISTRO_INVALIDO")


def leer_registro(ruta: Path, modo: str, entorno: Mapping[str, str], raiz: Path) -> list[tuple[Descriptor, dict[str, Path]]]:
    try:
        entradas = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ErrorIntegridad("REGISTRO_INVALIDO") from None
    pares = []
    for rol in ROLES_POR_MODO[modo]:
        del_rol = [e for e in entradas if isinstance(e, dict) and e.get("rol") == rol] if isinstance(entradas, list) else []
        if len(del_rol) != 1:
            raise ErrorIntegridad("REGISTRO_INCOMPLETO")
        e = del_rol[0]
        try:
            archivos = e["archivos"]
            descriptor = Descriptor(
                id=e["id"], rol=rol, sha256={k: v["sha256"] for k, v in archivos.items()}, n_casos=e["n_casos"],
                n_mensajes=e.get("n_mensajes"), privado=bool(e.get("privado", False)), todos_criticos=bool(e.get("todos_criticos", True)),
            )
            resueltas: dict[str, Path] = {}
            for nombre in ("casos", "anotaciones", "esperadas"):
                if nombre in archivos:
                    resueltas[nombre] = _ruta(archivos[nombre], resueltas, entorno, raiz)
        except (KeyError, TypeError, AttributeError):
            raise ErrorIntegridad("REGISTRO_INVALIDO") from None
        pares.append((descriptor, resueltas))
    return pares


def _arbol_limpio(raiz: Path) -> bool:
    salida = subprocess.run(["git", "-C", str(raiz), "status", "--porcelain"], capture_output=True, text=True)
    return salida.returncode == 0 and not salida.stdout.strip()


def _sha_git(raiz: Path) -> str:
    salida = subprocess.run(["git", "-C", str(raiz), "rev-parse", "HEAD"], capture_output=True, text=True)
    return salida.stdout.strip() if salida.returncode == 0 else "desconocido"


def _hashes_datos(directorio: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(directorio).glob("*.parquet"))}


def _evaluar(conjunto: Conjunto, cliente: ClienteEvaluacion, datos) -> list:
    resultados = []
    for caso in conjunto.casos:
        r = cliente.enviar(caso.entrada)
        resultados.append(evaluar_caso(caso, conjunto.anotaciones.get(caso.id), r.codigo, r.cuerpo, r.cuerpo_decimal, datos))
    return resultados


def ejecutar(
    modo: str, registro: Path, base_url: str, timeout: float, salida: Path, entorno: Mapping[str, str] | None = None,
    cliente: ClienteEvaluacion | None = None, raiz: Path = RAIZ, verificar_arbol: bool = True, salida_texto=None,
) -> int:
    entorno = os.environ if entorno is None else entorno
    imprimir = salida_texto or (lambda texto: print(texto))
    if verificar_arbol and not _arbol_limpio(raiz):
        imprimir("ARBOL_NO_LIMPIO")
        return 3
    # Fase 1: todo se verifica antes de crear el cliente o enviar cualquier petición.
    try:
        conjuntos = cargar_todos(leer_registro(registro, modo, entorno, raiz))
        directorio_datos = Path(entorno.get("DATA_DIR", raiz / "datos"))
        try:
            datos = cargar_datos(directorio_datos)
        except Exception:
            raise ErrorIntegridad("DATOS_INVALIDOS") from None
        if reporte._dentro(Path(salida), raiz):
            raise ErrorIntegridad("SALIDA_EN_REPOSITORIO")
    except ErrorIntegridad as error:
        imprimir(error.codigo)
        return 2
    cliente = cliente or ClienteEvaluacion(base_url, timeout)
    repeticiones = 1 if modo == "e3" else reporte.REPETICIONES_E6
    por_conjunto: dict[str, list] = {c.descriptor.id: [] for c in conjuntos}
    casos_privados: dict[str, list] = {c.descriptor.id: [] for c in conjuntos}
    for _ in range(repeticiones):
        for c in conjuntos:
            resultados = _evaluar(c, cliente, datos)
            por_conjunto[c.descriptor.id].append(reporte.resumir(resultados))
            casos_privados[c.descriptor.id].append([reporte.caso_dict(r) for r in resultados])
    metadatos = {
        "version": VERSION, "modo": modo, "git": _sha_git(raiz), "base_url": base_url, "timeout": timeout,
        "conjuntos": {c.descriptor.id: dict(c.descriptor.sha256) for c in conjuntos}, "datos": _hashes_datos(directorio_datos),
    }
    privado: dict[str, Any] = {"metadatos": metadatos, "conjuntos": {}}
    publico: dict[str, Any] = {"metadatos": {k: v for k, v in metadatos.items() if k != "base_url"}, "conjuntos": {}}
    if modo == "e3":
        dev, aj = (next(c for c in conjuntos if c.descriptor.rol == rol) for rol in ROLES_POR_MODO["e3"])
        veredicto = reporte.veredicto_e3(por_conjunto[dev.descriptor.id][0], por_conjunto[aj.descriptor.id][0])
        privado["veredicto"] = publico["veredicto"] = veredicto
        aprobado = veredicto["aprobado"]
    else:
        aprobado = True
        for c in conjuntos:
            v = reporte.veredicto_e6(por_conjunto[c.descriptor.id])
            aprobado &= v["aprobado"]
            privado["conjuntos"].setdefault(c.descriptor.id, {})["veredicto"] = v
            if c.descriptor.privado:
                publico["conjuntos"][c.descriptor.id] = {"sha256": c.descriptor.sha256["casos"], "aprobado": v["aprobado"]}
            else:
                publico["conjuntos"][c.descriptor.id] = {"veredicto": v}
    for c in conjuntos:
        bloque = privado["conjuntos"].setdefault(c.descriptor.id, {})
        bloque["resumenes"] = [reporte.resumen_dict(r) for r in por_conjunto[c.descriptor.id]]
        bloque["casos"] = casos_privados[c.descriptor.id]
        if not c.descriptor.privado:  # la Validación privada solo publica su hash y si se aprobó
            publico["conjuntos"].setdefault(c.descriptor.id, {})["resumenes"] = bloque["resumenes"]
    nombre = f"{datetime.now():%Y%m%d-%H%M%S}_{modo}_{metadatos['git'][:7]}"
    reporte.escribir(Path(salida), raiz, nombre, privado, publico)
    for id_conjunto, valor in publico["conjuntos"].items():
        if "sha256" in valor:
            imprimir(f"{id_conjunto}: {'APROBADO' if valor['aprobado'] else 'NO APROBADO'}")
        else:
            corto = [{"exactitud": r["exactitud"], "casos": r["casos"], "k_casos": r["k_casos"]} for r in valor["resumenes"]]
            imprimir(f"{id_conjunto}: {json.dumps(corto, ensure_ascii=False)}")
            if "veredicto" in valor:
                imprimir(f"{id_conjunto} veredicto: {json.dumps(valor['veredicto'], ensure_ascii=False)}")
    if modo == "e3":
        imprimir(f"E3 veredicto: {json.dumps(publico['veredicto'], ensure_ascii=False)}")
    return 0 if aprobado else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evaluacion")
    p.add_argument("--modo", choices=sorted(ROLES_POR_MODO), required=True)
    p.add_argument("--registro", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--salida-privada", type=Path, required=True)
    a = p.parse_args(argv)
    return ejecutar(a.modo, a.registro, a.base_url, a.timeout, a.salida_privada)


if __name__ == "__main__":
    sys.exit(main())
