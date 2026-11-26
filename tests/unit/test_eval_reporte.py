"""E2c-1: agregados y veredictos (E3 con D33; E6 con la alternativa A) y escritura de reportes."""

import json
import stat
from pathlib import Path

import pytest

from evaluacion import reporte
from evaluacion.criticos import ResultadoCaso, evaluar_caso
from evaluacion.conjuntos import Caso
from tests.fixtures.evaluacion_e2c import NE, L, P, a_json, anot, cuerpo, esperado

RAIZ = Path(__file__).resolve().parents[2]


def bien(i, critico=True, provisional=False, texto=True):
    return ResultadoCaso(f"Z{i}", critico, True, "OK", texto_coincide=texto, clasificacion_coincide=True, texto_provisional=provisional)


def mal(i, critico=True, **k):
    return ResultadoCaso(f"Z{i}", critico, True, "OK", ("lineas",), **k)


def resumen(correctos, casos, **errores):
    resultados = [bien(i) for i in range(correctos)] + [mal(i + correctos, **errores) for i in range(casos - correctos)]
    return reporte.resumir(resultados)


# ====================================================================== E3


def test_e3_usa_la_formula_ponderada_y_no_el_promedio_de_porcentajes():
    dev, aj = resumen(99, 100), resumen(4, 5)  # 99 % y 80 %: el promedio sería 89,5 %
    v = reporte.veredicto_e3(dev, aj)
    assert (v["correctos"], v["casos"]) == (103, 105) and v["exactitud"] == "98.10 %" and v["A1_exactitud"]
    dev, aj = resumen(9, 10), resumen(80, 100)  # 90 % y 80 %: el promedio sería 85 %, ponderado 80,9 %
    assert not reporte.veredicto_e3(dev, aj)["A1_exactitud"]


def test_umbral_exacto_90_aprueba_y_899_no():
    assert reporte.supera_umbral(9, 10) and reporte.supera_umbral(900, 1000)
    assert not reporte.supera_umbral(899, 1000) and not reporte.supera_umbral(0, 0)


def test_e3_a2_k5_en_cualquier_caso_bloquea():
    v = reporte.veredicto_e3(resumen(99, 100, critico=False, k5=1), resumen(10, 10))
    assert v["A1_exactitud"] and not v["A2_k5_cero"] and not v["aprobado"]


def test_e3_a3_critico_con_k_bloquea_aunque_supere_el_90():
    v = reporte.veredicto_e3(resumen(99, 100, k3=1), resumen(10, 10))
    assert v["A1_exactitud"] and v["A2_k5_cero"] and not v["A3_sin_criticos"] and not v["aprobado"]
    no_critico = reporte.veredicto_e3(resumen(99, 100, critico=False, k3=1), resumen(10, 10))
    assert no_critico["aprobado"]  # fuera de los críticos, K1-K4 hacen incorrecto el caso pero no bloquean


def test_e3_recuentos_de_k_presentes_incluso_en_cero():
    r = reporte.resumir([bien(0)])
    assert r.k_unidades == {k: 0 for k in ("k1", "k2", "k3", "k4", "k5")} and r.k_casos == r.k_unidades


# ====================================================================== E6 (alternativa A)


def test_e6_tres_repeticiones_cada_una_con_90_media_y_minimo():
    v = reporte.veredicto_e6([resumen(10, 10), resumen(9, 10), resumen(19, 20)])
    assert v["aprobado"] and v["media"] == "95.00 %" and v["minimo"] == "90.00 %"
    assert not reporte.veredicto_e6([resumen(10, 10), resumen(10, 10), resumen(8, 10)])["aprobado"]
    assert not reporte.veredicto_e6([resumen(10, 10), resumen(10, 10)])["aprobado"]  # deben ser 3


def test_e6_un_error_critico_no_se_compensa():
    v = reporte.veredicto_e6([resumen(30, 30), resumen(29, 30, k4=1), resumen(30, 30)])
    assert v["repeticiones"][1]["umbral"] and not v["repeticiones"][1]["sin_criticos"] and not v["aprobado"]


def test_e6_k5_bloquea_cada_repeticion():
    v = reporte.veredicto_e6([resumen(30, 30), resumen(29, 30, critico=False, k5=1), resumen(30, 30)])
    assert not v["repeticiones"][1]["k5_cero"] and not v["aprobado"]


# ====================================================================== métricas aparte


def test_texto_provisional_fuera_del_denominador():
    r = reporte.resumir([bien(0), bien(1, texto=False), bien(2, provisional=True, texto=False)])
    assert (r.texto_coincide, r.texto_denominador) == (1, 2)
    assert (r.texto_provisional_coincide, r.texto_provisional_total) == (0, 1)
    assert r.correctos == 3  # el texto no cambia la exactitud principal


def test_invalidos_por_codigo_en_el_denominador():
    r = reporte.resumir([bien(0), ResultadoCaso("Z1", True, False, "TIMEOUT"), ResultadoCaso("Z2", True, False, "HTTP_503")])
    assert r.casos == 3 and r.correctos == 1 and r.invalidos == {"TIMEOUT": 1, "HTTP_503": 1}


# ====================================================================== escritura


def test_reportes_fuera_del_repositorio_y_de_solo_lectura(tmp_path):
    carpeta = reporte.escribir(tmp_path, RAIZ, "corrida", {"a": 1}, {"b": 2})
    assert json.loads((carpeta / "reporte_privado.json").read_text()) == {"a": 1}
    assert stat.S_IMODE(carpeta.stat().st_mode) == 0o700
    assert all(stat.S_IMODE((carpeta / f).stat().st_mode) == 0o400 for f in ("reporte_privado.json", "resumen_publico.json"))
    with pytest.raises(reporte.ErrorSalida):
        reporte.escribir(RAIZ / "evaluacion", RAIZ, "x", {}, {})


def test_t5_reporte_identico_ante_permutaciones_y_sin_rangos(tmp_path):
    esp = esperado([L("GS6")], [P(motivo=NE)])
    obtenido = cuerpo(esperado([L("GS6")], [P("GS6"), P("GS6"), P(motivo=NE, texto="zqxkiwi")]))
    caso = Caso("Z01", "sintetico", {"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": ["zqx"]}, esp)
    anotacion = anot(["gaseosa sol"], ["zqxkiwi"])

    class SinDatos:  # el recálculo falla sin datos: K5 = 1, igual en todas las permutaciones
        clientes = {}

    salidas = set()
    for orden in ([0, 1, 2], [2, 1, 0], [1, 2, 0]):
        c = {**obtenido, "pendientes": [obtenido["pendientes"][i] for i in orden]}
        r = evaluar_caso(caso, anotacion, "OK", json.loads(a_json(c)), c, SinDatos())
        salidas.add(json.dumps(reporte.caso_dict(r), sort_keys=True))
    assert len(salidas) == 1 and "rango" not in salidas.pop()
