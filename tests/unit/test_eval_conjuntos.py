"""E2c-1: fase 1 del evaluador (integridad, formato, recuentos, coherencia y anotaciones) y la lista
cerrada de palabras genéricas. Todo con conjuntos sintéticos en directorios temporales."""

import copy
import hashlib
import json

import pytest

from app.datos.normalizacion import normalizar_texto
from evaluacion import comparacion
from evaluacion.__main__ import leer_registro, main
from evaluacion.conjuntos import EXCEPCIONES_CLAVE_GENERICA, SIN_AUTORIZACIONES, Descriptor, ErrorIntegridad, cargar, cargar_todos, clave_valida, contiene, palabras
from evaluacion.genericas import GENERICAS, PALABRAS_GENERICAS
from tests.fixtures.evaluacion_e2c import NE, L, P, S, anot, anotacion_json, caso, cuerpo, escribir_conjunto, esperado, medir

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


# ====================================================================== EX: excepción de clave genérica
# Contenido completamente sintético. Solo los identificadores coinciden con el par autorizado.

FRASE = ["seis", "sobres"]  # solo palabras de la lista genérica
SIN_OPCIONES = esperado(pendientes=[P(motivo=NE, texto="seis sobres")])
DOS_SIN_OPCIONES = esperado(pendientes=[P(motivo=NE, texto="seis sobres"), P(motivo=NE, texto="zqxb")])
CON_OPCIONES = esperado(pendientes=[P("GS6", "GS2", texto="seis sobres")])


def con_generica(claves=(["zqxlacteo"],), generica=FRASE, **otros):
    return {"productos": [{"claves": [list(c) for c in claves], "clave_generica": generica}], "consultados": [], **otros}


def _entrada(tmp_path, id_, rol, casos, anotaciones, privado, excepciones=None):
    esperadas = {"version": "sintetica", "casos": {c["id"]: {"esperado": c["esperado"]} for c in casos}}
    d, rutas = escribir_conjunto(tmp_path / f"{id_}_{rol}", casos, anotaciones, esperadas=esperadas, rol=rol, id=id_, privado=privado)
    entrada = {"id": id_, "rol": rol, "n_casos": d.n_casos, "privado": privado,
               "archivos": {k: {"sha256": v, "ruta": str(rutas[k])} for k, v in d.sha256.items()}}
    if excepciones is not None:
        entrada["excepciones_clave_generica"] = excepciones
    return entrada, dict(d.sha256), rutas


def _d39(tmp_path, anot_caso, esp=SIN_OPCIONES, excepciones=("U03",), id_="D39", id_caso="U03", rol="validacion_privada", privado=True, anot_u01=None):
    casos = [caso("U01", ["zqx alfa"], esperado(pendientes=[P(motivo=NE, texto="zqx")])), caso(id_caso, ["zqx beta"], esp)]
    anotaciones = {"U01": anot_u01 or anotacion_json([[["zqxuno"]]]), id_caso: anot_caso}
    return _entrada(tmp_path, id_, rol, casos, anotaciones, privado, list(excepciones) if excepciones is not None else None)


def _publico(tmp_path, id_="PUB"):
    return _entrada(tmp_path, id_, "validacion_publica", [caso("V01", ["zqx"], SIN_OPCIONES)], {"V01": anotacion_json([[["zqxkiwi"]]])}, False)


def _registrar(tmp_path, entradas, autorizados):
    registro = tmp_path / "registro.json"
    registro.write_text(json.dumps(entradas), encoding="utf-8")
    return cargar_todos(leer_registro(registro, "e6", {}, tmp_path, autorizados), autorizados)


def _resultado(tmp_path, entradas, autorizados):
    try:
        return _registrar(tmp_path, entradas, autorizados)
    except ErrorIntegridad as e:
        return e.codigo


