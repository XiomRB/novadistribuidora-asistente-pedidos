"""Errores críticos K1-K5 y evaluación completa de un caso.

Unidades: K1 = SKU distinto por caso; K2 = como máximo 1 por producto esperado; K3 = producto
esperado sin emparejar (solo en casos críticos); K4 = ítem obtenido; K5 = caso. Informativos:
sobrantes (ítems libres que no son K1 ni K4) y mixtos (ítems emparejados que también representan a
un consultado).

- K2 compara la respuesta con lo esperado: en cada par emparejado, la cantidad de la línea y cada
  sustitución del producto (identificada por su SKU solicitado) frente a la esperada, o un pendiente
  esperado de `cantidad_no_convertible` resuelto como línea.
- K5 compara la respuesta consigo misma: respuesta 200 fuera del contrato, o valores que no
  coinciden al recalcularla con E1a (`cerrar_pedido`, con sus invariantes de sustituciones): estado,
  líneas, sustituciones, total, fecha y motivos se comparan explícitamente con el resultado de E1a.
- Los inválidos (HTTP distinto de 200, timeout, conexión, JSON inválido) son incorrectos, no K5.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.datos.modelos import Datos
from app.dominio.cierre import cerrar_pedido
from app.dominio.resultado import LineaSolicitada, Motivo, Pendiente, Sustitucion
from evaluacion import comparacion
from evaluacion.conjuntos import Anotacion, Caso
from evaluacion.correspondencia import Correspondencia, emparejar

CNC = "cantidad_no_convertible"


@dataclass(frozen=True)
class ResultadoCaso:
    """Solo identificadores, códigos fijos, nombres de campos, indicadores y recuentos."""

    id: str
    critico: bool
    valido: bool
    codigo: str  # OK | HTTP_<n> | TIMEOUT | CONEXION | JSON_INVALIDO | CONTRATO
    campos_distintos: tuple[str, ...] = ()
    k1: int = 0
    k2: int = 0
    k3: int = 0
    k4: int = 0
    k5: int = 0
    sobrantes: int = 0
    mixtos: int = 0
    clasificacion_coincide: bool | None = None
    texto_coincide: bool | None = None
    texto_provisional: bool = False

    @property
    def correcto(self) -> bool:
        return self.valido and not self.campos_distintos and not (self.k1 or self.k2 or self.k3 or self.k4 or self.k5)

    @property
    def critico_con_error(self) -> bool:
        return self.critico and bool(self.k1 or self.k2 or self.k3 or self.k4)


# ====================================================================== K5: recálculo con E1a


def recalculo_coincide(cuerpo: Mapping[str, Any], entrada: Mapping[str, Any], datos: Datos) -> bool:
    try:
        lineas = [LineaSolicitada(l["sku"], Decimal(str(l["cantidad"]))) for l in cuerpo["lineas"]]
        pendientes = [Pendiente(Motivo(p["motivo"]), p["texto"], tuple(p["opciones"])) for p in cuerpo["pendientes"]]
        sustituciones = [Sustitucion(s["sku_solicitado"], s["sku_entregado"], Decimal(str(s["cantidad"]))) for s in cuerpo["sustituciones"]]
        r = cerrar_pedido(
            cliente_id=entrada["cliente_id"], fecha_hora=datetime.fromisoformat(entrada["fecha_hora"]),
            lineas_solicitadas=lineas, pendientes=pendientes, sustituciones=sustituciones,
            hay_eventos_pedido=bool(lineas or pendientes or sustituciones), datos=datos,
        )
    except Exception:  # cualquier incoherencia que E1a rechace es K5 (nunca se guarda el mensaje)
        return False
    obtenido = comparacion.normalizar(cuerpo)
    recalculado = Counter((l.sku, l.cantidad, l.precio_unitario, l.descuento_pct, l.subtotal) for l in r.lineas)
    sustituciones_recalculadas = Counter((s.sku_solicitado, s.sku_entregado, s.cantidad) for s in r.sustituciones)
    return (
        cuerpo["cliente_id"] == entrada["cliente_id"]
        and obtenido.estado == r.estado.value
        and obtenido.lineas == recalculado
        and obtenido.sustituciones == sustituciones_recalculadas
        and obtenido.total == r.total
        and obtenido.fecha_entrega == (r.fecha_entrega.isoformat() if r.fecha_entrega else None)
        and obtenido.motivos_revision == Counter(m.value for m in r.motivos_revision)
    )


# ====================================================================== K1-K4


def _sustituciones_por_linea(cuerpo: Mapping[str, Any]) -> dict[str, Counter]:
    resultado: dict[str, Counter] = {}
    for s in cuerpo["sustituciones"]:
        resultado.setdefault(s["sku_entregado"], Counter())[s["sku_solicitado"]] += Decimal(str(s["cantidad"]))
    return resultado


def k2(corr: Correspondencia, cuerpo: Mapping[str, Any]) -> int:
    obtenidas = _sustituciones_por_linea(cuerpo)
    total = 0
    for i, j in enumerate(corr.asignacion):
        if j is None:
            continue
        e, o = corr.esperados[i], corr.obtenidos[j]
        if e.tipo == "L" and o.tipo == "L":
            distinta = o.cantidad != e.cantidad
            por_solicitado = obtenidas.get(o.sku, Counter())
            for solicitado, cantidad in (e.sustituciones or {}).items():
                if solicitado in por_solicitado and por_solicitado[solicitado] != cantidad:
                    distinta = True
            total += distinta  # como máximo 1 por producto esperado
        elif e.tipo == "P" and e.motivo == CNC and o.tipo == "L":
            total += 1
    return total


def k1_k4_sobrantes(corr: Correspondencia, cuerpo: Mapping[str, Any]) -> tuple[int, int, int, int]:
    esperados = frozenset().union(*(e.skus for e in corr.esperados)) if corr.esperados else frozenset()
    libres = corr.libres()
    k4_items = [j for j in libres if corr.representa_consultado[j]]
    skus_k4 = {corr.obtenidos[j].sku for j in k4_items if corr.obtenidos[j].tipo == "L"}
    candidatos = {l["sku"] for l in cuerpo["lineas"]}
    candidatos |= {s[c] for s in cuerpo["sustituciones"] for c in ("sku_solicitado", "sku_entregado")}
    k1_skus = {s for s in candidatos if s not in esperados and s not in skus_k4}
    k1_items = {j for j in libres if corr.obtenidos[j].tipo == "L" and corr.obtenidos[j].sku in k1_skus}
    sobrantes = len([j for j in libres if j not in k1_items and j not in k4_items])
    mixtos = sum(1 for j in corr.asignacion if j is not None and corr.representa_consultado[j])
    return len(k1_skus), len(k4_items), sobrantes, mixtos


# ====================================================================== evaluación de un caso


def evaluar_caso(caso: Caso, anotacion: Anotacion | None, codigo: str, cuerpo_normal: Any, cuerpo_decimal: Any, datos: Datos) -> ResultadoCaso:
    critico = anotacion.critico if anotacion else True
    provisional = anotacion.texto_provisional if anotacion else False
    if codigo != "OK":
        return ResultadoCaso(caso.id, critico, False, codigo, texto_provisional=provisional)
    if not comparacion.cumple_contrato(cuerpo_normal):
        return ResultadoCaso(caso.id, critico, False, "CONTRATO", k5=1, texto_provisional=provisional)
    k5 = 0 if recalculo_coincide(cuerpo_decimal, caso.entrada, datos) else 1
    obtenido, esperado = comparacion.normalizar(cuerpo_decimal), comparacion.normalizar(caso.esperado)
    corr = emparejar(caso.esperado, cuerpo_decimal, anotacion)
    k1, k4, sobrantes, mixtos = k1_k4_sobrantes(corr, cuerpo_decimal)
    k3 = sum(1 for j in corr.asignacion if j is None) if critico else 0
    return ResultadoCaso(
        caso.id, critico, True, "OK", comparacion.campos_distintos(obtenido, esperado),
        k1=k1, k2=k2(corr, cuerpo_decimal), k3=k3, k4=k4, k5=k5, sobrantes=sobrantes, mixtos=mixtos,
        clasificacion_coincide=comparacion.clasificacion_coincide(obtenido, esperado),
        texto_coincide=comparacion.textos_coinciden(obtenido, esperado), texto_provisional=provisional,
    )
