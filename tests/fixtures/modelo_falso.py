"""Modelo de lenguaje falso para las pruebas del intérprete LLM (hito 1). Solo existe en las pruebas."""

SECRETO = "sk-or-ZQXSECRETO"  # clave inventada: sirve para comprobar que nunca se filtra


class Cadena:
    """Sustituto de la cadena de LangChain: devuelve en orden las salidas dadas (o las lanza si son
    excepciones; la última se repite) y registra los mensajes recibidos."""

    def __init__(self, *salidas):
        self.salidas = list(salidas)
        self.llamadas = []

    def invoke(self, mensajes):
        self.llamadas.append(mensajes)
        salida = self.salidas.pop(0) if len(self.salidas) > 1 else self.salidas[0]
        if isinstance(salida, BaseException):
            raise salida
        return salida
