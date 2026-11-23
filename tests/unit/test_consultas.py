import pytest

from app.dominio.consultas import (
    consultas_puras,
    dentro_de_consulta,
    es_interrogativa,
    segmentar,
    tiene_marcador_compra,
)
from app.dominio.texto import Span


class TestSegmentacion:
    def test_posiciones_originales(self):
        mensaje = "Buenas, ¿tienen kola? Si hay, mándeme 2. Gracias!"
        partes = segmentar(mensaje, 4)
        assert [mensaje[o.span.inicio : o.span.fin] for o in partes] == ["Buenas,", "¿tienen kola?", "Si hay, mándeme 2.", "Gracias!"]
        assert all(o.span.mensaje == 4 and o.texto == mensaje[o.span.inicio : o.span.fin] for o in partes)

    def test_punto_decimal_no_corta(self):
        assert len(segmentar("mándeme kola 1.5 y agua 0.5. gracias", 0)) == 2

    def test_saltos_de_linea_y_lista(self):
        partes = segmentar("pedido:\n- 2 de kola\n- sopa rapida", 0)
        assert [o.texto for o in partes] == ["pedido:", "- 2 de kola", "- sopa rapida"]
        assert all(o.marcador_compra for o in partes[1:])

    def test_vacio(self):
        assert segmentar("   ", 0) == []


class TestClasificacion:
    @pytest.mark.parametrize(
        "texto",
        [
            "¿Tienen kola de 600?", "¿Cuánto cuesta el aceite?", "¿La próxima semana tendrán jabón?",
            "¿tienen 3 fardos de kola 600?", "tienen aceite dorado", "Buenas tardes, hay jabon rosa",
            "Quiero saber si ya tienen la lista de precios", "a como esta la kola", "¿Ya no van a venir los sábados?",
            "(audio transcrito) eh buenas este tienen aceite", "CUANTO ESTA EL FARDO DE AGUA",
            "necesito saber si tienen frijol rojo",
        ],
    )
    def test_consultas_puras(self, texto):
        (o,) = segmentar(texto, 0)
        assert o.consulta_pura, texto

    @pytest.mark.parametrize(
        "texto",
        [
            "¿me manda 2 fardos de agua pura 600?", "¿Me puede apuntar 3 de sal pacífico?", "¿me regala 2 de kola 600 porfa?",
            "¿Me hace favor de mandarme 3 cajas de aceite?", "¿me trae 4 de frijol negro?", "¿le encargo 2 de cloro?",
            "¿me anota 5 de sopa?", "¿me pone 2 cajas de café?", "¿me despacha 3 fardos de agua?", "¿quiero 2 de kola, se puede?",
        ],
    )
    def test_pedidos_interrogativos_no_son_consulta(self, texto):
        (o,) = segmentar(texto, 0)
        assert o.interrogativa and o.marcador_compra and not o.consulta_pura, texto

    @pytest.mark.parametrize("texto", ["mándeme 2 de kola", "y 48 latas de energía max", "tres de jabon rosa", "- sopa rapida", "sal pacifico: 5"])
    def test_marcadores_sin_pregunta(self, texto):
        assert tiene_marcador_compra(texto) and not es_interrogativa(texto)

    @pytest.mark.parametrize("texto", ["Gracias don", "ya me llegó todo completo", "Buenas"])
    def test_neutras(self, texto):
        (o,) = segmentar(texto, 0)
        assert not o.consulta_pura and not o.marcador_compra


class TestConsultaYPedido:
    def test_consulta_seguida_de_pedido(self):
        mensaje = "¿Tienen kola de 600? Si hay, mándeme 2"
        puras = consultas_puras([mensaje])
        assert puras == [Span(0, 0, 20)]
        pedido = Span(0, mensaje.index("mándeme"), len(mensaje))
        assert not dentro_de_consulta(pedido, puras)
        assert dentro_de_consulta(Span(0, 8, 19), puras)  # "kola de 600" dentro de la pregunta

    def test_mensajes_separados(self):
        puras = consultas_puras(["¿La próxima semana tendrán jabón?", "mándeme 3 de sal pacífico"])
        assert [s.mensaje for s in puras] == [0]

    def test_dentro_de_consulta_por_mitad(self):
        consulta = [Span(0, 0, 10)]
        assert dentro_de_consulta(Span(0, 5, 15), consulta)
        assert not dentro_de_consulta(Span(0, 6, 17), consulta)
        assert not dentro_de_consulta(Span(1, 0, 10), consulta)
        assert not dentro_de_consulta(Span(0, 3, 3), consulta)
