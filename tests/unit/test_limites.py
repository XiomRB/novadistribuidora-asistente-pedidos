"""D72: límite combinado de fragmentos (consultas + instrucciones rechazadas <= 20)."""

import json

import pytest
from pydantic import ValidationError

from app.dominio.esquema_eventos import Interpretacion
from app.dominio.limites import MAX_FRAGMENTOS_COMBINADOS, LimitesExcedidos, validar_interpretacion, validar_limites

MARCADOR = "ZQX-TEXTO-PRIVADO"


def datos(consultas: int, rechazadas: int) -> dict:
    fragmento = {"mensaje": 0, "texto": f"{MARCADOR} fragmento"}
    return {"eventos": [], "consultas": [fragmento] * consultas, "instrucciones_rechazadas": [fragmento] * rechazadas}


def test_limite_es_veinte():
    assert MAX_FRAGMENTOS_COMBINADOS == 20


@pytest.mark.parametrize(("consultas", "rechazadas"), [(0, 0), (20, 0), (0, 20), (10, 10), (13, 7), (1, 19)])
def test_hasta_veinte_combinados_es_valido(consultas, rechazadas):
    interpretacion = validar_interpretacion(datos(consultas, rechazadas), 1)
    validar_limites(interpretacion)
    assert len(interpretacion.consultas) + len(interpretacion.instrucciones_rechazadas) == consultas + rechazadas


@pytest.mark.parametrize(("consultas", "rechazadas"), [(20, 1), (1, 20), (11, 10), (10, 11), (20, 20)])
def test_mas_de_veinte_combinados_es_invalido(consultas, rechazadas):
    with pytest.raises(LimitesExcedidos, match="máximo combinado es 20"):
        validar_interpretacion(datos(consultas, rechazadas), 1)
    # El esquema de E1b-1 (límites individuales) acepta estos casos; el límite combinado los rechaza.
    interpretacion = Interpretacion.validar(datos(consultas, rechazadas), 1)
    with pytest.raises(LimitesExcedidos):
        validar_limites(interpretacion)


@pytest.mark.parametrize(("consultas", "rechazadas"), [(21, 0), (0, 21)])
def test_lista_individual_sobre_veinte_sigue_rechazada_por_e1b1(consultas, rechazadas):
    with pytest.raises(ValidationError):
        validar_interpretacion(datos(consultas, rechazadas), 1)


def test_acepta_json():
    texto = json.dumps(datos(10, 10))
    assert len(validar_interpretacion(texto, 1).consultas) == 10
    with pytest.raises(LimitesExcedidos):
        validar_interpretacion(json.dumps(datos(11, 10)), 1)


def test_error_sin_contenido_de_los_fragmentos():
    with pytest.raises(LimitesExcedidos) as info:
        validar_interpretacion(datos(15, 15), 1)
    assert MARCADOR not in str(info.value) and MARCADOR not in repr(info.value)
    assert "15 consultas + 15 instrucciones rechazadas = 30" in str(info.value)
