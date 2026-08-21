"""
Backend para consumir el endpoint de Linear Learner en SageMaker.
Encapsula la lógica de serialización y llamadas al endpoint.
"""
import numpy as np
import pandas as pd
import boto3
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Union, List, Tuple


class SimpleCSVSerializer:
    """Convierte un array de NumPy o lista en una línea CSV codificada en bytes."""

    content_type = "text/csv"  # Tipo de contenido que espera el endpoint

    def serialize(self, data):
        """
        Serializa datos a formato CSV en bytes.
        
        Args:
            data: Puede ser np.ndarray, lista, tupla o cualquier tipo convertible a string
            
        Returns:
            bytes: Datos serializados en formato CSV codificados en UTF-8
        """
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


def process_dataframe_for_linear_learner(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Procesa un DataFrame para que sea compatible con el modelo Linear Learner.

    El modelo espera exactamente 16 columnas numéricas (features), que corresponden
    a las columnas desde el índice 3 hasta el 18 del dataset original (King County
    house sales): se descartan las 3 primeras (id, date, price) y las 2 últimas
    (sqft_living15, sqft_lot15).

    Args:
        df: DataFrame de pandas con los datos

    Returns:
        Tuple[pd.DataFrame, List[str]]: DataFrame procesado y lista de nombres de columnas usadas

    Raises:
        ValueError: Si el DataFrame no tiene suficientes columnas o no se pueden procesar
    """
    EXPECTED_FEATURES = 16
    # Rango de columnas usadas en entrenamiento: [FEATURE_START, FEATURE_END)
    FEATURE_START = 3
    FEATURE_END = 19  # exclusivo -> 19 - 3 = 16 columnas

    n_cols = len(df.columns)

    # Caso 1: el CSV tiene exactamente 16 columnas -> asumimos que ya vienen solo features
    if n_cols == EXPECTED_FEATURES:
        processed_df = df.copy()
        used_columns = list(df.columns)
    # Caso 2: el CSV trae el layout completo del dataset original (>=19 columnas)
    # tomamos columnas [3:19] para saltar id/date/price y las dos últimas.
    elif n_cols >= FEATURE_END:
        processed_df = df.iloc[:, FEATURE_START:FEATURE_END].copy()
        used_columns = list(df.columns[FEATURE_START:FEATURE_END])
    else:
        raise ValueError(
            f"El CSV debe tener {EXPECTED_FEATURES} columnas (solo features) "
            f"o al menos {FEATURE_END} columnas (dataset original). "
            f"Se encontraron {n_cols} columnas."
        )
    
    # Convertimos todas las columnas a numérico, reemplazando valores no numéricos por NaN
    for col in processed_df.columns:
        processed_df[col] = pd.to_numeric(processed_df[col], errors='coerce')
    
    # Verificamos si hay valores nulos después de la conversión
    null_counts = processed_df.isnull().sum()
    if null_counts.sum() > 0:
        # Rellenamos valores nulos con 0 (podrías usar otra estrategia como la media)
        processed_df = processed_df.fillna(0)
    
    # Convertimos a float32 como se hizo en el entrenamiento
    processed_df = processed_df.astype('float32')
    
    return processed_df, used_columns


class SageMakerPredictor:
    """
    Clase para hacer predicciones usando un endpoint de SageMaker Linear Learner.
    """
    
    def __init__(
        self,
        endpoint_name: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str = "us-east-2"
    ):
        """
        Inicializa el predictor con las credenciales de AWS y el nombre del endpoint.
        
        Args:
            endpoint_name: Nombre del endpoint desplegado en SageMaker
            aws_access_key_id: Access Key ID de AWS
            aws_secret_access_key: Secret Access Key de AWS
            region_name: Región de AWS donde está el endpoint (default: us-east-2)
        """
        self.endpoint_name = endpoint_name
        self.serializer = SimpleCSVSerializer()
        
        # Creamos una sesión de boto3 con las credenciales proporcionadas
        self.boto_session = boto3.Session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )
        
        # Cliente especializado para invocar endpoints de SageMaker
        self.runtime_client = self.boto_session.client("sagemaker-runtime")
    
    def predict(self, data: Union[np.ndarray, List]) -> float:
        """
        Hace una predicción usando el endpoint de Linear Learner.
        
        Args:
            data: Array de NumPy o lista con los valores de las features
            
        Returns:
            float: Valor de la predicción (score)
            
        Raises:
            Exception: Si hay un error al invocar el endpoint o procesar la respuesta
        """
        # Serializamos la entrada al formato CSV que espera el modelo
        payload = self.serializer.serialize(data)
        
        # Llamamos al endpoint de SageMaker pasando el CSV como cuerpo de la petición
        response = self.runtime_client.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="text/csv",
            Body=payload,
        )
        
        # Leemos el cuerpo de la respuesta y lo convertimos de texto JSON a diccionario
        body = response["Body"].read().decode("utf-8")
        result = json.loads(body)
        
        # Extraemos el score de la primera predicción devuelta por el modelo
        # El formato de Linear Learner es: {"predictions": [{"score": valor}]}
        prediccion = result["predictions"][0]["score"]
        
        return prediccion
    
    def predict_batch(self, data_list: List[Union[np.ndarray, List]]) -> List[float]:
        """
        Hace múltiples predicciones de forma secuencial.

        Args:
            data_list: Lista de arrays/listas, cada uno representa una observación

        Returns:
            List[float]: Lista con las predicciones correspondientes
        """
        predictions = []
        for data in data_list:
            pred = self.predict(data)
            predictions.append(pred)
        return predictions

    def _predict_chunk(self, chunk: np.ndarray) -> List[float]:
        """
        Envía un mini-lote de filas al endpoint en una sola llamada HTTP.
        Linear Learner con text/csv acepta múltiples filas separadas por '\\n'.
        """
        # Una fila por línea, valores separados por coma. Usamos str() sobre
        # cada valor para preservar la precisión de float32 tal como en el
        # serializador original de SimpleCSVSerializer.
        lines = [",".join(str(v) for v in row.tolist()) for row in chunk]
        payload = "\n".join(lines).encode("utf-8")

        response = self.runtime_client.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="text/csv",
            Body=payload,
        )
        body = response["Body"].read().decode("utf-8")
        result = json.loads(body)
        # Linear Learner devuelve una lista de predicciones en el mismo orden
        return [p["score"] for p in result["predictions"]]

    def predict_from_dataframe(
        self,
        df: pd.DataFrame,
        chunk_size: int = 500,
        max_workers: int = 8,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Procesa un DataFrame y hace predicciones por lotes en paralelo.

        Args:
            df: DataFrame con los datos de entrada.
            chunk_size: Cantidad de filas por request al endpoint (default 500).
                Mantener payloads por debajo de ~5 MB para no exceder el límite
                de SageMaker (6 MB por invocación).
            max_workers: Número de hilos que invocan el endpoint en paralelo.
            progress_callback: Función opcional llamada como (filas_procesadas, total).

        Returns:
            Tuple[pd.DataFrame, List[str]]: DataFrame con predicciones y columnas usadas.
        """
        processed_df, used_columns = process_dataframe_for_linear_learner(df)
        X = processed_df.to_numpy()
        total = X.shape[0]

        # Dividimos en mini-lotes
        chunks = [X[i:i + chunk_size] for i in range(0, total, chunk_size)]
        predictions: List[Optional[List[float]]] = [None] * len(chunks)

        done_rows = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(self._predict_chunk, chunk): i
                for i, chunk in enumerate(chunks)
            }
            for future in future_to_idx:
                idx = future_to_idx[future]
                predictions[idx] = future.result()
                done_rows += len(chunks[idx])
                if progress_callback is not None:
                    progress_callback(min(done_rows, total), total)

        # Aplanamos las predicciones en el mismo orden del DataFrame
        flat_predictions: List[float] = []
        for chunk_preds in predictions:
            flat_predictions.extend(chunk_preds or [])

        result_df = df.copy()
        result_df["prediccion"] = flat_predictions

        return result_df, used_columns