from datetime import datetime, timedelta, timezone

import pytest

from app.dominio.entrada import MAX_CARACTERES_MENSAJE, MAX_MENSAJES, EntradaInvalida, EntradaPedido

AHORA = datetime(2026, 11, 23, 15, 20)


def test_entrada_valida_convierte_a_tupla():
    entrada = EntradaPedido("C001", AHORA, ["hola", "mándeme 2 fardos"])  # type: ignore[arg-type]
    assert entrada.mensajes == ("hola", "mándeme 2 fardos")


def test_cliente_no_se_normaliza():
    assert EntradaPedido(" c001 ", AHORA, ("x",)).cliente_id == " c001 "


@pytest.mark.parametrize("cliente", ["", "   ", None, 7])
def test_cliente_invalido(cliente):
    with pytest.raises(EntradaInvalida, match="cliente_id"):
        EntradaPedido(cliente, AHORA, ("x",))  # type: ignore[arg-type]


def test_fecha_con_zona_horaria_rechazada():
    with pytest.raises(EntradaInvalida, match="zona horaria"):
        EntradaPedido("C001", AHORA.replace(tzinfo=timezone(timedelta(hours=-6))), ("x",))


def test_fecha_debe_ser_datetime():
    with pytest.raises(EntradaInvalida):
        EntradaPedido("C001", "2026-11-23T15:20", ("x",))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mensajes",
    [(), ("",), ("  ", "\n"), "un texto suelto", tuple("x" for _ in range(MAX_MENSAJES + 1)), ("x" * (MAX_CARACTERES_MENSAJE + 1),), (3,)],
)
def test_mensajes_invalidos(mensajes):
    with pytest.raises(EntradaInvalida):
        EntradaPedido("C001", AHORA, mensajes)  # type: ignore[arg-type]


def test_limites_exactos_admitidos():
    entrada = EntradaPedido("C001", AHORA, tuple(["x" * MAX_CARACTERES_MENSAJE] * MAX_MENSAJES))
    assert len(entrada.mensajes) == MAX_MENSAJES


def test_blancos_sueltos_admitidos():
    assert EntradaPedido("C001", AHORA, ("", "pedido")).mensajes == ("", "pedido")
