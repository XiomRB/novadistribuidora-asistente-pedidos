"""Reconocedor determinista de consultas puras (D36).

Una oración es *consulta pura* si es interrogativa y no contiene un marcador de compra.
Una consulta con cantidad y sin marcador de compra ("¿tienen 3 fardos de kola?") es consulta.
Los pedidos formulados como pregunta ("¿me manda 2 fardos…?") llevan marcador de compra y
no son consultas puras.

Las posiciones (`Span`) se refieren a la cadena original de cada mensaje.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.dominio.texto import Span, plegar

# Cierres de oración: ? ! ; y salto de línea; el punto cierra salvo entre dígitos ("1.5").
_CIERRES = frozenset("?!;\n")


def _punto_decimal(texto: str, i: int) -> bool:
    return 0 < i < len(texto) - 1 and texto[i - 1].isdigit() and texto[i + 1].isdigit()

# Saludos y muletillas que pueden preceder a la pregunta.
_SALUDO = re.compile(
    r"^(?:\s|,|hola|buenas|buenos|buen|dias|dia|tardes|noches|que tal|qué tal|don|dona|seno|seño|"
    r"disculpe|disculpa|oiga|fijese que|mire que|mire|fijese|este|eh|ey|porfa|por favor|(?:\(audio transcrito\)))+"
)
_INICIO_INTERROGATIVO = re.compile(
    r"^(?:tienen|tiene|tendran|tendra|hay|habra|venden|vende|manejan|maneja|cuanto|cuantos|cuanta|a como|"
    r"que precio|a que hora|que hora|cuando|ya llego|ya llegaron|ya tienen|me puede decir|me podria decir|"
    r"sabe si|saben si|me confirma si|como|donde|por que|porque|ya no)\b"
)
# Frases de consulta que no son compra aunque usen verbos como "quiero" o "necesito".
_FRASES_CONSULTA = re.compile(r"\b(?:quiero|quisiera|queria|necesito|ocupo)\s+(?:saber|preguntar|consultar|confirmar)\b")
# Marcadores de compra (sobre texto plegado: sin tildes y en minúsculas).
_MARCADOR_COMPRA = re.compile(
    r"\b(?:mand\w*|(?:me|nos)\s+(?:(?:puede|podria|podra|va\s+a)\s+)?(?:trae\w*|traig\w*|traer\w*)|traigame|traiganos|"
    r"apunt\w*|anot\w*|encarg\w*|"
    r"quiero|quisiera|queria|necesito|necesitamos|ocupo|ocupamos|deme|denme|dame|pongame|ponga|pone|"
    r"regal\w*|despach\w*|envie\w*|enviar\w*|me\s+hace\s+(?:el\s+)?favor|hagame\s+(?:el\s+)?favor|"
    r"le\s+hago\s+(?:mi|el)\s+pedido|para\s+el\s+pedido|le\s+paso\s+el\s+pedido)\b"
)
_LISTA = re.compile(r"^\s*(?:[-*•]|\w[\w ]{0,40}:\s*\d)")
_NUMEROS = r"(?:\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|veinte)"
_CONTINUACION = re.compile(
    rf"^(?:y|tambien|ah y|ah|ademas|y tambien)?\s*{_NUMEROS}\s+"
    r"(?:de|fardos?|fardit\w*|cajas?|cajit\w*|displays?|quintal\w*|docenas?|botell\w*|latas?|bolsa\w*|bolsit\w*|sobres?|paquet\w*)\b"
)


@dataclass(frozen=True)
class Oracion:
    span: Span
    texto: str
    interrogativa: bool
    marcador_compra: bool

    @property
    def consulta_pura(self) -> bool:
        return self.interrogativa and not self.marcador_compra


def _plegado(texto: str) -> str:
    plegado, _ = plegar(texto)
    return re.sub(r"\s+", " ", plegado).strip()


def es_interrogativa(texto: str) -> bool:
    if "?" in texto or "¿" in texto:
        return True
    sin_saludo = _SALUDO.sub("", _plegado(texto)).strip(" ,")
    return bool(_INICIO_INTERROGATIVO.match(sin_saludo) or _FRASES_CONSULTA.match(sin_saludo) or sin_saludo.startswith("una pregunta"))


def tiene_marcador_compra(texto: str) -> bool:
    plegado = _plegado(texto)
    if _LISTA.match(texto):
        return True
    sin_consulta = _FRASES_CONSULTA.sub(" ", plegado)
    if _MARCADOR_COMPRA.search(sin_consulta):
        return True
    sin_saludo = _SALUDO.sub("", sin_consulta).strip(" ,")
    return bool(_CONTINUACION.match(sin_saludo))


def segmentar(mensaje: str, indice_mensaje: int) -> list[Oracion]:
    """Divide un mensaje en oraciones conservando sus posiciones originales.

    El signo '¿' abre una oración nueva; '?', '!', ';', el salto de línea y el punto
    (no decimal) la cierran (el cierre queda incluido en la oración).
    """
    cortes: list[tuple[int, int]] = []
    inicio = 0
    for i, caracter in enumerate(mensaje):
        if caracter == "¿" and mensaje[inicio:i].strip():
            cortes.append((inicio, i))
            inicio = i
        elif caracter in _CIERRES or (caracter == "." and not _punto_decimal(mensaje, i)):
            cortes.append((inicio, i + 1))
            inicio = i + 1
    cortes.append((inicio, len(mensaje)))
    oraciones = []
    for a, b in cortes:
        texto = mensaje[a:b]
        if not texto.strip():
            continue
        desplazamiento = len(texto) - len(texto.lstrip())
        recorte = len(texto.rstrip())
        span = Span(indice_mensaje, a + desplazamiento, a + recorte)
        limpio = mensaje[span.inicio : span.fin]
        oraciones.append(Oracion(span, limpio, es_interrogativa(limpio), tiene_marcador_compra(limpio)))
    return oraciones


def oraciones(mensajes: tuple[str, ...] | list[str]) -> list[Oracion]:
    return [o for i, m in enumerate(mensajes) for o in segmentar(m, i)]


def consultas_puras(mensajes: tuple[str, ...] | list[str]) -> list[Span]:
    return [o.span for o in oraciones(mensajes) if o.consulta_pura]


def dentro_de_consulta(span: Span, consultas: list[Span]) -> bool:
    """True si al menos la mitad del fragmento cae dentro de una consulta pura."""
    if span.longitud == 0:
        return False
    return any(2 * span.interseccion(c) >= span.longitud for c in consultas)
