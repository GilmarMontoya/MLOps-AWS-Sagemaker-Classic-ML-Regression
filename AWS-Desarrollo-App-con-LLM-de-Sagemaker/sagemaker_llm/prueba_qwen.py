"""
Script de prueba para confirmar el formato de payload que acepta el endpoint
de Qwen3-4b desplegado en SageMaker (JumpStart HF TGI).

Mismo patrón que `consumo-simple-de-modelo.py` del módulo de regresión:
    load_dotenv -> boto3.Session -> client("sagemaker-runtime") -> invoke_endpoint

La diferencia es el formato: en vez de CSV, enviamos JSON con una lista de
mensajes estilo chat (Messages API de TGI).
"""
import os
import json

import boto3
from dotenv import load_dotenv

load_dotenv()

boto_session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION"),
)

runtime_client = boto_session.client("sagemaker-runtime")

endpoint = os.getenv("SAGEMAKER_ENDPOINT_NAME")

payload = {
    "messages": [
        {"role": "system", "content": "Eres un asistente útil y conciso. Responde en español."},
        {"role": "user", "content": "¿Cuál es la capital de Francia? Responde en una sola frase."},
    ],
    "max_tokens": 256,
    "temperature": 0.7,
}

response = runtime_client.invoke_endpoint(
    EndpointName=endpoint,
    ContentType="application/json",
    Body=json.dumps(payload).encode("utf-8"),
)

body = response["Body"].read().decode("utf-8")
result = json.loads(body)

print("=== Respuesta cruda ===")
print(json.dumps(result, indent=2, ensure_ascii=False))

print("\n=== Texto extraído ===")
# TGI Messages API devuelve formato tipo OpenAI: choices[0].message.content
if isinstance(result, dict) and "choices" in result:
    print(result["choices"][0]["message"]["content"])
# TGI "generate" clásico devuelve: [{"generated_text": "..."}]
elif isinstance(result, list) and result and "generated_text" in result[0]:
    print(result[0]["generated_text"])
else:
    print("(Formato no reconocido — revisa la respuesta cruda arriba)")
