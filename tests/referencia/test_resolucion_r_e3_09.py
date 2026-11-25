"""D92 (R-E3-09) con el catálogo real (local; se omite sin DATA_DIR).

- Negativos: las menciones que antes confirmaban un producto equivocado.
- Marcas ajenas y jerga: D45 y D064 sin cambios; ninguna línea solo por el LLM.
- Positivos: 37 menciones, incluidos errores leves, con el mismo resultado de E1b-1.
- Corpus: las 475 descripciones generadas de nombres y alias dan exactamente los mismos resultados
  que antes de D92 (huella sha256 calculada con `main` en ac1eab4, antes de D92; solo el hash se versiona,
  nunca las descripciones, que derivan de los datos del curso).
"""

import hashlib
import json

import pytest

from app.dominio.catalogo import Evidencia as TipoEvidencia
from app.dominio.catalogo import IndiceCatalogo, TipoResolucion
from app.dominio.unidades import LexicoUnidades

R, A, N, AG = TipoResolucion.RESUELTO, TipoResolucion.AMBIGUO, TipoResolucion.NO_EXISTE, TipoResolucion.AGOTADO_SIN_SUSTITUTO
HUELLA_CORPUS = "918d25250a794b65b1c44c731eeebe372eaf6404fd5ee9f9d8475356cf7dddef"
TOTAL_CORPUS = 475


@pytest.fixture(scope="module")
def indice(datos_reales):
    return IndiceCatalogo(datos_reales, LexicoUnidades(datos_reales).palabras_cantidad())


def res(indice, texto, candidatos=()):
    r = indice.resolver(texto, list(candidatos))
    return r.tipo, r.sku, r.opciones


@pytest.mark.parametrize(
    ("texto", "candidatos", "esperado"),
    [
        ("levadura en polvo", (), (N, None, ())),
        ("levadura en polvo", ("A16",), (N, None, ())),
        ("chocolates amargos", (), (N, None, ())),
        ("chocolates amargos", ("S02",), (N, None, ())),
        ("chocolate amargo", (), (N, None, ())),
        ("leche Lala", (), (A, None, ())),
        ("leche Lala", ("A16",), (A, None, ())),
        ("café Sereno de 400 g", (), (A, None, ())),
        ("café Sereno de 400 g", ("A12",), (A, None, ())),
        ("arroz integral", (), (A, None, ())),
        ("arroz integral", ("A01",), (A, None, ())),
        ("fanta", (), (N, None, ())),
        ("sprite", (), (N, None, ())),
        ("Maizenas", (), (N, None, ())),
        ("leche descremada de medio litro", (), (N, None, ())),
    ],
)
def test_negativos_sin_lineas_ni_opciones_sin_evidencia(indice, texto, candidatos, esperado):
    assert res(indice, texto, candidatos) == esperado


def test_r1a_con_catalogo_real_registra_candidatos_llm_ignorados(indice):
    r = indice.resolver("levadura en polvo", ["A16"])
    assert (r.tipo, r.opciones, r.codigos) == (N, (), ("CANDIDATOS_LLM_IGNORADOS", "SIN_ANCLA_CATALOGO"))
    assert indice.resolver("levadura en polvo").codigos == ("SIN_ANCLA_CATALOGO",)


@pytest.mark.parametrize(("texto", "candidatos"), [("fanta", ("B01",)), ("fanta", ("B01", "B02", "B03")), ("sprite", ("B01",)), ("sprite", ("B01", "B02", "B03"))])
def test_marcas_ajenas_con_candidatos_son_d45_nunca_linea(indice, texto, candidatos):
    assert res(indice, texto, candidatos) == (A, None, ("B01", "B02", "B03"))


@pytest.mark.parametrize("texto", ["café Sereno de 8 litros", "leche Lala de 8 litros"])
def test_r2_con_medidas_contradictorias_conserva_no_existe(indice, texto):
    r = indice.resolver(texto)
    assert (r.tipo, r.opciones) == (N, ()) and "MEDIDA_SIN_PRODUCTO" in r.codigos


