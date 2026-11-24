"""Atributos de D48, D75 y D76 sobre el catálogo sintético."""

import pytest

from app.dominio.atributos import Atributos, a_descripcion, combinar
from tests.fixtures.historial_e1b2 import cargar_contexto


@pytest.fixture(scope="module")
def vocab(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("atr")).vocabulario


def medidas(a):
    return sorted(f"{m.valor.normalize():f}{m.unidad or ''}" for m in a.medidas)


class TestExtraer:
    @pytest.mark.parametrize(
        ("texto", "grupo", "marcas", "variantes", "ms"),
        [
            ("gaseosa sol 600 ml", "gaseosa", ["sol"], [], ["600ml"]),
            ("la de 2 litros", None, [], [], ["2000ml"]),
            ("frijol negro", "frijol", [], ["negro"], []),
            ("aceite girasol oro", "aceite", ["oro"], ["girasol"], []),
            ("el girasol oro", None, ["oro"], ["girasol"], []),
            ("pasta fina coditos", "pasta", ["fina"], ["coditos"], []),
            ("no, mejor esa", None, [], [], []),
            ("", None, [], [], []),
        ],
    )
    def test_dimensiones(self, vocab, texto, grupo, marcas, variantes, ms):
        a = vocab.extraer(texto)
        assert (a.grupo, sorted(a.marcas), sorted(a.variantes), medidas(a)) == (grupo, marcas, variantes, ms)

    def test_vacio(self, vocab):
        assert vocab.extraer("no, mejor esa").vacio and not vocab.extraer("la de 2 litros").vacio

    def test_nombres_del_catalogo_son_compatibles_con_su_producto(self, vocab):
        for sku, producto in vocab.datos.productos.items():
            assert vocab.comparar(vocab.del_producto(sku), sku).compatible, sku


class TestComparar:
    @pytest.mark.parametrize(
        ("texto", "sku", "positivos", "contradiccion"),
        [
            ("la de 2 litros", "GS2", 1, False),
            ("la de 2 litros", "GS6", 0, True),
            ("gaseosa sol", "GS6", 2, False),
            ("gaseosa luz", "GS6", 1, True),
            ("frijol negro", "FR1", 1, True),
            ("2 de gaseosa", "GS6", 1, False),  # número sin unidad: no contradice
            ("la grande", "GS6", 0, False),  # sin información: no es compatible (D76)
        ],
    )
    def test_casos(self, vocab, texto, sku, positivos, contradiccion):
        c = vocab.comparar(vocab.extraer(texto), sku)
        assert (c.positivos, c.contradiccion) == (positivos, contradiccion)
        assert c.compatible is (positivos > 0 and not contradiccion)


class TestCombinar:
    def test_prevalece_lo_posterior_por_dimension(self, vocab):
        c = combinar(vocab.extraer("gaseosa sol 600 ml"), vocab.extraer("la de 2 litros"))
        assert (c.grupo, sorted(c.marcas), medidas(c)) == ("gaseosa", ["sol"], ["2000ml"])

    def test_cambio_de_grupo_toma_lo_nuevo(self, vocab):
        c = combinar(vocab.extraer("gaseosa sol 600 ml"), vocab.extraer("arroz sierra de libra"))
        assert (c.grupo, sorted(c.marcas), medidas(c)) == ("arroz", ["sierra"], ["1lb"])

    def test_descripcion_sintetica_se_resuelve(self, vocab):
        c = combinar(vocab.extraer("gaseosa sol 600 ml"), vocab.extraer("la de 2 litros"))
        assert a_descripcion(c) == "gaseosa sol 2000ml"
        assert vocab.indice.resolver(a_descripcion(c)).sku == "GS2"

    def test_vacios(self):
        assert combinar(Atributos(), Atributos()).vacio and a_descripcion(Atributos()) == ""
