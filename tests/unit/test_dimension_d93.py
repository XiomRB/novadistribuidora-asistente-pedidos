"""D93: evidencia de que la unidad física es la de la cantidad total (E1-E3, T2-T4).

Casos numerados de la matriz aprobada (1-79), con ejemplos sintéticos: «detergente espuma» (un
producto que se vende por peso) en el papel de un producto pedido por volumen, y «cloro claro»
(se vende por volumen) pedido por peso. Aquí se prueba solo si D93 se activa y con qué dimensión;
los resultados del pedido están en `tests/integracion/test_pedido_d93.py`.
"""

from decimal import Decimal

import pytest

from app.dominio.esquema_eventos import Evento
from app.dominio.plegado import _decimal_sin_ambiguedad, contar_expresiones_numericas, dimension_cantidad_total

X = "detergente espuma"
V, M = "volumen", "masa"


def ev(texto, tipo="agregar", producto=X, cantidad="5", unidad="otra", unidad_texto="litros", **otros):
    campos = dict(producto=producto, cantidad=cantidad, unidad=unidad, unidad_texto=unidad_texto, **otros)
    if tipo == "corregir":
        campos["ref"] = "e1"
    return Evento(id="e2" if tipo == "corregir" else "e1", mensaje=0, tipo=tipo, texto=texto, **{k: v for k, v in campos.items() if v is not None})