def test_ex1_con_la_excepcion_autorizada_el_pendiente_generico_se_empareja(tmp_path):
    privada, sha, _ = _d39(tmp_path, con_generica())
    conjuntos = _registrar(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha})
    anotacion = next(c for c in conjuntos if c.descriptor.id == "D39").anotaciones["U03"]
    assert anotacion.claves == ((("zqxlacteo",), ("seis", "sobres")),)
    obtenido = cuerpo(SIN_OPCIONES)
    assert comparacion.campos_distintos(comparacion.normalizar(obtenido), comparacion.normalizar(SIN_OPCIONES)) == ()
    assert medir(SIN_OPCIONES, obtenido, anotacion)[0] == {"K1": 0, "K2": 0, "K3": 0, "K4": 0, "sobrantes": 0, "mixtos": 0}
    assert medir(SIN_OPCIONES, obtenido, anot(["zqxlacteo"]))[0]["K3"] == 1  # sin la excepción, K3 = 1


def test_ex2_clave_generica_en_un_caso_no_declarado(tmp_path):
    privada, sha, _ = _d39(tmp_path, con_generica(), anot_u01=con_generica(claves=(["zqxuno"],), generica=["tres", "kilos"]))
    assert _resultado(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha}) == "CLAVE_GENERICA_NO_AUTORIZADA"


@pytest.mark.parametrize(
    "variante",
    ["d39_publico", "otro_conjunto_con_u03", "hashes_distintos", "id_duplicado", "produccion_sin_hashes", "no_privado", "campo_no_documentado"],
)
def test_ex3_la_excepcion_no_se_hereda(tmp_path, variante):
    publico = _publico(tmp_path)[0]
    if variante == "d39_publico":
        d39, sha, _ = _d39(tmp_path, con_generica(), rol="validacion_publica", privado=False)
        privada, _, _ = _d39(tmp_path / "otro", anotacion_json([[["zqxlacteo"]]]), id_="PRIV", excepciones=None)
        entradas, autorizados = [d39, privada], {"D39": sha}
    elif variante == "otro_conjunto_con_u03":
        privada, sha, _ = _d39(tmp_path, con_generica(), id_="D40")
        entradas, autorizados = [publico, privada], {"D40": sha, "D39": sha}
    elif variante == "hashes_distintos":
        privada, sha, _ = _d39(tmp_path, con_generica())
        entradas, autorizados = [publico, privada], {"D39": {**sha, "anotaciones": "0" * 64}}
    elif variante == "id_duplicado":
        privada, sha, _ = _d39(tmp_path, con_generica())
        entradas, autorizados = [_publico(tmp_path, id_="D39")[0], privada], {"D39": sha}
    elif variante == "produccion_sin_hashes":
        privada, sha, _ = _d39(tmp_path, con_generica())
        registro = tmp_path / "registro.json"
        registro.write_text(json.dumps([publico, privada]), encoding="utf-8")
        with pytest.raises(ErrorIntegridad) as e:
            leer_registro(registro, "e6", {}, tmp_path)  # sin autorizaciones: rechazo
        assert e.value.codigo == "REGISTRO_INVALIDO"
        return
    elif variante == "no_privado":
        privada, sha, _ = _d39(tmp_path, con_generica(), privado=False)
        entradas, autorizados = [publico, privada], {"D39": sha}
    else:  # un registro no puede declarar hashes autorizados ni ningún otro campo
        privada, sha, _ = _d39(tmp_path, con_generica())
        entradas, autorizados = [publico, {**privada, "hashes_autorizados": {"D39": sha}}], {"D39": sha}
    assert _resultado(tmp_path, entradas, autorizados) == "REGISTRO_INVALIDO"


def test_ex3_la_cli_no_admite_hashes_autorizados(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    ayuda = capsys.readouterr().out
    assert "autoriz" not in ayuda and "hash" not in ayuda


def test_ex4_frase_generica_en_claves_sigue_siendo_clave_generica(tmp_path):
    privada, sha, _ = _d39(tmp_path, con_generica(claves=(["zqxlacteo"], FRASE)))
    assert _resultado(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha}) == "CLAVE_GENERICA"


