"""E2a: esquema de la solicitud (D15, D56, D77, D90) y formato de errores 422 (D78), 404, 503 y 500."""

import json

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import errores
from app.api.esquemas import MAX_CARACTERES_CLIENTE_ID, SolicitudPedido
from app.dominio.entrada import MAX_CARACTERES_MENSAJE, MAX_MENSAJES, EntradaInvalida, EntradaPedido

MARCA = "ZQXECO"
VALIDA = {"cliente_id": "C001", "fecha_hora": "2026-11-23T15:20", "mensajes": ["Buenas, mándeme 2 fardos de kola 600"]}


def con(**cambios):
    solicitud = dict(VALIDA)
    for clave, valor in cambios.items():
        if valor is ...:
            solicitud.pop(clave)
        else:
            solicitud[clave] = valor
    return solicitud


def errores_de(datos):
    with pytest.raises(ValidationError) as error:
        SolicitudPedido.model_validate(datos)
    return errores.cuerpo_422(error.value.errors())["detail"]


def campos(detalle):
    return {e["campo"] for e in detalle}


# ====================================================================== solicitudes válidas


def test_solicitud_valida_produce_la_entrada_del_dominio():
    entrada = SolicitudPedido.model_validate(VALIDA).a_entrada()
    assert isinstance(entrada, EntradaPedido)
    assert (entrada.cliente_id, entrada.fecha_hora.isoformat(), entrada.mensajes) == (
        "C001", "2026-11-23T15:20:00", ("Buenas, mándeme 2 fardos de kola 600",)
    )
    assert entrada.fecha_hora.tzinfo is None  # hora local de Guatemala, sin zona horaria


def test_d77_campos_adicionales_se_ignoran():
    solicitud = SolicitudPedido.model_validate(con(extra="x", otro={"a": 1}))
    assert solicitud.model_dump() == VALIDA


def test_d15_cliente_id_no_se_normaliza():
    assert SolicitudPedido.model_validate(con(cliente_id="c001")).a_entrada().cliente_id == "c001"
    assert SolicitudPedido.model_validate(con(cliente_id=" C001 ")).a_entrada().cliente_id == " C001 "


@pytest.mark.parametrize(
    "mensajes",
    [["x" * MAX_CARACTERES_MENSAJE], ["hola"] * MAX_MENSAJES, ["", "  ", "hola"], ["👍" * MAX_CARACTERES_MENSAJE]],
    ids=["2000_caracteres", "20_mensajes", "blancos_sueltos", "2000_emojis"],
)
def test_limites_de_mensajes_aceptados(mensajes):
    assert SolicitudPedido.model_validate(con(mensajes=mensajes)).a_entrada().mensajes == tuple(mensajes)


@pytest.mark.parametrize("fecha", ["2026-11-23T00:00", "2026-11-23T23:59", "2028-02-29T14:00", "2026-12-31T19:00"])
def test_fechas_validas(fecha):
    assert SolicitudPedido.model_validate(con(fecha_hora=fecha)).a_entrada().fecha_hora.strftime("%Y-%m-%dT%H:%M") == fecha


# ====================================================================== D90: cliente_id


class TestClienteId:
    @pytest.mark.parametrize("valor", ["C" * MAX_CARACTERES_CLIENTE_ID, "👍" * MAX_CARACTERES_CLIENTE_ID, "é" * MAX_CARACTERES_CLIENTE_ID])
    def test_64_caracteres_se_aceptan_sin_importar_los_bytes(self, valor):
        # 64 emojis son 256 bytes UTF-8: se cuentan caracteres, no bytes.
        assert len(valor.encode("utf-8")) >= MAX_CARACTERES_CLIENTE_ID
        assert SolicitudPedido.model_validate(con(cliente_id=valor)).cliente_id == valor

    @pytest.mark.parametrize("valor", ["C" * 65, "👍" * 65, MARCA * 20])
    def test_mas_de_64_caracteres_se_rechaza(self, valor):
        detalle = errores_de(con(cliente_id=valor))
        assert detalle == [{"campo": "cliente_id", "motivo": "debe tener entre 1 y 64 caracteres"}]

    @pytest.mark.parametrize("valor", ["", "   ", "\t\n"])
    def test_vacio_o_en_blanco_se_rechaza(self, valor):
        assert errores_de(con(cliente_id=valor)) == [{"campo": "cliente_id", "motivo": "debe tener entre 1 y 64 caracteres"}]

    @pytest.mark.parametrize(("valor", "motivo"), [(1, "debe ser un texto"), (None, "debe ser un texto"), (["C001"], "debe ser un texto"), (..., "es obligatorio")])
    def test_tipo_o_ausencia(self, valor, motivo):
        assert errores_de(con(cliente_id=valor)) == [{"campo": "cliente_id", "motivo": motivo}]

    def test_misma_regla_en_un_solo_lugar(self):
        # 64 en el esquema es el único límite de longitud del cliente: el dominio no tiene otro.
        assert MAX_CARACTERES_CLIENTE_ID == 64
        EntradaPedido("C" * 65, VALIDA_FECHA, ("hola",))  # el dominio acepta cualquier longitud


