"""Mensaje de confirmación al cliente, determinista (D16, D49, D65; secciones 3.6 y 3.7).

Se construye solo con datos del catálogo y del pedido calculado: **nunca con texto del
cliente** (ni los mensajes ni el texto de los pendientes) y sin montos (D16).

- Saludo según la hora de `fecha_hora` (hora local de Guatemala): de 00:00 a 11:59
  "Buenos días"; de 12:00 a 18:59 "Buenas tardes"; de 19:00 a 23:59 "Buenas noches".
- Fecha en palabras con tablas propias ("jueves 26 de noviembre"), sin depender del locale.
- Líneas: "2 fardos de Kola Norte 600 ml", con plural por regla (vocal +s, consonante +es,
  terminación en "y" +s).
- No promete productos agotados ni pendientes: solo enumera las líneas calculadas.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.datos.modelos import Datos
from app.datos.normalizacion import normalizar_texto
from app.dominio.catalogo import IndiceCatalogo
from app.dominio.clasificacion import Clasificacion
from app.dominio.resultado import Estado, Motivo, Pendiente, ResultadoCierre
from app.dominio.texto import singular

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
VOCALES = frozenset("aeiouáéíóú")

CONSULTA = "Gracias por escribirnos. Un asesor atenderá su consulta."
CANCELADO = "Entendimos que por ahora no desea pedir nada; si fue un error, escríbanos."
SIN_EFECTO = "Un asesor atenderá su solicitud."
AMBIGUO = "Sobre la solicitud de {grupo}, un asesor le confirmará el producto."  # D49
AMBIGUO_SIN_OPCIONES = "Sobre parte de su pedido, un asesor le confirmará los productos."  # D65
NO_EXISTE = "Algunos productos solicitados no los manejamos."
AGOTADO = "{nombre} no está disponible por ahora."
NO_CONVERTIBLE = "Un asesor le confirmará la cantidad de {nombre}."
SUSTITUCION = "En lugar de {solicitado} le enviaremos {entregado}."
CREDITO = "Un asesor revisará su pedido antes de enviarlo."
REVISION = "Un asesor confirmará su pedido."
GRACIAS = "¡Gracias!"


def saludo(fecha_hora: datetime) -> str:
    if fecha_hora.hour < 12:
        return "Buenos días"
    if fecha_hora.hour < 19:
        return "Buenas tardes"
    return "Buenas noches"


def fecha_en_palabras(fecha: date) -> str:
    return f"{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]}"


def plural(palabra: str) -> str:
    if not palabra:
        return palabra
    final = palabra[-1].lower()
    if final in VOCALES or final == "y":
        return palabra + "s"
    return palabra + "es"


def _cantidad(valor: Decimal) -> str:
    return f"{valor.normalize():f}"


def _unir(partes: list[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " y " + partes[-1]


class RedactorConfirmacion:
    def __init__(self, datos: Datos, indice: IndiceCatalogo):
        self.datos = datos
        self.indice = indice

    def _nombre(self, sku: str) -> str:
        producto = self.datos.productos.get(sku)
        return producto.nombre if producto is not None else "un producto"

    def _grupo(self, sku: str) -> str:
        """Sustantivo del grupo tal como se escribe en el nombre del catálogo ("jabón")."""
        grupo = self.indice.grupo(sku)
        for palabra in self._nombre(sku).split():
            if singular(normalizar_texto(palabra)) == grupo:
                return palabra.lower()
        return grupo

    def _linea(self, sku: str, cantidad: Decimal) -> str:
        producto = self.datos.productos[sku]
        unidad = producto.unidad_venta if cantidad == 1 else plural(producto.unidad_venta)
        return f"{_cantidad(cantidad)} {unidad} de {producto.nombre}"

    def _pendientes(self, pendientes: tuple[Pendiente, ...]) -> list[str]:
        frases: list[str] = []

        def agregar(frase: str) -> None:
            if frase not in frases:
                frases.append(frase)

        for p in pendientes:
            opciones = [s for s in p.opciones if s in self.datos.productos]
            if p.motivo is Motivo.PRODUCTO_AMBIGUO:
                agregar(AMBIGUO.format(grupo=self._grupo(opciones[0])) if opciones else AMBIGUO_SIN_OPCIONES)
            elif p.motivo is Motivo.PRODUCTO_NO_EXISTE:
                agregar(NO_EXISTE)
            elif p.motivo is Motivo.AGOTADO_SIN_SUSTITUTO:
                agregar(AGOTADO.format(nombre=self._nombre(opciones[0])) if opciones else NO_EXISTE)
            elif p.motivo is Motivo.CANTIDAD_NO_CONVERTIBLE:
                agregar(NO_CONVERTIBLE.format(nombre=self._nombre(opciones[0])) if opciones else AMBIGUO_SIN_OPCIONES)
        return frases

    def redactar(self, resultado: ResultadoCierre, clasificacion: Clasificacion, fecha_hora: datetime) -> str:
        inicio = f"¡{saludo(fecha_hora)}!"
        if clasificacion is Clasificacion.CONSULTA:
            return f"{inicio} {CONSULTA}"
        if clasificacion is Clasificacion.PEDIDO_CANCELADO:
            return f"{inicio} {CANCELADO}"
        if clasificacion is Clasificacion.SIN_EFECTO or resultado.estado is Estado.FUERA_DE_ALCANCE:
            return f"{inicio} {SIN_EFECTO}"

        partes = [inicio]
        if resultado.lineas:
            partes.append("Recibimos su pedido: " + _unir([self._linea(l.sku, l.cantidad) for l in resultado.lineas]) + ".")
        else:
            partes.append("Recibimos su pedido.")
        for s in resultado.sustituciones:
            partes.append(SUSTITUCION.format(solicitado=self._nombre(s.sku_solicitado), entregado=self._nombre(s.sku_entregado)))
        partes.extend(self._pendientes(resultado.pendientes))
        if Motivo.CREDITO_EXCEDIDO in resultado.motivos_revision:
            partes.append(CREDITO)
        if resultado.fecha_entrega is not None:
            partes.append(f"Entrega el {fecha_en_palabras(resultado.fecha_entrega)}.")
        if resultado.estado is Estado.REQUIERE_REVISION:
            partes.append(REVISION)
        partes.append(GRACIAS)
        return " ".join(partes)
