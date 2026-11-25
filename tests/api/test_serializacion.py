"""E2a: respuesta del contrato (9 campos del Anexo) y serialización de montos (D03, D91 opción A).

- Claves: el conjunto de claves de primer nivel y de cada objeto anidado es exactamente el del
  Anexo (sin faltantes ni adicionales). El orden textual de las claves no es un requisito.
- Montos: número JSON (nunca texto) y **igualdad numérica exacta** al leer el JSON como
  `Decimal`. No se exige un texto concreto (no se conservan los ceros finales).
- Los cálculos siguen en `Decimal`: la conversión a número ocurre solo al serializar a JSON.
"""

import json
import random
from datetime import date
from decimal import Decimal

import pytest
from pydantic import PlainSerializer, TypeAdapter, ValidationError

from app.api.esquemas import LineaRespuesta, Monto, PendienteRespuesta, RespuestaPedido, SustitucionRespuesta, _entero
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.pedido_e1b2b import cargar_recursos, frag, procesar

CLAVES_RESPUESTA = {
    "cliente_id", "estado", "lineas", "total", "fecha_entrega", "sustituciones", "pendientes", "motivos_revision", "mensaje_cliente",
}
CLAVES_LINEA = {"sku", "cantidad", "precio_unitario", "descuento_pct", "subtotal"}
CLAVES_SUSTITUCION = {"sku_solicitado", "sku_entregado", "cantidad"}
CLAVES_PENDIENTE = {"motivo", "texto", "opciones"}


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("serializacion"))[1]