VALIDA_FECHA = SolicitudPedido.model_validate(VALIDA).a_entrada().fecha_hora


# ====================================================================== fecha_hora (D15)


@pytest.mark.parametrize(
    "fecha",
    ["2026-11-23 15:20", "2026-11-23T15:20:00", "2026-11-23T15:20Z", "2026-11-23T15:20-06:00", "2026-11-23", "23/11/2026 15:20",
     "2026-02-31T10:00", "2026-11-23T24:00", "2026-11-23T15:60", "2026-13-01T10:00", "2027-02-29T10:00", "２０２６-11-23T15:20",
     " 2026-11-23T15:20", "2026-11-23T15:20 ", "2026-11-23t15:20", ""],
)
def test_fechas_invalidas(fecha):
    assert errores_de(con(fecha_hora=fecha)) == [
        {"campo": "fecha_hora", "motivo": "debe tener el formato AAAA-MM-DDTHH:MM y ser una fecha y hora válidas"}
    ]


@pytest.mark.parametrize(("valor", "motivo"), [(20261123, "debe ser un texto"), (None, "debe ser un texto"), (..., "es obligatorio")])
def test_fecha_tipo_o_ausencia(valor, motivo):
    assert errores_de(con(fecha_hora=valor)) == [{"campo": "fecha_hora", "motivo": motivo}]


# ====================================================================== mensajes (D15, D56)


@pytest.mark.parametrize(
    ("mensajes", "esperado"),
    [
        ([], [{"campo": "mensajes", "motivo": "debe contener entre 1 y 20 mensajes"}]),
        (["hola"] * (MAX_MENSAJES + 1), [{"campo": "mensajes", "motivo": "debe contener entre 1 y 20 mensajes"}]),
        (["x" * (MAX_CARACTERES_MENSAJE + 1)], [{"campo": "mensajes", "motivo": "supera 2000 caracteres"}]),
        (["", "   ", "\n"], [{"campo": "mensajes", "motivo": "al menos un mensaje debe tener texto"}]),
        ("hola", [{"campo": "mensajes", "motivo": "debe ser una lista de textos"}]),
        ({"0": "hola"}, [{"campo": "mensajes", "motivo": "debe ser una lista de textos"}]),
        (["hola", 3], [{"campo": "mensajes[1]", "motivo": "debe ser un texto"}]),
        (None, [{"campo": "mensajes", "motivo": "debe ser una lista de textos"}]),
        (..., [{"campo": "mensajes", "motivo": "es obligatorio"}]),
    ],
    ids=["vacia", "21_mensajes", "2001_caracteres", "todos_en_blanco", "texto", "objeto", "elemento_no_texto", "nulo", "falta"],
)
def test_mensajes_invalidos(mensajes, esperado):
    assert errores_de(con(mensajes=mensajes)) == esperado


def test_varios_errores_a_la_vez():
    detalle = errores_de({"cliente_id": "", "fecha_hora": "mal", "mensajes": []})
    assert campos(detalle) == {"cliente_id", "fecha_hora", "mensajes"}


