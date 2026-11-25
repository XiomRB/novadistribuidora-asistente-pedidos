"""Mensaje al cliente (D16, D49, D65; 3.6 y 3.7): plantillas deterministas sin texto del cliente."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.dominio.clasificacion import Clasificacion
from app.dominio.resultado import Estado, Linea, Motivo, Pendiente, ResultadoCierre, Sustitucion
from app.mensajes import confirmacion
from app.mensajes.confirmacion import RedactorConfirmacion, fecha_en_palabras, plural, saludo
from tests.fixtures.historial_e1b2 import cargar_contexto

D = Decimal
MARCADOR = "ZQXCLIENTE"


@pytest.fixture(scope="module")
def redactor(tmp_path_factory):
    ctx = cargar_contexto(tmp_path_factory.mktemp("confirmacion"))
    return RedactorConfirmacion(ctx.datos, ctx.indice)


def cierre(estado=Estado.CONFIRMADO, lineas=(), pendientes=(), sustituciones=(), motivos=(), fecha=date(2026, 12, 3), total=D("0.00")):
    return ResultadoCierre("K04", estado, tuple(lineas), total, fecha if lineas else None, tuple(sustituciones), tuple(pendientes), tuple(motivos))


def linea(sku, cantidad, precio="100.00"):
    return Linea(sku, D(cantidad), D(precio), D(0), D(precio) * D(cantidad))


@pytest.mark.parametrize(
    ("hora", "minuto", "esperado"),
    [(0, 0, "Buenos días"), (11, 59, "Buenos días"), (12, 0, "Buenas tardes"), (13, 59, "Buenas tardes"),
     (14, 0, "Buenas tardes"), (18, 59, "Buenas tardes"), (19, 0, "Buenas noches"), (23, 59, "Buenas noches")],
)
def test_saludo_por_hora(hora, minuto, esperado):
    assert saludo(datetime(2026, 12, 1, hora, minuto)) == esperado


@pytest.mark.parametrize(
    ("fecha", "esperado"),
    [(date(2026, 11, 26), "jueves 26 de noviembre"), (date(2026, 11, 30), "lunes 30 de noviembre"),
     (date(2026, 12, 1), "martes 1 de diciembre"), (date(2027, 1, 2), "sábado 2 de enero"), (date(2026, 12, 6), "domingo 6 de diciembre"),
     (date(2026, 12, 2), "miércoles 2 de diciembre")],
)
def test_fecha_en_palabras_con_tablas_propias(fecha, esperado):
    assert fecha_en_palabras(fecha) == esperado


@pytest.mark.parametrize(
    ("palabra", "esperado"), [("fardo", "fardos"), ("caja", "cajas"), ("display", "displays"), ("quintal", "quintales")]
)
def test_plural_por_regla(palabra, esperado):
    assert plural(palabra) == esperado


def test_confirmado_con_singular_y_plural_y_sin_montos(redactor):
    r = cierre(lineas=[linea("GS6", 2), linea("ARQ", 1, "480.00")], total=D("680.00"))
    texto = redactor.redactar(r, Clasificacion.PEDIDO, datetime(2026, 12, 1, 15, 20))
    assert texto == (
        "¡Buenas tardes! Recibimos su pedido: 2 fardos de Gaseosa Sol 600 ml y 1 quintal de Arroz Sierra quintal. "
        "Entrega el jueves 3 de diciembre. ¡Gracias!"
    )
    assert "680" not in texto and "Q" not in texto  # D16: sin montos


def test_sustitucion(redactor):
    r = cierre(lineas=[linea("GS2", 3)], sustituciones=[Sustitucion("GS3", "GS2", D(3))])
    assert "En lugar de Gaseosa Sol 3 L le enviaremos Gaseosa Sol 2 L." in redactor.redactar(r, Clasificacion.PEDIDO, datetime(2026, 12, 1, 9))


def test_requiere_revision_con_cada_situacion(redactor):
    pendientes = [
        Pendiente(Motivo.PRODUCTO_AMBIGUO, f"{MARCADOR} jabón", ("PC2", "PE2", "PD7")),
        Pendiente(Motivo.PRODUCTO_AMBIGUO, f"{MARCADOR} otra cosa", ()),
        Pendiente(Motivo.PRODUCTO_NO_EXISTE, f"{MARCADOR} cerveza"),
        Pendiente(Motivo.PRODUCTO_NO_EXISTE, f"{MARCADOR} velas"),
        Pendiente(Motivo.AGOTADO_SIN_SUSTITUTO, "Galletas Luna Chocolate", ("GC1",)),
        Pendiente(Motivo.CANTIDAD_NO_CONVERTIBLE, f"{MARCADOR} 36 botellas", ("GS6",)),
    ]
    motivos = (Motivo.PRODUCTO_AMBIGUO, Motivo.PRODUCTO_NO_EXISTE, Motivo.AGOTADO_SIN_SUSTITUTO, Motivo.CANTIDAD_NO_CONVERTIBLE, Motivo.CREDITO_EXCEDIDO)
    r = cierre(Estado.REQUIERE_REVISION, lineas=[linea("FN1", 1)], pendientes=pendientes, motivos=motivos)
    texto = redactor.redactar(r, Clasificacion.PEDIDO, datetime(2026, 12, 1, 20))
    assert texto == (
        "¡Buenas noches! Recibimos su pedido: 1 fardo de Frijol Negro Campo 1 lb. "
        "Sobre la solicitud de pasta, un asesor le confirmará el producto. "  # D49
        "Sobre parte de su pedido, un asesor le confirmará los productos. "  # D65
        "Algunos productos solicitados no los manejamos. "  # una sola vez
        "Galletas Luna Chocolate no está disponible por ahora. "
        "Un asesor le confirmará la cantidad de Gaseosa Sol 600 ml. "
        "Un asesor revisará su pedido antes de enviarlo. "
        "Entrega el jueves 3 de diciembre. Un asesor confirmará su pedido. ¡Gracias!"
    )
    assert MARCADOR not in texto  # nunca usa texto del cliente


def test_d49_usa_el_grupo_tal_como_se_escribe_en_el_catalogo(redactor):
    r = cierre(Estado.REQUIERE_REVISION, pendientes=[Pendiente(Motivo.PRODUCTO_AMBIGUO, "x", ("PH4", "PHD"))], motivos=(Motivo.PRODUCTO_AMBIGUO,))
    texto = redactor.redactar(r, Clasificacion.PEDIDO, datetime(2026, 12, 1, 9))
    assert texto == (
        "¡Buenos días! Recibimos su pedido. Sobre la solicitud de papel, un asesor le confirmará el producto. "
        "Un asesor confirmará su pedido. ¡Gracias!"
    )


@pytest.mark.parametrize(
    ("clasificacion", "frase"),
    [(Clasificacion.CONSULTA, confirmacion.CONSULTA), (Clasificacion.PEDIDO_CANCELADO, confirmacion.CANCELADO),
     (Clasificacion.SIN_EFECTO, confirmacion.SIN_EFECTO)],
)
def test_mensajes_sin_pedido(redactor, clasificacion, frase):
    r = cierre(Estado.FUERA_DE_ALCANCE)
    assert redactor.redactar(r, clasificacion, datetime(2026, 12, 1, 12)) == f"¡Buenas tardes! {frase}"


def test_cambio_de_mes_en_la_fecha_de_entrega(redactor):
    r = cierre(lineas=[linea("GS6", 1)], fecha=date(2027, 1, 4))
    assert "Entrega el lunes 4 de enero." in redactor.redactar(r, Clasificacion.PEDIDO, datetime(2026, 12, 31, 16))
