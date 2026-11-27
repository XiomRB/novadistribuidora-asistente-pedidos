"""Intérprete con LangChain y modelos de OpenRouter (hito 1).

- `InterpreteLLM(cadena, instrucciones)`: la cadena es cualquier objeto con `invoke(mensajes)` que
  devuelve la interpretación estructurada (en producción, `ChatOpenAI(...).with_structured_output`;
  en las pruebas, un modelo falso). Su salida pasa en todos los casos por `validar_interpretacion` (D72): una
  estructura inválida o un índice de mensaje fuera de rango se rechaza completa (503), nunca se
  procesa parcialmente.
- Estados para `/health` (ver `base.py`): no verificado hasta la primera invocación exitosa;
  `error_al_invocar_modelo` si la última falló; operativo si la última produjo una interpretación
  válida. `/health` nunca llama al proveedor.
- `crear_interprete_openrouter(config, datos)`: `ChatOpenAI` con la URL de OpenRouter, el modelo y la
  clave del entorno, `temperature=0`, timeout y reintentos acotados, y salida estructurada por
  llamada a función (la forma más compatible entre proveedores).
- Privacidad: al modelo solo van las instrucciones y los mensajes delimitados (sin `cliente_id` ni
  fecha). Los errores nunca conservan el mensaje del proveedor, la clave ni la solicitud.
- Hito 2: se pide a OpenRouter el coste real (`usage: {include: true}`) y la salida cruda
  (`include_raw`). Tokens de entrada y salida y coste efectivo se anotan en la traza; si el proveedor
  no informa el coste, queda `None` (nunca una estimación).
"""

from __future__ import annotations

import numbers
import threading
from typing import Any

from app.datos.modelos import Datos
from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Interpretacion
from app.dominio.limites import validar_interpretacion
from app.interprete.base import MOTIVO_ERROR_INVOCACION, MOTIVO_NO_VERIFICADO, InterpreteNoDisponible
from app.interprete.instrucciones import instrucciones_sistema, mensajes_usuario
from app.observabilidad import registro as traza

URL_OPENROUTER = "https://openrouter.ai/api/v1"
MOTIVO_SALIDA_INVALIDA = "interpretacion_invalida"


class InterpreteLLM:
    def __init__(self, cadena: Any, instrucciones: str):
        self._cadena = cadena
        self._instrucciones = instrucciones
        self._candado = threading.Lock()
        self._operativo: bool | None = None  # None: conectividad no verificada

    def _registrar(self, operativo: bool) -> None:
        with self._candado:
            self._operativo = operativo

    def mensajes(self, entrada: EntradaPedido) -> list[tuple[str, str]]:
        return [("system", self._instrucciones), ("human", mensajes_usuario(entrada.mensajes))]

    def interpretar(self, entrada: EntradaPedido) -> Interpretacion:
        try:
            bruto = self._cadena.invoke(self.mensajes(entrada))
        except Exception:  # noqa: BLE001 - timeout, HTTP, autenticación o salida no estructurada
            self._registrar(False)
            raise InterpreteNoDisponible(MOTIVO_ERROR_INVOCACION) from None
        bruto = _separar_uso(bruto)
        try:
            datos = bruto.model_dump() if hasattr(bruto, "model_dump") else bruto
            interpretacion = validar_interpretacion(datos, len(entrada.mensajes))
        except Exception:  # noqa: BLE001 - estructura inválida, índices fuera de rango o límites
            self._registrar(False)
            raise InterpreteNoDisponible(MOTIVO_SALIDA_INVALIDA) from None
        self._registrar(True)
        return interpretacion

    def estado(self) -> tuple[bool, str | None]:
        with self._candado:
            operativo = self._operativo
        if operativo is None:
            return False, MOTIVO_NO_VERIFICADO
        return (True, None) if operativo else (False, MOTIVO_ERROR_INVOCACION)


def _uso(mensaje: Any) -> dict[str, Any]:
    uso = getattr(mensaje, "usage_metadata", None) or {}
    tokens = (getattr(mensaje, "response_metadata", None) or {}).get("token_usage") or {}
    coste = tokens.get("cost")
    return {
        "tokens_entrada": uso.get("input_tokens", tokens.get("prompt_tokens")),
        "tokens_salida": uso.get("output_tokens", tokens.get("completion_tokens")),
        "coste_usd": coste if isinstance(coste, numbers.Real) and not isinstance(coste, bool) else None,
        "modelo_respuesta": (getattr(mensaje, "response_metadata", None) or {}).get("model_name"),
    }


def _separar_uso(bruto: Any) -> Any:
    """Con `include_raw`, la cadena devuelve {raw, parsed, parsing_error}: anota el uso y devuelve lo analizado."""
    if isinstance(bruto, dict) and set(bruto) == {"raw", "parsed", "parsing_error"}:
        traza.anotar("interprete", **{k: v for k, v in _uso(bruto["raw"]).items() if k != "modelo_respuesta" or v})
        if bruto["parsing_error"] is not None:
            return None  # salida no estructurada: se rechaza en la validación
        return bruto["parsed"]
    return bruto


def crear_cadena_openrouter(modelo: str, clave: str, timeout_s: int, reintentos: int, http_client: Any = None) -> Any:
    from langchain_openai import ChatOpenAI  # solo aquí: el resto de la aplicación no depende de LangChain

    chat = ChatOpenAI(
        model=modelo,
        api_key=clave,
        base_url=URL_OPENROUTER,
        temperature=0,
        timeout=timeout_s,
        max_retries=reintentos,
        http_client=http_client,
        extra_body={"usage": {"include": True}},  # OpenRouter informa el coste efectivo
    )
    return chat.with_structured_output(Interpretacion, method="function_calling", include_raw=True)


def crear_interprete_openrouter(config: Any, datos: Datos | None = None, http_client: Any = None) -> InterpreteLLM:
    cadena = crear_cadena_openrouter(config.llm_modelo, config.openrouter_api_key, config.llm_timeout_s, config.llm_reintentos, http_client)
    return InterpreteLLM(cadena, instrucciones_sistema(config.llm_instrucciones, datos))