@pytest.fixture(scope="module")
def resultados(rec):
    """Resultados reales del motor (E1b) en los tres estados, con sustituciones, pendientes y crédito."""
    return {
        "confirmado": procesar(rec, ["2 fardos de gaseosa sol 600 y 3 de frijol negro"], [
            ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
            ev(2, 0, "agregar", "3 de frijol negro", producto="frijol negro", cantidad="3"),
        ]),
        "habitual": procesar(rec, ["lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K01"),
        "credito": procesar(rec, ["1 de cloro claro"], [ev(1, 0, "agregar", "1 de cloro claro", producto="cloro claro", cantidad="1")], cliente="K02"),
        "consulta": procesar(rec, ["¿Tienen gaseosa sol de 600?"], consultas=[frag(0, "¿Tienen gaseosa sol de 600?")]),
        "descuento": procesar(rec, ["24 de frijol negro"], [ev(1, 0, "agregar", "24 de frijol negro", producto="frijol negro", cantidad="24")]),
    }


def json_de(resultado):
    return RespuestaPedido.desde_resultado(resultado).model_dump_json()


# ====================================================================== claves (sin orden)


@pytest.mark.parametrize("nombre", ["confirmado", "habitual", "credito", "consulta", "descuento"])
def test_claves_exactas_en_cada_nivel(resultados, nombre):
    cuerpo = json.loads(json_de(resultados[nombre]))
    assert set(cuerpo) == CLAVES_RESPUESTA and len(cuerpo) == 9
    assert all(set(l) == CLAVES_LINEA for l in cuerpo["lineas"])
    assert all(set(s) == CLAVES_SUSTITUCION for s in cuerpo["sustituciones"])
    assert all(set(p) == CLAVES_PENDIENTE for p in cuerpo["pendientes"])


def test_hay_objetos_anidados_de_cada_tipo(resultados):
    cuerpo = json.loads(json_de(resultados["habitual"]))
    assert cuerpo["lineas"] and cuerpo["sustituciones"] and cuerpo["pendientes"] and cuerpo["motivos_revision"]


def test_las_claves_se_comparan_como_conjunto_no_por_orden(resultados):
    cuerpo = json.loads(json_de(resultados["confirmado"]))
    invertido = dict(reversed(list(cuerpo.items())))
    assert set(invertido) == CLAVES_RESPUESTA  # el orden no forma parte del contrato


def test_no_se_admiten_claves_adicionales_en_ningun_nivel():
    with pytest.raises(ValidationError):
        LineaRespuesta(sku="X", cantidad=1, precio_unitario=Decimal("1.00"), descuento_pct=0, subtotal=Decimal("1.00"), extra=1)
    with pytest.raises(ValidationError):
        SustitucionRespuesta(sku_solicitado="A", sku_entregado="B", cantidad=1, extra=1)
    with pytest.raises(ValidationError):
        PendienteRespuesta(motivo="producto_ambiguo", texto="x", opciones=[], extra=1)
    assert set(RespuestaPedido.model_fields) == CLAVES_RESPUESTA


# ====================================================================== tipos


@pytest.mark.parametrize("nombre", ["confirmado", "habitual", "credito", "consulta", "descuento"])
def test_tipos_json(resultados, nombre):
    cuerpo = json.loads(json_de(resultados[nombre]))
    assert isinstance(cuerpo["cliente_id"], str) and isinstance(cuerpo["mensaje_cliente"], str)
    assert cuerpo["estado"] in ("confirmado", "requiere_revision", "fuera_de_alcance")
    assert isinstance(cuerpo["total"], float)  # número JSON, nunca texto
    for linea in cuerpo["lineas"]:
        assert isinstance(linea["precio_unitario"], float) and isinstance(linea["subtotal"], float)
        assert type(linea["cantidad"]) is int and type(linea["descuento_pct"]) is int
    for sustitucion in cuerpo["sustituciones"]:
        assert type(sustitucion["cantidad"]) is int
    for pendiente in cuerpo["pendientes"]:
        assert isinstance(pendiente["texto"], str) and all(isinstance(o, str) for o in pendiente["opciones"])
    fecha = cuerpo["fecha_entrega"]
    assert fecha is None or date.fromisoformat(fecha).isoformat() == fecha


def test_fecha_nula_sin_lineas_y_con_formato_aaaa_mm_dd(resultados):
    assert json.loads(json_de(resultados["consulta"]))["fecha_entrega"] is None
    fecha = json.loads(json_de(resultados["confirmado"]))["fecha_entrega"]
    assert fecha == resultados["confirmado"].cierre.fecha_entrega.isoformat() and len(fecha) == 10


def test_los_montos_nunca_salen_como_texto(resultados):
    for resultado in resultados.values():
        texto = json_de(resultado)
        for campo in ("total", "subtotal", "precio_unitario"):
            assert f'"{campo}":"' not in texto


def test_regresion_el_serializador_numerico_esta_en_todos_los_montos():
    for modelo, campo in [(RespuestaPedido, "total"), (LineaRespuesta, "precio_unitario"), (LineaRespuesta, "subtotal")]:
        assert any(isinstance(m, PlainSerializer) and m.when_used == "json" for m in modelo.model_fields[campo].metadata), campo


# ====================================================================== igualdad numérica exacta


@pytest.mark.parametrize("nombre", ["confirmado", "habitual", "credito", "consulta", "descuento"])
def test_igualdad_numerica_exacta_con_el_motor(resultados, nombre):
    resultado = resultados[nombre]
    cierre = resultado.cierre
    cuerpo = json.loads(json_de(resultado), parse_float=Decimal)
    assert cuerpo["total"] == cierre.total
    assert [(l["sku"], l["cantidad"], l["precio_unitario"], l["descuento_pct"], l["subtotal"]) for l in cuerpo["lineas"]] == [
        (l.sku, l.cantidad, l.precio_unitario, l.descuento_pct, l.subtotal) for l in cierre.lineas
    ]
    assert [(s["sku_solicitado"], s["sku_entregado"], s["cantidad"]) for s in cuerpo["sustituciones"]] == [
        (s.sku_solicitado, s.sku_entregado, s.cantidad) for s in cierre.sustituciones
    ]
    assert [(p["motivo"], p["texto"], tuple(p["opciones"])) for p in cuerpo["pendientes"]] == [
        (p.motivo.value, p.texto, p.opciones) for p in cierre.pendientes
    ]
    assert cuerpo["motivos_revision"] == [m.value for m in cierre.motivos_revision]
    assert (cuerpo["cliente_id"], cuerpo["estado"], cuerpo["mensaje_cliente"]) == (cierre.cliente_id, cierre.estado.value, resultado.mensaje_cliente)


def test_descuento_entero_en_la_respuesta(resultados):
    (linea,) = json.loads(json_de(resultados["descuento"]))["lineas"]
    assert type(linea["descuento_pct"]) is int and linea["descuento_pct"] > 0


def _montos_de_prueba():
    rnd = random.Random(20261125)
    exhaustivos = (Decimal(c).scaleb(-2) for c in range(0, 200_001))  # 0.00 a 2000.00, todos los centavos
    aleatorios = (Decimal(rnd.randrange(0, 10**13)).scaleb(-2) for _ in range(100_000))  # hasta 10^11
    bordes = [Decimal(v) for v in ("0.00", "0.01", "0.10", "0.99", "1.00", "1164.00", "2240.64", "99999.99", "100000.00",
                                     "1234567.89", "9999999999.99", "99999999999.99")]
    return list(exhaustivos) + list(aleatorios) + bordes


def test_igualdad_numerica_exacta_de_los_montos_en_su_rango():
    """Cada monto con 2 decimales, serializado y leído como Decimal, vuelve a ser exactamente el
    mismo valor. Es igualdad numérica: no se afirma nada sobre el texto (1164.00 se escribe 1164.0)."""
    adaptador = TypeAdapter(Monto)
    fallos = [m for m in _montos_de_prueba() if json.loads(adaptador.dump_json(m), parse_float=Decimal) != m]
    assert fallos == []


def test_el_texto_no_conserva_los_ceros_finales():
    # Documenta el comportamiento aceptado en D91 (opción A): solo igualdad numérica.
    assert TypeAdapter(Monto).dump_json(Decimal("1164.00")) == b"1164.0"
    assert json.loads(TypeAdapter(Monto).dump_json(Decimal("1164.00")), parse_float=Decimal) == Decimal("1164.00")


# ====================================================================== sin float en los cálculos


def test_los_montos_siguen_siendo_decimal_fuera_del_json(resultados):
    respuesta = RespuestaPedido.desde_resultado(resultados["habitual"])
    assert isinstance(respuesta.total, Decimal) and all(isinstance(l.subtotal, Decimal) for l in respuesta.lineas)
    python = respuesta.model_dump()  # modo Python: sin conversión
    assert isinstance(python["total"], Decimal) and all(isinstance(l["precio_unitario"], Decimal) for l in python["lineas"])


def test_la_respuesta_no_recalcula_nada(resultados):
    resultado = resultados["habitual"]
    respuesta = RespuestaPedido.desde_resultado(resultado)
    assert respuesta.total == resultado.cierre.total and respuesta.total is resultado.cierre.total


@pytest.mark.parametrize("valor", [Decimal("2.5"), Decimal("0.1"), 2, 2.0, "2"])
def test_enteros_exactos(valor):
    with pytest.raises(ValueError):
        _entero(valor)


@pytest.mark.parametrize(("valor", "esperado"), [(Decimal("2"), 2), (Decimal("2.00"), 2), (Decimal("10"), 10), (Decimal("0"), 0)])
def test_enteros_desde_decimal(valor, esperado):
    assert _entero(valor) == esperado and type(_entero(valor)) is int


def test_estados_y_motivos_solo_del_contrato():
    with pytest.raises(ValidationError):
        PendienteRespuesta(motivo="credito_excedido", texto="x", opciones=[])  # solo va en motivos_revision
    with pytest.raises(ValidationError):
        RespuestaPedido(cliente_id="K04", estado="otro", lineas=[], total=Decimal("0.00"), fecha_entrega=None, sustituciones=[],
                        pendientes=[], motivos_revision=[], mensaje_cliente="x")
