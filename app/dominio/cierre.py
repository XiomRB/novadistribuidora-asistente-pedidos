"""Cierre del pedido: de líneas ya resueltas y pendientes al resultado del contrato.

E1b (interpretación determinista) entrega aquí las líneas resueltas, los pendientes y las
sustituciones; este módulo calcula precios, descuentos, total, crédito, fecha, estado y motivos.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from app.datos.modelos import Datos
from app.dominio.dinero import CANTIDAD, a_decimal, exigir_decimal
from app.dominio.errores import ClienteNoEncontrado, EntradaCierreIncoherente
from app.dominio.estado import determinar_estado, motivos_revision, verificar_invariantes
from app.dominio.reglas import credito_excedido, descuento_pct, fecha_entrega, subtotal, total
from app.dominio.resultado import Estado, Linea, LineaSolicitada, Pendiente, ResultadoCierre, Sustitucion


def _validar_entrada(
    lineas: Sequence[LineaSolicitada],
    sustituciones: Sequence[Sustitucion],
    hay_eventos_pedido: bool,
    pendientes: Sequence[Pendiente],
    datos: Datos,
) -> None:
    if not hay_eventos_pedido and (lineas or pendientes or sustituciones):
        raise EntradaCierreIncoherente("sin eventos de pedido no puede haber líneas, pendientes ni sustituciones")
    vistos: set[str] = set()
    cantidad_por_sku: dict[str, Decimal] = {}
    for linea in lineas:
        producto = datos.productos.get(linea.sku)
        if producto is None:
            raise EntradaCierreIncoherente(f"sku inexistente en una línea: {linea.sku}")
        if not producto.disponible:
            raise EntradaCierreIncoherente(f"sku no disponible en una línea: {linea.sku}")
        if linea.sku in vistos:
            raise EntradaCierreIncoherente(f"sku repetido en las líneas: {linea.sku}")
        vistos.add(linea.sku)
        exigir_decimal(linea.cantidad)
        a_decimal(linea.cantidad, CANTIDAD, f"cantidad[{linea.sku}]")
        cantidad_por_sku[linea.sku] = linea.cantidad
    sustituido_por_sku: dict[str, Decimal] = {}
    for s in sustituciones:
        if s.sku_entregado not in vistos:
            raise EntradaCierreIncoherente(f"sustitución hacia un sku sin línea: {s.sku_entregado}")
        solicitado = datos.productos.get(s.sku_solicitado)
        if solicitado is None or solicitado.disponible or solicitado.sustituto_sku != s.sku_entregado:
            raise EntradaCierreIncoherente(f"sustitución no respaldada por el catálogo: {s.sku_solicitado}")
        exigir_decimal(s.cantidad)
        a_decimal(s.cantidad, CANTIDAD, f"sustitucion[{s.sku_solicitado}]")
        sustituido_por_sku[s.sku_entregado] = sustituido_por_sku.get(s.sku_entregado, Decimal(0)) + s.cantidad
    # La línea entregada puede incluir además unidades pedidas directamente de ese sku,
    # pero nunca menos unidades que las sustituidas hacia ella.
    for sku, sustituido in sustituido_por_sku.items():
        if sustituido > cantidad_por_sku[sku]:
            raise EntradaCierreIncoherente(
                f"las sustituciones hacia {sku} suman {sustituido} y superan la cantidad de la línea ({cantidad_por_sku[sku]})"
            )


def cerrar_pedido(
    *,
    cliente_id: str,
    fecha_hora: datetime,
    lineas_solicitadas: Sequence[LineaSolicitada],
    pendientes: Sequence[Pendiente],
    hay_eventos_pedido: bool,
    datos: Datos,
    sustituciones: Sequence[Sustitucion] = (),
) -> ResultadoCierre:
    cliente = datos.clientes.get(cliente_id)
    if cliente is None:
        raise ClienteNoEncontrado(cliente_id)
    _validar_entrada(lineas_solicitadas, sustituciones, hay_eventos_pedido, pendientes, datos)

    vacio = ResultadoCierre(
        cliente_id=cliente_id,
        estado=Estado.FUERA_DE_ALCANCE,
        lineas=(),
        total=Decimal("0.00"),
        fecha_entrega=None,
        sustituciones=(),
        pendientes=(),
        motivos_revision=(),
    )
    # Prioridad 1 y 3: sin eventos de pedido, o pedido vaciado sin pendientes.
    if not hay_eventos_pedido or (not lineas_solicitadas and not pendientes):
        verificar_invariantes(vacio)
        return vacio

    lineas: list[Linea] = []
    for solicitada in lineas_solicitadas:
        producto = datos.productos[solicitada.sku]
        pct = descuento_pct(producto.categoria, solicitada.cantidad, datos.escalas)
        lineas.append(
            Linea(
                sku=producto.sku,
                cantidad=solicitada.cantidad,
                precio_unitario=producto.precio,
                descuento_pct=pct,
                subtotal=subtotal(solicitada.cantidad, producto.precio, pct),
            )
        )
    total_pedido = total(linea.subtotal for linea in lineas)
    credito = credito_excedido(cliente.saldo_pendiente, cliente.limite_credito, total_pedido)
    estado = determinar_estado(
        hay_eventos_pedido=True,
        hay_lineas=bool(lineas),
        hay_pendientes=bool(pendientes),
        credito=credito,
    )
    resultado = ResultadoCierre(
        cliente_id=cliente_id,
        estado=estado,
        lineas=tuple(lineas),
        total=total_pedido,
        fecha_entrega=fecha_entrega(fecha_hora, cliente.dias_visita) if lineas else None,
        sustituciones=tuple(sustituciones),
        pendientes=tuple(pendientes),
        motivos_revision=motivos_revision(pendientes, credito),
    )
    verificar_invariantes(resultado)
    return resultado
