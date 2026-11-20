# Imagen de la app Streamlit que consume el endpoint de SageMaker.
# Se despliega en ECS Express Mode; las credenciales vienen del rol IAM de la tarea.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app_frontend_de_consumo_linear.py app_backend_de_consumo_linear.py prueba-una-casa.csv ./

EXPOSE 8501

CMD ["streamlit", "run", "app_frontend_de_consumo_linear.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
