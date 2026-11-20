"""
Backend para consumir el LLM (Qwen3-4B, contenedor LMI/vLLM) desplegado en un endpoint de SageMaker.

El endpoint habla el formato de OpenAI chat completions:
    entrada:  {"messages": [...], "max_tokens": ..., "temperature": ..., "stream": bool}
    salida:   {"choices": [{"message": {"content": "..."}}], "usage": {...}}
    stream:   líneas "data: {...}" con choices[0].delta.content

Qwen3 "piensa" antes de responder y lo devuelve dentro de <think>...</think>.
Este módulo separa ese razonamiento de la respuesta final.
"""
import json
import re
import time
from dataclasses import dataclass, field
from typing import Iterator, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

THINK_RE = re.compile(r"<think>(.*?)</think>\s*", re.DOTALL)


@dataclass
class RespuestaLLM:
    """Resultado de una llamada no-streaming."""
    texto: str
    razonamiento: str = ""
    segundos: float = 0.0
    uso: dict = field(default_factory=dict)


def separar_razonamiento(texto: str) -> tuple[str, str]:
    """Devuelve (razonamiento, respuesta). Si el modelo se cortó a mitad del <think>, todo es razonamiento."""
    m = THINK_RE.search(texto)
    if m:
        return m.group(1).strip(), THINK_RE.sub("", texto).strip()
    if "<think>" in texto:
        return texto.split("<think>", 1)[1].strip(), ""
    return "", texto.strip()


def explicar_error(e: Exception) -> str:
    """Traduce los errores típicos de AWS a un mensaje entendible para el alumno."""
    if isinstance(e, NoCredentialsError):
        return "No hay credenciales de AWS. Configura `aws configure` o el `.env` (en ECS se usa el rol de la tarea)."
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        if code in ("AccessDeniedException", "AccessDenied"):
            if "service control policy" in msg:
                return ("Acceso denegado por una **SCP de la organización** (no es un problema de IAM ni de la app): "
                        "la organización bloquea `sagemaker:InvokeEndpoint` en esta cuenta/región.\n\n" + msg)
            return "Acceso denegado: el usuario o rol no tiene `sagemaker:InvokeEndpoint` sobre este endpoint.\n\n" + msg
        if code == "ValidationError" and "not found" in msg.lower():
            return "El endpoint no existe en esta región (¿se borró o la región es otra?).\n\n" + msg
        if code in ("UnrecognizedClientException", "InvalidClientTokenId", "ExpiredTokenException"):
            return "Las credenciales de AWS no son válidas o expiraron.\n\n" + msg
        if code == "ModelError":
            return "El modelo devolvió un error (¿demasiados tokens o payload inválido?).\n\n" + msg
        return f"{code}: {msg}"
    return f"{type(e).__name__}: {e}"


class ClienteLLMSageMaker:
    """Wrapper mínimo sobre sagemaker-runtime para un endpoint de chat."""

    def __init__(
        self,
        endpoint_name: str,
        region_name: str = "us-east-2",
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        self.endpoint_name = endpoint_name
        # Con keys explícitas (laptop con .env) o sin ellas (cadena estándar: ~/.aws o rol de la tarea en ECS)
        if aws_access_key_id and aws_secret_access_key:
            session = boto3.Session(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region_name,
            )
        else:
            session = boto3.Session(region_name=region_name)
        self.runtime = session.client("sagemaker-runtime")

    @staticmethod
    def armar_payload(
        historial: list[dict],
        system_prompt: str,
        max_tokens: int,
        temperature: float,
        pensar: bool,
        stream: bool,
    ) -> dict:
        mensajes = [{"role": "system", "content": system_prompt}] if system_prompt else []
        mensajes += [{"role": m["role"], "content": m["content"]} for m in historial]
        # Interruptor "suave" de Qwen3: /no_think en el último mensaje del usuario desactiva el razonamiento
        if not pensar and mensajes and mensajes[-1]["role"] == "user":
            mensajes[-1] = {**mensajes[-1], "content": mensajes[-1]["content"] + " /no_think"}
        return {"messages": mensajes, "max_tokens": max_tokens, "temperature": temperature, "stream": stream}

    def responder(self, historial: list[dict], system_prompt: str = "", max_tokens: int = 1024,
                  temperature: float = 0.7, pensar: bool = True) -> RespuestaLLM:
        """Llamada normal: espera la respuesta completa."""
        payload = self.armar_payload(historial, system_prompt, max_tokens, temperature, pensar, stream=False)
        t0 = time.time()
        r = self.runtime.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps(payload).encode("utf-8"),
        )
        body = json.loads(r["Body"].read())
        razonamiento, texto = separar_razonamiento(body["choices"][0]["message"]["content"] or "")
        return RespuestaLLM(texto=texto, razonamiento=razonamiento,
                            segundos=time.time() - t0, uso=body.get("usage", {}))

    def responder_stream(self, historial: list[dict], system_prompt: str = "", max_tokens: int = 1024,
                         temperature: float = 0.7, pensar: bool = True) -> Iterator[str]:
        """Streaming: va devolviendo trozos de texto (incluye el <think> crudo; el frontend lo separa)."""
        payload = self.armar_payload(historial, system_prompt, max_tokens, temperature, pensar, stream=True)
        r = self.runtime.invoke_endpoint_with_response_stream(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps(payload).encode("utf-8"),
        )
        buffer = ""
        for evento in r["Body"]:
            parte = evento.get("PayloadPart", {}).get("Bytes")
            if not parte:
                continue
            buffer += parte.decode("utf-8")
            # Los eventos pueden llegar partidos: solo se procesan líneas completas
            while "\n" in buffer:
                linea, buffer = buffer.split("\n", 1)
                trozo = self._extraer_trozo(linea)
                if trozo:
                    yield trozo
        trozo = self._extraer_trozo(buffer)
        if trozo:
            yield trozo

    @staticmethod
    def _extraer_trozo(linea: str) -> str:
        linea = linea.strip()
        if linea.startswith("data:"):
            linea = linea[5:].strip()
        if not linea or linea == "[DONE]":
            return ""
        try:
            datos = json.loads(linea)
        except json.JSONDecodeError:
            return ""
        choices = datos.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or choices[0].get("message") or {}
        return delta.get("content") or ""
