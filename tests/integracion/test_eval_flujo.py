"""E2c-1: flujo completo del evaluador contra la aplicación en proceso (datos sintéticos).

- Con el intérprete de referencia (solo en las pruebas) los conjuntos dan 100 %; con la producción
  (503) dan 0 %, con exactamente una petición por caso y sin reintentos.
- Timeout, JSON inválido y respuestas fuera del contrato son incorrectos y siguen en el
  denominador; solo la respuesta fuera del contrato es K5.
- Fase 1: un byte alterado, un archivo o una variable faltantes, un registro incompleto, datos
  inválidos o una salida dentro del repositorio terminan con el código 2 y 0 peticiones; un árbol de
  Git no limpio, con el código 3.
"""

import copy
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import crear_app
from evaluacion.__main__ import ejecutar
from evaluacion.cliente import ClienteEvaluacion
from tests.fixtures.evaluacion_e2c import anotacion_json, escribir_conjunto
from tests.fixtures.historial_e1b2 import escribir as escribir_datos
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpretePorFuncion

RAIZ = Path(__file__).resolve().parents[2]

# Mensaje sintético -> (eventos de referencia, claves de cada producto esperado, en orden)
MENSAJES = {
    "2 fardos de frijol negro": ([ev(1, 0, "agregar", "2 fardos de frijol negro", producto="frijol negro", cantidad="2", unidad="venta", unidad_texto="fardos")],
                                 [[["frijol", "negro"]]]),
    "zqxpido zqxtortas": ([ev(1, 0, "agregar", "zqxtortas", producto="zqxtortas")], [[["zqxtortas"]]]),
    "3 fardos de frijol rojo y zqxpastel": ([ev(1, 0, "agregar", "3 fardos de frijol rojo", producto="frijol rojo", cantidad="3", unidad="venta", unidad_texto="fardos"),
                                             ev(2, 0, "agregar", "zqxpastel", producto="zqxpastel")], [[["frijol", "rojo"]], [["zqxpastel"]]]),
}


def interpretar(entrada):
    return {"eventos": MENSAJES[entrada.mensajes[0]][0], "consultas": [], "instrucciones_rechazadas": []}


@pytest.fixture(scope="module")
def datos_dir(tmp_path_factory):
    return escribir_datos(tmp_path_factory.mktemp("datos_eval"))


@pytest.fixture(scope="module")
def app_referencia(datos_dir):
    from app.datos.carga import cargar_datos

    return crear_app(datos=cargar_datos(datos_dir), interprete=InterpretePorFuncion(interpretar))


def esperados_de_referencia(app):
    """Respuestas que produce el motor con la interpretación de referencia (sin `cliente_id` ni `mensaje_cliente`)."""
    with TestClient(app) as tc:
        resultado = {}
        for mensaje in MENSAJES:
            r = tc.post("/v1/pedidos/interpretar", json={"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": [mensaje]})
            cuerpo = json.loads(r.text, parse_float=Decimal, parse_int=Decimal)
            resultado[mensaje] = {k: v for k, v in cuerpo.items() if k not in ("cliente_id", "mensaje_cliente")}
    return resultado


def preparar(tmp_path, app, roles, privado_rol="validacion_privada", alterar=None):
    """Escribe un conjunto por rol y el registro; devuelve (registro, entorno, número de casos por rol)."""
    esperados = esperados_de_referencia(app)
    entradas, entorno = [], {}
    for rol in roles:
        casos, anot = [], {}
        for i, (mensaje, (_, claves)) in enumerate(MENSAJES.items()):
            cid = f"{rol[:3].upper()}{i}"
            esp = copy.deepcopy(esperados[mensaje])
            if alterar and alterar[0] == rol and alterar[1] == i:
                esp["estado"] = "confirmado" if esp["estado"] != "confirmado" else "requiere_revision"
            casos.append({"id": cid, "tipo": "sintetico", "entrada": {"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": [mensaje]}, "esperado": esp})
            anot[cid] = anotacion_json(claves)
        d, rutas = escribir_conjunto(tmp_path / rol, casos, anot, rol=rol, id=f"sint_{rol}", privado=(rol == privado_rol))
        archivos = {}
        for nombre, ruta in rutas.items():
            variable = f"EVAL_SINT_{rol.upper()}_{nombre.upper()}"
            entorno[variable] = str(ruta)
            archivos[nombre] = {"sha256": d.sha256[nombre], "variable": variable}
        entradas.append({"id": d.id, "rol": rol, "n_casos": d.n_casos, "n_mensajes": d.n_mensajes, "privado": d.privado, "archivos": archivos})
    registro = tmp_path / "registro.json"
    registro.write_text(json.dumps(entradas), encoding="utf-8")
    return registro, entorno


