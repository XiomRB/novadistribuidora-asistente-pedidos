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

D92 (R-E3-09), antes de lo anterior. Cada token significativo de la mención (sin palabras de
unidad) se clasifica con la misma tolerancia a errores leves (peso >= 7) como:
- ancla: sustantivo de un grupo, token de marca o primer token de un nombre o alias;
- conocido: cualquier otro token del catálogo (p. ej. "polvo", del nombre Leche en Polvo);
- desconocido: no se parece a ningún token del catálogo ("levadura", "lala").
Los candidatos del LLM nunca son evidencia textual. Reglas, en este orden de precedencia:
- R1-a: sin ancla y con algún token conocido -> NO_EXISTE, con o sin candidatos del LLM. Prevalece
  sobre R1-b: un token conocido sin ancla indica otro producto ("levadura en polvo").
- R1-b (D45, sin cambios): sin ancla, sin tokens conocidos (jerga pura: "cocas", "chescos") ->
  resolución original: ambiguo con los hermanos de los candidatos o NO_EXISTE sin candidatos (R1-c).
- R2: ancla y algún token desconocido (marca o variante que no vendemos) -> AMBIGUO sin opciones.
  Excepciones: se conserva el NO_EXISTE cuando se debe a medidas explícitas contradictorias
  (código MEDIDA_SIN_PRODUCTO) o, desde D93, a la dimensión de la cantidad total
  (DIMENSION_CANTIDAD_INCOMPATIBLE). Cualquier otro NO_EXISTE (p. ej. SIN_COINCIDENCIAS) queda
  como AMBIGUO sin opciones.
- En todos los casos, una mención sin ancla nunca produce una línea (resuelto o agotado).

D93 (dimensión de la cantidad total), entre la resolución por texto y las reglas de D92. Solo con
`dimensiones` (las que el plegado demostró para la cantidad total: "volumen" o "masa"):
- La dimensión de un producto sale de las medidas de su presentación (ml -> volumen; g, lb -> masa);
  sin una sola dimensión (rollos, paquetes, sobres) nunca se descarta.
- Se descartan las opciones cuya dimensión no coincide con todas las dimensiones de la cantidad.
  Ninguna compatible -> NO_EXISTE (código interno DIMENSION_CANTIDAD_INCOMPATIBLE). Algunas -> se
  conservan solo esas, sin confirmar nunca un producto (si había varias, sigue ambiguo).
- Solo se compara la dimensión, nunca el valor: el valor lo decide la conversión de siempre.
- R2 conserva ese NO_EXISTE igual que el de MEDIDA_SIN_PRODUCTO.
- Sin `dimensiones`, `resolver` se comporta exactamente como antes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.datos.modelos import Datos, Producto
from app.datos.normalizacion import normalizar_texto
from app.dominio.texto import Medida, extraer_medidas, peso_coincidencia, singular, tokens, variantes
from app.dominio.unidades import DOCENAS, SUELTAS

BONO_ALIAS = 5
PESO_EVIDENCIA = 7  # D92: la misma tolerancia a errores leves que el resto de la resolución
# Palabras de unidad que nunca cuentan como evidencia de producto. Esta constante contiene solo
# las fijas del léxico de unidades de E1b-1 (`SUELTAS` y `DOCENAS`); `IndiceCatalogo.__init__`
# les agrega `palabras_cantidad` (si se recibe) y las unidades de venta del catálogo cargado.
_UNIDADES_BASE = frozenset(SUELTAS) | DOCENAS


# D93: dimensión física de cada unidad base de `extraer_medidas`.
DIMENSION_DE_UNIDAD = {"ml": "volumen", "g": "masa", "lb": "masa"}
CODIGO_DIMENSION = "DIMENSION_CANTIDAD_INCOMPATIBLE"
_CONSERVAN_NO_EXISTE = frozenset({"MEDIDA_SIN_PRODUCTO", CODIGO_DIMENSION})  # excepciones de R2


