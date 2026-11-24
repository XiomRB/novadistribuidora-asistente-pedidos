"""Orquestador `procesar_pedido`: de la interpretación estructurada al resultado del contrato.

Pasos, en este orden (plan de E1b-2, B11, D72):
1. El cliente debe existir (`ClienteNoEncontrado`), antes que cualquier otra comprobación.
2. Validación de la interpretación por el punto de entrada único `validar_interpretacion`
   (esquema de E1b-1 con el número de mensajes como contexto y el límite combinado de D72),
   **antes** del anclaje.
3. Anclaje (E1b-1). Un evento sin ancla se descarta (`SIN_ANCLA`); un evento dentro de una
   consulta pura según el código se descarta (`DESCARTADO_CONSULTA`, D36). Los demás son los
   eventos efectivos.
4. Plegado (E1b-2a) de los eventos efectivos.
5. Sustituciones (E1b-2a).
6. Omisiones (D05, D59, D60, D61): solo cubren los eventos efectivos y las consultas puras
   del código.
7. Clasificación (`CONSULTA`, `PEDIDO_CANCELADO`, `SIN_EFECTO`, `PEDIDO`), de la que sale
   `hay_eventos_pedido`.
8. Cierre de E1a (`cerrar_pedido`, sin modificarlo). Pendientes en el orden de D64: primero
   los de eventos y del habitual en orden de creación; al final los de omisión por posición.
9. Mensaje al cliente (plantilla determinista).
10. Diagnóstico: solo códigos, posiciones, SKU, cantidades y medidas (nunca textos,
    `cliente_id` ni `pedido_id`).

D68: el índice del catálogo, el léxico de unidades, el vocabulario de atributos y el detector
de omisiones se pueden construir una sola vez (`Recursos`) y reutilizar entre solicitudes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.datos.modelos import Datos
from app.dominio.atributos import VocabularioAtributos
from app.dominio.catalogo import IndiceCatalogo
from app.dominio.cierre import cerrar_pedido
from app.dominio.clasificacion import Clasificacion, clasificar
from app.dominio.consultas import dentro_de_consulta, oraciones
from app.dominio.diagnostico import DiagEvento, Diagnostico, posicion
from app.dominio.entrada import EntradaPedido
from app.dominio.errores import ClienteNoEncontrado
from app.dominio.esquema_eventos import Interpretacion
from app.dominio.limites import validar_interpretacion
from app.dominio.omisiones import DetectorOmisiones, ResultadoOmisiones
from app.dominio.plegado import ResultadoPlegado, plegar
from app.dominio.resultado import ResultadoCierre
from app.dominio.sustitucion import Salida, aplicar_sustituciones
from app.dominio.texto import EventoAnclado, anclar
from app.dominio.unidades import LexicoUnidades
from app.mensajes.confirmacion import RedactorConfirmacion

SIN_ANCLA = "SIN_ANCLA"
DESCARTADO_CONSULTA = "DESCARTADO_CONSULTA"


@dataclass(frozen=True)
class Recursos:
    """Estructuras derivadas del catálogo, reutilizables entre solicitudes (D68)."""

    datos: Datos
    indice: IndiceCatalogo
    lexico: LexicoUnidades
    vocabulario: VocabularioAtributos
    detector: DetectorOmisiones
    redactor: RedactorConfirmacion

    @classmethod
    def construir(
        cls, datos: Datos, indice: IndiceCatalogo | None = None, lexico: LexicoUnidades | None = None
    ) -> Recursos:
        lexico = lexico or LexicoUnidades(datos)
        indice = indice or IndiceCatalogo(datos, lexico.palabras_cantidad())
        return cls(
            datos=datos,
            indice=indice,
            lexico=lexico,
            vocabulario=VocabularioAtributos(datos, indice),
            detector=DetectorOmisiones(datos, indice, lexico),
            redactor=RedactorConfirmacion(datos, indice),
        )


@dataclass(frozen=True)
class ResultadoPedido:
    cierre: ResultadoCierre
    mensaje_cliente: str
    clasificacion: Clasificacion
    diagnostico: Diagnostico


def _descartado(ea: EventoAnclado, codigo: str) -> DiagEvento:
    e = ea.evento
    return DiagEvento(evento=e.id, tipo=e.tipo, codigo=codigo, posicion=posicion(ea.span), candidatos_llm=tuple(e.candidatos))


def procesar_pedido(
    entrada: EntradaPedido,
    interpretacion: Interpretacion | dict[str, Any] | str | bytes,
    datos: Datos,
    indice: IndiceCatalogo | None = None,
    lexico: LexicoUnidades | None = None,
    recursos: Recursos | None = None,
) -> ResultadoPedido:
    # 1. Cliente.
    if entrada.cliente_id not in datos.clientes:
        raise ClienteNoEncontrado(entrada.cliente_id)

    # 2. Validación con contexto y límites (D56, D72), antes del anclaje.
    bruto = interpretacion.model_dump() if isinstance(interpretacion, Interpretacion) else interpretacion
    interp = validar_interpretacion(bruto, len(entrada.mensajes))

    if recursos is None or recursos.datos is not datos:
        recursos = Recursos.construir(datos, indice, lexico)

    # 3. Anclaje y descarte de eventos.
    anclaje = anclar(interp, entrada)
    lista_oraciones = oraciones(entrada.mensajes)
    puras = [o.span for o in lista_oraciones if o.consulta_pura]
    efectivos: list[EventoAnclado] = []
    descartados: list[DiagEvento] = []
    for ea in anclaje.eventos:
        if ea.span is None:
            descartados.append(_descartado(ea, SIN_ANCLA))
        elif dentro_de_consulta(ea.span, puras):
            descartados.append(_descartado(ea, DESCARTADO_CONSULTA))
        else:
            efectivos.append(ea)

    # 4 y 5. Plegado y sustituciones.
    plegado: ResultadoPlegado = plegar(
        entrada=entrada, eventos=efectivos, datos=datos, indice=recursos.indice, lexico=recursos.lexico,
        vocabulario=recursos.vocabulario,
    )
    salida: Salida = aplicar_sustituciones(plegado.lineas_activas(), datos)

    # 6. Omisiones.
    omisiones: ResultadoOmisiones = recursos.detector.detectar(
        entrada.mensajes, lista_oraciones, [ea.span for ea in efectivos]
    )

    # 7. Clasificación.
    pendientes_plegado = plegado.pendientes()
    pendientes_omision = omisiones.pendientes
    clasificacion = clasificar(
        eventos_efectivos=len(efectivos),
        creo_items=plegado.creo_items,
        quedan_items=bool(salida.lineas or pendientes_plegado),
        pendientes_omision=len(pendientes_omision),
    )

    # 8. Cierre (E1a). D64: pendientes de eventos y habitual, luego los de omisión.
    hay_eventos = clasificacion.hay_eventos_pedido
    cierre = cerrar_pedido(
        cliente_id=entrada.cliente_id,
        fecha_hora=entrada.fecha_hora,
        lineas_solicitadas=salida.lineas if hay_eventos else (),
        pendientes=(pendientes_plegado + pendientes_omision) if hay_eventos else (),
        sustituciones=salida.sustituciones if hay_eventos else (),
        hay_eventos_pedido=hay_eventos,
        datos=datos,
    )

    # 9. Mensaje.
    mensaje = recursos.redactor.redactar(cierre, clasificacion, entrada.fecha_hora)

    # 10. Diagnóstico.
    diagnostico = replace(
        plegado.diagnostico(salida),
        omisiones=omisiones.diagnostico(),
        clasificacion=clasificacion.value,
        consultas=len(interp.consultas),
        instrucciones_rechazadas=len(interp.instrucciones_rechazadas),
        eventos_descartados=tuple(descartados),
    )
    return ResultadoPedido(cierre=cierre, mensaje_cliente=mensaje, clasificacion=clasificacion, diagnostico=diagnostico)
