"""
Script de inferencia para el endpoint de SageMaker.

Reproduce EXACTAMENTE el contrato de entrada/salida del algoritmo nativo
`linear-learner` de SageMaker, para que el endpoint sea intercambiable:

    ENTRADA  ->  text/csv   : "3,1.0,1180,5650,1.0,0,0,3,7,1180,0,1955,0,98178,47.5112,-122.257"
    SALIDA   ->  JSON       : {"predictions": [{"score": 221900.0}]}

Asi, los scripts de consumo (consumo-simple-de-modelo-linear-learned.py,
app_backend_de_consumo_linear.py, el frontend de Streamlit) siguen funcionando
sin cambiar una sola linea.

El modelo se guarda como un JSON de numeros (no como un pickle / .joblib) a
proposito: el contenedor de SageMaker trae numpy 1.x y sklearn 1.2, mientras que
la laptop entrena con numpy 2.x y sklearn 1.9. Un pickle creado con numpy 2 NO se
puede abrir con numpy 1 ("No module named numpy._core"). Con JSON el artefacto es
portable entre cualquier version, y ademas es legible: son 16 coeficientes.
"""

import io
import json
import os

import numpy as np

# Numero de features con el que se entreno (bedrooms .. long) = 16 columnas
FEATURE_DIM = 16


# ----------------------------------------------------------------------------
# 1) Cargar el modelo: SageMaker llama a esto UNA vez, al arrancar el endpoint
# ----------------------------------------------------------------------------
def model_fn(model_dir):
    """Carga el artefacto que SageMaker descomprimio de model.tar.gz en /opt/ml/model."""
    with open(os.path.join(model_dir, "model.json"), encoding="utf-8") as f:
        crudo = json.load(f)

    modelo = {
        "coef": np.asarray(crudo["coef"], dtype=np.float64),
        "intercept": float(crudo["intercept"]),
        "x_mean": np.asarray(crudo["x_mean"], dtype=np.float64),
        "x_std": np.asarray(crudo["x_std"], dtype=np.float64),
        "y_mean": float(crudo["y_mean"]),
        "y_std": float(crudo["y_std"]),
    }
    print(f"[model_fn] Modelo cargado: {modelo['coef'].shape[0]} coeficientes. "
          f"Entrenado con {crudo.get('hiperparametros')}")
    return modelo


# ----------------------------------------------------------------------------
# 2) Deserializar la peticion: convertir el body HTTP en una matriz NumPy
# ----------------------------------------------------------------------------
def input_fn(request_body, request_content_type):
    """Acepta text/csv (como linear-learner) y application/json (extra, por comodidad)."""
    if isinstance(request_body, (bytes, bytearray)):
        request_body = request_body.decode("utf-8")

    tipo = (request_content_type or "").split(";")[0].strip().lower()

    if tipo in ("text/csv", "text/plain", ""):
        filas = [f for f in request_body.strip().splitlines() if f.strip()]
        X = np.array([[float(v) for v in fila.split(",")] for fila in filas], dtype=np.float64)

    elif tipo == "application/json":
        datos = json.loads(request_body)
        # Aceptamos {"instances": [[...]]} o directamente [[...]] o [...]
        if isinstance(datos, dict):
            datos = datos.get("instances", datos.get("data", datos.get("inputs")))
        X = np.asarray(datos, dtype=np.float64)

    elif tipo == "application/x-npy":
        X = np.load(io.BytesIO(request_body if isinstance(request_body, bytes)
                               else request_body.encode()), allow_pickle=False)
        X = np.asarray(X, dtype=np.float64)

    else:
        raise ValueError(f"Content-Type no soportado: {request_content_type}")

    # Una sola casa llega como vector plano -> la convertimos en matriz de 1 fila
    if X.ndim == 1:
        X = X.reshape(1, -1)

    if X.shape[1] != FEATURE_DIM:
        raise ValueError(
            f"Se esperaban {FEATURE_DIM} features por fila, llegaron {X.shape[1]}. "
            "Orden correcto: bedrooms, bathrooms, sqft_living, sqft_lot, floors, "
            "waterfront, view, condition, grade, sqft_above, sqft_basement, "
            "yr_built, yr_renovated, zipcode, lat, long"
        )
    return X


# ----------------------------------------------------------------------------
# 3) Predecir: la misma matematica que hace linear-learner internamente
# ----------------------------------------------------------------------------
def predict_fn(X, modelo):
    """
    linear-learner normaliza features y label internamente (normalize_data=True,
    normalize_label=True) y el endpoint recibe los datos EN CRUDO. Hacemos lo mismo:

        1. normalizar    X_n = (X - x_mean) / x_std
        2. modelo lineal y_n = X_n . coef + intercept
        3. desnormalizar y   = y_n * y_std + y_mean
    """
    X_n = (X - modelo["x_mean"]) / modelo["x_std"]
    y_n = X_n @ modelo["coef"] + modelo["intercept"]
    return y_n * modelo["y_std"] + modelo["y_mean"]


# ----------------------------------------------------------------------------
# 4) Serializar la respuesta con el MISMO JSON que devuelve linear-learner
# ----------------------------------------------------------------------------
def output_fn(prediccion, accept):
    cuerpo = json.dumps(
        {"predictions": [{"score": float(p)} for p in np.ravel(prediccion)]}
    )
    return cuerpo, "application/json"