def correr(modo, registro, entorno, datos_dir, salida, cliente, verificar_arbol=False, raiz=RAIZ):
    lineas = []
    codigo = ejecutar(modo, registro, "http://testserver", 5, salida, {**entorno, "DATA_DIR": str(datos_dir)}, cliente=cliente,
                      raiz=raiz, verificar_arbol=verificar_arbol, salida_texto=lineas.append)
    return codigo, lineas


def leer(salida):
    (carpeta,) = list(Path(salida).iterdir())
    return json.loads((carpeta / "reporte_privado.json").read_text()), json.loads((carpeta / "resumen_publico.json").read_text())


# ====================================================================== resultados


def test_e3_con_intérprete_de_referencia_da_100(tmp_path, app_referencia, datos_dir):
    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"])
    with TestClient(app_referencia, raise_server_exceptions=False) as tc:
        cliente = ClienteEvaluacion(cliente=tc)
        codigo, lineas = correr("e3", registro, entorno, datos_dir, tmp_path / "salida", cliente)
    privado, publico = leer(tmp_path / "salida")
    assert codigo == 0 and cliente.peticiones == 2 * len(MENSAJES)
    assert publico["veredicto"] == {**publico["veredicto"], "exactitud": "100.00 %", "aprobado": True}
    assert all(r["k_casos"] == {k: 0 for k in ("k1", "k2", "k3", "k4", "k5")} for c in privado["conjuntos"].values() for r in c["resumenes"])


def test_e3_un_caso_alterado_baja_la_exactitud(tmp_path, app_referencia, datos_dir):
    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"], alterar=("ajuste", 1))
    with TestClient(app_referencia, raise_server_exceptions=False) as tc:
        codigo, _ = correr("e3", registro, entorno, datos_dir, tmp_path / "salida", ClienteEvaluacion(cliente=tc))
    _, publico = leer(tmp_path / "salida")
    assert codigo == 1 and publico["veredicto"]["correctos"] == 2 * len(MENSAJES) - 1


def test_e6_tres_repeticiones_y_validacion_privada_sin_detalle_publico(tmp_path, app_referencia, datos_dir):
    registro, entorno = preparar(tmp_path, app_referencia, ["validacion_publica", "validacion_privada"])
    with TestClient(app_referencia, raise_server_exceptions=False) as tc:
        cliente = ClienteEvaluacion(cliente=tc)
        codigo, lineas = correr("e6", registro, entorno, datos_dir, tmp_path / "salida", cliente)
    privado, publico = leer(tmp_path / "salida")
    assert codigo == 0 and cliente.peticiones == 3 * 2 * len(MENSAJES)
    assert set(publico["conjuntos"]["sint_validacion_privada"]) == {"sha256", "aprobado"}
    assert len(privado["conjuntos"]["sint_validacion_privada"]["resumenes"]) == 3
    assert publico["conjuntos"]["sint_validacion_publica"]["veredicto"]["minimo"] == "100.00 %"
    assert "sint_validacion_privada: APROBADO" in lineas


def test_produccion_503_da_0_con_una_peticion_por_caso(tmp_path, app_referencia, datos_dir):
    from app.datos.carga import cargar_datos

    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"])
    with TestClient(crear_app(datos=cargar_datos(datos_dir)), raise_server_exceptions=False) as tc:
        cliente = ClienteEvaluacion(cliente=tc)
        codigo, _ = correr("e3", registro, entorno, datos_dir, tmp_path / "salida", cliente)
    privado, publico = leer(tmp_path / "salida")
    assert codigo == 1 and cliente.peticiones == 2 * len(MENSAJES) and publico["veredicto"]["exactitud"] == "0.00 %"
    assert privado["conjuntos"]["sint_desarrollo"]["resumenes"][0]["invalidos"] == {"HTTP_503": len(MENSAJES)}


