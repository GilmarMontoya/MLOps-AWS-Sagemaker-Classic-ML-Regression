import os                   # Para leer variables de entorno
import numpy as np          # Para manejar vectores y matrices numéricas
import boto3                # SDK de AWS para llamar servicios (SageMaker, etc.)
import json                 # Para convertir la respuesta JSON a diccionario de Python
from dotenv import load_dotenv  # Para cargar variables desde el archivo .env

# Cargamos las variables definidas en el archivo .env al entorno
load_dotenv()


class SimpleCSVSerializer:
    """Convierte un array de NumPy en una línea CSV codificada en bytes."""

    content_type = "text/csv"  # Tipo de contenido que espera el endpoint

    def serialize(self, data):
        # Si recibimos un array de NumPy, lo convertimos a lista plana
        if isinstance(data, np.ndarray):
            data = data.flatten().tolist()
        # Si es lista o tupla, unimos los valores separados por comas
        if isinstance(data, (list, tuple)):
            payload = ",".join(map(str, data))
        else:
            # Cualquier otro tipo lo convertimos simplemente a texto
            payload = str(data)
        # El endpoint espera bytes, por eso codificamos en UTF‑8
        return payload.encode("utf-8")


# Creamos una sesión de boto3 con nuestras credenciales y región de AWS
boto_session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION"),
)

# Cliente especializado para invocar endpoints de SageMaker
runtime_client = boto_session.client("sagemaker-runtime")

# Nombre del endpoint desplegado en SageMaker
endpoint = os.getenv("SAGEMAKER_XGBOOST_ENDPOINT_NAME")

# Ejemplo de observación de entrada (mismas features que usaste al entrenar)
X_test = np.array(
    [3, 1.00, 1180, 5650, 1.0, 0, 0, 3, 7, 1180, 0, 1955, 0, 98178, 47.5112, -122.257]
)

# Serializamos la entrada al formato CSV que espera el modelo
serializer = SimpleCSVSerializer()
payload = serializer.serialize(X_test)

# Llamamos al endpoint de SageMaker pasando el CSV como cuerpo de la petición
response = runtime_client.invoke_endpoint(
    EndpointName=endpoint,
    ContentType="text/csv",
    Body=payload,
)

# Leemos el cuerpo de la respuesta como texto
body = response["Body"].read().decode("utf-8").strip()

# Para este endpoint XGBoost, la salida es un único número en texto, no un JSON
prediccion = float(body)

# Mostramos la predicción final por consola
print(prediccion)