"""Utilidades sintéticas para las pruebas del evaluador (E2c-1). Sin datos reales ni privados."""

from __future__ import annotations

import hashlib
import itertools
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from evaluacion.conjuntos import Anotacion, Consultado, Descriptor, palabras
from evaluacion.correspondencia import Correspondencia, emparejar, items_obtenidos, par, productos_esperados, representa_consultado
from evaluacion.criticos import k1_k4_sobrantes, k2

NE, AM, CN, AG = "producto_no_existe", "producto_ambiguo", "cantidad_no_convertible", "agotado_sin_sustituto"


def L(sku: str, cantidad: int = 1, precio: str = "10.00", descuento: int = 0, subtotal: str | None = None) -> dict:
    sub = subtotal if subtotal is not None else str(Decimal(precio) * cantidad)
    return {"sku": sku, "cantidad": Decimal(cantidad), "precio_unitario": Decimal(precio), "descuento_pct": Decimal(descuento), "subtotal": Decimal(sub)}


def P(*opciones: str, motivo: str = AM, texto: str = "zqx") -> dict:
    return {"motivo": motivo, "texto": texto, "opciones": list(opciones)}


def S(solicitado: str, entregado: str, cantidad: int) -> dict:
    return {"sku_solicitado": solicitado, "sku_entregado": entregado, "cantidad": Decimal(cantidad)}


def esperado(lineas=(), pendientes=(), sustituciones=(), estado="requiere_revision", total=None, fecha=None, motivos=None) -> dict:
    lineas = list(lineas)
    tot = total if total is not None else sum((l["subtotal"] for l in lineas), Decimal(0))
    return {
        "estado": estado, "lineas": lineas, "total": Decimal(tot), "fecha_entrega": fecha,
        "sustituciones": list(sustituciones), "pendientes": list(pendientes),
        "motivos_revision": list(motivos) if motivos is not None else sorted({p["motivo"] for p in pendientes}),
    }


def cuerpo(esp: dict, cliente: str = "K04", mensaje: str = "Gracias") -> dict:
    """Respuesta con los números como `Decimal` (como la lee el comparador)."""
    return {"cliente_id": cliente, **esp, "mensaje_cliente": mensaje}


def a_json(dato: Any) -> str:
    def codificar(x):
        if isinstance(x, Decimal):
            return int(x) if x == x.to_integral_value() and "." not in str(x) else float(x)
        raise TypeError
    return json.dumps(dato, default=codificar, ensure_ascii=False)


def anot(*claves_por_producto, consultados=(), provisional=False, critico=True) -> Anotacion:
    """`anot(["zqx kiwi"], ["gaseosa sol", "gaseosas sol"], consultados=[co(...)])`."""
    claves = tuple(tuple(palabras(c) for c in grupo) for grupo in claves_por_producto)
    return Anotacion(claves, tuple(consultados), provisional, critico)


def co(*skus: str, claves=(), pedido_como=None) -> Consultado:
    return Consultado(frozenset(skus), tuple(palabras(c) for c in claves), pedido_como)


def medir(esp: dict, cue: dict, anotacion: Anotacion | None) -> tuple[dict, tuple]:
    corr = emparejar(esp, cue, anotacion)
    k1, k4, sobrantes, mixtos = k1_k4_sobrantes(corr, cue)
    critico = anotacion.critico if anotacion else True
    k3 = sum(1 for j in corr.asignacion if j is None) if critico else 0
    return {"K1": k1, "K2": k2(corr, cue), "K3": k3, "K4": k4, "sobrantes": sobrantes, "mixtos": mixtos}, corr.trazabilidad()


def exhaustiva(esp: dict, cue: dict, anotacion: Anotacion | None) -> tuple:
    """Referencia independiente de Kuhn-Munkres: prueba todas las asignaciones y aplica el orden
    lexicográfico (emparejados, tipo, pureza, ítems con consulta emparejados, vector de posiciones)."""
    esperados = productos_esperados(esp, anotacion)
    obtenidos, rangos = items_obtenidos(cue)
    consultados = [c for c in (anotacion.consultados if anotacion else ()) if c.pedido_como is None]
    cons = [representa_consultado(o, esperados, consultados) for o in obtenidos]
    n, m = len(esperados), len(obtenidos)
    optimo = None
    for asig in itertools.product(*[[None] + list(range(m)) for _ in range(n)]):
        usados = [j for j in asig if j is not None]
        if len(usados) != len(set(usados)):
            continue
        pares = [None if j is None else par(i, obtenidos[j], esperados, consultados) for i, j in enumerate(asig)]
        if any(j is not None and q is None for j, q in zip(asig, pares)):
            continue
        clave = (len(usados), sum(q[0] for q in pares if q), sum(q[1] for q in pares if q), sum(cons[j] for j in usados), tuple(-(m if j is None else j) for j in asig))
        if optimo is None or clave > optimo[0]:
            optimo = (clave, asig)
    asig = optimo[1] if optimo else ()
    return Correspondencia(esperados, obtenidos, rangos, tuple(asig), tuple(cons)).trazabilidad()


# ---------------------------------------------------------------- conjuntos en archivos temporales


def escribir_conjunto(directorio: Path, casos: list[dict], anotaciones: dict, esperadas: dict | None = None, rol: str = "validacion_publica", **descriptor) -> tuple[Descriptor, dict[str, Path]]:
    directorio.mkdir(parents=True, exist_ok=True)
    rutas = {"casos": directorio / "casos.jsonl", "anotaciones": directorio / "anotaciones.json"}
    rutas["casos"].write_text("".join(a_json(c) + "\n" for c in casos), encoding="utf-8")
    rutas["anotaciones"].write_text(json.dumps({"version": "sintetica", "casos": anotaciones}, ensure_ascii=False), encoding="utf-8")
    if esperadas is not None:
        rutas["esperadas"] = directorio / "esperadas.json"
        rutas["esperadas"].write_text(a_json(esperadas), encoding="utf-8")
    sha = {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in rutas.items()}
    n_mensajes = sum(len(c["entrada"]["mensajes"]) for c in casos)
    d = Descriptor(id=descriptor.pop("id", "sintetico"), rol=rol, sha256=sha, n_casos=len(casos), n_mensajes=n_mensajes, **descriptor)
    return d, rutas


def caso(id_: str, mensajes: list[str], esp: dict, cliente: str = "K04", fecha_hora: str = "2026-12-01T10:00") -> dict:
    return {"id": id_, "tipo": "sintetico", "entrada": {"cliente_id": cliente, "fecha_hora": fecha_hora, "mensajes": mensajes}, "esperado": esp}


def anotacion_json(productos: list[list[list[str]]], consultados=(), **otros) -> dict:
    return {"productos": [{"claves": c} for c in productos], "consultados": list(consultados), **otros}
