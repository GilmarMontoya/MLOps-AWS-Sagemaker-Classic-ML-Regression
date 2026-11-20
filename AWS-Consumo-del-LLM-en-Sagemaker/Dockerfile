# Imagen de la app Streamlit que consume el LLM (Qwen3-4B) desplegado en SageMaker.
# En ECS las credenciales vienen del rol IAM de la tarea (sagemaker:InvokeEndpoint sobre el endpoint).
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app_frontend_de_consumo_llm.py app_backend_de_consumo_llm.py ./

EXPOSE 8501

CMD ["streamlit", "run", "app_frontend_de_consumo_llm.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
