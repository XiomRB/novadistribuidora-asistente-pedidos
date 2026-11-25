"""Formato de `eventos_dev.json` (D51, D66, D61-a): validación con lista blanca y reconstrucción.

El archivo guarda **solo datos estructurados**: identificadores, enumeraciones, SKU,
cantidades en dígitos, un booleano y posiciones enteras. Ningún campo admite texto libre: el
texto de cada evento se reconstruye al ejecutar las pruebas como `mensajes[m][i:f]` del caso
publicado (`EVAL_DEV_PATH`), que nunca se copia al repositorio. Los resultados esperados
también se leen únicamente de `EVAL_DEV_PATH`.

Reglas (plan final de E1b-2, sección 1, y precisiones posteriores):
- Raíz: `version` (exactamente 1) y `casos` (claves `^D\\d{3}$`).
- Caso: `eventos` (0 a 40), `consultas` e `instrucciones_rechazadas` (posiciones
  `{"m", "i", "f"}`), con `len(consultas) + len(instrucciones_rechazadas) <= 20` (D56, D72).
- Evento: `id` y `ref` (`^e[1-9][0-9]{0,2}$`, consecutivos), `tipo` y `unidad` (enumeraciones),
  `m` (entero >= 0), `texto` (`[i, f]` con `0 <= i < f`), `producto`, `presentacion` y
  `unidad_texto` (`[i, f]` o null, **contenidos en `texto`**: `texto.i <= i < f <= texto.f`),
  `candidatos` (hasta 10 SKU `^[A-Z]{1,3}[0-9]{1,4}$`), `cantidad` (`^[0-9]{1,5}(\\.[0-9]{1,3})?$`
  o null) y `cantidad_incierta` (el único booleano).
- Se rechaza cualquier clave desconocida, cualquier cadena fuera de su formato, números no
  enteros, booleanos fuera de `cantidad_incierta`, nulls no permitidos y estructuras anidadas
  donde se espera un valor simple.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.dominio.esquema_eventos import MAX_EVENTOS, Interpretacion
from app.dominio.limites import MAX_FRAGMENTOS_COMBINADOS, validar_interpretacion

RUTA = Path(__file__).with_name("eventos_dev.json")

ID_CASO = re.compile(r"^D\d{3}$")
ID_EVENTO = re.compile(r"^e[1-9][0-9]{0,2}$")
SKU = re.compile(r"^[A-Z]{1,3}[0-9]{1,4}$")
CANTIDAD = re.compile(r"^[0-9]{1,5}(\.[0-9]{1,3})?$")
TIPOS = frozenset({"agregar", "corregir", "quitar", "precisar", "habitual"})
UNIDADES = frozenset({"venta", "suelta", "docena", "no_indicada", "otra"})
MAX_CANDIDATOS = 10

CLAVES_RAIZ = frozenset({"version", "casos"})
CLAVES_CASO = frozenset({"eventos", "consultas", "instrucciones_rechazadas"})
CLAVES_EVENTO = frozenset(
    {"id", "tipo", "m", "texto", "producto", "presentacion", "unidad_texto", "candidatos", "cantidad",
     "cantidad_incierta", "unidad", "ref"}
)
CLAVES_FRAGMENTO = frozenset({"m", "i", "f"})
CAMPOS_POSICION = ("producto", "presentacion", "unidad_texto")


class FormatoInvalido(ValueError):
    """El archivo no cumple la lista blanca. El mensaje indica la ruta del campo, nunca su valor."""


def _entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _exigir(condicion: bool, ruta: str, motivo: str) -> None:
    if not condicion:
        raise FormatoInvalido(f"{ruta}: {motivo}")


def _claves(objeto: Any, permitidas: frozenset[str], ruta: str, obligatorias: frozenset[str] | None = None) -> None:
    _exigir(isinstance(objeto, dict), ruta, "se esperaba un objeto")
    extra = set(objeto) - permitidas
    _exigir(not extra, ruta, f"{len(extra)} clave(s) no permitida(s)")
    faltan = (obligatorias if obligatorias is not None else permitidas) - set(objeto)
    _exigir(not faltan, ruta, f"faltan claves: {', '.join(sorted(faltan))}")


def _cadena(valor: Any, patron: re.Pattern[str] | frozenset[str], ruta: str) -> None:
    _exigir(isinstance(valor, str), ruta, "se esperaba una cadena con formato")
    valido = valor in patron if isinstance(patron, frozenset) else bool(patron.fullmatch(valor))
    _exigir(valido, ruta, "cadena fuera del formato permitido")


def _posicion(valor: Any, ruta: str) -> tuple[int, int]:
    _exigir(isinstance(valor, list) and len(valor) == 2, ruta, "se esperaba [i, f]")
    i, f = valor
    _exigir(_entero(i) and _entero(f), ruta, "las posiciones deben ser enteros")
    _exigir(0 <= i < f, ruta, "se requiere 0 <= i < f")
    return i, f


def validar_estructura(documento: Any) -> None:
    """Lista blanca (corre en CI): solo con los valores del archivo."""
    _claves(documento, CLAVES_RAIZ, "raiz")
    _exigir(_entero(documento["version"]) and documento["version"] == 1, "raiz.version", "debe ser 1")
    casos = documento["casos"]
    _exigir(isinstance(casos, dict), "raiz.casos", "se esperaba un objeto")
    for cid, caso in casos.items():
        _cadena(cid, ID_CASO, "raiz.casos.<clave>")
        ruta = f"casos.{cid}"
        _claves(caso, CLAVES_CASO, ruta)
        eventos = caso["eventos"]
        _exigir(isinstance(eventos, list) and len(eventos) <= MAX_EVENTOS, f"{ruta}.eventos", f"lista de 0 a {MAX_EVENTOS}")
        for clave in ("consultas", "instrucciones_rechazadas"):
            lista = caso[clave]
            _exigir(isinstance(lista, list), f"{ruta}.{clave}", "se esperaba una lista")
            for k, fragmento in enumerate(lista):
                rf = f"{ruta}.{clave}[{k}]"
                _claves(fragmento, CLAVES_FRAGMENTO, rf)
                _exigir(all(_entero(fragmento[c]) for c in CLAVES_FRAGMENTO), rf, "m, i y f deben ser enteros")
                _exigir(fragmento["m"] >= 0 and 0 <= fragmento["i"] < fragmento["f"], rf, "se requiere m >= 0 y 0 <= i < f")
        total = len(caso["consultas"]) + len(caso["instrucciones_rechazadas"])
        _exigir(total <= MAX_FRAGMENTOS_COMBINADOS, ruta, f"consultas + instrucciones_rechazadas > {MAX_FRAGMENTOS_COMBINADOS}")
        for n, evento in enumerate(eventos, start=1):
            re_ = f"{ruta}.eventos[{n - 1}]"
            _claves(evento, CLAVES_EVENTO, re_)
            _cadena(evento["id"], ID_EVENTO, f"{re_}.id")
            _exigir(evento["id"] == f"e{n}", f"{re_}.id", "los ids deben ser consecutivos")
            _cadena(evento["tipo"], TIPOS, f"{re_}.tipo")
            _cadena(evento["unidad"], UNIDADES, f"{re_}.unidad")
            _exigir(_entero(evento["m"]) and evento["m"] >= 0, f"{re_}.m", "entero >= 0")
            ti, tf = _posicion(evento["texto"], f"{re_}.texto")
            for campo in CAMPOS_POSICION:
                valor = evento[campo]
                if valor is None:
                    continue
                i, f = _posicion(valor, f"{re_}.{campo}")
                _exigir(ti <= i and f <= tf, f"{re_}.{campo}", "debe estar contenido en texto")
            candidatos = evento["candidatos"]
            _exigir(isinstance(candidatos, list) and len(candidatos) <= MAX_CANDIDATOS, f"{re_}.candidatos", "lista de SKU")
            for k, sku in enumerate(candidatos):
                _cadena(sku, SKU, f"{re_}.candidatos[{k}]")
            if evento["cantidad"] is not None:
                _cadena(evento["cantidad"], CANTIDAD, f"{re_}.cantidad")
            _exigir(isinstance(evento["cantidad_incierta"], bool), f"{re_}.cantidad_incierta", "se esperaba un booleano")
            if evento["ref"] is not None:
                _cadena(evento["ref"], ID_EVENTO, f"{re_}.ref")


def cargar(ruta: Path = RUTA) -> dict[str, Any]:
    documento = json.loads(ruta.read_text(encoding="utf-8"))
    validar_estructura(documento)
    return documento


def validar_contra_mensajes(caso: dict[str, Any], mensajes: list[str], ruta: str = "caso") -> None:
    """Con EVAL_DEV_PATH: cada posición cae dentro de su mensaje."""
    for n, evento in enumerate(caso["eventos"]):
        m = evento["m"]
        _exigir(m < len(mensajes), f"{ruta}.eventos[{n}].m", "mensaje inexistente")
        _exigir(evento["texto"][1] <= len(mensajes[m]), f"{ruta}.eventos[{n}].texto", "fuera del mensaje")
    for clave in ("consultas", "instrucciones_rechazadas"):
        for k, fragmento in enumerate(caso[clave]):
            _exigir(fragmento["m"] < len(mensajes), f"{ruta}.{clave}[{k}].m", "mensaje inexistente")
            _exigir(fragmento["f"] <= len(mensajes[fragmento["m"]]), f"{ruta}.{clave}[{k}]", "fuera del mensaje")


def reconstruir(caso: dict[str, Any], mensajes: list[str]) -> Interpretacion:
    """Arma la interpretación con los textos del caso publicado y la valida con el punto de
    entrada único (`validar_interpretacion`: esquema de E1b-1 y límite combinado de D72)."""
    validar_contra_mensajes(caso, mensajes)

    def texto(m: int, posicion: list[int] | None) -> str | None:
        return None if posicion is None else mensajes[m][posicion[0] : posicion[1]]

    eventos = []
    for evento in caso["eventos"]:
        m = evento["m"]
        eventos.append({
            "id": evento["id"], "mensaje": m, "tipo": evento["tipo"], "texto": texto(m, evento["texto"]),
            "producto": texto(m, evento["producto"]), "presentacion": texto(m, evento["presentacion"]),
            "unidad_texto": texto(m, evento["unidad_texto"]), "candidatos": list(evento["candidatos"]),
            "cantidad": evento["cantidad"], "cantidad_incierta": evento["cantidad_incierta"],
            "unidad": evento["unidad"], "ref": evento["ref"],
        })

    def fragmentos(lista: list[dict[str, int]]) -> list[dict[str, Any]]:
        return [{"mensaje": f["m"], "texto": mensajes[f["m"]][f["i"] : f["f"]]} for f in lista]

    datos = {
        "eventos": eventos,
        "consultas": fragmentos(caso["consultas"]),
        "instrucciones_rechazadas": fragmentos(caso["instrucciones_rechazadas"]),
    }
    return validar_interpretacion(datos, len(mensajes))