# (número de caso, fragmento, campos del evento, dimensión esperada o None = D93 no se activa)
CASOS = [
    (1, f"2 cajas de {X} de 1 litro", dict(cantidad="2", unidad="venta", unidad_texto="cajas", presentacion="1 litro"), None),  # E2
    (2, f"2 cajas de {X} de 1 litro", dict(cantidad="1", unidad_texto="litro"), None),  # T3, T4
    (3, f"2 cajas de {X} de 1 litro", dict(cantidad="2", unidad_texto="litro"), None),  # T2, T4
    (4, f"6 bolsitas de {X} de medio litro", dict(cantidad="6", unidad="suelta", unidad_texto="bolsitas", presentacion="medio litro"), None),  # E2
    (5, f"6 bolsitas de {X} de medio litro", dict(cantidad="0.5", unidad_texto="litro"), None),  # T2, T3
    (6, f"5 litros de {X}", dict(), V),
    (10, "3 botellas de gaseosa sol de 600 ml", dict(producto="gaseosa sol", cantidad="3", unidad="suelta", unidad_texto="botellas", presentacion="600 ml"), None),  # E2
    (11, f"dame {X} de 5 litros", dict(), None),  # T4: sustantivo antes del número
    (12, f"dame {X} de 5 litros", dict(cantidad=None, unidad="no_indicada", unidad_texto=None, presentacion="5 litros"), None),  # E1
    (13, f"2 litros de {X}", dict(cantidad="2"), V),
    (14, "6 libras de cloro claro", dict(producto="cloro claro", cantidad="6", unidad_texto="libras"), M),
    (15, "2 libras de pasta", dict(producto="pasta", cantidad="2", unidad_texto="libras"), M),
    (16, "3 kilos de frijol negro", dict(producto="frijol negro", cantidad="3", unidad_texto="kilos"), M),
    (17, "4 libras de frijol rojo", dict(producto="frijol rojo", cantidad="4", unidad_texto="libras"), M),
    (18, "1/2 libra de frijol negro", dict(producto="frijol negro", cantidad="0.5", unidad_texto="libra"), None),  # T2, T3
    (19, "6 bolsitas de medio litro", dict(tipo="corregir", producto=None, cantidad="6", unidad="suelta", unidad_texto="bolsitas", presentacion="medio litro"), None),  # E2
    (20, f"5 litros de {X}", dict(cantidad=None, unidad="no_indicada", unidad_texto=None, presentacion="5 litros"), None),  # E1
    (21, f"cinco litros de {X}", dict(), None),  # T2/T3: sin cifra
    (22, f"5 litros de {X}", dict(unidad="no_indicada"), None),  # E2
    (23, f"5 de {X}", dict(), None),  # T2/T4: la unidad no está escrita
    (25, f"5 litros de {X} en 2 bolsas", dict(), None),  # T3
    (26, f"5 litros de {X} y una caja", dict(), None),  # T3
    (27, "3 botellas de 1 litro de cloro claro", dict(producto="cloro claro", cantidad="1", unidad_texto="litro"), None),  # T3, T4
    (28, f"{X} en envase de 1 litro", dict(cantidad="1", unidad_texto="litro"), None),  # T4
    (29, f"{X} presentación 1 litro", dict(cantidad="1", unidad_texto="litro"), None),  # T4
    (30, f"botella de 1 litro de {X}", dict(cantidad="1", unidad_texto="litro"), None),  # T4
    (31, f"{X}, 5 litros", dict(), None),  # T4
    (32, f"1 litro de {X}", dict(cantidad="1", unidad_texto="litro"), V),
    (33, f"mándeme 5 litros de {X} por favor", dict(), V),
    (34, f"5l de {X}", dict(unidad_texto="l"), V),
    (35, f"5 litros de {X}", dict(cantidad="5.0"), V),
    (36, f"5 litros de {X}", dict(cantidad="5,0"), V),
    (37, f"5,0 litros de {X}", dict(cantidad="5"), V),
    (38, f"1,5 litros de {X}", dict(cantidad="1.5"), V),
    (39, f"1.500 litros de {X}", dict(cantidad="1.5"), None),  # T2: ambiguo
    (40, f"5,5 litros de {X}", dict(cantidad="5"), None),  # T2: valores distintos
    (41, f"1.000,5 litros de {X}", dict(cantidad="1000.5"), None),  # T2: inválido
    (42, f"0 litros de {X}", dict(cantidad="0"), None),  # T2: cero
    (43, f"5 litros de {X}", dict(unidad="venta"), None),  # E2
    (44, f"5 litros de {X}", dict(presentacion="5 litros"), None),  # E3
    (46, "mejor 5 litros de los grandes", dict(tipo="corregir", producto=None), None),  # T4: no es Q2
    (47, f"1,500 litros de {X}", dict(cantidad="1.5"), None),  # T2: coma y 3 dígitos
    (48, f"1.500 litros de {X}", dict(cantidad="1500"), None),  # T2: punto y 3 dígitos
    (49, f"0,125 litros de {X}", dict(cantidad="0.125"), None),  # T2
    (50, f"1,25 litros de {X}", dict(cantidad="1.25"), V),
    (51, f"12345 litros de {X}", dict(cantidad="12345"), V),  # límite de 5 dígitos
    (52, f"123456 litros de {X}", dict(cantidad="12345"), None),  # T2: 6 dígitos
    (53, f"1.5 litros de {X}", dict(cantidad="1.500"), None),  # T2: la cantidad del evento es ambigua
    (54, f"5. litros de {X}", dict(), None),  # T2/T4
    (55, f"1/2 litro de {X}", dict(cantidad="0.5", unidad_texto="litro"), None),  # T3: fracción
    (56, f"1 / 2 litro de {X}", dict(cantidad="0.5", unidad_texto="litro"), None),  # T3: fracción con espacios
    (57, f"medio litro de {X}", dict(cantidad="0.5", unidad_texto="litro"), None),  # T3: frase
    (58, f"1 1/2 litros de {X}", dict(cantidad="1.5"), None),  # T3: frase
    (59, f"5 litros de {X} y una bolsa", dict(), None),  # T3: «una»
    (60, f"5 litros de {X} para todos", dict(), None),  # T4: texto tras el producto
    (61, f"5 litros de {X} familiar", dict(producto=f"{X} familiar"), V),  # «familiar» no es «mil»
    (62, f"5 litros de {X} en 2 cajas", dict(), None),  # T3
    (63, f"5 litros de {X}, 3 botellas", dict(), None),  # T3
    (64, f"x2 5 litros de {X}", dict(), None),  # T3
    (65, f"dame 5 litros de {X}, unas dos", dict(), None),  # T3
    (66, f"una docena de 5 litros de {X}", dict(), None),  # T3, T4
    (67, f"me trae 5 litros de {X} porfa", dict(), V),
    (68, f"apúnteme 2 litros de {X}, gracias", dict(cantidad="2"), V),
    (69, f"hola, necesito 5 litros de {X}", dict(), V),
    (70, f"le encargo 5 litros de la {X}", dict(), V),
    (71, f"por favor 5 litros de {X}", dict(), V),
    (72, f"hago mi pedido de 5 litros de {X}", dict(), None),  # T4: prefijos no admitidos
    (73, f"5 litros de {X}, gracias, nos vemos", dict(), None),  # T4: sufijo no admitido
    (74, f"5 litros de {X} 🙏", dict(), None),  # T4: carácter no permitido
    (75, f"5 litros de {X} azul", dict(), None),  # T4: texto tras el producto
    ("75b", f"5 litros de {X} azul", dict(producto=f"{X} azul"), V),
    (77, f"dame dame dame dame dame 5 litros de {X}", dict(), None),  # T4: más de 4 prefijos
    (78, "que sean 5 litros porfa", dict(tipo="corregir", producto=None), V),  # Q2
    ("9q2", "mejor 5 litros", dict(tipo="corregir", producto=None), V),  # caso 9: la corrección es Q2
]


