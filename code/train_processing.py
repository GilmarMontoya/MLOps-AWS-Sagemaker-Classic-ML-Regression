"""
Script que corre DENTRO de un Processing Job de SageMaker (ml.t3.medium).

La gracia: la cuenta tiene cuota 0 para "training job usage" pero cuota 4 para
"ml.t3.medium for processing job usage". Un Processing Job es otro tipo de trabajo
de SageMaker, con su propia cuota, y nada impide que el codigo que corre adentro
sea un entrenamiento. Asi entrenamos EN AWS sin cuota de entrenamiento.

Rutas que monta SageMaker dentro del contenedor:

    /opt/ml/processing/input/data   <- el CSV que le pasamos desde S3
    /opt/ml/processing/input/lib    <- linear_learner_local.py (nuestro algoritmo)
    /opt/ml/processing/output       <- lo que dejemos aqui se sube solo a S3
"""

import argparse
import json
import os
import sys
import tarfile
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

# El algoritmo viaja como input montado, no como dependencia instalada
sys.path.insert(0, "/opt/ml/processing/input/lib")
import linear_learner_local as ll  # noqa: E402

ENTRADA = "/opt/ml/processing/input/data"
SALIDA = "/opt/ml/processing/output"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-models", type=int, default=16)
    parser.add_argument("--epocas", type=int, default=200)
    parser.add_argument("--test-size", type=float, default=0.3)
    parser.add_argument("--random-state", type=int, default=0)
    args = parser.parse_args()

    # ------------------------------------------------------------------ datos
    csv = [f for f in os.listdir(ENTRADA) if f.endswith(".csv")][0]
    print(f"Leyendo {csv}")
    base_casas = pd.read_csv(os.path.join(ENTRADA, csv))
    print(f"  {base_casas.shape[0]:,} filas x {base_casas.shape[1]} columnas")

    # Mismo preprocesamiento que el notebook: columnas 3..18 (bedrooms..long), y = precio
    X = np.array(base_casas.iloc[:, 3:19].values).astype("float32")
    y = np.array(base_casas.iloc[:, 2].values).astype("float32")

    X_entrenamiento, X_test, y_entrenamiento, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state
    )
    print(f"  entrenamiento={X_entrenamiento.shape}  test={X_test.shape}")

    # ------------------------------------------------------------- entrenamiento
    print(f"\nEntrenando {args.num_models} modelos (Adam, mini-batches)...")
    inicio = time.time()
    modelo = ll.entrenar(X_entrenamiento, y_entrenamiento,
                         num_models=args.num_models, epocas=args.epocas)
    print(f"Listo en {time.time() - inicio:.1f}s")

    metricas_test = ll.metricas(y_test, ll.predecir(modelo, X_test))
    print("\nMetricas en test:", {k: round(v, 4) for k, v in metricas_test.items()})

    # ------------------------------------------------------------------ salidas
    os.makedirs(SALIDA, exist_ok=True)

    artefacto = {
        "coef": modelo["coef"].tolist(),
        "intercept": modelo["intercept"],
        "x_mean": modelo["x_mean"].tolist(),
        "x_std": modelo["x_std"].tolist(),
        "y_mean": modelo["y_mean"],
        "y_std": modelo["y_std"],
        "hiperparametros": modelo["hiperparametros"],
        "features": list(base_casas.columns[3:19]),
        "metricas_test": metricas_test,
    }

    ruta_json = os.path.join(SALIDA, "model.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(artefacto, f, indent=2)

    # El endpoint solo sabe leer model.tar.gz, asi que lo armamos aqui mismo
    with tarfile.open(os.path.join(SALIDA, "model.tar.gz"), "w:gz") as tar:
        tar.add(ruta_json, arcname="model.json")

    with open(os.path.join(SALIDA, "metricas.json"), "w", encoding="utf-8") as f:
        json.dump({"test": metricas_test,
                   "competencia": modelo["resultados_competencia"]}, f, indent=2)

    # Guardamos el conjunto de prueba EXACTO que se aparto aqui, para poder
    # evaluar el endpoint despues con las mismas filas (trazabilidad de datos)
    columnas = list(base_casas.columns[3:19])
    df_test = pd.DataFrame(X_test, columns=columnas)
    df_test.insert(0, "price", y_test)
    df_test.to_csv(os.path.join(SALIDA, "test.csv"), index=False)

    print("\nArchivos dejados en", SALIDA, ":", sorted(os.listdir(SALIDA)))


if __name__ == "__main__":
    main()
