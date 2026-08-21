# Entrenar en la laptop y publicar el endpoint en SageMaker

Copia del notebook `linear-learner-houses.ipynb` adaptada para **entrenar localmente** y
**publicar el modelo como endpoint de SageMaker**, porque esta cuenta de AWS tiene cuota **0**
para entrenar.

---

## 1. El diagnóstico

Las cuotas de SageMaker **no son una sola bolsa**: cada tipo de trabajo y cada tipo de instancia
tienen su propia cuota, **por región**. En **us-east-2** (la región del bucket) están así:

| Cuota | Valor | Significa |
|---|---|---|
| *cualquier* instancia **for training job usage** | **0** | ❌ ningún `estimator.fit()` puede correr |
| *cualquier* instancia **for spot training job usage** | **0** | ❌ tampoco con spot (`use_spot_instances=True`) |
| `ml.m5.xlarge` **for endpoint usage** | **0** | ❌ el `deploy(ml.m5.xlarge)` del notebook original también fallaba |
| `ml.m4.xlarge` **for endpoint usage** | **6** | ✅ aquí publicamos |
| `ml.t3.medium` **for processing job usage** | **4** | ✅ el "plan B" entrena aquí, dentro de AWS |

Verificación:

```bash
aws service-quotas list-service-quotas --service-code sagemaker --region us-east-2 \
  --query "Quotas[?contains(QuotaName,'training job usage')].[QuotaName,Value]" --output table
```

**Conclusión:** el entrenamiento tiene que salir de AWS (o entrar por otra puerta), pero el
endpoint sí se puede publicar.

---

## 2. Los dos notebooks

### `linear-learner-houses-LOCAL.ipynb` — el principal

Entrena en tu MacBook. **No necesita Docker ni cuota de nada.**

```
CSV → EDA (idéntico) → preprocesamiento (idéntico) → RecordIO → S3
    → entrenamiento en la laptop (16 modelos, Adam, ~2 segundos)
    → model.tar.gz → S3
    → endpoint en ml.m4.xlarge
```

### `linear-learner-houses-PROCESSING-JOB.ipynb` — el plan B

Entrena **dentro de AWS** aunque la cuota de entrenamiento sea 0, usando un **Processing Job**
en `ml.t3.medium`, que tiene su propia cuota. Útil para mostrar que "cuota 0 de training" no
significa "no puedo entrenar en la nube".

Un Processing Job **no** es un Training Job: no da métricas en la consola, ni spot, ni
Hyperparameter Tuning, y el `model.tar.gz` lo genera tu script. Pero entrena igual.

---

## 3. ¿Qué se conserva del notebook original?

| Etapa | Estado |
|---|---|
| Carga, `describe()`, missing values, heatmap de correlaciones | 🟢 idéntico |
| `X = iloc[:, 3:19]`, `y = iloc[:, 2]`, split 70/30 `random_state=0` | 🟢 idéntico |
| Conversión a RecordIO-Protobuf y subida a S3 | 🟢 idéntico |
| Hiperparámetros `feature_dim=16`, `predictor_type='regressor'`, `num_models=16` | 🟢 idénticos |
| Contrato del endpoint: `text/csv` → `{"predictions":[{"score":…}]}` | 🟢 idéntico |
| Scripts de `AWS-Consumo-del-Modelo-ML-Regresion/` | 🟢 **funcionan sin cambios** |
| El entrenamiento | 🟡 mismo algoritmo, reimplementado en NumPy |
| El contenedor del endpoint | 🟡 `sagemaker-scikit-learn` en vez de `linear-learner` |
| La instancia del endpoint | 🟡 `ml.m4.xlarge` en vez de `ml.m5.xlarge` |

### ¿Es "el mismo" algoritmo?

