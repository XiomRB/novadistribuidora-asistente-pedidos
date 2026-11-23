import pytest

from app.datos.normalizacion import normalizar_texto, parsear_dias_visita


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Miércoles", "miercoles"),
        ("  SÁBADO ", "sabado"),
        ("Jabón   de   barra", "jabon de barra"),
        ("¿Qué tal?", "que tal"),
        ("ñandú", "nandu"),
        ("", ""),
    ],
)
def test_normalizar_texto(texto, esperado):
    assert normalizar_texto(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("lunes,jueves", {0, 3}),
        ("Miércoles , SÁBADO", {2, 5}),
        ("lunes,miércoles,viernes", {0, 2, 4}),
        ("domingo", {6}),
        ("martes,,viernes", {1, 4}),
        ("lunes,lunes", {0}),
        ("", set()),
    ],
)
def test_parsear_dias(texto, esperado):
    assert parsear_dias_visita(texto) == frozenset(esperado)


def test_dia_desconocido():
    with pytest.raises(ValueError, match="lunez"):
        parsear_dias_visita("lunez,jueves")
