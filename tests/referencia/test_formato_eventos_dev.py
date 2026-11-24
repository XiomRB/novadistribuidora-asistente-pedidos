"""D61-a y D66: formato de `eventos_dev.json` con lista blanca.

- En CI (sin datos): el archivo versionado cumple la lista blanca y cada valor inyectado en un
  campo (texto libre, datos personales, formatos inválidos, posiciones fuera de `texto`) hace
  fallar la validación. Cada caso negativo modifica un solo campo de un ejemplo válido.
- En local (`EVAL_DEV_PATH`, `DATA_DIR`): las posiciones caen dentro de los mensajes
  publicados, la reconstrucción pasa la validación de E1b-1 y D72, hay exactamente los casos
  publicados y los SKU candidatos existen en el catálogo real.
"""

import copy
import json

import pytest

from tests.referencia.formato_eventos_dev import (
    CAMPOS_POSICION,
    RUTA,
    FormatoInvalido,
    cargar,
    reconstruir,
    validar_contra_mensajes,
    validar_estructura,
)

VALIDO = {
    "version": 1,
    "casos": {
        "D001": {
            "eventos": [
                {"id": "e1", "tipo": "agregar", "m": 0, "texto": [40, 70], "producto": [45, 70], "presentacion": None,
                 "unidad_texto": [42, 44], "candidatos": ["A01"], "cantidad": "3", "cantidad_incierta": False,
                 "unidad": "venta", "ref": None},
                {"id": "e2", "tipo": "corregir", "m": 0, "texto": [72, 80], "producto": None, "presentacion": None,
                 "unidad_texto": None, "candidatos": [], "cantidad": "5", "cantidad_incierta": False,
                 "unidad": "no_indicada", "ref": "e1"},
            ],
            "consultas": [{"m": 0, "i": 0, "f": 10}],
            "instrucciones_rechazadas": [],
        }
    },
}
MENSAJE_100 = ["x" * 100]


def con(ruta, valor):
    """Copia del ejemplo válido con un solo campo modificado (ruta: lista de claves e índices)."""
    documento = copy.deepcopy(VALIDO)
    objeto = documento
    for clave in ruta[:-1]:
        objeto = objeto[clave]
    objeto[ruta[-1]] = valor
    return documento


EVENTO = ["casos", "D001", "eventos", 0]


def test_ejemplo_valido():
    validar_estructura(VALIDO)


def test_archivo_versionado_cumple_la_lista_blanca():
    documento = cargar()
    assert len(documento["casos"]) == 84
    assert sum(len(c["eventos"]) for c in documento["casos"].values()) > 84


# ---------------------------------------------------------------- texto libre y datos personales

TEXTO_LIBRE = "kola norte 600"


@pytest.mark.parametrize("campo", ["tipo", "unidad", "cantidad", "ref", "id"])
def test_texto_libre_en_campos_de_cadena(campo):
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(EVENTO + [campo], TEXTO_LIBRE))


@pytest.mark.parametrize("nivel", [EVENTO, ["casos", "D001"], []])
@pytest.mark.parametrize("clave", ["producto_texto", "comentario"])
def test_clave_nueva_en_cualquier_nivel(nivel, clave):
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(nivel + [clave], TEXTO_LIBRE))


@pytest.mark.parametrize("valor", ["Persona Ficticia", "persona@ejemplo.com", "PERSONA", "a01", "A01 ", "A-01", "AB12345"])
def test_datos_personales_o_texto_en_candidatos(valor):
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(EVENTO + ["candidatos"], [valor]))


@pytest.mark.parametrize("valor", ["dos", "2 fardos", "1e3", "-1", "2,5", 2, 2.5])
def test_cantidad_solo_digitos(valor):
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(EVENTO + ["cantidad"], valor))


@pytest.mark.parametrize("campo", CAMPOS_POSICION)
@pytest.mark.parametrize("valor", [[45], [70, 45], [-1, 5], [0, 5, 9], [0.5, 4], "45-70", {"i": 45, "f": 70}, TEXTO_LIBRE, True])
def test_formato_de_posiciones(campo, valor):
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(EVENTO + [campo], valor))


@pytest.mark.parametrize("valor", [[0.5, 4], "45-70", {"i": 45, "f": 70}, None, [5, 5]])
def test_formato_de_texto(valor):
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(EVENTO + ["texto"], valor))


def test_booleano_fuera_de_cantidad_incierta_y_tipos_incorrectos():
    for ruta, valor in [(EVENTO + ["ref"], True), (EVENTO + ["m"], "1"), (EVENTO + ["m"], True), (EVENTO + ["cantidad_incierta"], "no"),
                        (["version"], 2), (["version"], "1")]:
        with pytest.raises(FormatoInvalido):
            validar_estructura(con(ruta, valor))


@pytest.mark.parametrize("campo", ["tipo", "unidad", "cantidad", "ref", "candidatos", "producto", "texto", "m"])
def test_objeto_anidado_en_cualquier_campo(campo):
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(EVENTO + [campo], {"nota": "x"}))


