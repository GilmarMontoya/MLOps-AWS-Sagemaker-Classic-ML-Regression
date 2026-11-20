"""
Cliente para consumir un endpoint de SageMaker que sirve un modelo de chat
(LMI / TGI con Messages API, formato OpenAI chat completions).

Expone la misma interfaz `.invoke({"messages": [...]})` que usa el agente de
LangChain, para que `app.py` no tenga que distinguir entre proveedores.
"""
import json

import boto3
from langchain_core.messages import AIMessage, BaseMessage

from .serializers import strip_thinking, to_openai_messages


class SageMakerChatClient:
    """Wrapper mínimo sobre `sagemaker-runtime.invoke_endpoint` con interfaz
    compatible con el agente de LangChain (método `.invoke`)."""

    def __init__(
        self,
        endpoint_name: str,
        region: str,
        aws_access_key_id: str | None,
        aws_secret_access_key: str | None,
        temperature: float,
        system_prompt: str,
        max_tokens: int = 512,
        hide_thinking: bool = True,
    ):
        self.endpoint_name = endpoint_name
        self.temperature = temperature
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.hide_thinking = hide_thinking

        # Misma sesión de boto3 que usan los scripts de regresión: credenciales
        # explícitas vía .env. Si faltan, boto3 cae a la cadena estándar
        # (AWS_PROFILE, rol, etc.).
        session = boto3.Session(
            aws_access_key_id=aws_access_key_id or None,
            aws_secret_access_key=aws_secret_access_key or None,
            region_name=region,
        )
        self.runtime = session.client("sagemaker-runtime")

    def invoke(self, input_dict: dict) -> dict:
        lc_messages: list[BaseMessage] = input_dict["messages"]

        payload = {
            "messages": to_openai_messages(lc_messages, system_prompt=self.system_prompt),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        response = self.runtime.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps(payload).encode("utf-8"),
        )

        body = json.loads(response["Body"].read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]

        if self.hide_thinking:
            content = strip_thinking(content)

        # Devolvemos el mismo shape que el agente de LangChain:
        # {"messages": [..., AIMessage]}, para que `run_turn` en agent.py funcione.
        return {"messages": lc_messages + [AIMessage(content=content)]}
