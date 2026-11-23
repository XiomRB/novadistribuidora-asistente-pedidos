"""Índice del catálogo y resolución de productos.

La existencia de un SKU propuesto por el LLM nunca basta: el código exige evidencia textual
(tokens del nombre, marca o alias) y descarta lo que el texto contradice (presentación).

Algoritmo de `resolver`:
1. Medidas y tokens de la mención (producto + presentación).
2. Puntaje por producto: coincidencias de tokens (10 idéntico, 9 en singular, 8 sin
   diminutivo, 7 parecido) más bonificación por alias completo.
3. Universo = productos con puntaje, candidatos válidos del LLM y todos sus hermanos (grupo).
4. Filtro por medida: se descarta lo que contradice la presentación mencionada.
   - Cada medida con unidad explícita es obligatoria: todas deben coincidir.
   - Los números sin unidad (pueden ser cantidades: "2 de aceite dorado") solo filtran si no
     hay medidas explícitas y si al menos un candidato del universo coincide con alguno; si
     ninguno coincide, se ignoran como filtro (código NUMERO_IGNORADO). Esta tolerancia nunca
     anula una contradicción de medidas explícitas.
5. Sin evidencia textual (solo candidatos del LLM): ambiguo con el universo (D45).
6. Sin sobrevivientes: no existe. Un único máximo: resuelto. Empate: ambiguo.
7. Resuelto y agotado sin sustituto disponible: pendiente de agotado (D38).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.datos.modelos import Datos, Producto
from app.dominio.texto import Medida, extraer_medidas, peso_coincidencia, singular, tokens

BONO_ALIAS = 5


class TipoResolucion(StrEnum):
    RESUELTO = "resuelto"
    AMBIGUO = "ambiguo"
    NO_EXISTE = "no_existe"
    AGOTADO_SIN_SUSTITUTO = "agotado_sin_sustituto"


@dataclass(frozen=True)
class Resolucion:
    tipo: TipoResolucion
    sku: str | None = None
    opciones: tuple[str, ...] = ()
    codigos: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntradaIndice:
    sku: str
    orden: int
    grupo: str
    tokens: frozenset[str]
    medidas: frozenset[Medida]
    alias: tuple[tuple[tuple[str, ...], frozenset[Medida]], ...]


def _grupo(producto: Producto) -> str:
    nombre = tokens(producto.nombre)
    marca = set(tokens(producto.marca))
    prefijo: list[str] = []
    for token in nombre:
        if token in marca:
            break
        prefijo.append(token)
    base = prefijo or tokens(producto.marca) or nombre or [producto.sku.lower()]
    return singular(base[0])


class IndiceCatalogo:
    def __init__(self, datos: Datos, palabras_cantidad: frozenset[str] = frozenset()):
        self.datos = datos
        self.palabras_cantidad = palabras_cantidad
        alias_por_sku: dict[str, list[tuple[tuple[str, ...], frozenset[Medida]]]] = {}
        for alias in datos.alias:
            alias_por_sku.setdefault(alias.sku, []).append(
                (tuple(tokens(alias.alias)), extraer_medidas(alias.alias, palabras_cantidad))
            )
        self.entradas: dict[str, EntradaIndice] = {}
        for orden, producto in enumerate(datos.productos.values()):
            lista_alias = tuple(alias_por_sku.get(producto.sku, ()))
            todos = set(tokens(producto.nombre)) | set(tokens(producto.marca))
            for alias_tokens, _ in lista_alias:
                todos |= set(alias_tokens)
            self.entradas[producto.sku] = EntradaIndice(
                sku=producto.sku,
                orden=orden,
                grupo=_grupo(producto),
                tokens=frozenset(todos),
                medidas=extraer_medidas(producto.presentacion) | extraer_medidas(producto.nombre),
                alias=lista_alias,
            )
        self.por_grupo: dict[str, tuple[str, ...]] = {}
        for entrada in self.entradas.values():
            self.por_grupo.setdefault(entrada.grupo, ())
            self.por_grupo[entrada.grupo] += (entrada.sku,)

    # ------------------------------------------------------------ consultas del índice

    def hermanos(self, sku: str) -> tuple[str, ...]:
        return self.por_grupo[self.entradas[sku].grupo]

    def grupo(self, sku: str) -> str:
        return self.entradas[sku].grupo

    def _ordenar(self, skus) -> tuple[str, ...]:
        return tuple(sorted(set(skus), key=lambda s: self.entradas[s].orden))

    def compatible_con_medidas(self, sku: str, medidas: frozenset[Medida]) -> bool:
        """Cada medida con unidad explícita es una restricción: todas deben coincidir.

        Si no hay medidas explícitas, basta con que coincida uno de los números sin unidad.
        La tolerancia a números que son cantidades ("2 de aceite dorado") se aplica en
        `resolver`, sobre el universo de candidatos.
        """
        if not medidas:
            return True
        propias = self.entradas[sku].medidas
        explicitas = [m for m in medidas if m.unidad is not None]
        if explicitas:
            return all(any(m.coincide(p) for p in propias) for m in explicitas)
        return any(m.coincide(p) for m in medidas for p in propias)

    def _puntaje(self, sku: str, tokens_mencion: list[str], medidas: frozenset[Medida]) -> int:
        entrada = self.entradas[sku]
        puntaje = sum(max((peso_coincidencia(t, p) for p in entrada.tokens), default=0) for t in tokens_mencion)
        for alias_tokens, alias_medidas in entrada.alias:
            if not alias_tokens:
                continue
            todos = all(any(peso_coincidencia(t, a) for t in tokens_mencion) for a in alias_tokens)
            medidas_ok = all(any(m.coincide(a) or a.coincide(m) for m in medidas) for a in alias_medidas)
            if todos and medidas_ok:
                puntaje += BONO_ALIAS
                break
        return puntaje

    # ------------------------------------------------------------ resolución

    def resolver(self, descripcion: str, candidatos_llm: Sequence[str] = ()) -> Resolucion:
        codigos: list[str] = []
        validos = [s for s in candidatos_llm if s in self.entradas]
        if len(validos) != len(candidatos_llm):
            codigos.append("SKU_LLM_INEXISTENTE")
        medidas = extraer_medidas(descripcion, self.palabras_cantidad)
        tokens_mencion = tokens(descripcion)

        puntajes = {s: self._puntaje(s, tokens_mencion, medidas) for s in self.entradas} if tokens_mencion else {}
        con_evidencia = {s for s, p in puntajes.items() if p > 0}
        universo: set[str] = set()
        for sku in con_evidencia | set(validos):
            universo.update(self.hermanos(sku))
        if not universo:
            return Resolucion(TipoResolucion.NO_EXISTE, codigos=tuple(codigos + ["SIN_COINCIDENCIAS"]))

        explicitas = frozenset(m for m in medidas if m.unidad is not None)
        sin_unidad = medidas - explicitas
        if explicitas:
            filtrado = {s for s in universo if self.compatible_con_medidas(s, explicitas)}
        else:
            filtrado = set(universo)
            if sin_unidad:
                coinciden = {s for s in universo if self.compatible_con_medidas(s, sin_unidad)}
                if coinciden:
                    filtrado = coinciden
                else:
                    codigos.append("NUMERO_IGNORADO")
        if not con_evidencia & universo:
            # D45: solo hay candidatos del LLM; nunca se acepta un SKU sin evidencia textual.
            opciones = self._ordenar(filtrado or universo)
            return Resolucion(TipoResolucion.AMBIGUO, opciones=opciones, codigos=tuple(codigos + ["SIN_EVIDENCIA_TEXTUAL"]))
        if not filtrado:
            return Resolucion(TipoResolucion.NO_EXISTE, codigos=tuple(codigos + ["MEDIDA_SIN_PRODUCTO"]))

        maximo = max(puntajes.get(s, 0) for s in filtrado)
        if maximo == 0:
            return Resolucion(TipoResolucion.AMBIGUO, opciones=self._ordenar(filtrado), codigos=tuple(codigos))
        mejores = self._ordenar(s for s in filtrado if puntajes.get(s, 0) == maximo)
        if len(mejores) > 1:
            return Resolucion(TipoResolucion.AMBIGUO, opciones=mejores, codigos=tuple(codigos))

        sku = mejores[0]
        if validos and sku not in validos:
            codigos.append("CONTRADICCION_LLM")
        producto = self.datos.productos[sku]
        if not producto.disponible:
            sustituto = self.datos.productos.get(producto.sustituto_sku) if producto.sustituto_sku else None
            if sustituto is None or not sustituto.disponible:
                return Resolucion(
                    TipoResolucion.AGOTADO_SIN_SUSTITUTO, sku=sku, opciones=(sku,), codigos=tuple(codigos)
                )
            codigos.append("AGOTADO_CON_SUSTITUTO")
        return Resolucion(TipoResolucion.RESUELTO, sku=sku, opciones=(sku,), codigos=tuple(codigos))