def test_r2_barrido_de_anclas_reales_con_token_desconocido(indice):
    for ancla in sorted(indice.anclas):
        for texto in (f"{ancla} zqxkw", f"{ancla} zqxkw de 5 litros", f"{ancla} zqxkw 999 g"):
            if indice.evidencia(texto) is not TipoEvidencia.TOKEN_DESCONOCIDO:
                continue
            r = indice.resolver(texto)
            assert (r.tipo, r.opciones) == (A, ()) or (r.tipo is N and "MEDIDA_SIN_PRODUCTO" in r.codigos), texto


def test_d45_y_d064_sin_cambios(indice):
    assert res(indice, "cocas", ("B01", "B02", "B03")) == (A, None, ("B01", "B02", "B03"))
    assert res(indice, "chescos de 600", ("B01",)) == (A, None, ("B01",))
    assert res(indice, "cocas") == (N, None, ())


@pytest.mark.parametrize(
    ("texto", "sku"),
    [("cloro", "L03"), ("detergente", "L01"), ("chicharritos", "S04"), ("sopa rapida", "A15")],
)
def test_precedentes_genericos_se_conservan(indice, texto, sku):
    assert res(indice, texto)[:2] == (R, sku)


POSITIVOS = [
    "shampoo birsa sobre 10 ml", "aceite girasol dordo 750 ml", "friijol negro", "nranjita 600 ml", "narannjita 1.5", "espagueti bellla",
    "laavaplatos brillo", "deetrgente espumoso 500 g", "paapel suave 4", "jaabon lavandero", "galletas saladdas crac", "té qutezal", "TE QUTZAL",
    "galletas ducitas vainilla", "chicharritos picntes 30 g", "maní sallado la finca 50 g", "juguitos", "naranjitas", "pasta", "aceite", "jabon",
    "coditos bella", "dulcitas vainilla", "desodorante fresco", "volcan 600", "leche en polvo vaquita 360 g", "leche vaquita", "jugo huerto naranja",
    "kola de litro y medio", "cloro blancura 1 l", "jabón de barra lavandero 350 g", "sopa rápida pollo 64 g", "agua cristal 600",
    "energia max", "harina mazorca", "sal pacifico 1 lb", "frijol negro monte verde 1 lb",
]


@pytest.mark.parametrize("texto", POSITIVOS)
def test_positivos_iguales_a_la_resolucion_de_e1b1(indice, texto):
    assert indice.resolver(texto) == indice._resolver_por_texto(texto)


def test_el_corpus_de_475_descripciones_no_cambia(datos_reales, indice):
    d = datos_reales
    corpus = set()
    for p in d.productos.values():
        corpus |= {p.nombre, p.nombre.lower(), f"{p.nombre} {p.presentacion}", f"2 de {p.nombre}", f"3 cajas de {p.nombre}"}
    for a in d.alias:
        pres = d.productos[a.sku].presentacion
        corpus |= {a.alias, f"{a.alias} {pres}", f"2 de {a.alias}", f"5 de {a.alias} {pres}", f"y 4 {a.alias}"}
    corpus |= {"pasta", "jabon", "frijol", "naranjitas", "aceite", "galletas", "juguitos", "kola 600",
               "kola de litro y medio", "kola norte 1.5 l", "agua pura 600", "shampoo birsa sobre 10 ml", "arroz ceiba de libra",
               "arroz quintal", "jugo de naranja", "kola de 5 litros", "kola de 3", "papel suave 4", "papel suave de 12"}
    filas = sorted(json.dumps([c, indice.resolver(c).tipo.value, indice.resolver(c).sku, list(indice.resolver(c).opciones)], ensure_ascii=False) for c in corpus)
    assert len(corpus) == TOTAL_CORPUS
    assert hashlib.sha256("\n".join(filas).encode("utf-8")).hexdigest() == HUELLA_CORPUS
