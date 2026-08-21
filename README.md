# MLOps en AWS SageMaker — Regresión con ML clásico

Predicción de precios de casas (King County) con **Amazon SageMaker**: entrenamiento, deploy de un
endpoint en tiempo real y consumo desde aplicaciones.

Material del curso **MLOps — Módulo 3, Sesión 1: Deploy del Modelo de ML (Regresión)**.

---

## El problema que resuelve este repo

El flujo clásico de SageMaker es `Estimator.fit()` → `.deploy()`. Pero una cuenta de AWS nueva (o
la de un alumno) suele tener **cuota 0 para instancias de entrenamiento**, y entonces `fit()`
falla siempre, sin importar la instancia que elijas.

Este repo muestra **tres caminos** al mismo endpoint, para que la falta de cuota no bloquee la clase:

| Notebook | Dónde entrena | Cuota que necesita |
|---|---|---|
| `linear-learner-houses.ipynb` | Training Job en AWS con el algoritmo nativo `linear-learner` | `... for training job usage` |
| **`linear-learner-houses-LOCAL.ipynb`** | **en tu laptop**, con el algoritmo reimplementado en NumPy | **ninguna** para entrenar |
| `linear-learner-houses-PROCESSING-JOB.ipynb` | Processing Job en AWS (`ml.t3.medium`) | `... for processing job usage` |

Los tres terminan igual: un `model.tar.gz` en S3 y un **endpoint en `ml.m4.xlarge`** que responde
el mismo contrato, así que las apps de consumo funcionan con cualquiera de los tres.

👉 **El detalle completo está en [`README-entrenamiento-local.md`](README-entrenamiento-local.md)**:
cómo se reimplementó el algoritmo, la comparación de métricas contra el óptimo teórico, y los seis
obstáculos reales que aparecieron (ECR bloqueado, región, `get_execution_role()`, pickles de numpy,
SDK v2 vs v3, endpoint config duplicado).

---

## Estructura

```
linear-learner-houses.ipynb                  Training Job en AWS (requiere cuota)
linear-learner-houses-LOCAL.ipynb            Entrena en la laptop  ← empieza por aquí
linear-learner-houses-PROCESSING-JOB.ipynb   Entrena en AWS sin cuota de training
README-entrenamiento-local.md                Documentación técnica detallada

code/
  inference.py             Script de serving del endpoint
  linear_learner_local.py  El algoritmo: Adam + mini-batches + num_models
  train_processing.py      Lo que corre dentro del Processing Job

modelo-local/
  model.json               El modelo entrenado: 16 coeficientes + normalización
  model.tar.gz             El artefacto que consume el endpoint

AWS-Consumo-del-Modelo-ML-Regresion/
  consumo-simple-de-modelo-linear-learned.py   Invocación mínima con boto3
  app_backend_de_consumo_linear.py             Backend con predicción por lotes
  app_frontend_de_consumo_linear.py            Interfaz en Streamlit
  prueba-una-casa.csv                          CSV de ejemplo para el frontend
  .env.example                                 Plantilla de configuración

house_prices.csv                             Dataset (King County, 21,613 casas)
s3-enviar-archivo.ipynb / s3-traer-archivo.ipynb   Utilidades de S3
```

---

## Puesta en marcha

### 1. Entorno

```bash
conda create -y -n MLOps-AWS-Regresion-Houses python=3.11
conda activate MLOps-AWS-Regresion-Houses
pip install "sagemaker<3" boto3 pandas numpy scikit-learn matplotlib seaborn \
            python-dotenv ipykernel streamlit
python -m ipykernel install --user --name mlops-aws-regresion-houses \
    --display-name "Python (MLOps-AWS-Regresion-Houses)"
```

> ⚠️ **`sagemaker<3` no es un capricho.** El SDK 3.x es una reescritura completa: ya no existen
> `sagemaker.session`, `sagemaker.amazon.common` (RecordIO), `Estimator` ni `SKLearnModel`.

### 2. Entrenar y desplegar

Abre `linear-learner-houses-LOCAL.ipynb` y ejecútalo. El entrenamiento tarda ~2 segundos; la celda
del `deploy` entre 5 y 10 minutos. Al final actualiza solo el `.env` con el nombre del endpoint.

### 3. Consumir el endpoint

```bash
cd AWS-Consumo-del-Modelo-ML-Regresion
cp .env.example .env        # y rellena tus credenciales
python consumo-simple-de-modelo-linear-learned.py
streamlit run app_frontend_de_consumo_linear.py
```

---

## Resultados

Modelo lineal sobre el 30% de prueba (6,484 casas):

| Modelo | R² | RMSE | MAE |
|---|---|---|---|
| Linear Learner reimplementado (Adam, 16 modelos) | 0.6876 | 207,104 | 125,226 |
| Óptimo teórico (OLS forma cerrada) | 0.6885 | 206,804 | 124,012 |

La brecha de R² es de **0.0009**: el descenso de gradiente llega prácticamente al óptimo
matemático, que es el techo de cualquier modelo lineal sobre estos datos — el de AWS incluido.

---

## Contrato del endpoint

Idéntico al del algoritmo nativo `linear-learner`, para que sea intercambiable:

```
POST  ContentType: text/csv
      3,1.00,1180,5650,1.0,0,0,3,7,1180,0,1955,0,98178,47.5112,-122.257

200   {"predictions": [{"score": 224453.12529499497}]}
```

Las 16 features, en orden: `bedrooms, bathrooms, sqft_living, sqft_lot, floors, waterfront, view,
condition, grade, sqft_above, sqft_basement, yr_built, yr_renovated, zipcode, lat, long`.

Acepta varias filas por petición (una por línea) y devuelve una predicción por fila.

---

## ⚠️ Costos

Un endpoint de SageMaker se cobra **por hora encendida**, no por predicción:

| Recurso | Costo aproximado |
|---|---|
| `ml.m4.xlarge` (endpoint) | US$0.28/h ≈ **US$6.7/día** |
| `ml.t3.medium` (Processing Job) | US$0.05/h, solo ~5 min por corrida |

**Apágalo al terminar:**

```bash
aws sagemaker delete-endpoint        --endpoint-name        linear-learner-houses-local --region us-east-2
aws sagemaker delete-endpoint-config --endpoint-config-name linear-learner-houses-local --region us-east-2
```

---

## Seguridad

- El `.env` con credenciales **está en el `.gitignore`** y nunca debe subirse. Usa `.env.example`.
- Para producción, prefiere **roles IAM** en lugar de access keys en un archivo.
- El usuario que solo invoca el endpoint necesita únicamente `sagemaker:InvokeEndpoint`.
