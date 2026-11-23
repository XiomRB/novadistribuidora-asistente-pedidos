"""Texto: plegado con mapa de posiciones, tokens, similitud, presentaciones y anclaje.

- Las posiciones (`Span`) son intervalos semiabiertos [inicio, fin) sobre la cadena original.
- Los umbrales de similitud son porcentajes enteros (sin literales float en el dominio).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from app.datos.normalizacion import normalizar_texto
from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Evento, Fragmento, Interpretacion

UMBRAL_TOKEN = 80  # % de similitud entre tokens (ambos de 4 o más letras)
UMBRAL_ANCLA = 85  # % de similitud para anclar un fragmento de forma aproximada

PALABRAS_VACIAS = frozenset(
    {"de", "del", "la", "el", "los", "las", "y", "e", "con", "para", "en", "al", "a", "por", "un", "una",
     "unos", "unas", "mi", "su", "que", "o", "lo", "le", "me", "se", "medio", "media"}
)

# Unidades de medida -> (unidad canónica, factor)
UNIDADES_MEDIDA: dict[str, tuple[str, int]] = {
    "ml": ("ml", 1), "mililitros": ("ml", 1), "mililitro": ("ml", 1), "cc": ("ml", 1),
    "l": ("ml", 1000), "lt": ("ml", 1000), "lts": ("ml", 1000), "litro": ("ml", 1000), "litros": ("ml", 1000),
    "g": ("g", 1), "gr": ("g", 1), "grs": ("g", 1), "gramo": ("g", 1), "gramos": ("g", 1),
    "kg": ("g", 1000), "kilo": ("g", 1000), "kilos": ("g", 1000),
    "lb": ("lb", 1), "lbs": ("lb", 1), "libra": ("lb", 1), "libras": ("lb", 1),
}
# Contenedores declarados en presentaciones -> lema
CONTENEDORES: dict[str, str] = {
    "paquete": "paquete", "paquetes": "paquete",
    "sobre": "sobre", "sobres": "sobre",
    "bolsa": "bolsa", "bolsas": "bolsa", "bolsita": "bolsa", "bolsitas": "bolsa",
    "rollo": "rollo", "rollos": "rollo",
}
PALABRAS_MEDIDA = frozenset(UNIDADES_MEDIDA) | frozenset(CONTENEDORES)


# ---------------------------------------------------------------- plegado y posiciones


def plegar(texto: str) -> tuple[str, list[int]]:
    """Minúsculas y sin diacríticos, con el índice original de cada carácter resultante."""
    salida: list[str] = []
    mapa: list[int] = []
    for indice, caracter in enumerate(texto):
        for c in unicodedata.normalize("NFKD", caracter.casefold()):
            if not unicodedata.combining(c):
                salida.append(c)
                mapa.append(indice)
    return "".join(salida), mapa


@dataclass(frozen=True, order=True)
class Span:
    """Intervalo semiabierto [inicio, fin) dentro de `mensajes[mensaje]` (cadena original)."""

    mensaje: int
    inicio: int
    fin: int

    def __post_init__(self) -> None:
        if not 0 <= self.inicio <= self.fin or self.mensaje < 0:
            raise ValueError("Span inválido")

    @property
    def longitud(self) -> int:
        return self.fin - self.inicio

    def interseccion(self, otro: Span) -> int:
        if self.mensaje != otro.mensaje:
            return 0
        return max(0, min(self.fin, otro.fin) - max(self.inicio, otro.inicio))

    def contiene(self, otro: Span) -> bool:
        return self.mensaje == otro.mensaje and self.inicio <= otro.inicio and otro.fin <= self.fin


def _similitud_pct(a: str, b: str) -> int:
    return round(SequenceMatcher(None, a, b).ratio() * 100)


def localizar(fragmento: str, mensaje: str, indice_mensaje: int, desde: int = 0) -> Span | None:
    """Ubica `fragmento` en `mensaje`: exacto, luego sin mayúsculas ni tildes, luego aproximado.

    Prefiere la primera aparición a partir de `desde` (posición original).
    """
    patron_crudo = fragmento.strip()
    if not patron_crudo or not mensaje:
        return None
    for inicio in (desde, 0):
        encontrado = mensaje.find(patron_crudo, inicio)
        if encontrado >= 0:
            return Span(indice_mensaje, encontrado, encontrado + len(patron_crudo))

    plegado, mapa = plegar(mensaje)
    patron, _ = plegar(patron_crudo)
    desde_plegado = next((k for k, v in enumerate(mapa) if v >= desde), len(mapa))
    for inicio in (desde_plegado, 0):
        encontrado = plegado.find(patron, inicio)
        if encontrado >= 0:
            return Span(indice_mensaje, mapa[encontrado], mapa[encontrado + len(patron) - 1] + 1)

    # Aproximado: ventanas de longitud parecida; la secuencia fija (patrón) va en seq2 por eficiencia.
    n = len(patron)
    comparador = SequenceMatcher(None, "", patron)
    mejor: tuple[int, int, int, int] | None = None  # (similitud, preferida, -inicio, longitud)
    for largo in sorted({max(1, n * 4 // 5), n, n * 6 // 5 + 1}):
        for k in range(0, max(1, len(plegado) - largo + 1)):
            comparador.set_seq1(plegado[k : k + largo])
            if comparador.real_quick_ratio() * 100 < UMBRAL_ANCLA or comparador.quick_ratio() * 100 < UMBRAL_ANCLA:
                continue
            similitud = round(comparador.ratio() * 100)
            if similitud < UMBRAL_ANCLA:
                continue
            clave = (similitud, int(mapa[k] >= desde), -k, largo)
            if mejor is None or clave > mejor:
                mejor = clave
    if mejor is None:
        return None
    k, largo = -mejor[2], mejor[3]
    fin = min(k + largo, len(plegado)) - 1
    return Span(indice_mensaje, mapa[k], mapa[fin] + 1)


# ---------------------------------------------------------------- tokens y similitud

_DIMINUTIVOS = (("citos", ""), ("citas", ""), ("cito", ""), ("cita", ""), ("itos", "o"), ("itas", "a"), ("ito", "o"), ("ita", "a"))


def singular(token: str) -> str:
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def sin_diminutivo(token: str) -> frozenset[str]:
    resultado = set()
    for sufijo, reemplazo in _DIMINUTIVOS:
        if token.endswith(sufijo) and len(token) - len(sufijo) >= 3:
            resultado.add(token[: -len(sufijo)] + reemplazo)
    return frozenset(resultado)


def variantes(token: str) -> frozenset[str]:
    """El token, su singular y su forma sin diminutivo."""
    return frozenset({token, singular(token)}) | sin_diminutivo(token)


def peso_coincidencia(token_mencion: str, token_producto: str) -> int:
    """10 = idéntico; 9 = idéntico en singular; 8 = idéntico sin diminutivo; 7 = parecido; 0 = distinto."""
    if token_mencion == token_producto:
        return 10
    sm, sp = {token_mencion, singular(token_mencion)}, {token_producto, singular(token_producto)}
    if sm & sp:
        return 9
    vm, vp = variantes(token_mencion), variantes(token_producto)
    if vm & vp:
        return 8
    for a in vm:
        for b in vp:
            if len(a) >= 4 and len(b) >= 4 and _similitud_pct(a, b) >= UMBRAL_TOKEN:
                return 7
    return 0


def tokens(texto: str) -> list[str]:
    """Tokens significativos: sin palabras vacías, números ni unidades de medida."""
    return [
        t for t in normalizar_texto(texto).split()
        if t not in PALABRAS_VACIAS and not any(c.isdigit() for c in t) and t not in PALABRAS_MEDIDA
    ]


# ---------------------------------------------------------------- presentaciones


@dataclass(frozen=True)
class Medida:
    """Medida de una presentación. `unidad` None indica un número sin unidad (p. ej. 'kola 600')."""

    valor: Decimal
    unidad: str | None

    def coincide(self, otra: Medida) -> bool:
        """`self` es la mención; `otra`, una medida del producto."""
        if self.unidad is None:
            return self.valor == otra.valor or (
                otra.unidad in ("ml", "g") and self.valor * 1000 == otra.valor
            )
        return self.valor == otra.valor and self.unidad == otra.unidad


_FRASES = (
    (re.compile(r"\b(?:un\s+)?litro\s+y\s+medio\b|\b1\s+1/2\b|\b1\s+y\s+medio\b"), Medida(Decimal(1500), "ml")),
    (re.compile(r"\bmedio\s+litro\b"), Medida(Decimal(500), "ml")),
    (re.compile(r"\b(?:de|la|el)\s+litro\b"), Medida(Decimal(1000), "ml")),
    (re.compile(r"\b(?:de|la|una)\s+libra\b"), Medida(Decimal(1), "lb")),
)
_NUMERO = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?:\s*([a-z]+))?")


def _plegado_simple(texto: str) -> str:
    plegado, _ = plegar(texto)
    return re.sub(r"\s+", " ", plegado)


def extraer_medidas(texto: str, ignorar: frozenset[str] = frozenset()) -> frozenset[Medida]:
    """Medidas presentes en un texto. Se omiten números seguidos de una palabra de `ignorar`
    (p. ej. '2 fardos'), salvo que sea un contenedor de presentación ('12 rollos')."""
    t = _plegado_simple(texto)
    medidas: set[Medida] = set()
    for patron, medida in _FRASES:
        if patron.search(t):
            medidas.add(medida)
            t = patron.sub(" ", t)
    for coincidencia in _NUMERO.finditer(t):
        valor = Decimal(coincidencia.group(1).replace(",", "."))
        palabra = coincidencia.group(2)
        if palabra in UNIDADES_MEDIDA:
            unidad, factor = UNIDADES_MEDIDA[palabra]
            medidas.add(Medida(valor * factor, unidad))
        elif palabra in CONTENEDORES:
            medidas.add(Medida(valor, CONTENEDORES[palabra]))
        elif palabra is not None and (palabra in ignorar or singular(palabra) in ignorar):
            continue
        else:
            medidas.add(Medida(valor, None))
    return frozenset(medidas)


def normalizar_presentacion(texto: str) -> str | None:
    """Forma canónica de una presentación: '1.5 L' -> '1500ml'; 'litro y medio' -> '1500ml';
    '12 rollos' -> '12rollo'. None si no hay exactamente una medida."""
    medidas = extraer_medidas(texto)
    if len(medidas) != 1:
        return None
    medida = next(iter(medidas))
    return f"{medida.valor.normalize():f}{medida.unidad or ''}"


# ---------------------------------------------------------------- anclaje


@dataclass(frozen=True)
class EventoAnclado:
    evento: Evento
    span: Span | None

    @property
    def anclado(self) -> bool:
        return self.span is not None


@dataclass(frozen=True)
class FragmentoAnclado:
    fragmento: Fragmento
    span: Span | None


@dataclass(frozen=True)
class Anclaje:
    eventos: tuple[EventoAnclado, ...]
    consultas: tuple[FragmentoAnclado, ...]
    rechazadas: tuple[FragmentoAnclado, ...]


def texto_original(span: Span, entrada: EntradaPedido) -> str:
    """Fragmento original exacto de un mensaje según su posición."""
    return entrada.mensajes[span.mensaje][span.inicio : span.fin]


def anclar(interpretacion: Interpretacion, entrada: EntradaPedido) -> Anclaje:
    """Ubica cada evento y fragmento en su mensaje. Los eventos avanzan un cursor por mensaje
    para que fragmentos repetidos se asignen en orden de aparición."""
    if any(e.mensaje >= len(entrada.mensajes) for e in interpretacion.eventos):
        raise ValueError("la interpretación referencia un mensaje inexistente")
    cursor: dict[int, int] = {}
    eventos = []
    for evento in interpretacion.eventos:
        mensaje = entrada.mensajes[evento.mensaje]
        span = localizar(evento.texto, mensaje, evento.mensaje, cursor.get(evento.mensaje, 0))
        if span is not None:
            cursor[evento.mensaje] = span.fin
        eventos.append(EventoAnclado(evento, span))

    def fragmentos(lista: list[Fragmento]) -> tuple[FragmentoAnclado, ...]:
        resultado = []
        for f in lista:
            if f.mensaje >= len(entrada.mensajes):
                raise ValueError("un fragmento referencia un mensaje inexistente")
            resultado.append(FragmentoAnclado(f, localizar(f.texto, entrada.mensajes[f.mensaje], f.mensaje)))
        return tuple(resultado)

    return Anclaje(tuple(eventos), fragmentos(interpretacion.consultas), fragmentos(interpretacion.instrucciones_rechazadas))
