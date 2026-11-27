"""Conjuntos de evaluación: integridad, formato y anotaciones (fase 1, antes de cualquier petición).

Todo error es `ErrorIntegridad` con un código fijo (y, como máximo, el identificador del caso o el
número de línea): nunca lleva mensajes, respuestas esperadas, claves ni el texto de una excepción.

Archivos lógicos de un conjunto: `casos` (JSONL con el formato de los casos de desarrollo),
`esperadas` (opcional, JSON canónico con las respuestas esperadas) y `anotaciones` (JSON).

Excepción de clave genérica: un producto puede llevar `clave_generica` (una clave hecha solo de
palabras genéricas) únicamente en un par (conjunto, caso) de `EXCEPCIONES_CLAVE_GENERICA` que su
descriptor declare. El literal vive solo en las anotaciones privadas; aquí solo hay identificadores.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.datos.normalizacion import normalizar_texto
from evaluacion.genericas import GENERICAS

ROLES = ("desarrollo", "ajuste", "validacion_publica", "validacion_privada")
CLAVES_CASO = {"id", "tipo", "entrada", "esperado"}
CLAVES_ESPERADO = {"estado", "lineas", "total", "fecha_entrega", "sustituciones", "pendientes", "motivos_revision"}
CLAVES_LINEA = {"sku", "cantidad", "precio_unitario", "descuento_pct", "subtotal"}
CLAVES_SUSTITUCION = {"sku_solicitado", "sku_entregado", "cantidad"}
CLAVES_PENDIENTE = {"motivo", "texto", "opciones"}
MIN_CARACTERES_DISTINTIVA = 3
# Único par autorizado (revisión del PR #10). Ampliarlo exige modificar el código mediante un PR revisado.
EXCEPCIONES_CLAVE_GENERICA = frozenset({("D39", "U03")})
MIN_PALABRAS_CLAVE_GENERICA = 2
ARCHIVOS_VINCULADOS = frozenset({"casos", "esperadas", "anotaciones"})
# Hashes autorizados por id de conjunto. Su ausencia implica el rechazo de la excepción.
SIN_AUTORIZACIONES: Mapping[str, Mapping[str, str]] = MappingProxyType({})


class ErrorIntegridad(Exception):
    """Fallo de la fase 1. `str()` solo devuelve el código fijo."""

    def __init__(self, codigo: str, caso: str | None = None, linea: int | None = None):
        super().__init__(codigo)
        self.codigo, self.caso, self.linea = codigo, caso, linea

    def __str__(self) -> str:
        return self.codigo


@dataclass(frozen=True)
class Descriptor:
    """Conjunto autorizado: hashes de sus archivos completos y recuentos esperados."""

    id: str
    rol: str
    sha256: Mapping[str, str]  # nombre lógico -> SHA-256 del archivo completo
    n_casos: int
    n_mensajes: int | None = None
    privado: bool = False
    todos_criticos: bool = True
    excepciones_clave_generica: frozenset[str] = frozenset()  # casos; validados en el registro


@dataclass(frozen=True)
class Consultado:
    skus: frozenset[str] = frozenset()
    claves: tuple[tuple[str, ...], ...] = ()
    pedido_como: int | None = None


@dataclass(frozen=True)
class Anotacion:
    claves: tuple[tuple[tuple[str, ...], ...], ...]  # por producto esperado (líneas y luego pendientes)
    consultados: tuple[Consultado, ...] = ()
    texto_provisional: bool = False
    critico: bool = True


@dataclass(frozen=True)
class Caso:
    id: str
    tipo: str
    entrada: Mapping[str, Any]
    esperado: Mapping[str, Any]  # números como Decimal


@dataclass(frozen=True)
class Conjunto:
    descriptor: Descriptor
    casos: tuple[Caso, ...]
    anotaciones: Mapping[str, Anotacion] = field(default_factory=dict)


# ====================================================================== utilidades


def sha256_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def palabras(texto: str) -> tuple[str, ...]:
    return tuple(normalizar_texto(texto).split())


def clave_valida(clave: tuple[str, ...]) -> bool:
    return any(p not in GENERICAS and not p.isdigit() and len(p) >= MIN_CARACTERES_DISTINTIVA for p in clave)


def contiene(texto: tuple[str, ...], clave: tuple[str, ...]) -> bool:
    """La clave aparece como subsecuencia contigua de palabras completas."""
    n = len(clave)
    return n > 0 and any(texto[i : i + n] == clave for i in range(len(texto) - n + 1))


def _es_decimal(valor: Any, entero: bool = False) -> bool:
    if isinstance(valor, bool) or not isinstance(valor, Decimal) or not valor.is_finite():
        return False
    return not entero or valor == valor.to_integral_value()


def _cargar_json(contenido: bytes, codigo: str) -> Any:
    try:
        return json.loads(contenido.decode("utf-8"), parse_float=Decimal, parse_int=Decimal)
    except (UnicodeDecodeError, ValueError):
        raise ErrorIntegridad(codigo) from None


# ====================================================================== formato de los casos


def _validar_esperado(esperado: Any, caso: str) -> None:
    def exigir(condicion: bool) -> None:
        if not condicion:
            raise ErrorIntegridad("FORMATO_ESPERADO", caso)

    exigir(isinstance(esperado, dict) and set(esperado) == CLAVES_ESPERADO)
    exigir(isinstance(esperado["estado"], str) and _es_decimal(esperado["total"]))
    exigir(esperado["fecha_entrega"] is None or isinstance(esperado["fecha_entrega"], str))
    for nombre, claves in (("lineas", CLAVES_LINEA), ("sustituciones", CLAVES_SUSTITUCION), ("pendientes", CLAVES_PENDIENTE)):
        exigir(isinstance(esperado[nombre], list))
        for x in esperado[nombre]:
            exigir(isinstance(x, dict) and set(x) == claves)
    for l in esperado["lineas"]:
        exigir(isinstance(l["sku"], str) and _es_decimal(l["cantidad"], True) and _es_decimal(l["descuento_pct"], True))
        exigir(_es_decimal(l["precio_unitario"]) and _es_decimal(l["subtotal"]))
    for s in esperado["sustituciones"]:
        exigir(isinstance(s["sku_solicitado"], str) and isinstance(s["sku_entregado"], str) and _es_decimal(s["cantidad"], True))
    for p in esperado["pendientes"]:
        exigir(isinstance(p["motivo"], str) and isinstance(p["texto"], str))
        exigir(isinstance(p["opciones"], list) and all(isinstance(o, str) for o in p["opciones"]))
    exigir(isinstance(esperado["motivos_revision"], list) and all(isinstance(m, str) for m in esperado["motivos_revision"]))


def _cargar_casos(contenido: bytes) -> tuple[Caso, ...]:
    try:
        texto = contenido.decode("utf-8")
    except UnicodeDecodeError:
        raise ErrorIntegridad("FORMATO_CASOS") from None
    casos, vistos = [], set()
    for numero, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip():
            continue
        try:
            dato = json.loads(linea, parse_float=Decimal, parse_int=Decimal)
        except ValueError:
            raise ErrorIntegridad("FORMATO_CASOS", linea=numero) from None
        if not isinstance(dato, dict) or set(dato) != CLAVES_CASO or not isinstance(dato["id"], str) or not isinstance(dato["tipo"], str):
            raise ErrorIntegridad("FORMATO_CASOS", linea=numero)
        caso_id, entrada = dato["id"], dato["entrada"]
        if caso_id in vistos:
            raise ErrorIntegridad("CASO_DUPLICADO", linea=numero)
        vistos.add(caso_id)
        if not (
            isinstance(entrada, dict) and set(entrada) == {"cliente_id", "fecha_hora", "mensajes"}
            and isinstance(entrada["cliente_id"], str) and isinstance(entrada["fecha_hora"], str)
            and isinstance(entrada["mensajes"], list) and entrada["mensajes"] and all(isinstance(m, str) for m in entrada["mensajes"])
        ):
            raise ErrorIntegridad("FORMATO_ENTRADA", caso_id)
        _validar_esperado(dato["esperado"], caso_id)
        casos.append(Caso(caso_id, dato["tipo"], entrada, dato["esperado"]))
    return tuple(casos)


def _verificar_esperadas(contenido: bytes, casos: tuple[Caso, ...]) -> None:
    documento = _cargar_json(contenido, "FORMATO_ESPERADAS")
    if not isinstance(documento, dict) or not isinstance(documento.get("casos"), dict):
        raise ErrorIntegridad("FORMATO_ESPERADAS")
    if set(documento["casos"]) != {c.id for c in casos}:
        raise ErrorIntegridad("INCOHERENCIA_ESPERADAS")
    for caso in casos:
        dato = documento["casos"][caso.id]
        if not isinstance(dato, dict) or dato.get("esperado") != caso.esperado:
            raise ErrorIntegridad("INCOHERENCIA_ESPERADAS", caso.id)
        for clave, valor in (("cliente_id", caso.entrada["cliente_id"]), ("fecha_hora", caso.entrada["fecha_hora"]), ("n_mensajes", len(caso.entrada["mensajes"]))):
            if clave in dato and dato[clave] != valor:
                raise ErrorIntegridad("INCOHERENCIA_ESPERADAS", caso.id)


# ====================================================================== anotaciones


def skus_esperados(esperado: Mapping[str, Any]) -> list[frozenset[str]]:
    """`skus(e)` de cada producto esperado: líneas (con el SKU solicitado de su sustitución) y pendientes."""
    resultado = []
    for linea in esperado["lineas"]:
        solicitados = {s["sku_solicitado"] for s in esperado["sustituciones"] if s["sku_entregado"] == linea["sku"]}
        resultado.append(frozenset({linea["sku"]} | solicitados))
    resultado += [frozenset(p["opciones"]) for p in esperado["pendientes"]]
    return resultado


def _claves(valor: Any, caso: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(valor, list):
        raise ErrorIntegridad("ANOTACION_INVALIDA", caso)
    claves = []
    for clave in valor:
        if not isinstance(clave, list) or not clave or not all(isinstance(p, str) for p in clave):
            raise ErrorIntegridad("ANOTACION_INVALIDA", caso)
        normalizada = palabras(" ".join(clave))
        if not clave_valida(normalizada):
            raise ErrorIntegridad("CLAVE_GENERICA", caso)
        claves.append(normalizada)
    return tuple(claves)


def _solapan(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    return contiene(a, b) or contiene(b, a)


def _clave_generica(valor: Any, caso: str) -> tuple[str, ...]:
    """Una sola clave de 2 o más palabras, todas de la lista genérica (las demás van en `claves`)."""
    if not isinstance(valor, list) or not valor or not all(isinstance(p, str) for p in valor):
        raise ErrorIntegridad("CLAVE_GENERICA_NO_AUTORIZADA", caso)
    normalizada = palabras(" ".join(valor))
    if len(normalizada) < MIN_PALABRAS_CLAVE_GENERICA or not all(p in GENERICAS for p in normalizada):
        raise ErrorIntegridad("CLAVE_GENERICA_NO_AUTORIZADA", caso)
    return normalizada


def _validar_anotacion(dato: Any, caso: Caso, todos_criticos: bool, excepcion: bool = False) -> Anotacion:
    cid = caso.id
    permitidas = {"productos", "consultados", "texto_provisional", "critico", "justificacion_no_critico"}
    if not isinstance(dato, dict) or not set(dato) <= permitidas or not isinstance(dato.get("productos"), list):
        raise ErrorIntegridad("ANOTACION_INVALIDA", cid)
    critico = dato.get("critico", True)
    provisional = dato.get("texto_provisional", False)
    if not isinstance(critico, bool) or not isinstance(provisional, bool):
        raise ErrorIntegridad("ANOTACION_INVALIDA", cid)
    if not critico:
        justificacion = dato.get("justificacion_no_critico")
        if todos_criticos or not isinstance(justificacion, str) or not justificacion.strip():
            raise ErrorIntegridad("CRITICIDAD_INVALIDA", cid)
    esperados = skus_esperados(caso.esperado)
    if len(dato["productos"]) != len(esperados):  # antes de cualquier acceso por índice
        raise ErrorIntegridad("ANOTACION_INCOMPLETA", cid)
    n_lineas, pendientes = len(caso.esperado["lineas"]), caso.esperado["pendientes"]
    claves_productos, con_generica = [], 0
    for indice, producto in enumerate(dato["productos"]):
        if not isinstance(producto, dict) or "claves" not in producto or not set(producto) <= {"claves", "clave_generica"}:
            raise ErrorIntegridad("ANOTACION_INVALIDA", cid)
        claves = _claves(producto["claves"], cid)  # validación normal, sin excepciones
        if critico and not claves:
            raise ErrorIntegridad("PRODUCTO_SIN_CLAVE", cid)
        if "clave_generica" in producto:
            posicion = indice - n_lineas  # productos: líneas y luego pendientes
            sin_opciones = 0 <= posicion < len(pendientes) and not pendientes[posicion]["opciones"]
            if not excepcion or con_generica or not sin_opciones:
                raise ErrorIntegridad("CLAVE_GENERICA_NO_AUTORIZADA", cid)
            claves += (_clave_generica(producto["clave_generica"], cid),)
            con_generica += 1
        claves_productos.append(claves)
    if excepcion and not con_generica:
        raise ErrorIntegridad("EXCEPCION_SIN_USO", cid)
    union_esperada = frozenset().union(*esperados) if esperados else frozenset()
    consultados, indices = [], set()
    for c in dato.get("consultados", []):
        if not isinstance(c, dict) or not set(c) <= {"skus", "claves", "pedido_como"} or "pedido_como" not in c:
            raise ErrorIntegridad("ANOTACION_INVALIDA", cid)
        indice = c["pedido_como"]
        if indice is None:
            skus = c.get("skus", [])
            if not isinstance(skus, list) or not all(isinstance(s, str) for s in skus):
                raise ErrorIntegridad("ANOTACION_INVALIDA", cid)
            claves = _claves(c.get("claves", []), cid)
            if not skus and not claves:
                raise ErrorIntegridad("CONSULTADO_SIN_EVIDENCIA", cid)
            if set(skus) & union_esperada:
                raise ErrorIntegridad("SKU_CONSULTADO_ESPERADO", cid)
            consultados.append(Consultado(frozenset(skus), claves, None))
            continue
        if not _es_decimal(indice, True) or not 0 <= indice < len(esperados) or set(c) != {"pedido_como"} or int(indice) in indices:
            raise ErrorIntegridad("PEDIDO_COMO_INVALIDO", cid)
        indices.add(int(indice))
        consultados.append(Consultado(pedido_como=int(indice)))
    # Solapamiento por palabras entre productos distintos (esperados y solo consultados).
    grupos = list(claves_productos) + [c.claves for c in consultados if c.pedido_como is None]
    for i, a in enumerate(grupos):
        for b in grupos[i + 1 :]:
            if any(_solapan(x, y) for x in a for y in b):
                raise ErrorIntegridad("CLAVES_SOLAPADAS", cid)
    return Anotacion(tuple(claves_productos), tuple(consultados), provisional, critico)


def _cargar_anotaciones(contenido: bytes, casos: tuple[Caso, ...], descriptor: Descriptor) -> dict[str, Anotacion]:
    documento = _cargar_json(contenido, "FORMATO_ANOTACIONES")
    if not isinstance(documento, dict) or not isinstance(documento.get("casos"), dict):
        raise ErrorIntegridad("FORMATO_ANOTACIONES")
    if set(documento["casos"]) != {c.id for c in casos}:
        raise ErrorIntegridad("ANOTACIONES_INCOMPLETAS")
    excepciones = descriptor.excepciones_clave_generica
    return {c.id: _validar_anotacion(documento["casos"][c.id], c, descriptor.todos_criticos, c.id in excepciones) for c in casos}


# ====================================================================== carga verificada


def excepcion_autorizada(id_: Any, rol: Any, privado: Any, sha256: Any, casos: Any, autorizados: Any) -> bool:
    """Regla única de la excepción, usada por el registro y por `cargar()`: par autorizado (lo que
    implica `id == "D39"`), `validacion_privada`, `privado is True` y los tres hashes del conjunto
    idénticos a los autorizados para ese id. Sin autorización para el id, el resultado es False."""
    vinculados = autorizados.get(id_) if isinstance(autorizados, Mapping) and isinstance(id_, str) else None
    return (
        isinstance(casos, frozenset) and bool(casos)
        and all((id_, caso) in EXCEPCIONES_CLAVE_GENERICA for caso in casos)
        and rol == "validacion_privada" and privado is True
        and isinstance(sha256, Mapping) and isinstance(vinculados, Mapping)
        and set(sha256) == ARCHIVOS_VINCULADOS and dict(sha256) == dict(vinculados)
    )


def _verificar_excepcion(descriptor: Descriptor, autorizados: Mapping[str, Mapping[str, str]]) -> None:
    """Independiente del registro: aunque el descriptor se construya directamente, la excepción
    exige la regla completa, incluido el vínculo con los hashes autorizados que recibe `cargar()`."""
    d = descriptor
    if d.excepciones_clave_generica and not excepcion_autorizada(d.id, d.rol, d.privado, d.sha256, d.excepciones_clave_generica, autorizados):
        raise ErrorIntegridad("REGISTRO_INVALIDO")


def cargar(descriptor: Descriptor, rutas: Mapping[str, Path], autorizados: Mapping[str, Mapping[str, str]] = SIN_AUTORIZACIONES) -> Conjunto:
    """Fase 1: hashes de todos los archivos, formato, recuentos, coherencia y anotaciones.

    `autorizados` solo se usa para la excepción de clave genérica: el descriptor debe coincidir con
    ellos (antes de leer nada) y cada archivo con el descriptor (al leerlo), así que los archivos
    quedan vinculados a la autorización. Sin `autorizados`, la excepción se rechaza."""
    if descriptor.rol not in ROLES or "casos" not in descriptor.sha256 or "anotaciones" not in descriptor.sha256:
        raise ErrorIntegridad("DESCRIPTOR_INVALIDO")
    if set(descriptor.sha256) - {"casos", "esperadas", "anotaciones"}:
        raise ErrorIntegridad("DESCRIPTOR_INVALIDO")
    _verificar_excepcion(descriptor, autorizados)  # antes de leer ningún archivo
    contenidos = {}
    for nombre, hash_autorizado in descriptor.sha256.items():
        ruta = rutas.get(nombre)
        if ruta is None or not Path(ruta).is_file():
            raise ErrorIntegridad("ARCHIVO_FALTANTE")
        contenido = Path(ruta).read_bytes()
        if hashlib.sha256(contenido).hexdigest() != hash_autorizado:
            raise ErrorIntegridad("HASH_DISTINTO")
        contenidos[nombre] = contenido
    casos = _cargar_casos(contenidos["casos"])
    if len(casos) != descriptor.n_casos:
        raise ErrorIntegridad("RECUENTO_CASOS")
    if descriptor.n_mensajes is not None and sum(len(c.entrada["mensajes"]) for c in casos) != descriptor.n_mensajes:
        raise ErrorIntegridad("RECUENTO_MENSAJES")
    if "esperadas" in contenidos:
        _verificar_esperadas(contenidos["esperadas"], casos)
    if not descriptor.excepciones_clave_generica <= {c.id for c in casos}:  # los casos declarados existen
        raise ErrorIntegridad("REGISTRO_INVALIDO")
    anotaciones = _cargar_anotaciones(contenidos["anotaciones"], casos, descriptor)
    return Conjunto(descriptor, casos, anotaciones)


def cargar_todos(pares: list[tuple[Descriptor, Mapping[str, Path]]],
                 autorizados: Mapping[str, Mapping[str, str]] = SIN_AUTORIZACIONES) -> list[Conjunto]:
    """Verifica todos los conjuntos antes de devolver ninguno (ninguna petición antes de esto)."""
    return [cargar(d, r, autorizados) for d, r in pares]
