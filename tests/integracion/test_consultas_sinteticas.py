"""Consultas puras frente a pedidos interrogativos, con productos sintéticos.

- Consultas: el fragmento del producto cae dentro de una consulta pura (0 falsos positivos:
  ninguna se trataría como pedido).
- Pedidos en forma de pregunta: el fragmento del producto NO cae en una consulta pura
  (0 pedidos descartados).
"""

import pytest

from app.dominio.consultas import consultas_puras, dentro_de_consulta
from app.dominio.texto import localizar

CONSULTAS = [
    (["¿Tienen gaseosa sol de 600?"], "gaseosa sol de 600"),
    (["¿Cuánto cuesta el aceite girasol?"], "aceite girasol"),
    (["¿La próxima semana tendrán jabón nube?"], "jabón nube"),
    (["¿tienen 3 fardos de gaseosa sol 600?"], "3 fardos de gaseosa sol 600"),
    (["Buenas, ¿hay frijol negro?"], "frijol negro"),
    (["buenas tardes tienen cafe monte molido"], "cafe monte molido"),
    (["¿A cómo está el fardo de arroz sierra?"], "arroz sierra"),
    (["¿Ya llegó el shampoo ola?"], "shampoo ola"),
    (["Quiero saber si tienen galletas luna"], "galletas luna"),
    (["necesito saber si ya hay detergente espuma"], "detergente espuma"),
    (["Hola", "¿manejan leche en polvo nieve?"], "leche en polvo nieve"),
    (["¿Qué precio tiene el cloro claro?"], "cloro claro"),
    (["CUANTO ESTA LA GASEOSA DE 2 LITROS"], "GASEOSA DE 2 LITROS"),
    (["(audio transcrito) eh buenas este tienen chicharrines picantes"], "chicharrines picantes"),
    (["¿Venden pasta fina coditos? 🙏"], "pasta fina coditos"),
    (["Disculpe, ¿cuándo vuelve a haber galletas luna chocolate?"], "galletas luna chocolate"),
    (["¿tienen papel higiénico nube de 12 rollos?"], "papel higiénico nube de 12 rollos"),
    (["Gracias don", "¿hay bebida rayo?"], "bebida rayo"),
    (["¿Me puede decir si hay arroz sierra quintal?"], "arroz sierra quintal"),
    (["¿Sabe si van a traer frijol rojo campo?"], "frijol rojo campo"),
    (["seño, ¿cuántos paquetes trae la galleta kris?"], "galleta kris"),
    (["¿cuanto cuesta la caja de aceite palma?"], "aceite palma"),
    (["¿Tienen brío de 600 ml?"], "brío de 600 ml"),
    (["¿Hay café monte instantáneo?"], "café monte instantáneo"),
    (["Una pregunta, ¿la gaseosa luz viene en 2 litros?"], "gaseosa luz"),
]

PEDIDOS_INTERROGATIVOS = [
    (["¿me manda 2 fardos de gaseosa sol 600?"], "2 fardos de gaseosa sol 600"),
    (["¿Me puede apuntar 3 de frijol negro?"], "3 de frijol negro"),
    (["¿me regala 2 de cloro claro porfa?"], "2 de cloro claro"),
    (["¿Me hace favor de mandarme 3 cajas de aceite girasol?"], "3 cajas de aceite girasol"),
    (["¿me trae 4 de arroz sierra de libra?"], "4 de arroz sierra de libra"),
    (["¿le encargo 2 cajas de café monte molido?"], "2 cajas de café monte molido"),
    (["¿me anota 5 displays de galletas luna vainilla?"], "5 displays de galletas luna vainilla"),
    (["¿me pone 2 fardos de detergente espuma?"], "2 fardos de detergente espuma"),
    (["¿me despacha 3 de shampoo ola?"], "3 de shampoo ola"),
    (["Buenas, ¿me puede mandar 6 de leche en polvo nieve?"], "6 de leche en polvo nieve"),
    (["¿Tienen gaseosa sol de 600? Si hay, mándeme 2"], "mándeme 2"),
    (["¿Hay frijol rojo?", "mándeme 3 de frijol rojo campo"], "3 de frijol rojo campo"),
    (["¿me deja 2 quintales de arroz sierra? quiero 2"], "quiero 2"),
    (["¿necesito 4 fardos de bebida rayo, me los manda?"], "4 fardos de bebida rayo"),
    (["¿Quisiera 2 displays de chicharrines picantes?"], "2 displays de chicharrines picantes"),
    (["y ¿3 de pasta fina coditos también?", "mándeme eso porfa"], "mándeme eso"),
]


def _ubicar(mensajes, fragmento):
    for indice, mensaje in enumerate(mensajes):
        span = localizar(fragmento, mensaje, indice)
        if span is not None:
            return span
    raise AssertionError(f"fragmento no encontrado: {fragmento}")


@pytest.mark.parametrize(("mensajes", "fragmento"), CONSULTAS, ids=[f"Q{i:02d}" for i in range(1, len(CONSULTAS) + 1)])
def test_consultas_sin_falsos_positivos(mensajes, fragmento):
    assert dentro_de_consulta(_ubicar(mensajes, fragmento), consultas_puras(mensajes))


@pytest.mark.parametrize(
    ("mensajes", "fragmento"), PEDIDOS_INTERROGATIVOS, ids=[f"P{i:02d}" for i in range(1, len(PEDIDOS_INTERROGATIVOS) + 1)]
)
def test_pedidos_interrogativos_no_se_descartan(mensajes, fragmento):
    assert not dentro_de_consulta(_ubicar(mensajes, fragmento), consultas_puras(mensajes))


def test_tamano_de_los_conjuntos():
    assert len(CONSULTAS) >= 25 and len(PEDIDOS_INTERROGATIVOS) >= 15
