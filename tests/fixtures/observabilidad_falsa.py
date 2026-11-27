"""Observabilidad falsa para las pruebas de la API (hito 2): MLflow simulado, sin red ni MLflow real."""

from app.observabilidad.estado_mlflow import MOTIVO_MLFLOW_NO_CONFIGURADO, MOTIVO_MLFLOW_NO_DISPONIBLE


class EstadoFalso:
    """Estado de MLflow controlable: `configurado` y `disponible` se cambian en la prueba."""

    def __init__(self, configurado=True, disponible=True, uri="sqlite:///zqx.db"):
        self.configurado, self._disponible = configurado, disponible
        self.uri = uri if configurado else None
        self.iniciado = self.detenido = False

    @property
    def disponible(self):
        return self.configurado and self._disponible

    def poner(self, disponible):
        self._disponible = disponible

    def iniciar(self):
        self.iniciado = True

    def detener(self):
        self.detenido = True

    def sonda(self):
        if not self.configurado:
            return False, MOTIVO_MLFLOW_NO_CONFIGURADO
        return (True, None) if self._disponible else (False, MOTIVO_MLFLOW_NO_DISPONIBLE)


class TrazadorFalso:
    """Guarda los registros que recibiría MLflow."""

    def __init__(self, estado=None):
        self.estado = estado
        self.registros = []
        self.cerrado = False

    def registrar(self, registro):
        self.registros.append(registro)

    def cerrar(self):
        self.cerrado = True


def observabilidad_ok():
    estado = EstadoFalso()
    return estado, TrazadorFalso(estado)
