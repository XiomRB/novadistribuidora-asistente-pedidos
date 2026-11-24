"""Plegado de eventos: aplica en orden los eventos ya anclados sobre una lista de ítems.

Un ítem es una línea (SKU solicitado y cantidad en unidades de venta) o un pendiente.
Los ítems nunca se borran: cambian de estado (`eliminado`, `reemplazado`, `fusionado`) y
guardan su bitácora, de modo que toda referencia (`ref`) se resuelve siguiendo la cadena
de sucesores hasta el ítem activo.

Reglas aprobadas que implementa (ver CLAUDE.md y el plan de E1b-2a):
- agregar: suma por SKU (si ambas cantidades son convertibles); D47 (fusión de ambiguos);
  D62 (cantidad 0 sin efecto); D38 (agotado sin sustituto antes que la unidad).
- corregir / precisar: D37 + D75 (ref inválido o en conflicto: sin cambios y pendiente),
  D10 + D76 (sin ref: único ítem compatible por atributos), D13 (varios: pendiente),
  D11 + D48 + D48-a/b/c (reemplazo atómico de producto), D63 (solo cantidad de un ambiguo),
  D69 (producto de un ambiguo: combinar y resolver de nuevo).
- quitar: D13, D37 + D75, D57 (exclusión anticipada del habitual del mismo mensaje),
  D58 (quitar algo ya eliminado no tiene efecto).
- habitual: D53, D70, D73 (habitual.py), D07, D42 y agotados.

Nada de este módulo usa texto de los mensajes en el diagnóstico: solo códigos y posiciones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.datos.modelos import Datos
from app.datos.normalizacion import normalizar_texto
from app.dominio.atributos import Atributos, VocabularioAtributos, a_descripcion, combinar
from app.dominio.catalogo import IndiceCatalogo, Resolucion, TipoResolucion
from app.dominio.diagnostico import (
    DiagAccion,
    DiagDesacuerdo,
    DiagEvento,
    DiagItem,
    DiagMedidas,
    Diagnostico,
    posicion,
)
from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Evento
from app.dominio.habitual import ultimo_entregado
from app.dominio.resultado import Motivo, Pendiente
from app.dominio.texto import EventoAnclado, extraer_medidas, localizar, texto_original
from app.dominio.unidades import CodigoConversion, Conversion, LexicoUnidades, convertir

CERO = Decimal(0)
CODIGOS_DESACUERDO = ("CONTRADICCION_LLM", "SKU_LLM_INEXISTENTE", "SIN_EVIDENCIA_TEXTUAL", "NUMERO_IGNORADO")


class Clase(StrEnum):
    LINEA = "linea"
    PENDIENTE = "pendiente"


class EstadoItem(StrEnum):
    ACTIVO = "activo"
    ELIMINADO = "eliminado"
    REEMPLAZADO = "reemplazado"
    FUSIONADO = "fusionado"


@dataclass(frozen=True)
class Entrada:
    """Cantidad tal como se expresó (para sumar, corregir o reconvertir sin perder información)."""

    evento: str | None
    cantidad: Decimal | None
    incierta: bool = False
    unidad_declarada: str = "venta"
    unidad_texto: str | None = None

    @classmethod
    def de_evento(cls, evento: Evento) -> Entrada:
        return cls(evento.id, evento.cantidad_decimal(), evento.cantidad_incierta, evento.unidad, evento.unidad_texto)


@dataclass
class Item:
    id: str
    clase: Clase
    sku: str | None = None
    cantidad: Decimal | None = None
    motivo: Motivo | None = None
    opciones: tuple[str, ...] = ()
    texto: str = ""  # solo para la respuesta del contrato; nunca va al diagnóstico
    entradas: list[Entrada] = field(default_factory=list)
    origen: list[str] = field(default_factory=list)
    estado: EstadoItem = EstadoItem.ACTIVO
    sucesor: str | None = None
    atributos: Atributos = field(default_factory=Atributos)
    desde_habitual: bool = False
    fusionable: bool = True  # D47: solo ambiguos creados por agregar, sin ref

    @property
    def activo(self) -> bool:
        return self.estado is EstadoItem.ACTIVO

    def skus(self) -> set[str]:
        return ({self.sku} if self.sku else set()) | set(self.opciones)


@dataclass
class ResultadoPlegado:
    items: list[Item]
    eventos: list[DiagEvento]
    acciones: list[DiagAccion]
    medidas: list[DiagMedidas]
    desacuerdos: list[DiagDesacuerdo]
    habitual_usado: bool
    creo_items: bool

    def lineas_activas(self) -> list[Item]:
        return [i for i in self.items if i.activo and i.clase is Clase.LINEA]

    def pendientes_activos(self) -> list[Item]:
        return [i for i in self.items if i.activo and i.clase is Clase.PENDIENTE]

    def pendientes(self) -> tuple[Pendiente, ...]:
        return tuple(Pendiente(i.motivo, i.texto, i.opciones) for i in self.pendientes_activos())

    def diagnostico(self, salida=None) -> Diagnostico:
        """Diagnóstico del plegado (y de las sustituciones, si se pasa la salida de
        `sustitucion.aplicar_sustituciones`). Sin textos ni identificadores de pedido."""
        return Diagnostico(
            eventos=tuple(self.eventos),
            items=self.diag_items(),
            acciones=tuple(self.acciones),
            medidas_rechazo=tuple(self.medidas),
            desacuerdos=tuple(self.desacuerdos),
            sustituciones=salida.diagnostico if salida is not None else (),
            salida_lineas=salida.items_por_linea if salida is not None else (),
            salida_pendientes=tuple(i.id for i in self.pendientes_activos()),
            habitual_usado=self.habitual_usado,
        )

    def diag_items(self) -> tuple[DiagItem, ...]:
        return tuple(
            DiagItem(
                i.id, i.clase.value, i.estado.value, i.sku, i.motivo.value if i.motivo else None,
                i.opciones, tuple(i.origen), i.sucesor,
            )
            for i in self.items
        )


def _texto_decimal(valor: Decimal | None) -> str | None:
    return None if valor is None else f"{valor.normalize():f}"


class Plegador:
    def __init__(
        self,
        entrada: EntradaPedido,
        datos: Datos,
        indice: IndiceCatalogo,
        lexico: LexicoUnidades,
        vocabulario: VocabularioAtributos | None = None,
    ):
        self.entrada = entrada
        self.datos = datos
        self.indice = indice
        self.lexico = lexico
        self.vocab = vocabulario or VocabularioAtributos(datos, indice)
        self.items: list[Item] = []
        self._por_id: dict[str, Item] = {}
        self.por_evento: dict[str, str] = {}
        self.por_evento_habitual: dict[str, list[str]] = {}
        self.eventos: list[DiagEvento] = []
        self.acciones: list[DiagAccion] = []
        self.medidas: list[DiagMedidas] = []
        self.desacuerdos: list[DiagDesacuerdo] = []
        self.habitual_usado = False
        self._habitual_expandido = False
        self._diferidas: list[EventoAnclado] = []
        self._creo_items = False

    # ================================================================== utilidades

    def _nuevo_id(self) -> str:
        return f"i{len(self.items) + 1}"

    def _accion(self, item: Item, evento: str | None, accion: str, sku_antes=None, sku_despues=None, cant_antes=None, cant_despues=None):
        self.acciones.append(
            DiagAccion(item.id, evento, accion, sku_antes, sku_despues, _texto_decimal(cant_antes), _texto_decimal(cant_despues))
        )

    def _crear(self, clase: Clase, evento: str | None, **campos) -> Item:
        item = Item(id=self._nuevo_id(), clase=clase, **campos)
        self.items.append(item)
        self._por_id[item.id] = item
        self._creo_items = True
        self._accion(item, evento, "CREAR", sku_despues=item.sku, cant_despues=item.cantidad)
        return item

    def _seguir(self, item_id: str) -> Item:
        item = self._por_id[item_id]
        while item.estado in (EstadoItem.REEMPLAZADO, EstadoItem.FUSIONADO) and item.sucesor:
            item = self._por_id[item.sucesor]
        return item

    def _activos(self, excluir: Item | None = None) -> list[Item]:
        return [i for i in self.items if i.activo and i is not excluir]

    def _registrar(self, ea: EventoAnclado, codigo: str, item: Item | None = None, **extra) -> None:
        e = ea.evento
        self.eventos.append(
            DiagEvento(
                evento=e.id, tipo=e.tipo, codigo=codigo, posicion=posicion(ea.span),
                candidatos_llm=tuple(e.candidatos), sku=extra.get("sku", item.sku if item else None),
                opciones=extra.get("opciones", item.opciones if item else ()),
                cantidad=_texto_decimal(extra.get("cantidad", item.cantidad if item else None)),
                codigo_unidad=extra.get("codigo_unidad"), item=item.id if item else None,
            )
        )

    def _fragmento(self, ea: EventoAnclado) -> str:
        return texto_original(ea.span, self.entrada) if ea.span is not None else ea.evento.texto

    def _texto_pendiente(self, ea: EventoAnclado) -> str:
        """D59 / D59-a: `producto` solo si se encuentra dentro del fragmento anclado."""
        fragmento = self._fragmento(ea)
        producto = ea.evento.producto
        if producto and localizar(producto, fragmento, 0) is not None:
            return producto
        return fragmento

    def _descripcion(self, ea: EventoAnclado) -> str:
        return ea.evento.descripcion() or self._fragmento(ea)

    def _resolver(self, ea: EventoAnclado, descripcion: str) -> Resolucion:
        r = self.indice.resolver(descripcion, ea.evento.candidatos)
        for codigo in r.codigos:
            if codigo in CODIGOS_DESACUERDO:
                self.desacuerdos.append(DiagDesacuerdo(ea.evento.id, codigo))
            if codigo == "MEDIDA_SIN_PRODUCTO":
                # D67: solo medidas explícitas de la descripción del evento, normalizadas.
                explicitas = [m for m in extraer_medidas(ea.evento.descripcion() or descripcion, self.indice.palabras_cantidad) if m.unidad]
                self.medidas.append(
                    DiagMedidas(
                        ea.evento.id, posicion(ea.span),
                        tuple(sorted(f"{m.valor.normalize():f}{m.unidad}" for m in explicitas)), codigo,
                    )
                )
        return r

    def _convertir(self, entrada: Entrada, sku: str, evento: str | None = None) -> Conversion:
        c = convertir(
            cantidad=entrada.cantidad, cantidad_incierta=entrada.incierta, unidad_declarada=entrada.unidad_declarada,
            unidad_texto=entrada.unidad_texto, producto=self.datos.productos[sku], lexico=self.lexico,
        )
        if c.desacuerdo_llm and evento:
            self.desacuerdos.append(DiagDesacuerdo(evento, "DESACUERDO_UNIDAD"))
        return c

    def _convertir_todas(self, entradas: Sequence[Entrada], sku: str, evento: str | None) -> tuple[Decimal | None, str]:
        """Suma de todas las entradas convertidas; None si alguna no es convertible."""
        total = CERO
        for entrada in entradas:
            c = self._convertir(entrada, sku, evento)
            if not c.convertible:
                return None, c.codigo.value
            total += c.cantidad_venta
        return total, CodigoConversion.OK.value

    def _agotado_sin_sustituto(self, sku: str) -> bool:
        producto = self.datos.productos[sku]
        if producto.disponible:
            return False
        sustituto = self.datos.productos.get(producto.sustituto_sku) if producto.sustituto_sku else None
        return sustituto is None or not sustituto.disponible

    def _ordenar(self, skus) -> tuple[str, ...]:
        orden = {s: i for i, s in enumerate(self.datos.productos)}
        return tuple(sorted(set(skus), key=lambda s: orden.get(s, len(orden))))

    # ================================================================== creación de ítems

    def _linea_o_suma(self, sku: str, cantidad: Decimal, entradas, origen, atributos, evento, excluir=None, desde_habitual=False) -> Item:
        existente = next(
            (i for i in self._activos(excluir) if i.clase is Clase.LINEA and i.sku == sku), None
        )
        if existente is not None:
            antes = existente.cantidad
            existente.cantidad = antes + cantidad
            existente.entradas.extend(entradas)
            existente.origen.extend(o for o in origen if o not in existente.origen)
            self._accion(existente, evento, "SUMAR", sku, sku, antes, existente.cantidad)
            return existente
        return self._crear(
            Clase.LINEA, evento, sku=sku, cantidad=cantidad, entradas=list(entradas), origen=list(origen),
            atributos=atributos, desde_habitual=desde_habitual,
        )

    def _pendiente(self, motivo: Motivo, texto: str, opciones, entradas, origen, atributos, evento, sku=None, fusionable=False, excluir=None) -> Item:
        # `excluir`: el ítem que se está reemplazando nunca absorbe a su propio reemplazo.
        if motivo is Motivo.AGOTADO_SIN_SUSTITUTO and sku:
            existente = next(
                (i for i in self._activos(excluir) if i.clase is Clase.PENDIENTE and i.motivo is motivo and i.sku == sku), None
            )
            if existente is not None:
                existente.entradas.extend(entradas)
                existente.origen.extend(o for o in origen if o not in existente.origen)
                self._accion(existente, evento, "SUMAR")
                return existente
        if motivo is Motivo.PRODUCTO_AMBIGUO and fusionable:
            clave = normalizar_texto(texto)
            existente = next(
                (
                    i for i in self._activos(excluir)
                    if i.clase is Clase.PENDIENTE and i.motivo is motivo and i.fusionable
                    and normalizar_texto(i.texto) == clave and i.opciones == tuple(opciones)
                ),
                None,
            )
            if existente is not None:  # D47: una sola salida, todas las entradas conservadas
                existente.entradas.extend(entradas)
                existente.origen.extend(o for o in origen if o not in existente.origen)
                self._accion(existente, evento, "FUSIONAR")
                return existente
        return self._crear(
            Clase.PENDIENTE, evento, sku=sku, motivo=motivo, opciones=tuple(opciones), texto=texto,
            entradas=list(entradas), origen=list(origen), atributos=atributos, fusionable=fusionable,
        )

    def _materializar(self, ea: EventoAnclado, r: Resolucion, entradas, atributos, origen, fusionable, excluir=None) -> tuple[Item, str]:
        """Convierte una resolución en un ítem (operación atómica: línea completa o pendiente)."""
        e = ea.evento
        if r.tipo is TipoResolucion.RESUELTO:
            total, codigo = self._convertir_todas(entradas, r.sku, e.id)
            if total is not None and total > 0:
                return self._linea_o_suma(r.sku, total, entradas, origen, atributos, e.id, excluir), "RESUELTO"
            if total is not None and total == 0:
                return None, "CANTIDAD_CERO"
            item = self._pendiente(
                Motivo.CANTIDAD_NO_CONVERTIBLE, self._texto_pendiente(ea), (r.sku,), entradas, origen, atributos, e.id, sku=r.sku, excluir=excluir
            )
            return item, codigo
        if r.tipo is TipoResolucion.AGOTADO_SIN_SUSTITUTO:
            nombre = self.datos.productos[r.sku].nombre
            return self._pendiente(Motivo.AGOTADO_SIN_SUSTITUTO, nombre, (r.sku,), entradas, origen, atributos, e.id, sku=r.sku, excluir=excluir), "AGOTADO_SIN_SUSTITUTO"
        if r.tipo is TipoResolucion.AMBIGUO:
            item = self._pendiente(
                Motivo.PRODUCTO_AMBIGUO, self._texto_pendiente(ea), r.opciones, entradas, origen, atributos, e.id, fusionable=fusionable, excluir=excluir
            )
            return item, "AMBIGUO"
        item = self._pendiente(Motivo.PRODUCTO_NO_EXISTE, self._texto_pendiente(ea), (), entradas, origen, atributos, e.id, excluir=excluir)
        return item, "NO_EXISTE"

    def _pendiente_d37(self, ea: EventoAnclado, codigo: str, opciones) -> None:
        """D37 / D13 / D75: no se modifica nada y se registra un pendiente ambiguo."""
        item = self._pendiente(
            Motivo.PRODUCTO_AMBIGUO, self._texto_pendiente(ea), self._ordenar(opciones),
            [Entrada.de_evento(ea.evento)], [ea.evento.id], Atributos(), ea.evento.id,
        )
        self.por_evento[ea.evento.id] = item.id
        self._registrar(ea, codigo, item)

    # ================================================================== destino de un evento

    def _compatible(self, atributos: Atributos, item: Item) -> bool:
        """D76: al menos una coincidencia positiva y ninguna contradicción."""
        if atributos.vacio:
            return False
        if item.sku and item.motivo is not Motivo.PRODUCTO_AMBIGUO:
            return self.vocab.comparar(atributos, item.sku).compatible
        return any(self.vocab.comparar(atributos, s).compatible for s in item.opciones)

    def _destino(self, ea: EventoAnclado):
        """Devuelve (codigo, item, extra). Códigos: OK, REF_INVALIDA, REF_ELIMINADA,
        REF_CONFLICTO (D75), DESTINO_AMBIGUO (D13) y SIN_DESTINO."""
        e = ea.evento
        descripcion = e.descripcion()
        atributos = self.vocab.extraer(descripcion) if descripcion else Atributos()
        if e.ref is not None:
            if e.ref in self.por_evento_habitual:
                candidatos = [self._seguir(i) for i in self.por_evento_habitual[e.ref]]
                candidatos = [c for c in candidatos if c.activo and self._compatible(atributos, c)]
                if len(candidatos) == 1:
                    return "OK", candidatos[0], None
                if len(candidatos) > 1:
                    return "DESTINO_AMBIGUO", None, candidatos
                return "REF_INVALIDA", None, None
            if e.ref not in self.por_evento:
                return "REF_INVALIDA", None, None
            destino = self._seguir(self.por_evento[e.ref])
            if destino.estado is EstadoItem.ELIMINADO:
                return "REF_ELIMINADA", destino, None
            if descripcion and (not atributos.vacio or e.candidatos):
                # D75: la descripción identifica (con respaldo del catálogo) otro ítem activo.
                r = self.indice.resolver(descripcion, e.candidatos)
                if r.tipo is not TipoResolucion.NO_EXISTE:
                    skus = set(r.opciones) if r.tipo is TipoResolucion.AMBIGUO else {r.sku}
                    otros = [i for i in self._activos(destino) if i.skus() & skus]
                    if otros:
                        return "REF_CONFLICTO", destino, (otros, r)
            return "OK", destino, None
        compatibles = [i for i in self._activos() if self._compatible(atributos, i)]
        if len(compatibles) == 1:
            return "OK", compatibles[0], None
        if len(compatibles) > 1:
            return "DESTINO_AMBIGUO", None, compatibles
        return "SIN_DESTINO", None, None

    def _opciones_conflicto(self, destino: Item | None, extra) -> set[str]:
        opciones: set[str] = destino.skus() if destino else set()
        if isinstance(extra, tuple):
            otros, r = extra
            for otro in otros:
                opciones |= otro.skus()
            opciones |= set(r.opciones)
        elif isinstance(extra, list):
            for otro in extra:
                opciones |= otro.skus()
        return opciones

    # ================================================================== eventos

    def agregar(self, ea: EventoAnclado) -> None:
        e = ea.evento
        cantidad = e.cantidad_decimal()
        if cantidad is not None and cantidad == 0 and not e.cantidad_incierta:
            self._registrar(ea, "CANTIDAD_CERO")  # D62
            return
        descripcion = self._descripcion(ea)
        r = self._resolver(ea, descripcion)
        item, codigo = self._materializar(
            ea, r, [Entrada.de_evento(e)], self.vocab.extraer(descripcion), [e.id], fusionable=True
        )
        if item is None:
            self._registrar(ea, codigo)
            return
        self.por_evento[e.id] = item.id
        self._registrar(ea, codigo, item)

    def corregir(self, ea: EventoAnclado) -> None:
        self._corregir_o_precisar(ea)

    def precisar(self, ea: EventoAnclado) -> None:
        self._corregir_o_precisar(ea)

    def _corregir_o_precisar(self, ea: EventoAnclado) -> None:
        e = ea.evento
        codigo, destino, extra = self._destino(ea)
        if codigo == "REF_INVALIDA":
            r = self.indice.resolver(e.descripcion(), e.candidatos) if e.descripcion() else None
            self._pendiente_d37(ea, "REF_INVALIDA", r.opciones if r else ())
            return
        if codigo in ("REF_CONFLICTO", "DESTINO_AMBIGUO"):
            self._pendiente_d37(ea, codigo, self._opciones_conflicto(destino, extra))
            return
        if codigo == "REF_ELIMINADA":
            if e.tipo == "precisar":
                self._pendiente_d37(ea, "REF_ELIMINADA", destino.skus())
                return
            self._volver_a_agregar(ea, destino)
            return
        if codigo == "SIN_DESTINO":
            self.agregar(ea)  # D10: sin destino, corregir/precisar se tratan como agregar
            return
        self._aplicar_correccion(ea, destino)

    def _volver_a_agregar(self, ea: EventoAnclado, eliminado: Item) -> None:
        """corregir sobre una cadena que termina en un ítem eliminado: prevalece la última instrucción."""
        e = ea.evento
        descripcion = e.descripcion()
        atributos = self.vocab.extraer(descripcion) if descripcion else Atributos()
        nueva = self._entrada_nueva(e)
        entradas = [nueva] if nueva else list(eliminado.entradas)
        if atributos.vacio and eliminado.sku and eliminado.motivo is not Motivo.PRODUCTO_AMBIGUO:
            r = Resolucion(TipoResolucion.RESUELTO, sku=eliminado.sku, opciones=(eliminado.sku,))
            if self._agotado_sin_sustituto(eliminado.sku):
                r = Resolucion(TipoResolucion.AGOTADO_SIN_SUSTITUTO, sku=eliminado.sku, opciones=(eliminado.sku,))
            combinado = eliminado.atributos
        else:
            combinado = combinar(eliminado.atributos, atributos)
            r = self._resolver(ea, a_descripcion(combinado) or self._descripcion(ea))
        item, codigo = self._materializar(ea, r, entradas, combinado, [e.id], fusionable=False)
        if item is None:
            self._registrar(ea, codigo)
            return
        self.por_evento[e.id] = item.id
        self._registrar(ea, "REAGREGAR_" + codigo, item)

    @staticmethod
    def _entrada_nueva(evento: Evento) -> Entrada | None:
        if evento.cantidad is None and not evento.cantidad_incierta:
            return None
        return Entrada.de_evento(evento)

    def _aplicar_correccion(self, ea: EventoAnclado, destino: Item) -> None:
        e = ea.evento
        descripcion = e.descripcion()
        atributos = self.vocab.extraer(descripcion) if descripcion else Atributos()
        nueva = self._entrada_nueva(e)
        if destino.clase is Clase.LINEA:
            cambia_producto = not atributos.vacio and not self.vocab.cumple(atributos, destino.sku)
            if cambia_producto:
                self._reemplazar_linea(ea, destino, atributos, nueva)
            else:
                self._corregir_cantidad_linea(ea, destino, nueva, "PRECISION_COMPATIBLE" if not atributos.vacio else "SIN_EFECTO")
            return
        self._corregir_pendiente(ea, destino, atributos, nueva)

    def _corregir_cantidad_linea(self, ea: EventoAnclado, linea: Item, nueva: Entrada | None, codigo_sin_cantidad: str) -> None:
        e = ea.evento
        if nueva is None:
            self.por_evento[e.id] = linea.id
            self._registrar(ea, codigo_sin_cantidad, linea)
            return
        c = self._convertir(nueva, linea.sku, e.id)
        if c.codigo is CodigoConversion.CANTIDAD_CERO:
            self._eliminar(linea, e.id)
            self.por_evento[e.id] = linea.id
            self._registrar(ea, "CORREGIR_A_CERO", linea)
            return
        if c.convertible:
            antes = linea.cantidad
            linea.cantidad = c.cantidad_venta
            linea.entradas = [nueva]
            if e.id not in linea.origen:
                linea.origen.append(e.id)
            self._accion(linea, e.id, "CORREGIR_CANTIDAD", linea.sku, linea.sku, antes, linea.cantidad)
            self.por_evento[e.id] = linea.id
            self._registrar(ea, "CORREGIR_CANTIDAD", linea, codigo_unidad=c.codigo.value)
            return
        # Cantidad nueva no convertible o incierta: la corrección prevalece y nunca se confirma.
        pendiente = self._pendiente(
            Motivo.CANTIDAD_NO_CONVERTIBLE, self._texto_pendiente(ea), (linea.sku,), [nueva],
            linea.origen + [e.id], linea.atributos, e.id, sku=linea.sku,
        )
        self._sustituir_por(linea, pendiente, e.id, "REEMPLAZAR_POR_PENDIENTE")
        self.por_evento[e.id] = pendiente.id
        self._registrar(ea, "CORREGIR_NO_CONVERTIBLE", pendiente, codigo_unidad=c.codigo.value)

    def _reemplazar_linea(self, ea: EventoAnclado, linea: Item, atributos: Atributos, nueva: Entrada | None) -> None:
        """D48, D48-a, D48-b, D48-c: reemplazo atómico del producto de una línea."""
        e = ea.evento
        combinado = combinar(linea.atributos, atributos)
        r = self._resolver(ea, a_descripcion(combinado))
        entradas = [nueva] if nueva else list(linea.entradas)  # D48-b: cantidad tal como se expresó
        if r.tipo is TipoResolucion.RESUELTO and r.sku == linea.sku:
            self._corregir_cantidad_linea(ea, linea, nueva, "PRECISION_COMPATIBLE")
            return
        if r.tipo is TipoResolucion.RESUELTO:
            total, codigo = self._convertir_todas(entradas, r.sku, e.id)
            if total is not None and total > 0:
                nuevo = self._linea_o_suma(r.sku, total, entradas, linea.origen + [e.id], combinado, e.id, excluir=linea)
                self._sustituir_por(linea, nuevo, e.id, "REEMPLAZAR_PRODUCTO")
                self.por_evento[e.id] = nuevo.id
                self._registrar(ea, "REEMPLAZO", nuevo)
                return
            if total is not None and total == 0:
                self._eliminar(linea, e.id)
                self.por_evento[e.id] = linea.id
                self._registrar(ea, "CORREGIR_A_CERO", linea)
                return
            # D48-c: la línea queda exactamente igual; pendiente asociado al evento.
            self._accion(linea, e.id, "REEMPLAZO_RECHAZADO", linea.sku, r.sku, linea.cantidad, linea.cantidad)
            pendiente = self._pendiente(
                Motivo.CANTIDAD_NO_CONVERTIBLE, self._texto_pendiente(ea), (r.sku,), entradas, [e.id], combinado, e.id, sku=r.sku
            )
            self.por_evento[e.id] = pendiente.id
            self._registrar(ea, "REEMPLAZO_NO_CONVERTIBLE", pendiente, codigo_unidad=codigo)
            return
        # Agotado sin sustituto, ambiguo o inexistente: la línea se conserva y se agrega un pendiente.
        pendiente, codigo = self._materializar(ea, r, entradas, combinado, [e.id], fusionable=False, excluir=linea)
        self._accion(linea, e.id, "REEMPLAZO_RECHAZADO", linea.sku, r.sku, linea.cantidad, linea.cantidad)
        self.por_evento[e.id] = pendiente.id
        self._registrar(ea, "REEMPLAZO_" + codigo, pendiente)

    def _corregir_pendiente(self, ea: EventoAnclado, pendiente: Item, atributos: Atributos, nueva: Entrada | None) -> None:
        e = ea.evento
        if atributos.vacio:
            # Solo cantidad (D63 en ambiguos). En no convertibles se intenta convertir de nuevo.
            if nueva is None:
                self.por_evento[e.id] = pendiente.id
                self._registrar(ea, "SIN_EFECTO", pendiente)
                return
            if pendiente.motivo is Motivo.CANTIDAD_NO_CONVERTIBLE and pendiente.sku:
                c = self._convertir(nueva, pendiente.sku, e.id)
                if c.codigo is CodigoConversion.CANTIDAD_CERO:
                    self._eliminar(pendiente, e.id)
                    self.por_evento[e.id] = pendiente.id
                    self._registrar(ea, "CORREGIR_A_CERO", pendiente)
                    return
                if c.convertible:
                    linea = self._linea_o_suma(
                        pendiente.sku, c.cantidad_venta, [nueva], pendiente.origen + [e.id], pendiente.atributos, e.id, excluir=pendiente
                    )
                    self._sustituir_por(pendiente, linea, e.id, "RESOLVER_CANTIDAD")
                    self.por_evento[e.id] = linea.id
                    self._registrar(ea, "CORREGIR_CANTIDAD", linea)
                    return
            if nueva.cantidad is not None and nueva.cantidad == 0 and not nueva.incierta:
                self._eliminar(pendiente, e.id)
                self.por_evento[e.id] = pendiente.id
                self._registrar(ea, "CORREGIR_A_CERO", pendiente)
                return
            pendiente.entradas = [nueva]  # D63: se reemplazan las entradas y sigue pendiente
            if e.id not in pendiente.origen:
                pendiente.origen.append(e.id)
            self._accion(pendiente, e.id, "CORREGIR_CANTIDAD")
            self.por_evento[e.id] = pendiente.id
            self._registrar(ea, "CORREGIR_CANTIDAD_PENDIENTE", pendiente)
            return
        # D69: cambia el producto: combinar descripciones y resolver de nuevo (atómico).
        combinado = combinar(pendiente.atributos, atributos)
        r = self._resolver(ea, a_descripcion(combinado) or e.descripcion())
        entradas = [nueva] if nueva else list(pendiente.entradas)
        nuevo, codigo = self._materializar(ea, r, entradas, combinado, pendiente.origen + [e.id], fusionable=False, excluir=pendiente)
        if nuevo is None:  # cantidad 0
            self._eliminar(pendiente, e.id)
            self.por_evento[e.id] = pendiente.id
            self._registrar(ea, "CORREGIR_A_CERO", pendiente)
            return
        self._sustituir_por(pendiente, nuevo, e.id, "PRECISAR")
        self.por_evento[e.id] = nuevo.id
        self._registrar(ea, "PRECISAR_" + codigo, nuevo)

    def _sustituir_por(self, anterior: Item, nuevo: Item, evento: str, accion: str) -> None:
        if nuevo is anterior:  # la cadena de sucesores nunca puede formar un ciclo
            raise RuntimeError("Un ítem no puede ser su propio sucesor")
        fusionado = any(a.item == nuevo.id and a.accion == "SUMAR" for a in self.acciones[-1:])
        anterior.estado = EstadoItem.FUSIONADO if fusionado else EstadoItem.REEMPLAZADO
        anterior.sucesor = nuevo.id
        self._accion(anterior, evento, accion, anterior.sku, nuevo.sku, anterior.cantidad, nuevo.cantidad)

    def _eliminar(self, item: Item, evento: str | None) -> None:
        item.estado = EstadoItem.ELIMINADO
        self._accion(item, evento, "ELIMINAR", item.sku, None, item.cantidad, None)

    def quitar(self, ea: EventoAnclado, restantes: Sequence[EventoAnclado] = ()) -> None:
        e = ea.evento
        codigo, destino, extra = self._destino(ea)
        if codigo == "REF_ELIMINADA":
            self._registrar(ea, "QUITAR_YA_ELIMINADO", destino)  # D58
            return
        if codigo == "REF_INVALIDA":
            r = self.indice.resolver(e.descripcion(), e.candidatos) if e.descripcion() else None
            self._pendiente_d37(ea, "REF_INVALIDA", r.opciones if r else ())
            return
        if codigo in ("REF_CONFLICTO", "DESTINO_AMBIGUO"):
            self._pendiente_d37(ea, codigo, self._opciones_conflicto(destino, extra))
            return
        if codigo == "SIN_DESTINO":
            habitual_despues = any(r.evento.tipo == "habitual" and r.evento.mensaje == e.mensaje for r in restantes)
            if habitual_despues and not self._habitual_expandido:
                self._diferidas.append(ea)  # D57
                self._registrar(ea, "QUITAR_DIFERIDO")
            else:
                self._registrar(ea, "QUITAR_SIN_DESTINO")
            return
        self._eliminar(destino, e.id)
        self.por_evento[e.id] = destino.id
        self._registrar(ea, "QUITAR", destino)

    def habitual(self, ea: EventoAnclado) -> None:
        e = ea.evento
        if self._habitual_expandido:
            self._registrar(ea, "HABITUAL_REPETIDO")
            return
        self._habitual_expandido = True
        pedido = ultimo_entregado(self.datos, self.entrada.cliente_id, self.entrada.fecha_hora.date())
        if pedido is None:  # D07
            item = self._pendiente(Motivo.PRODUCTO_AMBIGUO, self._fragmento(ea), (), [], [e.id], Atributos(), e.id)
            self.por_evento[e.id] = item.id
            self._registrar(ea, "HABITUAL_SIN_HISTORIAL", item)
            return
        self.habitual_usado = True  # D74: solo el indicador; el pedido_id no sale de aquí
        creados: list[str] = []
        for linea in pedido.lineas:
            entradas = [Entrada(None, linea.cantidad)]
            if linea.sku not in self.datos.productos:  # D42
                item = self._pendiente(Motivo.PRODUCTO_NO_EXISTE, linea.sku, (), entradas, ["habitual", e.id], Atributos(), e.id)
            elif self._agotado_sin_sustituto(linea.sku):
                nombre = self.datos.productos[linea.sku].nombre
                item = self._pendiente(
                    Motivo.AGOTADO_SIN_SUSTITUTO, nombre, (linea.sku,), entradas, ["habitual", e.id],
                    self.vocab.del_producto(linea.sku), e.id, sku=linea.sku,
                )
            else:
                item = self._linea_o_suma(
                    linea.sku, linea.cantidad, entradas, ["habitual", e.id], self.vocab.del_producto(linea.sku), e.id, desde_habitual=True
                )
            item.desde_habitual = True
            creados.append(item.id)
        self.por_evento_habitual[e.id] = creados
        self._registrar(ea, "HABITUAL")
        self._aplicar_diferidas(ea, creados)

    def _aplicar_diferidas(self, ea_habitual: EventoAnclado, creados: list[str]) -> None:
        for diferida in [d for d in self._diferidas if d.evento.mensaje == ea_habitual.evento.mensaje]:
            self._diferidas.remove(diferida)
            descripcion = diferida.evento.descripcion()
            atributos = self.vocab.extraer(descripcion) if descripcion else Atributos()
            unicos = {c.id: c for c in (self._seguir(i) for i in creados)}
            candidatos = [c for c in unicos.values() if c.activo and self._compatible(atributos, c)]
            if len(candidatos) == 1:
                self._eliminar(candidatos[0], diferida.evento.id)
                self.por_evento[diferida.evento.id] = candidatos[0].id
                self._registrar(diferida, "QUITAR_DIFERIDO_APLICADO", candidatos[0])
            elif len(candidatos) > 1:
                self._pendiente_d37(diferida, "DESTINO_AMBIGUO", self._opciones_conflicto(None, candidatos))
            else:
                self._registrar(diferida, "QUITAR_SIN_DESTINO")

    # ================================================================== ejecución

    def plegar(self, eventos: Sequence[EventoAnclado]) -> ResultadoPlegado:
        for posicion_evento, ea in enumerate(eventos):
            tipo = ea.evento.tipo
            if tipo == "agregar":
                self.agregar(ea)
            elif tipo == "corregir":
                self.corregir(ea)
            elif tipo == "precisar":
                self.precisar(ea)
            elif tipo == "quitar":
                self.quitar(ea, eventos[posicion_evento + 1 :])
            elif tipo == "habitual":
                self.habitual(ea)
        for diferida in self._diferidas:
            self._registrar(diferida, "QUITAR_SIN_DESTINO")
        self._diferidas.clear()
        return ResultadoPlegado(
            self.items, self.eventos, self.acciones, self.medidas, self.desacuerdos, self.habitual_usado, self._creo_items
        )


def plegar(
    *,
    entrada: EntradaPedido,
    eventos: Sequence[EventoAnclado],
    datos: Datos,
    indice: IndiceCatalogo,
    lexico: LexicoUnidades,
    vocabulario: VocabularioAtributos | None = None,
) -> ResultadoPlegado:
    return Plegador(entrada, datos, indice, lexico, vocabulario).plegar(eventos)