class Evidencia(StrEnum):
    """Clase de evidencia textual de una mención (D92)."""

    NORMAL = "normal"
    SIN_ANCLA_CON_CONOCIDO = "sin_ancla_con_conocido"  # R1-a
    JERGA = "jerga"  # R1-b / R1-c
    TOKEN_DESCONOCIDO = "token_desconocido"  # R2


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
        # D92: anclas, vocabulario y palabras de unidad, derivados de los datos.
        anclas: set[str] = set(self.por_grupo)
        vocabulario: set[str] = set()
        for sku, entrada in self.entradas.items():
            producto = datos.productos[sku]
            vocabulario |= set(entrada.tokens)
            anclas |= set(tokens(producto.marca))
            nombre = tokens(producto.nombre)
            if nombre:
                anclas.add(nombre[0])
            for alias_tokens, _ in entrada.alias:
                if alias_tokens:
                    anclas.add(alias_tokens[0])
        self.anclas = frozenset(anclas)
        self.vocabulario = frozenset(vocabulario | anclas)
        unidades = set(_UNIDADES_BASE) | set(palabras_cantidad)
        unidades |= {normalizar_texto(p.unidad_venta) for p in datos.productos.values()}
        self.unidades = frozenset(unidades)
        # D93: dimensión de cada producto según su presentación (None si no hay una sola).
        self.dimension: dict[str, str | None] = {}
        for sku, producto in datos.productos.items():
            dimensiones = {DIMENSION_DE_UNIDAD[m.unidad] for m in extraer_medidas(producto.presentacion) if m.unidad in DIMENSION_DE_UNIDAD}
            self.dimension[sku] = next(iter(dimensiones)) if len(dimensiones) == 1 else None

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

    # ------------------------------------------------------------ evidencia (D92)

    def _parece(self, token: str, conjunto: frozenset[str]) -> bool:
        return any(peso_coincidencia(token, v) >= PESO_EVIDENCIA for v in conjunto)

    def evidencia(self, descripcion: str) -> Evidencia:
        significativos = [
            t for t in tokens(descripcion) if not (variantes(t) & self.unidades) and singular(t) not in self.unidades
        ]
        if not significativos:
            return Evidencia.NORMAL
        if not any(self._parece(t, self.anclas) for t in significativos):
            if any(self._parece(t, self.vocabulario) for t in significativos):
                return Evidencia.SIN_ANCLA_CON_CONOCIDO
            return Evidencia.JERGA
        if any(not self._parece(t, self.vocabulario) for t in significativos):
            return Evidencia.TOKEN_DESCONOCIDO
        return Evidencia.NORMAL

    # ------------------------------------------------------------ resolución

    def _filtrar_dimension(self, r: Resolucion, dimensiones: frozenset[str]) -> Resolucion:
        """D93: descarta las opciones de otra dimensión física; nunca confirma un producto."""
        if r.tipo is TipoResolucion.NO_EXISTE:
            return r
        opciones = r.opciones or ((r.sku,) if r.sku else ())
        quedan = tuple(s for s in opciones if self.dimension.get(s) is None or dimensiones == {self.dimension[s]})
        if len(quedan) == len(opciones):
            return r
        if not quedan:
            return Resolucion(TipoResolucion.NO_EXISTE, codigos=r.codigos + (CODIGO_DIMENSION,))
        return Resolucion(TipoResolucion.AMBIGUO, opciones=quedan, codigos=r.codigos)

    def resolver(
        self, descripcion: str, candidatos_llm: Sequence[str] = (), dimensiones: frozenset[str] = frozenset()
    ) -> Resolucion:
        evidencia = self.evidencia(descripcion)
        if evidencia is Evidencia.SIN_ANCLA_CON_CONOCIDO:
            # R1-a (prioridad sobre R1-b): la coincidencia parcial indica otro producto; los
            # candidatos del LLM no son evidencia. Sin línea y sin opciones. Los códigos solo
            # indican qué ocurrió con los candidatos; nunca llevan texto ni identificadores.
            codigos: list[str] = []
            if any(s not in self.entradas for s in candidatos_llm):
                codigos.append("SKU_LLM_INEXISTENTE")
            if any(s in self.entradas for s in candidatos_llm):
                codigos.append("CANDIDATOS_LLM_IGNORADOS")
            return Resolucion(TipoResolucion.NO_EXISTE, codigos=tuple(codigos + ["SIN_ANCLA_CATALOGO"]))
        r = self._resolver_por_texto(descripcion, candidatos_llm)
        if dimensiones:
            r = self._filtrar_dimension(r, frozenset(dimensiones))  # D93
        if evidencia is Evidencia.JERGA:
            # R1-b / R1-c: D45 sin cambios. Una mención sin ancla nunca produce una línea.
            if r.tipo in (TipoResolucion.RESUELTO, TipoResolucion.AGOTADO_SIN_SUSTITUTO):
                return Resolucion(TipoResolucion.AMBIGUO, opciones=r.opciones, codigos=r.codigos + ("SIN_ANCLA_CATALOGO",))
            return r
        if evidencia is Evidencia.TOKEN_DESCONOCIDO:
            # R2: una marca o variante que no vendemos; ningún SKU cuenta con evidencia suficiente.
            if r.tipo is TipoResolucion.NO_EXISTE and _CONSERVAN_NO_EXISTE & set(r.codigos):
                return r  # excepciones: medidas explícitas contradictorias o dimensión (D93)
            return Resolucion(TipoResolucion.AMBIGUO, opciones=(), codigos=r.codigos + ("TOKEN_DESCONOCIDO",))
        return r

    def _resolver_por_texto(self, descripcion: str, candidatos_llm: Sequence[str] = ()) -> Resolucion:
        """Resolución de E1b-1, sin cambios: puntajes, universo, medidas y D45."""
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
