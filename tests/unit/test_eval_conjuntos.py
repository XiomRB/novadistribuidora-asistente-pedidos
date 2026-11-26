"""E2c-1: fase 1 del evaluador (integridad, formato, recuentos, coherencia y anotaciones) y la lista
cerrada de palabras genéricas. Todo con conjuntos sintéticos en directorios temporales."""

import copy
import hashlib

import pytest

from app.datos.normalizacion import normalizar_texto
from evaluacion.conjuntos import ErrorIntegridad, cargar, clave_valida, contiene, palabras
from evaluacion.genericas import GENERICAS, PALABRAS_GENERICAS
from tests.fixtures.evaluacion_e2c import NE, L, P, S, anotacion_json, caso, escribir_conjunto, esperado

HASH_GENERICAS = "663475b9f5ec501f96f665851efd34ab95dd8c4c35affe59044809b333500a3e"


# ====================================================================== G-0: palabras genéricas


def test_g0_lista_cerrada_normalizada_y_con_hash_fijado():
    assert len(PALABRAS_GENERICAS) == len(GENERICAS) == 198
    assert list(PALABRAS_GENERICAS) == sorted(PALABRAS_GENERICAS)
    assert all(normalizar_texto(p) == p and " " not in p and p for p in PALABRAS_GENERICAS)
    assert hashlib.sha256("\n".join(PALABRAS_GENERICAS).encode()).hexdigest() == HASH_GENERICAS


@pytest.mark.parametrize("clave", ["de la", "litro", "dos cajas", "12", "ab", "ok", "por favor"])
def test_g1_claves_genericas_invalidas(clave):
    assert not clave_valida(palabras(clave))


@pytest.mark.parametrize("clave", ["zqx de", "zqxkiwi", "gaseosa sol", "zqxkiwi gaseosa"])
def test_g2_claves_validas(clave):
    assert clave_valida(palabras(clave))


# ====================================================================== coincidencias por palabras completas


@pytest.mark.parametrize(
    ("texto", "clave", "coincide"),
    [
        ("zqxa zqx kiwi zqxb", "zqx kiwi", True), ("ZQX, Kiwi!", "zqx kiwi", True), ("zqxkíwi", "zqxkiwi", True), ("zqx-kiwi", "zqx kiwi", True),
        ("zqxkiwi", "kiwi", False), ("zqxkiwi", "zqx", False), ("kiwis", "kiwi", False), ("zqx de kiwi", "zqx kiwi", False),
        ("600ml", "600", False), ("kiwi zqx", "zqx kiwi", False), ("zqx-kiwi", "zqxkiwi", False), ("lunas", "una", False),
    ],
)
def test_coincidencia_por_palabras_completas(texto, clave, coincide):
    assert contiene(palabras(texto), palabras(clave)) is coincide


# ====================================================================== anotaciones


def _conjunto(tmp_path, esp, anot, nombre="c", **descriptor):
    casos = [caso("Z01", ["zqx mensaje"], esp)]
    return escribir_conjunto(tmp_path / nombre, casos, {"Z01": anot}, **descriptor)


def _codigo(tmp_path, esp, anot, **descriptor):
    d, rutas = _conjunto(tmp_path, esp, anot, **descriptor)
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas)
    return e.value.codigo


ESP = esperado([L("GS6")], [P("PC2", "PE2"), P(motivo=NE)])


def test_anotacion_valida_carga(tmp_path):
    d, rutas = _conjunto(tmp_path, ESP, anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"skus": ["CL1"], "pedido_como": None}, {"pedido_como": 2}]))
    conjunto = cargar(d, rutas)
    assert conjunto.anotaciones["Z01"].consultados[1].pedido_como == 2


@pytest.mark.parametrize(
    ("anotacion", "codigo"),
    [
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]]]), "ANOTACION_INCOMPLETA"),
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], []]), "PRODUCTO_SIN_CLAVE"),
        (anotacion_json([[["de", "la"]], [["zqxpasta"]], [["zqxkiwi"]]]), "CLAVE_GENERICA"),
        (anotacion_json([[["kiwi"]], [["zqxpasta"]], [["zqxbatido", "kiwi"]]]), "CLAVES_SOLAPADAS"),
        (anotacion_json([[["zqx", "kiwi"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"claves": [["zqx", "kiwi"]], "pedido_como": None}]), "CLAVES_SOLAPADAS"),
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"skus": ["GS6"], "pedido_como": None}]), "SKU_CONSULTADO_ESPERADO"),  # K4-13
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"pedido_como": None}]), "CONSULTADO_SIN_EVIDENCIA"),
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"pedido_como": 3}]), "PEDIDO_COMO_INVALIDO"),  # K4-9
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"pedido_como": -1}]), "PEDIDO_COMO_INVALIDO"),
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"pedido_como": 0, "skus": ["GS6"]}]), "PEDIDO_COMO_INVALIDO"),  # K4-14
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], [{"pedido_como": 0}, {"pedido_como": 0}]), "PEDIDO_COMO_INVALIDO"),
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], texto_provisional="sí"), "ANOTACION_INVALIDA"),
        (anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], [["zqxkiwi"]]], critico=False, justificacion_no_critico="zqx"), "CRITICIDAD_INVALIDA"),
    ],
)
def test_anotaciones_invalidas_dan_codigo_fijo(tmp_path, anotacion, codigo):
    assert _codigo(tmp_path, ESP, anotacion) == codigo