@pytest.mark.parametrize("cuerpo", ["no es json", '{"cliente_id": "C001",', "[1, 2]", '"texto"', "null"])
def test_cuerpo_no_json_u_objeto(cuerpo):
    with pytest.raises(ValidationError) as error:
        SolicitudPedido.model_validate_json(cuerpo)
    detalle = errores.cuerpo_422(error.value.errors())["detail"]
    assert campos(detalle) == {"cuerpo"} and all(e["motivo"].startswith("el cuerpo") for e in detalle)


# ====================================================================== coherencia con el dominio


@pytest.mark.parametrize(
    "mensajes",
    [["hola"] * (MAX_MENSAJES + 1), ["x" * (MAX_CARACTERES_MENSAJE + 1)], ["", " "], []],
)
def test_lo_que_el_dominio_rechaza_tambien_lo_rechaza_el_esquema(mensajes):
    with pytest.raises(EntradaInvalida):
        EntradaPedido("C001", VALIDA_FECHA, tuple(mensajes))
    errores_de(con(mensajes=mensajes))


# ====================================================================== D78: sin eco


ENTRADAS_CON_MARCA = [
    con(cliente_id=MARCA * 20),
    con(cliente_id=f"   "),
    con(fecha_hora=f"{MARCA} 2026"),
    con(mensajes=[f"{MARCA} " * 500]),
    con(mensajes=[MARCA] * 21),
    con(mensajes=f"{MARCA} texto"),
    con(mensajes=["ok", {"nota": MARCA}]),
    {"cliente_id": {"id": MARCA}, "fecha_hora": [MARCA], "mensajes": {MARCA: MARCA}},
]


@pytest.mark.parametrize("datos", ENTRADAS_CON_MARCA)
def test_ningun_error_repite_el_valor_recibido(datos):
    detalle = errores_de(datos)
    texto = json.dumps(detalle, ensure_ascii=False)
    assert MARCA not in texto
    assert all(set(e) == {"campo", "motivo"} for e in detalle)


def test_errores_de_fastapi_tambien_sin_eco_y_en_espanol():
    """Los errores reales de FastAPI (`loc` empieza con "body") se traducen igual. La aplicación
    es solo de prueba: las rutas y manejadores de producción son de E2b."""
    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    def _422(_request, error):
        return JSONResponse(status_code=422, content=errores.cuerpo_422(error.errors()))

    @app.post("/prueba")
    def _ruta(solicitud: SolicitudPedido):
        return {"ok": True}

    cliente = TestClient(app)
    for cuerpo in [
        {"cliente_id": MARCA * 20, "fecha_hora": f"{MARCA}", "mensajes": [f"{MARCA}"] * 21},
        {"fecha_hora": 5, "mensajes": [1, MARCA]},
    ]:
        respuesta = cliente.post("/prueba", json=cuerpo)
        assert respuesta.status_code == 422 and MARCA not in respuesta.text
        assert all(set(e) == {"campo", "motivo"} for e in respuesta.json()["detail"])
    respuesta = cliente.post("/prueba", content=f'{{"cliente_id": "{MARCA}", ', headers={"content-type": "application/json"})
    assert respuesta.status_code == 422 and MARCA not in respuesta.text
    assert respuesta.json() == {"detail": [{"campo": "cuerpo", "motivo": "el cuerpo no es un JSON válido"}]}
    assert cliente.post("/prueba", json=VALIDA).status_code == 200


def test_error_desconocido_usa_un_motivo_generico_sin_eco():
    detalle = errores.detalle_validacion([{"type": "otro_tipo", "loc": ("body", "x"), "msg": f"mensaje con {MARCA}", "input": MARCA, "ctx": {"v": MARCA}}])
    assert detalle == [{"campo": "x", "motivo": "valor inválido"}]
    assert errores.detalle_validacion([]) == [{"campo": "cuerpo", "motivo": "valor inválido"}]


# ====================================================================== 404, 503 y 500 (D79, D18, D82)


def test_cuerpos_de_error_fijos():
    assert errores.cuerpo_404() == {"detail": "Cliente no encontrado"}
    assert errores.cuerpo_503() == {"detail": "No fue posible interpretar el pedido; intente de nuevo"}
    assert errores.cuerpo_500() == {"detail": "Error interno"}


def test_retry_after_es_una_constante_de_10_segundos():
    assert errores.RETRY_AFTER_SEGUNDOS == 10
    assert errores.encabezados_503() == {"Retry-After": "10"}
