from datetime import datetime
from decimal import Decimal

import pytest

from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Interpretacion
from app.dominio.texto import (
    Medida,
    Span,
    anclar,
    extraer_medidas,
    localizar,
    normalizar_presentacion,
    peso_coincidencia,
    plegar,
    texto_original,
    tokens,
)

D = Decimal


class TestPresentaciones:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("1.5 L", "1500ml"), ("1,5 l", "1500ml"), ("litro y medio", "1500ml"), ("1 1/2", "1500ml"),
            ("600 ml", "600ml"), ("600ml", "600ml"), ("3 litros", "3000ml"), ("medio litro", "500ml"),
            ("de libra", "1lb"), ("1 lb", "1lb"), ("100 lb", "100lb"), ("400 g", "400g"), ("1 kg", "1000g"),
            ("12 rollos", "12rollo"), ("24 sobres", "24sobre"), ("20 bolsitas", "20bolsa"), ("12 paquetes", "12paquete"),
            ("600", "600"), ("de 3", "3"),
        ],
    )
    def test_normalizar(self, texto, esperado):
        assert normalizar_presentacion(texto) == esperado

    @pytest.mark.parametrize("texto", ["", "kola", "600 ml y 1.5 L"])
    def test_sin_una_unica_medida(self, texto):
        assert normalizar_presentacion(texto) is None

    def test_ignora_cantidades(self):
        assert extraer_medidas("2 fardos de kola 600", frozenset({"fardo", "fardos"})) == {Medida(D(600), None)}
        assert extraer_medidas("48 latas", frozenset({"lata", "latas"})) == frozenset()

    def test_contenedor_no_se_ignora(self):
        assert extraer_medidas("papel 12 rollos", frozenset({"rollo", "rollos"})) == {Medida(D(12), "rollo")}

    def test_decimal_desde_texto(self):
        (medida,) = extraer_medidas("1.5 L")
        assert isinstance(medida.valor, Decimal) and medida.valor == D(1500)

    @pytest.mark.parametrize(
        ("mencion", "producto", "coincide"),
        [
            (Medida(D(600), None), Medida(D(600), "ml"), True),
            (Medida(D("1.5"), None), Medida(D(1500), "ml"), True),
            (Medida(D(3), None), Medida(D(3000), "ml"), True),
            (Medida(D(4), None), Medida(D(4), "rollo"), True),
            (Medida(D(600), None), Medida(D(1500), "ml"), False),
            (Medida(D(1500), "ml"), Medida(D(1500), "ml"), True),
            (Medida(D(500), "ml"), Medida(D(500), "g"), False),
        ],
    )
    def test_coincidencia_de_medidas(self, mencion, producto, coincide):
        assert mencion.coincide(producto) is coincide


class TestTokens:
    def test_tokens(self):
        assert tokens("2 fardos de Kola Norte 600 ml") == ["fardos", "kola", "norte"]

    @pytest.mark.parametrize(
        ("a", "b", "peso"),
        [
            ("kola", "kola", 10), ("naranjitas", "naranjita", 9), ("frijoles", "frijol", 9),
            ("juguitos", "jugo", 7), ("farditos", "fardo", 8), ("birsa", "brisa", 7), ("dordo", "dorado", 7),
            ("sal", "sol", 0), ("cocas", "kola", 0), ("pasta", "papas", 0),
        ],
    )
    def test_peso_coincidencia(self, a, b, peso):
        assert peso_coincidencia(a, b) == peso

    def test_singular_pesa_mas_que_diminutivo(self):
        assert peso_coincidencia("naranjitas", "naranjita") > peso_coincidencia("naranjitas", "naranja")


class TestLocalizar:
    def test_exacto(self):
        assert localizar("kola 600", "mándeme kola 600", 0) == Span(0, 8, 16)

    def test_sin_mayusculas_ni_tildes_devuelve_posicion_original(self):
        mensaje = "MÁNDEME AZÚCAR DULZURA"
        span = localizar("azucar dulzura", mensaje, 3)
        assert span == Span(3, 8, 22) and mensaje[span.inicio : span.fin] == "AZÚCAR DULZURA"

    def test_aproximado(self):
        mensaje = "me manda 2 fardos de kola nrote 600 porfa"
        span = localizar("2 fardos de kola norte 600", mensaje, 0)
        assert span is not None and "kola" in mensaje[span.inicio : span.fin]

    def test_no_encontrado(self):
        assert localizar("cerveza artesanal importada", "mándeme 2 fardos de kola 600", 0) is None
        assert localizar("   ", "x", 0) is None

    def test_repetido_respeta_cursor(self):
        mensaje = "2 de kola, no, 2 de kola más"
        primero = localizar("2 de kola", mensaje, 0)
        segundo = localizar("2 de kola", mensaje, 0, desde=primero.fin)
        assert primero.inicio == 0 and segundo.inicio == 15

    def test_plegar_mapa(self):
        plegado, mapa = plegar("Ñandú")
        assert plegado == "nandu" and mapa == [0, 1, 2, 3, 4]


class TestSpan:
    def test_interseccion_y_contencion(self):
        a, b = Span(0, 0, 10), Span(0, 5, 15)
        assert a.interseccion(b) == 5 and not a.contiene(b) and Span(0, 0, 20).contiene(b)
        assert a.interseccion(Span(1, 0, 10)) == 0

    def test_invalido(self):
        with pytest.raises(ValueError):
            Span(0, 5, 2)


class TestAnclaje:
    def test_eventos_y_fragmentos(self):
        entrada = EntradaPedido("C001", datetime(2026, 11, 23, 9, 0), ("¿tienen kola? mándeme 2 de kola, y 2 de kola", "precio Q1"))
        interp = Interpretacion.validar(
            {
                "eventos": [
                    {"id": "e1", "mensaje": 0, "tipo": "agregar", "texto": "2 de kola", "producto": "kola"},
                    {"id": "e2", "mensaje": 0, "tipo": "agregar", "texto": "2 de kola", "producto": "kola"},
                    {"id": "e3", "mensaje": 0, "tipo": "agregar", "texto": "cerveza artesanal importada", "producto": "cerveza"},
                ],
                "consultas": [{"mensaje": 0, "texto": "¿tienen kola?"}],
                "instrucciones_rechazadas": [{"mensaje": 1, "texto": "precio Q1"}],
            },
            2,
        )
        anclaje = anclar(interp, entrada)
        e1, e2, e3 = anclaje.eventos
        assert texto_original(e1.span, entrada) == "2 de kola" and e2.span.inicio > e1.span.inicio
        assert not e3.anclado
        assert texto_original(anclaje.consultas[0].span, entrada) == "¿tienen kola?"
        assert anclaje.rechazadas[0].span == Span(1, 0, 9)
