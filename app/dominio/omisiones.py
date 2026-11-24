"""Detector determinista de omisiones: menciones de pedido que ningún evento representa.

Señales (sección 3.5 del plan de E1b y D60):
- S1: mención del catálogo. Solo el sustantivo del grupo (3 letras o más) o un alias o un
  nombre completo del catálogo; nunca una marca o una variante sueltas ("doña Rosa" no activa
  el jabón Rosa; "te mando" no activa el té).
- S2: número (en dígitos o en palabra) seguido de una palabra de unidad ("3 fardos", "una caja").
- S3: expresión de pedido habitual ("lo de siempre", "la vez pasada", …).
- S4: renglón de lista ("- x" o "x: n" al inicio de una línea).

Cobertura por posición (3.8). Una señal S queda cubierta solo si:
1. un evento efectivo E comparte con ella al menos la mitad de su longitud
   (`|S ∩ E| >= ceil(|S| / 2)`), o
2. S está completamente dentro de una oración que el código clasifica como consulta pura.
Las instrucciones rechazadas, los eventos descartados y las consultas del intérprete que el
código no confirma nunca cubren.

Contexto de pedido (D61). Las señales sin cubrir solo generan pendientes si se cumple al
menos una condición, evaluada fuera de las consultas puras:
- C1: hay al menos un evento efectivo.
- C2: alguna oración tiene un marcador de compra. Si su único marcador es el patrón de lista
  de E1b-1 ("x: n" o viñeta), solo cuenta si es una lista válida: un renglón S4 que contiene
  una señal S1, o dos o más renglones S4 en el mismo mensaje ("entrega: 10" o "saldo: 3" no
  activan C2).
- C3: hay un renglón de lista (S4).
- C4: hay una señal S2.
- C5: hay una señal S3.
Sin contexto (un reclamo o un comentario), no se genera nada.

Pendientes (D05, D59). Las señales sin cubrir que forman una misma mención (contiguas o
separadas solo por conectores como "de") se agrupan en un pendiente `producto_ambiguo` cuyo
texto es exactamente el tramo de la señal (`mensajes[m][inicio:fin]`, nunca el mensaje
completo) y cuyas opciones son los candidatos del código cuando hay una señal S1. Nunca se
crean líneas ni cantidades a partir de una omisión.

El diagnóstico solo recibe posiciones y tipos de señal (`DiagOmision`); nunca el texto.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.datos.modelos import Datos
from app.dominio.catalogo import IndiceCatalogo, TipoResolucion
# Solo lectura de E1b-1 (sin modificar consultas.py): el patrón con el que su reconocedor cuenta
# una oración como renglón de lista, para saber si ese es su único marcador de compra.
from app.dominio.consultas import _LISTA as _LISTA_E1B1
from app.dominio.consultas import Oracion, tiene_marcador_compra
from app.dominio.diagnostico import DiagOmision
from app.dominio.resultado import Motivo, Pendiente
from app.dominio.texto import (
    CONTENEDORES,
    PALABRAS_VACIAS,
    UNIDADES_MEDIDA,
    Span,
    extraer_medidas,
    peso_coincidencia,
    plegar,
    tokens,
    variantes,
)
from app.dominio.unidades import DOCENAS, SUELTAS, LexicoUnidades

MIN_LETRAS_GRUPO = 3
PESO_SENAL = 8  # idéntico, en singular o sin diminutivo
PESO_APROXIMADO = 7  # parecido (errores leves): solo grupos largos y con evidencia adyacente
MIN_LETRAS_APROXIMADO = 5

NUMEROS_PALABRA = frozenset(
    {"un", "una", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once",
     "doce", "trece", "catorce", "quince", "dieciseis", "veinte", "veinticuatro", "treinta", "cuarenta",
     "cincuenta", "cien", "media"}
)
_EXPRESIONES_HABITUAL = re.compile(
    r"\blo\s+de\s+siempre\b|\blo\s+mismo\b|\bla\s+vez\s+pasada\b|\bla\s+otra\s+vez\b|\b(?:lo\s+)?de\s+cada\s+semana\b|"
    r"\bel\s+ultimo\s+pedido\b|\bdel\s+ultimo\s+pedido\b|\bpedido\s+de\s+siempre\b|\blo\s+de\s+la\s+otra\s+vez\b"
)
_PALABRA = re.compile(r"[^\W_]+(?:[.,]\d+)?", re.UNICODE)
_VINETA = re.compile(r"^[ \t]*[-*•][ \t]*(?=\S)")
# "x: n" solo cuando la línea completa es el renglón (producto, dos puntos y número).
_RENGLON_CLAVE = re.compile(r"^[ \t]*(?=[^\W\d_])[^\n:,;!?]{1,40}:[ \t]*\d+(?:[.,]\d+)?[ \t]*[.;!]?[ \t]*$")
_SIN_LISTA = "· "  # prefijo que anula el patrón de lista de E1b-1 y deja los demás marcadores
_PUNTUACION = re.compile(r"[^\w\s]")  # cualquier signo entre la palabra y su evidencia
_FIN_RENGLON = re.compile(r"(?<!\d)[.;!?](?!\d)|\n")
# Palabras que unen las partes de una misma mención ("3 fardos de gaseosa"). "y", "o" y la coma
# separan menciones distintas, que generan pendientes distintos.
_CONECTORES = frozenset({"de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "con", "en", "x"})


class TipoSenal(StrEnum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


@dataclass(frozen=True)
class Senal:
    tipo: TipoSenal
    span: Span


@dataclass(frozen=True)
class Omision:
    """Señales sin cubrir agrupadas en una mención (un pendiente)."""

    span: Span
    senales: tuple[TipoSenal, ...]
    pendiente: Pendiente | None  # None si no hay contexto de pedido (D61)


@dataclass(frozen=True)
class Contexto:
    """Condiciones de D61, evaluadas fuera de las consultas puras."""

    c1_evento: bool
    c2_compra: bool
    c3_lista: bool
    c4_cantidad: bool
    c5_habitual: bool

    @property
    def hay_pedido(self) -> bool:
        return self.c1_evento or self.c2_compra or self.c3_lista or self.c4_cantidad or self.c5_habitual


@dataclass(frozen=True)
class ResultadoOmisiones:
    senales: tuple[Senal, ...]
    omisiones: tuple[Omision, ...]
    contexto: Contexto

    @property
    def pendientes(self) -> tuple[Pendiente, ...]:
        """Pendientes por omisión, ordenados por posición (D64)."""
        return tuple(o.pendiente for o in self.omisiones if o.pendiente is not None)

    def diagnostico(self) -> tuple[DiagOmision, ...]:
        return tuple(
            DiagOmision(
                (o.span.mensaje, o.span.inicio, o.span.fin),
                "+".join(s.value for s in o.senales),
                "OMISION" if o.pendiente is not None else "SIN_CONTEXTO",
            )
            for o in self.omisiones
        )


# ---------------------------------------------------------------- tokens con posición


@dataclass(frozen=True)
class _Token:
    texto: str  # plegado (minúsculas, sin tildes)
    inicio: int  # posiciones en la cadena original
    fin: int


def _tokens_con_posicion(mensaje: str) -> list[_Token]:
    plegado, mapa = plegar(mensaje)
    return [
        _Token(m.group(0), mapa[m.start()], mapa[m.end() - 1] + 1)
        for m in _PALABRA.finditer(plegado)
    ]


class DetectorOmisiones:
    """Vocabulario de señales derivado del catálogo; se construye una vez por catálogo."""

    def __init__(self, datos: Datos, indice: IndiceCatalogo, lexico: LexicoUnidades):
        self.indice = indice
        self.lexico = lexico
        self.grupos = frozenset(g for g in indice.por_grupo if len(g) >= MIN_LETRAS_GRUPO)
        frases: set[tuple[str, ...]] = set()
        for alias in datos.alias:
            frase = tuple(tokens(alias.alias))
            if frase:
                frases.add(frase)
        for producto in datos.productos.values():
            frase = tuple(tokens(producto.nombre))
            if frase:
                frases.add(frase)
        # Las frases de una sola palabra que no son un grupo (marcas, variantes) no son señal (D60).
        self.frases = tuple(sorted(f for f in frases if len(f) > 1 or f[0] in self.grupos))
        self.unidades = frozenset(lexico.palabras_cantidad()) | frozenset(SUELTAS) | DOCENAS
        # Marcas, variantes y medidas de cada grupo (evidencia adyacente para errores leves).
        self.vocabulario_grupo = {
            g: frozenset(t for sku in indice.por_grupo[g] for t in indice.entradas[sku].tokens if t != g)
            | frozenset(u for u in ("ml", "l", "lt", "litro", "litros", "g", "gr", "kg", "lb", "libra", "libras"))
            for g in self.grupos
        }

    # ------------------------------------------------------------ señales

    def _es_grupo(self, mensaje: str, utiles: Sequence[_Token], k: int) -> bool:
        """Sustantivo del grupo: idéntico, en singular o sin diminutivo. Un error leve
        ("nranjita", "friijol"; similitud >= 80 %) solo cuenta en grupos de 5 letras o más y
        con evidencia adyacente del **mismo** grupo:
        - una marca o una variante de ese grupo ("friijol negro"), o
        - un número que sea una presentación compatible con algún producto del grupo
          ("nranjita 600 ml", "narannjita 1.5"); un número cualquiera ("claro 2 veces",
          "harían 3 viajes") no es evidencia.
        Un signo de puntuación entre la palabra y la evidencia la anula ("Claro, 2 de …")."""
        token = utiles[k]
        if any(peso_coincidencia(token.texto, g) >= PESO_SENAL for g in self.grupos):
            return True
        if k + 1 >= len(utiles):
            return False
        siguiente = utiles[k + 1]
        if _PUNTUACION.search(mensaje[token.fin : siguiente.inicio]):
            return False
        medidas = None
        if any(c.isdigit() for c in siguiente.texto):
            fin = siguiente.fin
            if k + 2 < len(utiles) and utiles[k + 2].texto in UNIDADES_MEDIDA and not mensaje[fin : utiles[k + 2].inicio].strip():
                fin = utiles[k + 2].fin  # "600 ml": el número con su unidad
            medidas = extraer_medidas(mensaje[siguiente.inicio : fin])
        for g in self.grupos:
            if len(g) < MIN_LETRAS_APROXIMADO or peso_coincidencia(token.texto, g) < PESO_APROXIMADO:
                continue
            if medidas is not None:
                if medidas and any(self.indice.compatible_con_medidas(s, medidas) for s in self.indice.por_grupo[g]):
                    return True
            elif any(peso_coincidencia(siguiente.texto, v) >= PESO_SENAL for v in self.vocabulario_grupo[g]):
                return True
        return False

    def _es_unidad(self, token: str) -> bool:
        if variantes(token) & self.unidades:
            return True
        return self.lexico.lema_venta(token) is not None

    def senales(self, mensajes: Sequence[str]) -> list[Senal]:
        resultado: list[Senal] = []
        for indice, mensaje in enumerate(mensajes):
            lista = _tokens_con_posicion(mensaje)
            significativos = [t for t in lista if t.texto not in PALABRAS_VACIAS and not any(c.isdigit() for c in t.texto)]
            # S1: sustantivo del grupo.
            utiles = [t for t in lista if t.texto not in PALABRAS_VACIAS]
            for k, t in enumerate(utiles):
                if any(c.isdigit() for c in t.texto):
                    continue
                if self._es_grupo(mensaje, utiles, k):
                    resultado.append(Senal(TipoSenal.S1, Span(indice, t.inicio, t.fin)))
            # S1: alias o nombre completo (tokens significativos consecutivos).
            for frase in self.frases:
                n = len(frase)
                for k in range(len(significativos) - n + 1):
                    ventana = significativos[k : k + n]
                    if all(peso_coincidencia(t.texto, f) >= PESO_SENAL for t, f in zip(ventana, frase)):
                        resultado.append(Senal(TipoSenal.S1, Span(indice, ventana[0].inicio, ventana[-1].fin)))
            # S2: número seguido de una palabra de unidad.
            for a, b in zip(lista, lista[1:]):
                numero = a.texto.replace(",", ".").replace(".", "", 1).isdigit() or a.texto in NUMEROS_PALABRA
                if numero and self._es_unidad(b.texto):
                    resultado.append(Senal(TipoSenal.S2, Span(indice, a.inicio, b.fin)))
            # S3: expresión de pedido habitual.
            plegado, mapa = plegar(mensaje)
            for m in _EXPRESIONES_HABITUAL.finditer(plegado):
                resultado.append(Senal(TipoSenal.S3, Span(indice, mapa[m.start()], mapa[m.end() - 1] + 1)))
            # S4: renglón de lista al inicio de una línea.
            desplazamiento = 0
            for linea in mensaje.split("\n"):
                vineta = _VINETA.match(linea)
                if vineta or _RENGLON_CLAVE.match(linea):
                    inicio = vineta.end() if vineta else len(linea) - len(linea.lstrip())
                    corte = _FIN_RENGLON.search(linea, inicio)
                    fin = corte.start() if corte else len(linea)
                    fin = inicio + len(linea[inicio:fin].rstrip())
                    if fin > inicio:
                        resultado.append(Senal(TipoSenal.S4, Span(indice, desplazamiento + inicio, desplazamiento + fin)))
                desplazamiento += len(linea) + 1
        return sorted(set(resultado), key=lambda s: (s.span, s.tipo))

    # ------------------------------------------------------------ cobertura y contexto

    @staticmethod
    def cubierta(senal: Senal, eventos: Sequence[Span], consultas_puras: Sequence[Span]) -> bool:
        s = senal.span
        mitad = (s.longitud + 1) // 2
        if any(s.interseccion(e) >= mitad for e in eventos):
            return True
        return any(c.contiene(s) for c in consultas_puras)

    @staticmethod
    def contexto(
        senales: Sequence[Senal], oraciones: Sequence[Oracion], hay_eventos_efectivos: bool
    ) -> Contexto:
        puras = [o.span for o in oraciones if o.consulta_pura]

        def fuera(span: Span) -> bool:
            return not any(c.contiene(span) for c in puras)

        tipos = {s.tipo for s in senales if fuera(s.span)}
        renglones = [s for s in senales if s.tipo is TipoSenal.S4 and fuera(s.span)]
        productos = [s.span for s in senales if s.tipo is TipoSenal.S1]

        def lista_valida(o: Oracion) -> bool:
            """Revisión del PR #5: un renglón aislado solo vale como lista si contiene una
            señal S1; dos o más renglones S4 en el mismo mensaje valen como lista aunque sus
            productos no estén en el catálogo."""
            del_mensaje = [r for r in renglones if r.span.mensaje == o.span.mensaje]
            if len(del_mensaje) >= 2:
                return True
            return any(
                r.span.interseccion(o.span) > 0 and any(r.span.contiene(p) for p in productos) for r in del_mensaje
            )

        def compra(o: Oracion) -> bool:
            if not o.marcador_compra or o.consulta_pura:
                return False
            if not _LISTA_E1B1.match(o.texto):
                return True
            # El reconocedor de E1b-1 cuenta la oración como renglón de lista ("x: n" o viñeta):
            # vale si tiene otro marcador de compra o si es una lista válida.
            return tiene_marcador_compra(_SIN_LISTA + o.texto) or lista_valida(o)

        return Contexto(
            c1_evento=hay_eventos_efectivos,
            c2_compra=any(compra(o) for o in oraciones),
            c3_lista=TipoSenal.S4 in tipos,
            c4_cantidad=TipoSenal.S2 in tipos,
            c5_habitual=TipoSenal.S3 in tipos,
        )

    # ------------------------------------------------------------ agrupación y pendientes

    def _agrupar(self, mensajes: Sequence[str], sin_cubrir: list[Senal]) -> list[tuple[Span, tuple[TipoSenal, ...]]]:
        grupos: list[tuple[Span, set[TipoSenal]]] = []
        for senal in sorted(sin_cubrir, key=lambda s: (s.span.mensaje, s.span.inicio, -s.span.fin)):
            if grupos:
                span, tipos = grupos[-1]
                # Una expresión de habitual (S3) es siempre una mención aparte.
                mezcla_habitual = (TipoSenal.S3 in tipos) != (senal.tipo is TipoSenal.S3)
                if (
                    span.mensaje == senal.span.mensaje
                    and not mezcla_habitual
                    and self._contiguas(mensajes[span.mensaje], span, senal.span)
                ):
                    grupos[-1] = (Span(span.mensaje, span.inicio, max(span.fin, senal.span.fin)), tipos | {senal.tipo})
                    continue
            grupos.append((senal.span, {senal.tipo}))
        return [(self._con_presentacion(mensajes[span.mensaje], span), tuple(sorted(tipos))) for span, tipos in grupos]

    @staticmethod
    def _con_presentacion(mensaje: str, span: Span) -> Span:
        """Extiende la mención sobre la presentación que la sigue ("gaseosa sol" + " 600 ml"):
        números y palabras de medida contiguos, con un "de" opcional antes de un número."""
        fin = span.fin
        siguientes = _tokens_con_posicion(mensaje[span.fin :])
        k = 0
        while k < len(siguientes):
            t = siguientes[k]
            numero = any(c.isdigit() for c in t.texto)
            medida = t.texto in UNIDADES_MEDIDA or t.texto in CONTENEDORES
            de_numero = t.texto == "de" and k + 1 < len(siguientes) and any(c.isdigit() for c in siguientes[k + 1].texto)
            if not (numero or medida or de_numero):
                break
            if mensaje[fin : span.fin + t.inicio].strip():
                break  # signos de puntuación entre medio: termina la mención
            fin = span.fin + t.fin
            k += 1
        return Span(span.mensaje, span.inicio, fin)

    @staticmethod
    def _contiguas(mensaje: str, anterior: Span, siguiente: Span) -> bool:
        if siguiente.inicio <= anterior.fin:
            return True
        intermedio = mensaje[anterior.fin : siguiente.inicio]
        palabras = [t.texto for t in _tokens_con_posicion(intermedio)]
        resto = _PALABRA.sub(" ", plegar(intermedio)[0]).strip()
        return not resto and all(p in _CONECTORES for p in palabras)

    def _opciones(self, texto: str) -> tuple[str, ...]:
        r = self.indice.resolver(texto)
        if r.tipo is TipoResolucion.NO_EXISTE:
            return ()
        return r.opciones

    def detectar(
        self,
        mensajes: Sequence[str],
        oraciones: Sequence[Oracion],
        eventos_efectivos: Sequence[Span],
    ) -> ResultadoOmisiones:
        senales = self.senales(mensajes)
        puras = [o.span for o in oraciones if o.consulta_pura]
        contexto = self.contexto(senales, oraciones, bool(eventos_efectivos))
        sin_cubrir = [s for s in senales if not self.cubierta(s, eventos_efectivos, puras)]
        omisiones: list[Omision] = []
        for span, tipos in self._agrupar(mensajes, sin_cubrir):
            pendiente = None
            if contexto.hay_pedido:
                texto = mensajes[span.mensaje][span.inicio : span.fin]
                opciones = self._opciones(texto) if TipoSenal.S1 in tipos else ()
                pendiente = Pendiente(Motivo.PRODUCTO_AMBIGUO, texto, opciones)
            omisiones.append(Omision(span, tipos, pendiente))
        return ResultadoOmisiones(tuple(senales), tuple(omisiones), contexto)
