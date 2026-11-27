"""Hito 2 (D-M1): el contenido no se captura si la política no lo permite.

Se comprueba el `Registro` **antes** de exportar: tal como lo recibe `Trazador.registrar` (entrada del
búfer) y tal como sale del búfer hacia `_exportar`. Sin MLflow real: la exportación se sustituye.
"""

import copy

import pytest
from fastapi.testclient import TestClient

from app.interprete.llm import InterpreteLLM
from app.main import crear_app
from app.observabilidad.trazas import Trazador
from tests.fixtures.historial_e1b2 import cargar_contexto
from tests.fixtures.modelo_falso import Cadena
from tests.fixtures.observabilidad_falsa import EstadoFalso

MARCA = "zqxmarcacaptura"
EVENTO = {"id": "e1", "mensaje": 0, "tipo": "agregar", "texto": "2 fardos de frijol negro", "producto": "frijol negro",
          "cantidad": "2", "unidad": "venta", "unidad_texto": "fardos"}
LOCAL, REMOTA = "sqlite:///zqx.db", "https://mlflow.ejemplo.com"


class TrazadorEspia(Trazador):
    """Trazador real (política, búfer e hilo exportador) con la exportación a MLflow sustituida."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.experiment_id = "1"
        self.recibidos, self.del_bufer, self.registros = [], [], []

    def registrar(self, registro):
        self.registros.append(registro)
        self.recibidos.append((registro.captura_contenido, copy.deepcopy(registro.contenido)))
        super().registrar(registro)

    def _exportar(self, registro):
        self.del_bufer.append((registro.captura_contenido, copy.deepcopy(registro.contenido)))

    def cerrar(self):
        self._fin.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5)  # sin flush de MLflow: no se usa MLflow real


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("captura_datos")).datos


def ejecutar(datos, modo, uri, encabezados):
    from app.dominio.esquema_eventos import Interpretacion

    estado = EstadoFalso(uri=uri)
    trazador = TrazadorEspia(estado, modo=modo)
    interprete = InterpreteLLM(Cadena(Interpretacion.validar({"eventos": [EVENTO]}, 1)), "x")
    with TestClient(crear_app(datos=datos, interprete=interprete, observabilidad=(estado, trazador))) as cliente:
        r = cliente.post("/v1/pedidos/interpretar", json={"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00",
                                                          "mensajes": [f"{MARCA} 2 fardos de frijol negro"]},
                         headers={f"X-Evaluacion-{k}": v for k, v in encabezados.items()})
        assert r.status_code == 200
    assert len(trazador.recibidos) == 1 and len(trazador.del_bufer) == 1  # mismo comportamiento de exportación
    return trazador


@pytest.mark.parametrize(
    ("modo", "uri", "encabezados"),
    [
        ("metadatos", LOCAL, {"Conjunto": "PUB", "Privado": "0"}),
        ("completo", LOCAL, {"Conjunto": "D39", "Privado": "0"}),  # D39 declarado público por error
        ("completo", LOCAL, {"Conjunto": "D39", "Privado": "1"}),
        ("completo", LOCAL, {"Privado": "0"}),  # sin conjunto identificado
        ("completo", LOCAL, {"Conjunto": "PUB"}),  # sin "Privado: 0" explícito
        ("completo", REMOTA, {"Conjunto": "PUB", "Privado": "0"}),  # URI no local
        ("completo", LOCAL, {"Conjunto": "PUB;x", "Privado": "0"}),  # conjunto con caracteres no seguros
    ],
    ids=["metadatos_publico", "completo_d39_mal_configurado", "completo_d39", "completo_sin_conjunto",
         "completo_sin_privado_0", "completo_uri_remota", "completo_conjunto_invalido"],
)
def test_sin_autorizacion_el_contenido_no_entra_en_el_registro_ni_en_el_bufer(datos, modo, uri, encabezados):
    trazador = ejecutar(datos, modo, uri, encabezados)
    assert trazador.recibidos == [(False, {})]  # registro antes de entrar al búfer
    assert trazador.del_bufer == [(False, {})]  # registro tal como sale del búfer
    (registro,) = trazador.registros
    assert MARCA not in repr(registro) and "K04" not in repr(registro)  # ni en atributos ni en tramos


def test_completo_con_conjunto_publico_y_uri_local_conserva_el_contenido(datos):
    trazador = ejecutar(datos, "completo", LOCAL, {"Conjunto": "PUB", "Privado": "0"})
    ((captura, contenido),) = trazador.recibidos
    assert captura and contenido["entrada"] == {"mensajes": [f"{MARCA} 2 fardos de frijol negro"]}
    assert contenido["interpretacion"]["eventos"][0]["producto"] == "frijol negro"
    assert trazador.del_bufer == trazador.recibidos