@pytest.mark.parametrize(
    ("anotacion", "esp"),
    [
        (con_generica(generica=["kilos"]), SIN_OPCIONES),  # una sola palabra
        (con_generica(generica=["seis", "zqxsobres"]), SIN_OPCIONES),  # una palabra no genérica
        (con_generica(generica=[]), SIN_OPCIONES),
        (con_generica(generica="seis sobres"), SIN_OPCIONES),  # no es una lista
        ({"productos": [{"claves": [["zqxa"]], "clave_generica": FRASE}, {"claves": [["zqxb"]], "clave_generica": ["tres", "kilos"]}], "consultados": []},
         DOS_SIN_OPCIONES),  # dos productos con el campo
        (con_generica(), CON_OPCIONES),  # pendiente con opciones
    ],
    ids=["una_palabra", "no_generica", "vacia", "no_lista", "dos_productos", "con_opciones"],
)
def test_ex5_requisitos_de_la_clave_generica(tmp_path, anotacion, esp):
    privada, sha, _ = _d39(tmp_path, anotacion, esp=esp)
    assert _resultado(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha}) == "CLAVE_GENERICA_NO_AUTORIZADA"


@pytest.mark.parametrize("con", ["producto", "consultado"])
def test_ex6_la_clave_generica_no_puede_solaparse(tmp_path, con):
    if con == "producto":
        anotacion = {"productos": [{"claves": [["zqxa"]], "clave_generica": FRASE}, {"claves": [["zqxb", "seis", "sobres"]]}], "consultados": []}
        esp = DOS_SIN_OPCIONES
    else:
        anotacion = {**con_generica(), "consultados": [{"claves": [["zqxdulce", "seis", "sobres"]], "pedido_como": None}]}
        esp = SIN_OPCIONES
    privada, sha, _ = _d39(tmp_path, anotacion, esp=esp)
    assert _resultado(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha}) == "CLAVES_SOLAPADAS"


@pytest.mark.parametrize(
    ("variante", "codigo"),
    [("sin_uso", "EXCEPCION_SIN_USO"), ("caso_inexistente", "REGISTRO_INVALIDO"), ("repetido", "REGISTRO_INVALIDO"), ("no_lista", "REGISTRO_INVALIDO")],
)
def test_ex7_excepcion_sin_uso_o_mal_declarada(tmp_path, variante, codigo):
    if variante == "sin_uso":
        privada, sha, _ = _d39(tmp_path, anotacion_json([[["zqxlacteo"]]]))
    elif variante == "caso_inexistente":
        privada, sha, _ = _d39(tmp_path, anotacion_json([[["zqxlacteo"]]]), id_caso="U04")
    elif variante == "repetido":
        privada, sha, _ = _d39(tmp_path, con_generica(), excepciones=("U03", "U03"))
    else:
        privada, sha, _ = _d39(tmp_path, con_generica())
        privada["excepciones_clave_generica"] = "U03"
    assert _resultado(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha}) == codigo


def test_ex9_un_unico_par_autorizado():
    assert EXCEPCIONES_CLAVE_GENERICA == frozenset({("D39", "U03")})


@pytest.mark.parametrize("id_", [None, "", "   ", 5, ["D39"], {"id": "D39"}], ids=["ausente", "vacio", "espacios", "numero", "lista", "objeto"])
def test_ex3_ids_invalidos_antes_de_la_unicidad(tmp_path, id_):
    publico = _publico(tmp_path)[0]
    privada, sha, _ = _d39(tmp_path, anotacion_json([[["zqxlacteo"]]]), excepciones=None)
    if id_ is None:
        del privada["id"]
    else:
        privada["id"] = id_
    assert _resultado(tmp_path, [publico, privada], {}) == "REGISTRO_INVALIDO"


def test_ex3_unicidad_global_incluye_otros_roles_y_modos(tmp_path):
    publico, privada = _publico(tmp_path)[0], _d39(tmp_path, anotacion_json([[["zqxlacteo"]]]), excepciones=None)[0]
    desarrollo = {**_publico(tmp_path / "dev", id_="D39")[0], "rol": "desarrollo"}  # rol de otro modo, mismo id
    assert _resultado(tmp_path, [publico, privada, desarrollo], {}) == "REGISTRO_INVALIDO"
    desarrollo["id"] = "DEV"
    assert _resultado(tmp_path, [publico, privada, desarrollo], {}) != "REGISTRO_INVALIDO"