@pytest.mark.parametrize(
    ("respuesta", "codigo_caso", "k5"),
    [
        (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("t", request=request)), "TIMEOUT", 0),
        (lambda request: httpx.Response(200, content=b"no es json"), "JSON_INVALIDO", 0),
        (lambda request: httpx.Response(200, json={"estado": "confirmado"}), "CONTRATO", 1),
        (lambda request: httpx.Response(500, json={"detail": "x"}), "HTTP_500", 0),
    ],
    ids=["timeout", "json_invalido", "contrato", "http_500"],
)
def test_invalidos_cuentan_como_incorrectos_y_sin_reintentos(tmp_path, app_referencia, datos_dir, respuesta, codigo_caso, k5):
    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"])
    llamadas = []

    def manejador(request):
        llamadas.append(1)
        return respuesta(request)

    cliente = ClienteEvaluacion(cliente=httpx.Client(transport=httpx.MockTransport(manejador), base_url="http://x"))
    codigo, _ = correr("e3", registro, entorno, datos_dir, tmp_path / "salida", cliente)
    privado, publico = leer(tmp_path / "salida")
    casos = privado["conjuntos"]["sint_desarrollo"]["casos"][0]
    assert codigo == 1 and len(llamadas) == 2 * len(MENSAJES) and publico["veredicto"]["casos"] == 2 * len(MENSAJES)
    assert all(c["codigo"] == codigo_caso and c["k5"] == k5 and not c["correcto"] for c in casos)


# ====================================================================== fase 1: código 2 y 0 peticiones


def _cliente_contador():
    llamadas = []
    cliente = ClienteEvaluacion(cliente=httpx.Client(transport=httpx.MockTransport(lambda r: llamadas.append(1) or httpx.Response(500)), base_url="http://x"))
    return cliente, llamadas


@pytest.mark.parametrize("rol", ["desarrollo", "ajuste"])
@pytest.mark.parametrize("archivo", ["casos", "anotaciones"])
def test_un_byte_alterado_en_cualquier_conjunto_detiene_antes_de_pedir(tmp_path, app_referencia, datos_dir, rol, archivo):
    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"])
    ruta = Path(entorno[f"EVAL_SINT_{rol.upper()}_{archivo.upper()}"])
    contenido = bytearray(ruta.read_bytes())
    contenido[-1] ^= 1
    ruta.write_bytes(bytes(contenido))
    cliente, llamadas = _cliente_contador()
    codigo, lineas = correr("e3", registro, entorno, datos_dir, tmp_path / "salida", cliente)
    assert (codigo, lineas, llamadas) == (2, ["HASH_DISTINTO"], []) and not (tmp_path / "salida").exists()


@pytest.mark.parametrize(
    ("romper", "codigo_esperado"),
    [
        (lambda registro, entorno, tmp: entorno.pop("EVAL_SINT_AJUSTE_CASOS"), "ARCHIVO_FALTANTE"),
        (lambda registro, entorno, tmp: registro.write_text(json.dumps([e for e in json.loads(registro.read_text()) if e["rol"] != "ajuste"])), "REGISTRO_INCOMPLETO"),
        (lambda registro, entorno, tmp: registro.write_text("no es json"), "REGISTRO_INVALIDO"),
        (lambda registro, entorno, tmp: entorno.update(DATA_DIR_ROTO=True), "DATOS_INVALIDOS"),
    ],
    ids=["variable_faltante", "registro_incompleto", "registro_invalido", "datos_invalidos"],
)
def test_otros_fallos_de_fase_1(tmp_path, app_referencia, datos_dir, romper, codigo_esperado):
    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"])
    romper(registro, entorno, tmp_path)
    directorio = tmp_path / "no_existe" if entorno.pop("DATA_DIR_ROTO", False) else datos_dir
    cliente, llamadas = _cliente_contador()
    codigo, lineas = correr("e3", registro, entorno, directorio, tmp_path / "salida", cliente)
    assert (codigo, lineas, llamadas) == (2, [codigo_esperado], [])


def test_salida_dentro_del_repositorio_se_rechaza_antes_de_pedir(tmp_path, app_referencia, datos_dir):
    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"])
    cliente, llamadas = _cliente_contador()
    codigo, lineas = correr("e3", registro, entorno, datos_dir, RAIZ / "evaluacion" / "salida_no_permitida", cliente)
    assert (codigo, lineas, llamadas) == (2, ["SALIDA_EN_REPOSITORIO"], []) and not (RAIZ / "evaluacion" / "salida_no_permitida").exists()


def test_arbol_no_limpio_da_codigo_3_sin_pedir(tmp_path, app_referencia, datos_dir):
    registro, entorno = preparar(tmp_path, app_referencia, ["desarrollo", "ajuste"])
    cliente, llamadas = _cliente_contador()
    codigo, lineas = correr("e3", registro, entorno, datos_dir, tmp_path / "salida", cliente, verificar_arbol=True, raiz=tmp_path)  # no es un repositorio
    assert (codigo, lineas, llamadas) == (3, ["ARBOL_NO_LIMPIO"], [])
