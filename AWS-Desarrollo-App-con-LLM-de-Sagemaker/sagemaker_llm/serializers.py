"""
Utilidades para convertir mensajes entre el formato de LangChain y el formato
OpenAI-chat que espera el endpoint de SageMaker (LMI / TGI Messages API).
"""
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

# Qwen3 devuelve su razonamiento interno dentro de bloques <think>...</think>.
# Los quitamos para mostrar sólo la respuesta final al usuario.
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def to_openai_messages(
    lc_messages: list[BaseMessage],
    system_prompt: str | None = None,
) -> list[dict]:
    """Convierte mensajes de LangChain a la lista [{role, content}] de OpenAI."""
    msgs: list[dict] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    for m in lc_messages:
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        elif isinstance(m, SystemMessage):
            role = "system"
        else:
            role = "user"
        msgs.append({"role": role, "content": m.content})
    return msgs


def strip_thinking(text: str) -> str:
    """Elimina los bloques <think>...</think> que produce Qwen3 en modo reasoning."""
    return THINK_BLOCK_RE.sub("", text).strip()