@pytest.mark.parametrize(("numero", "fragmento", "campos", "esperado"), CASOS, ids=[f"c{c[0]}" for c in CASOS])
def test_matriz_d93(numero, fragmento, campos, esperado):
    campos = dict(campos)
    tipo = campos.pop("tipo", "agregar")
    assert dimension_cantidad_total(ev(fragmento, tipo, **campos), fragmento) == esperado


def test_la_matriz_cubre_todos_los_casos_de_la_funcion():
    # 7, 8, 9 y 45 dependen de varios eventos; 24 es el código interno: están en integración.
    # 76 es la prueba aislada de T3 (abajo).
    numeros = {str(c[0]) for c in CASOS} - {"9q2"} | {"7", "8", "9", "24", "45", "76"}
    assert numeros == {str(n) for n in range(1, 79)} | {"75b"}  # 79 casos


# ---------------------------------------------------------------- localización exacta del producto


@pytest.mark.parametrize(
    ("fragmento", "producto"),
    [
        (f"5 litros de {X}", "detergente espumoso"),  # coincidencia parcial: no es el mismo texto
        ("5 litros de detergent espuma", X),  # error de escritura: no se localiza exactamente
        (f"5 litros de {X}", "detergente"),  # el producto es solo una parte de X
        ("5 litros de detergente", X),  # X es solo una parte del producto
        (f"5 litros de {X}", "espuma detergente"),  # mismas palabras, otro orden
    ],
)
def test_localizacion_exacta_del_producto(fragmento, producto):
    assert dimension_cantidad_total(ev(fragmento, producto=producto), fragmento) is None


def test_mayusculas_y_tildes_no_impiden_la_localizacion():
    assert dimension_cantidad_total(ev("5 LITROS de Detergente Espúma", producto="detergente espuma"), "5 LITROS de Detergente Espúma") == V


def test_agregar_sin_producto_no_activa_d93():
    assert dimension_cantidad_total(ev("5 litros", producto=None), "5 litros") is None


# ---------------------------------------------------------------- T2: Decimal sin ambigüedad


@pytest.mark.parametrize(
    ("texto", "valor"),
    [("5", Decimal(5)), ("5.0", Decimal(5)), ("5,0", Decimal(5)), ("1,5", Decimal("1.5")), ("1.25", Decimal("1.25")),
     ("12345", Decimal(12345)), ("12345,12", Decimal("12345.12"))],
)
def test_t2_formatos_validos(texto, valor):
    assert _decimal_sin_ambiguedad(texto) == valor


@pytest.mark.parametrize(
    "texto",
    ["1.500", "1,500", "12.345", "0,125", "0.125",  # ambiguos (separador seguido de 3 dígitos)
     "123456", "1.2345", "5.", ",5", "1.000,5", "1.000.000", "5e0", "-5", "0", "0,0", ""],
)
def test_t2_formatos_ambiguos_invalidos_o_cero(texto):
    assert _decimal_sin_ambiguedad(texto) is None


def test_t2_5_5punto0_y_5coma0_son_el_mismo_decimal():
    assert _decimal_sin_ambiguedad("5") == _decimal_sin_ambiguedad("5.0") == _decimal_sin_ambiguedad("5,0")


# ---------------------------------------------------------------- T3: expresiones numéricas (caso 76)


@pytest.mark.parametrize(
    ("texto", "total"),
    [
        ("para todos familiar lunas atun", 0),  # caso 76: nunca dentro de otra palabra
        ("1/2 litro", 1), ("1 / 2 litro", 1), ("medio litro", 1), ("litro y medio", 1), ("un litro y medio", 1),
        ("1 1/2 litros", 1), ("de litro", 1), ("5 y medio", 1),
        ("2 cajas", 1), ("3 botellas", 1), ("5l", 1), ("x2", 1), ("1.000,5", 1),
        ("una", 1), ("dos", 1), ("docena", 1), ("par", 1), ("mil", 1),
        ("5 litros y una bolsa", 2), ("5 litros en 2 cajas", 2), ("x2 5 litros", 2), ("una docena", 2),
    ],
)
def test_t3_conteo_por_pasadas(texto, total):
    assert contar_expresiones_numericas(texto)[0] == total


def test_t3_las_frases_tienen_prioridad_sobre_sus_partes():
    total, cifras = contar_expresiones_numericas("1 1/2 litros")
    assert total == 1 and cifras == []  # una frase; ni fracción ni cifras sueltas
