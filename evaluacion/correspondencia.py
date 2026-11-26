"""Correspondencia determinista entre productos esperados y los ítems de la respuesta (K1-K4).

- Productos esperados E: líneas (con su sustitución) y después pendientes; índices desde 0.
- Ítems obtenidos O, en orden canónico (clave JSON del contenido; rango para los idénticos):
  así cualquier permutación de la respuesta da la misma asignación.
- Un ítem representa a un producto por SKU (línea, o pendiente con opciones) o, solo si es un
  pendiente sin opciones, por clave: subsecuencia contigua de palabras completas del texto
  normalizado. Pureza: por SKU, todos los SKU del ítem dentro de `skus(e)`; por clave, el texto no
  contiene claves de ningún otro producto anotado del caso.
- Prioridades lexicográficas estrictas: (1) productos emparejados, (2) coincidencias de tipo,
  (3) pureza, (4) menor K4, (5) desempate por el vector de posiciones canónicas.
- Kuhn-Munkres en una matriz N x N (N = n + m) con nodos ficticios y pesos enteros. Bases:
  B_k = 1 + Σ_{l>k} n·M_l·B_l + T_max (M_l = 1) y BIG = 1 + Σ_l n·M_l·B_l + T_max, de modo que
  cada nivel domina estrictamente a todos los inferiores y BIG excluye los pares incompatibles.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from evaluacion.conjuntos import Anotacion, contiene, palabras, skus_esperados


@dataclass(frozen=True)
class Esperado:
    tipo: str  # "L" | "P"
    skus: frozenset[str]
    claves: tuple[tuple[str, ...], ...]
    cantidad: Decimal | None = None  # líneas
    sustituciones: Mapping[str, Decimal] | None = None  # sku_solicitado -> cantidad (líneas)
    motivo: str | None = None  # pendientes


@dataclass(frozen=True)
class Obtenido:
    tipo: str  # "L" | "P"
    sku: str | None = None
    cantidad: Decimal | None = None
    opciones: tuple[str, ...] = ()
    motivo: str | None = None
    texto: tuple[str, ...] = ()

    def clave(self) -> str:
        cantidad = None if self.cantidad is None else f"{self.cantidad.normalize():f}"
        return json.dumps([self.tipo, self.sku, cantidad, list(self.opciones), self.motivo, list(self.texto)], ensure_ascii=False)

    def skus(self) -> frozenset[str]:
        return frozenset({self.sku}) if self.tipo == "L" else frozenset(self.opciones)


@dataclass(frozen=True)
class Correspondencia:
    esperados: tuple[Esperado, ...]
    obtenidos: tuple[Obtenido, ...]  # orden canónico
    rangos: tuple[int, ...]  # rango entre ítems idénticos (solo para la trazabilidad interna)
    asignacion: tuple[int | None, ...]  # por producto esperado: índice canónico o None
    representa_consultado: tuple[bool, ...]  # por ítem: representa a un solo consultado

    def libres(self) -> tuple[int, ...]:
        usados = {j for j in self.asignacion if j is not None}
        return tuple(j for j in range(len(self.obtenidos)) if j not in usados)

    def trazabilidad(self) -> tuple[tuple[int, str, int] | tuple[int, None], ...]:
        return tuple((i, None) if j is None else (i, self.obtenidos[j].clave(), self.rangos[j]) for i, j in enumerate(self.asignacion))


# ====================================================================== construcción


def productos_esperados(esperado: Mapping[str, Any], anotacion: Anotacion | None) -> tuple[Esperado, ...]:
    skus = skus_esperados(esperado)
    claves = anotacion.claves if anotacion else tuple(() for _ in skus)
    resultado = []
    for i, linea in enumerate(esperado["lineas"]):
        sustituciones = {s["sku_solicitado"]: s["cantidad"] for s in esperado["sustituciones"] if s["sku_entregado"] == linea["sku"]}
        resultado.append(Esperado("L", skus[i], claves[i], linea["cantidad"], sustituciones))
    base = len(esperado["lineas"])
    for k, p in enumerate(esperado["pendientes"]):
        resultado.append(Esperado("P", skus[base + k], claves[base + k], motivo=p["motivo"]))
    return tuple(resultado)


def items_obtenidos(cuerpo: Mapping[str, Any]) -> tuple[tuple[Obtenido, ...], tuple[int, ...]]:
    items = [Obtenido("L", sku=l["sku"], cantidad=Decimal(str(l["cantidad"]))) for l in cuerpo["lineas"]]
    items += [Obtenido("P", opciones=tuple(sorted(p["opciones"])), motivo=p["motivo"], texto=palabras(p["texto"])) for p in cuerpo["pendientes"]]
    items.sort(key=Obtenido.clave)
    rangos, vistos = [], {}
    for o in items:
        rangos.append(vistos.get(o.clave(), 0))
        vistos[o.clave()] = rangos[-1] + 1
    return tuple(items), tuple(rangos)


# ====================================================================== representación y pureza


def _por_clave(o: Obtenido, esperados: Sequence[Esperado], consultados: Sequence[Any]) -> set[tuple[str, int]]:
    k = {("e", i) for i, e in enumerate(esperados) if any(contiene(o.texto, c) for c in e.claves)}
    return k | {("c", j) for j, c in enumerate(consultados) if any(contiene(o.texto, cl) for cl in c.claves)}


def par(i: int, o: Obtenido, esperados: Sequence[Esperado], consultados: Sequence[Any]) -> tuple[int, int] | None:
    """(coincidencia de tipo, pureza) si `o` representa al producto i; None si no lo representa."""
    e = esperados[i]
    tipo = 1 if o.tipo == e.tipo else 0
    if o.tipo == "L" or o.opciones:
        if not (o.skus() & e.skus):
            return None
        return tipo, 1 if o.skus() <= e.skus else 0
    k = _por_clave(o, esperados, consultados)
    if ("e", i) not in k:
        return None
    return tipo, 1 if k == {("e", i)} else 0


def representa_consultado(o: Obtenido, esperados: Sequence[Esperado], consultados: Sequence[Any]) -> bool:
    if o.tipo == "L" or o.opciones:
        return any(o.skus() & c.skus for c in consultados)
    return any(tipo == "c" for tipo, _ in _por_clave(o, esperados, consultados))


# ====================================================================== asignación


def bases(n: int, m: int, maximos: Sequence[int] = (1, 1, 1, 1)) -> tuple[list[int], int, int]:
    """Bases B_1..B_4 (de mayor a menor prioridad), BIG y T_max, solo con enteros."""
    t_max = (m + 1) ** n - 1
    b = [0] * len(maximos)
    acumulado = t_max
    for k in reversed(range(len(maximos))):
        b[k] = 1 + acumulado
        acumulado += n * maximos[k] * b[k]
    return b, 1 + acumulado, t_max


def _hungaro_maximo(pesos: list[list[int]]) -> list[int]:
    """Kuhn-Munkres O(N^3) para el peso máximo en una matriz cuadrada de enteros: columna de cada fila."""
    n = len(pesos)
    tope = max(max(f) for f in pesos)
    costo = [[tope - w for w in fila] for fila in pesos]
    u, v, p, camino = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minimo: list[int | None] = [None] * (n + 1)
        usado = [False] * (n + 1)
        while True:
            usado[j0] = True
            i0, delta, j1 = p[j0], None, 0
            for j in range(1, n + 1):
                if not usado[j]:
                    actual = costo[i0 - 1][j - 1] - u[i0] - v[j]
                    if minimo[j] is None or actual < minimo[j]:
                        minimo[j], camino[j] = actual, j0
                    if delta is None or minimo[j] < delta:
                        delta, j1 = minimo[j], j
            for j in range(n + 1):
                if usado[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimo[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = camino[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    fila = [0] * n
    for j in range(1, n + 1):
        if p[j]:
            fila[p[j] - 1] = j - 1
    return fila


def emparejar(esperado: Mapping[str, Any], cuerpo: Mapping[str, Any], anotacion: Anotacion | None) -> Correspondencia:
    esperados = productos_esperados(esperado, anotacion)
    obtenidos, rangos = items_obtenidos(cuerpo)
    consultados = [c for c in (anotacion.consultados if anotacion else ()) if c.pedido_como is None]
    cons = tuple(representa_consultado(o, esperados, consultados) for o in obtenidos)
    n, m = len(esperados), len(obtenidos)
    if n == 0 or m == 0:
        return Correspondencia(esperados, obtenidos, rangos, tuple(None for _ in esperados), cons)
    (b1, b2, b3, b4), big, _ = bases(n, m)
    total = n + m
    pesos = [[0] * total for _ in range(total)]
    for i in range(total):
        for j in range(total):
            if i < n and j < m:  # producto real con ítem real
                q = par(i, obtenidos[j], esperados, consultados)
                pesos[i][j] = -big if q is None else b1 + q[0] * b2 + q[1] * b3 + cons[j] * b4 + (m - j) * (m + 1) ** (n - 1 - i)
            elif i < n:  # producto con su columna ficticia: queda sin pareja
                pesos[i][j] = 0 if j == m + i else -big
            elif j < m:  # fila ficticia con su ítem: el ítem queda libre
                pesos[i][j] = 0 if i == n + j else -big
    fila = _hungaro_maximo(pesos)
    asignacion = tuple(fila[i] if fila[i] < m else None for i in range(n))
    return Correspondencia(esperados, obtenidos, rangos, asignacion, cons)