@pytest.mark.parametrize("productos", [0, 2], ids=["menos_productos", "mas_productos"])
def test_ex5_cantidad_de_productos_antes_de_los_indices(tmp_path, productos):
    anotacion = {"productos": [{"claves": [[f"zqx{i}"]], "clave_generica": FRASE} for i in range(productos)], "consultados": []}
    privada, sha, _ = _d39(tmp_path, anotacion)
    assert _resultado(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha}) == "ANOTACION_INCOMPLETA"


@pytest.mark.parametrize(
    "producto",
    [None, 5, [], {}, {"clave_generica": FRASE}, {"claves": "zqx"}, {"claves": [["zqxa"]], "clave_generica": {"a": 1}},
     {"claves": [["zqxa"]], "clave_generica": [5, 6]}, {"claves": [["zqxa"]], "clave_generica": [["seis"], ["sobres"]]},
     {"claves": [["zqxa"]], "clave_generica": FRASE, "otro": 1}],
)
def test_ex5_anotaciones_malformadas_solo_dan_error_de_integridad(tmp_path, producto):
    privada, sha, _ = _d39(tmp_path, {"productos": [producto], "consultados": []})
    codigo = _resultado(tmp_path, [_publico(tmp_path)[0], privada], {"D39": sha})
    assert codigo in {"ANOTACION_INVALIDA", "CLAVE_GENERICA_NO_AUTORIZADA"}


# ---------------------------------------------------------------- llamada directa a cargar(), sin pasar por el registro


def _descriptor_directo(tmp_path, id_="D39", rol="validacion_privada", privado=True, excepciones=frozenset({"U03"}), id_caso="U03", anot_caso=None):
    """Descriptor construido a mano y los hashes sintéticos que lo autorizarían."""
    _, sha, rutas = _d39(tmp_path, anot_caso or con_generica(), id_=id_, id_caso=id_caso, rol=rol, privado=privado)
    return Descriptor(id=id_, rol=rol, sha256=sha, n_casos=2, privado=privado, excepciones_clave_generica=excepciones), rutas, {id_: dict(sha)}


@pytest.mark.parametrize(
    "cambio",
    [
        {"rol": "validacion_publica", "privado": False},  # descriptor público
        {"rol": "validacion_publica"},  # público aunque se marque privado
        {"privado": False},  # privado sin la marca
        {"id_": "D40"},  # otro conjunto con el caso U03
        {"id_": "d39"},  # el id se compara exacto
        {"rol": "desarrollo"},
        {"excepciones": frozenset({"U03", "U01"})},  # un caso fuera del par autorizado
        {"excepciones": frozenset({"U02"})},
        {"excepciones": frozenset({"U03"}), "id_caso": "U04"},  # el caso declarado no existe
        {"excepciones": ["U03"]},  # tipo distinto del esperado
    ],
    ids=["publico", "publico_marcado_privado", "no_privado", "otro_conjunto", "id_en_minusculas", "otro_rol",
         "caso_extra", "otro_caso", "caso_inexistente", "no_frozenset"],
)
def test_ex3_cargar_directo_no_activa_la_excepcion(tmp_path, cambio):
    d, rutas, autorizados = _descriptor_directo(tmp_path, **cambio)  # aun con sus hashes autorizados
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas, autorizados)
    assert e.value.codigo == "REGISTRO_INVALIDO"


@pytest.mark.parametrize("variante", ["publico", "sin_autorizacion"])
def test_ex3_cargar_directo_comprueba_antes_de_leer_archivos(tmp_path, variante):
    d, rutas, autorizados = _descriptor_directo(tmp_path, **({"rol": "validacion_publica", "privado": False} if variante == "publico" else {}))
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, {}, autorizados if variante == "publico" else SIN_AUTORIZACIONES)  # sin rutas: leer daría ARCHIVO_FALTANTE
    assert e.value.codigo == "REGISTRO_INVALIDO"