@pytest.mark.parametrize("clave", ["d001", "D001 extra", "D1", "caso1"])
def test_identificador_de_caso(clave):
    documento = copy.deepcopy(VALIDO)
    documento["casos"] = {clave: documento["casos"]["D001"]}
    with pytest.raises(FormatoInvalido):
        validar_estructura(documento)


def test_cadena_con_espacio_en_cada_campo_de_cadena():
    for campo, valor in [("id", "e 1"), ("tipo", "agregar "), ("unidad", " venta"), ("cantidad", "3 "), ("ref", "e1 ")]:
        with pytest.raises(FormatoInvalido):
            validar_estructura(con(EVENTO + [campo], valor))
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(EVENTO + ["candidatos"], ["A0 1"]))


def test_ids_no_consecutivos():
    with pytest.raises(FormatoInvalido):
        validar_estructura(con(["casos", "D001", "eventos", 1, "id"], "e3"))


def test_el_mensaje_de_error_no_incluye_el_valor():
    with pytest.raises(FormatoInvalido) as error:
        validar_estructura(con(EVENTO + ["candidatos"], ["Persona Ficticia"]))
    assert "Persona" not in str(error.value)


# ---------------------------------------------------------------- contención en `texto` (D66)


@pytest.mark.parametrize("campo", CAMPOS_POSICION)
@pytest.mark.parametrize(
    ("posicion", "valido"),
    [([40, 70], True), ([45, 60], True), ([10, 30], False), ([75, 90], False), ([35, 50], False), ([60, 75], False),
     ([30, 80], False), ([50, 50], False)],
)
def test_contencion_en_texto(campo, posicion, valido):
    documento = con(EVENTO + [campo], posicion)
    if valido:
        validar_estructura(documento)
        validar_contra_mensajes(documento["casos"]["D001"], MENSAJE_100)
    else:
        with pytest.raises(FormatoInvalido):
            validar_estructura(documento)


# ---------------------------------------------------------------- límite combinado (D56, D72)


@pytest.mark.parametrize(("consultas", "rechazadas", "valido"), [(0, 0, True), (20, 0, True), (0, 20, True), (10, 10, True),
                                                                 (21, 0, False), (20, 1, False), (1, 20, False), (11, 10, False)])
def test_limite_combinado_de_fragmentos(consultas, rechazadas, valido):
    documento = copy.deepcopy(VALIDO)
    caso = documento["casos"]["D001"]
    caso["consultas"] = [{"m": 0, "i": 0, "f": 1}] * consultas
    caso["instrucciones_rechazadas"] = [{"m": 0, "i": 0, "f": 1}] * rechazadas
    if valido:
        validar_estructura(documento)
    else:
        with pytest.raises(FormatoInvalido):
            validar_estructura(documento)


# ---------------------------------------------------------------- con los casos publicados (local)


def test_posiciones_dentro_de_los_mensajes_y_reconstruccion(casos_dev):
    documento = cargar()
    assert set(documento["casos"]) == {c["id"] for c in casos_dev}
    for caso in casos_dev:
        interpretacion = reconstruir(documento["casos"][caso["id"]], caso["entrada"]["mensajes"])
        assert len(interpretacion.eventos) == len(documento["casos"][caso["id"]]["eventos"])


def test_fuera_del_mensaje_se_rechaza(casos_dev):
    caso = next(c for c in casos_dev if c["id"] == "D001")
    mensajes = caso["entrada"]["mensajes"]
    largo = len(mensajes[0])
    documento = copy.deepcopy(cargar()["casos"]["D001"])
    documento["eventos"][0]["texto"] = [0, largo + 1]
    with pytest.raises(FormatoInvalido):
        validar_contra_mensajes(documento, mensajes)
    documento = copy.deepcopy(cargar()["casos"]["D001"])
    documento["eventos"][0]["m"] = 5
    with pytest.raises(FormatoInvalido):
        validar_contra_mensajes(documento, mensajes)


def test_candidatos_existen_en_el_catalogo_real(datos_reales):
    documento = cargar()
    candidatos = {s for c in documento["casos"].values() for e in c["eventos"] for s in e["candidatos"]}
    assert candidatos <= set(datos_reales.productos)


def test_el_archivo_no_contiene_texto_de_los_mensajes(casos_dev):
    """Además de D43 (que revisa todos los archivos), ninguna palabra de 4 letras o más de los
    mensajes aparece como valor de cadena en el archivo."""
    valores = set()

    def recorrer(objeto):
        if isinstance(objeto, dict):
            for v in objeto.values():
                recorrer(v)
        elif isinstance(objeto, list):
            for v in objeto:
                recorrer(v)
        elif isinstance(objeto, str):
            valores.add(objeto.casefold())

    recorrer(json.loads(RUTA.read_text(encoding="utf-8")))
    palabras = {p.casefold() for c in casos_dev for m in c["entrada"]["mensajes"] for p in m.split() if len(p) >= 4 and p.isalpha()}
    permitidas = {"agregar", "corregir", "quitar", "precisar", "habitual", "venta", "suelta", "docena", "otra", "no_indicada"}
    assert (valores & palabras) - permitidas == set()