`linear-learner` es un modelo lineal entrenado con descenso de gradiente. La
[documentación de AWS](https://docs.aws.amazon.com/sagemaker/latest/dg/ll_hyperparameters.html)
publica sus valores por defecto, y son los que reimplementamos: `optimizer=adam`,
`loss=squared_loss`, `mini_batch_size=1000`, `normalize_data=true`, `normalize_label=true`.

`num_models=16` no es un ensamble: AWS entrena 16 modelos con distintas combinaciones de
*learning rate* y regularización y **se queda solo con el mejor**. Eso es lo que hace el notebook.

**Resultado medido** sobre el 30% de prueba:

| Modelo | R² | RMSE | MAE |
|---|---|---|---|
| Nuestro Linear Learner (Adam, 16 modelos) | **0.6876** | 207,104 | 125,226 |
| Óptimo teórico (OLS forma cerrada) | 0.6885 | 206,804 | 124,012 |

Brecha de R²: **0.0009**. El descenso de gradiente llega prácticamente al óptimo, que es el techo
de cualquier modelo lineal sobre estos datos — incluido el de AWS.

---

## 4. Archivos

```
linear-learner-houses.ipynb                  # el original, intacto
linear-learner-houses-LOCAL.ipynb            # entrena en la laptop  <- principal
linear-learner-houses-PROCESSING-JOB.ipynb   # entrena en AWS sin cuota de training
README-entrenamiento-local.md                # este archivo

code/
  inference.py             # serving: replica el contrato de linear-learner
  linear_learner_local.py  # el algoritmo (Adam + num_models), reutilizable
  train_processing.py      # lo que corre dentro del Processing Job

modelo-local/
  model.json               # el modelo: 16 coeficientes + estadísticas de normalización
  model.tar.gz             # lo que sube a S3 y lee el endpoint
```

---

## 5. Cómo correrlo

```bash
conda create -y -n MLOps-AWS-Regresion-Houses python=3.11
conda activate MLOps-AWS-Regresion-Houses
pip install "sagemaker<3" boto3 pandas numpy scikit-learn matplotlib seaborn python-dotenv ipykernel
python -m ipykernel install --user --name mlops-aws-regresion-houses \
    --display-name "Python (MLOps-AWS-Regresion-Houses)"
```

Luego abre `linear-learner-houses-LOCAL.ipynb` y ejecuta todo. La celda del `deploy` tarda entre
5 y 10 minutos; el resto es inmediato.

> ⚠️ **Instala `sagemaker<3`.** El SDK **3.x es una reescritura completa**: ya no existen
> `sagemaker.session`, `sagemaker.amazon.common` (RecordIO), `Estimator` ni `SKLearnModel`.
> Solo quedan los módulos `core`, `train`, `serve`, `mlops` y `ai_registry`.

---

## 6. Los seis obstáculos que aparecieron (buen material de clase)

### a) La imagen de `linear-learner` no se puede descargar

La idea inicial era usar **SageMaker Local Mode**: entrenar en la laptop **dentro del contenedor
real de AWS**. No se puede — AWS lo bloquea con una política de ECR:

```
denied: User: .../tu-usuario-iam is not authorized to perform: ecr:BatchGetImage
on resource: arn:aws:ecr:us-east-1:382416733822:repository/linear-learner
because no resource-based policy allows the ecr:BatchGetImage action
```

Las imágenes de los **algoritmos nativos** de SageMaker solo se pueden usar desde dentro del
servicio. Las de los **frameworks** (`sagemaker-scikit-learn`, `sagemaker-xgboost`) sí son
públicas — por eso el endpoint usa una de esas.

### b) La región: el error que miente

SageMaker exige que el `model.tar.gz` esté en la **misma región** que el endpoint. Si no, el
mensaje de error culpa al rol IAM:

```
ValidationException: Could not access model data at s3://.../model.tar.gz.
Please ensure that the role ... allows "sts:AssumeRole" ... and that the role has
"s3:GetObject" permissions and that the object is located in us-east-1.
```

El rol estaba perfecto (`aws iam simulate-principal-policy` decía `allowed`). Lo que pasaba es
que **el bucket está en us-east-2** y `boto3` usaba us-east-1 por el default del CLI. Por eso los
notebooks fijan `REGION = 'us-east-2'` con `boto3.setup_default_session()`.

Ojo con el detalle: `boto3.setup_default_session()` cambia `boto3.DEFAULT_SESSION` (la que usan
`boto3.client(...)`, `boto3.resource(...)` y la `Session()` de SageMaker), pero **`boto3.Session()`
construye una sesión nueva** que vuelve a leer `~/.aws/config`. Por eso imprimir
`boto3.Session().region_name` engaña.

### c) `get_execution_role()` no funciona fuera de SageMaker

Dentro de Studio el notebook **ya corre con un rol** y esa función simplemente lo lee. En tu
laptop te autenticas como **usuario IAM**, no como rol, así que hay que pasar el ARN a mano. Los
notebooks lo buscan solos en IAM.

### d) Un pickle de numpy 2 no se abre con numpy 1

El contenedor de AWS trae `numpy 1.x` / `scikit-learn 1.2`; la laptop entrena con `numpy 2.x` /
`scikit-learn 1.9`. Guardar el modelo con `joblib` (que es un pickle) falla al cargarlo dentro del
contenedor con `No module named numpy._core`.

Por eso el modelo se guarda como **JSON**: son 16 coeficientes y 4 estadísticas. Portable entre
cualquier versión, y se puede leer con un editor de texto.

### e) Mezclar el SDK v2 y el v3 rompe el paquete

Instalar `sagemaker<3` sobre un entorno que ya tenía el v3, y luego desinstalar los sub-paquetes
del v3, **borra `sagemaker/__init__.py`** y deja el paquete inservible
(`ImportError: cannot import name 'ModelMetrics' from 'sagemaker' (unknown location)`).
La solución es desinstalar todo y reinstalar limpio.

### f) Re-ejecutar el deploy falla si no borras el *endpoint config*

El SDK crea el **endpoint config** con el **mismo nombre** que el endpoint. Si en la segunda
corrida borras solo el endpoint, `CreateEndpointConfig` falla:

```
ValidationException: Cannot create endpoint config linear-learner-houses-local.
The name already exists.
```

Los notebooks borran **las dos cosas** antes de desplegar. Es el error más probable el día que
re-ejecutes el notebook en clase.

---

## 7. Precisión: la diferencia de US$2 entre la laptop y el endpoint

El notebook manda el conjunto de prueba completo al endpoint y compara con el modelo local. No da
exactamente 0, y la razón vale explicarla:

`X_test` es `float32`, pero viaja **como texto CSV**. `str(np.float32(47.5112))` devuelve
`'47.5112'` (la cadena más corta que reconstruye ese `float32`), y `float('47.5112')` al otro lado
produce un `float64` que **no es el mismo número**. Como el coeficiente de `lat` vale ~620,000
dólares por unidad, ese redondeo se amplifica a **unos US$2** sobre casas de medio millón: ~4·10⁻⁶
del precio promedio.

Es la precisión de `float32` viajando por texto, no un error del modelo.

---

## 8. Costos y apagado

El endpoint se cobra **por hora encendida**, no por predicción:

| | Costo |
|---|---|
| `ml.m4.xlarge` (endpoint) | ≈ US$0.28/h ≈ **US$6.7/día** |
| `ml.t3.medium` (Processing Job) | ≈ US$0.05/h, y solo corre ~5 min |
| S3 + tráfico | centavos |

Para apagarlo:

```bash
aws sagemaker delete-endpoint        --endpoint-name        linear-learner-houses-local --region us-east-2
aws sagemaker delete-endpoint-config --endpoint-config-name linear-learner-houses-local --region us-east-2
```

O la última celda del notebook. Para ver qué está encendido:

```bash
aws sagemaker list-endpoints --region us-east-2 --output table
```