def test_ex3_cargar_directo_sin_excepcion_rechaza_la_clave_generica(tmp_path):
    d, rutas, autorizados = _descriptor_directo(tmp_path, excepciones=frozenset())
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas, autorizados)
    assert e.value.codigo == "CLAVE_GENERICA_NO_AUTORIZADA"


@pytest.mark.parametrize(
    "autorizacion",
    [
        None,  # ausente: argumento por defecto
        {},  # vacía
        {"D39": {}},
        "hash_distinto", "sin_esperadas", "archivo_extra", "bajo_otro_id", "no_es_mapa",
    ],
    ids=["ausente", "vacia", "sin_hashes_del_conjunto", "hash_distinto", "sin_esperadas", "archivo_extra", "bajo_otro_id", "no_es_mapa"],
)
def test_ex3_cargar_directo_sin_autorizacion_valida_rechaza(tmp_path, autorizacion):
    d, rutas, autorizados = _descriptor_directo(tmp_path)
    sha = autorizados["D39"]
    casos = {
        "hash_distinto": {"D39": {**sha, "anotaciones": "0" * 64}},
        "sin_esperadas": {"D39": {k: v for k, v in sha.items() if k != "esperadas"}},
        "archivo_extra": {"D39": {**sha, "otro": "0" * 64}},
        "bajo_otro_id": {"D40": sha},
        "no_es_mapa": {"D39": list(sha.values())},
    }
    autorizacion = casos.get(autorizacion, autorizacion) if isinstance(autorizacion, str) else autorizacion
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas) if autorizacion is None else cargar(d, rutas, autorizacion)
    assert e.value.codigo == "REGISTRO_INVALIDO"


def test_ex3_cargar_directo_archivo_distinto_del_autorizado(tmp_path):
    d, rutas, autorizados = _descriptor_directo(tmp_path)
    contenido = bytearray(rutas["anotaciones"].read_bytes())
    contenido[len(contenido) // 2] ^= 1
    rutas["anotaciones"].write_bytes(bytes(contenido))  # descriptor y autorización coinciden; el archivo no
    with pytest.raises(ErrorIntegridad) as e:
        cargar(d, rutas, autorizados)
    assert e.value.codigo == "HASH_DISTINTO"


def test_ex3_cargar_directo_con_autorizacion_correcta(tmp_path):
    d, rutas, autorizados = _descriptor_directo(tmp_path)
    assert cargar(d, rutas, autorizados).anotaciones["U03"].claves[0][-1] == ("seis", "sobres")


@pytest.mark.parametrize(("id_", "excepciones"), [("D40", ("U03",)), ("D39", ("U01",))], ids=["otro_conjunto", "otro_caso"])
def test_ex3_el_registro_rechaza_pares_no_autorizados_por_si_solo(tmp_path, id_, excepciones):
    privada, sha, _ = _d39(tmp_path, con_generica(), id_=id_, excepciones=excepciones)
    registro = tmp_path / "registro.json"
    registro.write_text(json.dumps([_publico(tmp_path)[0], privada]), encoding="utf-8")
    with pytest.raises(ErrorIntegridad) as e:
        leer_registro(registro, "e6", {}, tmp_path, {id_: sha})  # sin cargar(): solo el registro
    assert e.value.codigo == "REGISTRO_INVALIDO"


def test_ex3_el_registro_exige_el_vinculo_con_los_hashes_por_si_solo(tmp_path):
    privada, sha, _ = _d39(tmp_path, con_generica())
    registro = tmp_path / "registro.json"
    registro.write_text(json.dumps([_publico(tmp_path)[0], privada]), encoding="utf-8")
    for autorizados in (SIN_AUTORIZACIONES, {"D39": {**sha, "casos": "0" * 64}}):
        with pytest.raises(ErrorIntegridad) as e:
            leer_registro(registro, "e6", {}, tmp_path, autorizados)  # sin cargar(): solo el registro
        assert e.value.codigo == "REGISTRO_INVALIDO"
    assert leer_registro(registro, "e6", {}, tmp_path, {"D39": sha})[1][0].excepciones_clave_generica == {"U03"}