def test_claves_del_mismo_producto_pueden_solaparse_y_kiwi_frente_a_zqxkiwi_es_valido(tmp_path):
    # Mismo producto: «gaseosa sol» está dentro de «gaseosa sol grande» y es válido.
    # Productos distintos: «kiwi» y «zqxkiwi» son palabras distintas (no se comparan subcadenas).
    d, rutas = _conjunto(tmp_path, ESP, anotacion_json([[["gaseosa", "sol"], ["gaseosa", "sol", "grande"]], [["kiwi"]], [["zqxkiwi"]]]))
    assert cargar(d, rutas)


def test_tx7_claves_parcialmente_solapadas_son_validas(tmp_path):
    esp = esperado(pendientes=[P(motivo=NE)])
    d, rutas = _conjunto(tmp_path, esp, anotacion_json([[["zqx", "kiwi"]]], [{"claves": [["kiwi", "fresco"]], "pedido_como": None}]))
    assert cargar(d, rutas)


def test_no_critico_requiere_justificacion_y_conjunto_que_lo_permita(tmp_path):
    con = anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], []], critico=False, justificacion_no_critico="mide solo el mensaje")
    assert _codigo(tmp_path, ESP, con) == "CRITICIDAD_INVALIDA"  # todos_criticos por defecto
    d, rutas = _conjunto(tmp_path, ESP, con, nombre="permite", todos_criticos=False)
    assert cargar(d, rutas).anotaciones["Z01"].critico is False
    sin = anotacion_json([[["gaseosa", "sol"]], [["zqxpasta"]], []], critico=False)
    assert _codigo(tmp_path, ESP, sin, nombre="sin", todos_criticos=False) == "CRITICIDAD_INVALIDA"


# ====================================================================== integridad


def _completo(tmp_path):
    esp = esperado([L("PH4", 3)], sustituciones=[S("PHD", "PH4", 3)], estado="confirmado")
    casos = [caso("Z01", ["zqx uno", "zqx dos"], esp), caso("Z02", ["zqx tres"], esperado(pendientes=[P(motivo=NE)]))]
    anot = {"Z01": anotacion_json([[["zqxpapel"]]]), "Z02": anotacion_json([[["zqxkiwi"]]])}
    esperadas = {"version": "sintetica", "casos": {c["id"]: {"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "n_mensajes": len(c["entrada"]["mensajes"]),
                                                             "esperado": c["esperado"]} for c in casos}}
    return escribir_conjunto(tmp_path / "completo", casos, anot, esperadas=esperadas)


def test_conjunto_completo_carga(tmp_path):
    d, rutas = _completo(tmp_path)
    assert len(cargar(d, rutas).casos) == 2


@pytest.mark.parametrize("archivo", ["casos", "esperadas", "anotaciones"])
@pytest.mark.parametrize("posicion", ["inicio", "medio", "fin"])
def test_un_byte_alterado_da_hash_distinto(tmp_path, archivo, posicion):
    d, rutas = _completo(tmp_path)
    contenido = bytearray(rutas[archivo].read_bytes())
    i = {"inicio": 0, "medio": len(contenido) // 2, "fin": len(contenido) - 1}[posicion]
    contenido[i] = (contenido[i] + 1) % 256
    rutas[archivo].write_bytes(bytes(contenido))
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas)
    assert e.value.codigo == "HASH_DISTINTO"


@pytest.mark.parametrize("archivo", ["casos", "esperadas", "anotaciones"])
def test_archivo_faltante(tmp_path, archivo):
    d, rutas = _completo(tmp_path)
    rutas[archivo].unlink()
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas)
    assert e.value.codigo == "ARCHIVO_FALTANTE"


def test_incoherencia_entre_casos_y_esperadas(tmp_path):
    esp = esperado(pendientes=[P(motivo=NE)])
    otra = copy.deepcopy(esp)
    otra["estado"] = "confirmado"
    casos = [caso("Z01", ["zqx"], esp)]
    d, rutas = escribir_conjunto(tmp_path / "inc", casos, {"Z01": anotacion_json([[["zqxkiwi"]]])}, esperadas={"casos": {"Z01": {"esperado": otra}}})
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas)
    assert e.value.codigo == "INCOHERENCIA_ESPERADAS"


def test_recuentos_de_casos_y_mensajes(tmp_path):
    d, rutas = _completo(tmp_path)
    for cambio, codigo in (({"n_casos": 3}, "RECUENTO_CASOS"), ({"n_mensajes": 4}, "RECUENTO_MENSAJES")):
        with pytest.raises(ErrorIntegridad) as e:
            cargar(type(d)(**{**d.__dict__, **cambio}), rutas)
        assert e.value.codigo == codigo


def test_el_error_solo_lleva_el_codigo(tmp_path):
    d, rutas = _completo(tmp_path)
    rutas["casos"].write_text('{"id": "ZQXSECRETO", "texto": "ZQXSECRETO"}\n', encoding="utf-8")
    d = type(d)(**{**d.__dict__, "sha256": {**d.sha256, "casos": hashlib.sha256(rutas["casos"].read_bytes()).hexdigest()}})
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas)
    assert str(e.value) == "FORMATO_CASOS" and "ZQX" not in repr(e.value.args)
