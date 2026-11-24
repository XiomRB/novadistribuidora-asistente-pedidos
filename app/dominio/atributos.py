"""Atributos de una descripción de producto (D48, D75, D76).

Dimensiones: grupo (sustantivo base), marcas, variantes (distintivos dentro del grupo) y
medidas. Todo se deriva del catálogo; no se inventa vocabulario.

- `combinar(a0, a1)`: la descripción posterior prevalece en cada dimensión que menciona; si
  cambia de grupo, se toma completa (D48).
- `comparar(a, sku)`: cuántos atributos explícitos coinciden positivamente y si alguno
  contradice al producto. Compatible (D76) = al menos una coincidencia y ninguna
  contradicción; la falta de información nunca cuenta como coincidencia.
- Los números sin unidad solo cuentan si no hay medidas explícitas, y nunca contradicen
  (pueden ser cantidades; misma tolerancia que el resolvedor de E1b-1).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.datos.modelos import Datos
from app.dominio.catalogo import IndiceCatalogo
from app.dominio.texto import Medida, extraer_medidas, peso_coincidencia, tokens

PESO_FUERTE = 8  # idéntico, singular o diminutivo (detección del grupo)
PESO_EXACTO = 9  # idéntico o singular (marcas y variantes: evita "naranja" ~ marca "Naranjita")


@dataclass(frozen=True)
class Atributos:
    grupo: str | None = None
    marcas: frozenset[str] = frozenset()
    variantes: frozenset[str] = frozenset()
    medidas: frozenset[Medida] = frozenset()

    @property
    def vacio(self) -> bool:
        return self.grupo is None and not self.marcas and not self.variantes and not self.medidas

    @property
    def medidas_explicitas(self) -> frozenset[Medida]:
        return frozenset(m for m in self.medidas if m.unidad is not None)


@dataclass(frozen=True)
class Comparacion:
    positivos: int
    contradiccion: bool

    @property
    def compatible(self) -> bool:
        return self.positivos > 0 and not self.contradiccion


def _parecido(a: str, b: str) -> bool:
    return peso_coincidencia(a, b) >= PESO_EXACTO


class VocabularioAtributos:
    """Vocabulario de marcas y variantes derivado del catálogo."""

    def __init__(self, datos: Datos, indice: IndiceCatalogo):
        self.datos = datos
        self.indice = indice
        self.marcas_por_sku = {sku: frozenset(tokens(p.marca)) for sku, p in datos.productos.items()}
        self.marcas = frozenset().union(*self.marcas_por_sku.values()) if self.marcas_por_sku else frozenset()
        variantes: set[str] = set()
        for grupo, skus in indice.por_grupo.items():
            conjuntos = [set(indice.entradas[s].tokens) - self.marcas_por_sku[s] for s in skus]
            comunes = set.intersection(*conjuntos) if conjuntos else set()
            for conjunto in conjuntos:
                variantes |= {t for t in conjunto - comunes if peso_coincidencia(t, grupo) < PESO_FUERTE}
        self.variantes = frozenset(variantes - self.marcas)

    # ------------------------------------------------------------ extracción

    def extraer(self, descripcion: str) -> Atributos:
        if not descripcion or not descripcion.strip():
            return Atributos()
        lista = tokens(descripcion)
        grupo = None
        for token in lista:
            grupo = next((g for g in self.indice.por_grupo if peso_coincidencia(token, g) >= PESO_FUERTE), None)
            if grupo is not None:
                break
        marcas = frozenset(m for t in lista for m in self.marcas if _parecido(t, m))
        variantes = frozenset(
            v for t in lista for v in self.variantes if _parecido(t, v) and not (grupo and peso_coincidencia(t, grupo) >= PESO_FUERTE)
        )
        return Atributos(grupo, marcas, variantes, extraer_medidas(descripcion, self.indice.palabras_cantidad))

    def del_producto(self, sku: str) -> Atributos:
        producto = self.datos.productos[sku]
        return self.extraer(f"{producto.nombre} {producto.presentacion}")

    # ------------------------------------------------------------ comparación

    def comparar(self, atributos: Atributos, sku: str) -> Comparacion:
        entrada = self.indice.entradas[sku]
        positivos, contradiccion = 0, False
        if atributos.grupo is not None:
            if atributos.grupo == entrada.grupo:
                positivos += 1
            else:
                contradiccion = True
        if atributos.marcas:
            if any(_parecido(m, p) for m in atributos.marcas for p in self.marcas_por_sku[sku]):
                positivos += 1
            else:
                contradiccion = True
        for variante in atributos.variantes:
            if any(_parecido(variante, t) for t in entrada.tokens):
                positivos += 1
            else:
                contradiccion = True
        explicitas = atributos.medidas_explicitas
        if explicitas:
            if self.indice.compatible_con_medidas(sku, explicitas):
                positivos += 1
            else:
                contradiccion = True
        elif atributos.medidas and self.indice.compatible_con_medidas(sku, atributos.medidas):
            positivos += 1  # número sin unidad: suma si coincide, nunca contradice
        return Comparacion(positivos, contradiccion)

    def cumple(self, atributos: Atributos, sku: str) -> bool:
        """El producto no contradice ningún atributo explícito (D48: información compatible)."""
        return not self.comparar(atributos, sku).contradiccion


def combinar(anterior: Atributos, nuevo: Atributos) -> Atributos:
    """D48: la descripción posterior prevalece por dimensión; un cambio de grupo la toma completa."""
    if nuevo.grupo is not None and anterior.grupo is not None and nuevo.grupo != anterior.grupo:
        return nuevo
    return Atributos(
        grupo=nuevo.grupo or anterior.grupo,
        marcas=nuevo.marcas or anterior.marcas,
        variantes=nuevo.variantes or anterior.variantes,
        medidas=nuevo.medidas or anterior.medidas,
    )


def a_descripcion(atributos: Atributos) -> str:
    """Descripción sintética para el resolvedor (p. ej. 'kola norte 1500ml')."""
    partes = [atributos.grupo] if atributos.grupo else []
    partes += sorted(atributos.marcas) + sorted(atributos.variantes)
    for medida in sorted(atributos.medidas, key=lambda m: (m.unidad or "", m.valor)):
        partes.append(f"{medida.valor.normalize():f}{medida.unidad or ''}")
    return " ".join(partes)
