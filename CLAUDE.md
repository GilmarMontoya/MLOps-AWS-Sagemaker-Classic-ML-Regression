# Módulo 3 · Sesión 1 — Deploy del modelo de regresión en AWS SageMaker

Regresión de precios de casas (`house_prices.csv`) con un modelo lineal desplegado como
endpoint de SageMaker. El notebook principal es `linear-learner-houses-LOCAL.ipynb`.

## Qué hace `linear-learner-houses-LOCAL.ipynb`

Corre en la laptop, pero no todo se queda aquí:

| Paso | Dónde ocurre |
|---|---|
| Carga del CSV, EDA, preprocesamiento | Laptop |
| Entrenamiento (reimplementación de linear-learner con NumPy + Adam) | Laptop, gratis |
| Empaquetado en `modelo-local/model.tar.gz` (modelo en JSON, no joblib) | Laptop |
| Subida del dataset (RecordIO) y del `model.tar.gz` a S3 | AWS |
| `SKLearnModel(...).deploy(...)`: endpoint `linear-learner-houses-local-k2` | AWS, se cobra |
| Predicciones contra el endpoint | Se envían desde la laptop y el cálculo se hace en AWS |

Por qué se entrena en local: la cuenta tiene cuota **0** para *training jobs* en `us-east-2`,
así que `linear.fit()` en AWS falla siempre. Para endpoints sí hay cuota de `ml.m4.xlarge`.

Datos de AWS:
- Región: **`us-east-2`** (la del bucket). Si se usa otra región, el error que sale culpa al rol IAM.
- Bucket: `bucket-sagemaker-problema-regresion-modelo-linear-learner` (cuenta nueva, us-east-2).
  El bucket viejo `aws-sagemaker-datapath-ml-regresion-linear-learner-k` era de otra cuenta y da
  `AllAccessDisabled`. Todavía aparece en `linear-learner-houses.ipynb` y `linear-learner-houses-PROCESSING-JOB.ipynb`.
- Rol: se busca automáticamente el `AmazonSageMaker-ExecutionRole*` de la cuenta.
- Cuando termines: **borrar el endpoint** (última celda, `linear_regressor.delete_endpoint()`).
  Cuesta unos US$0.24/h mientras esté encendido.

## Entorno

```bash
conda create -y -n MLOps-AWS-Regresion-Houses python=3.11
conda activate MLOps-AWS-Regresion-Houses
pip install -r requirements.txt
```

- `requirements.txt` (raíz): dependencias de los notebooks. **`sagemaker<3` es obligatorio**: la v3 no tiene
  `sagemaker.session`, `sagemaker.amazon.common` ni `Estimator`.
- `AWS-Consumo-del-Modelo-ML-Regresion/requirements.txt`: dependencias de la app de consumo (incluye
  `streamlit`). Ya están instaladas en el mismo entorno conda. La app es
  `streamlit run app_frontend_de_consumo_linear.py` (ver `Comandos.md` de esa carpeta). Su `.env` tiene las
  credenciales nuevas (…PJ2Z).
- Se borraron los scripts `TEST-consumo-simple-*`. Están en el commit 5922380 como `consumo-simple-de-modelo-*.py`.
- Kernel de Jupyter registrado como **"Python (MLOps-AWS-Regresion-Houses)"**
  (`~/Library/Jupyter/kernels/mlops-aws-regresion-houses`). El kernel apunta a
  `/opt/anaconda3/envs/MLOps-AWS-Regresion-Houses/bin/python`.
- Requiere credenciales de AWS configuradas (`aws configure`).

## Bitácora

### 2026-11-19
- Creado el entorno conda `MLOps-AWS-Regresion-Houses` (Python 3.11, sagemaker 2.257.7, numpy 2.4,
  scikit-learn 1.9). No había otros entornos conda para borrar, solo `base`.
- La primera instalación falló porque el disco estaba lleno (175 MB libres). Para liberar espacio:
  - Se vaciaron las cachés de conda y pip.
  - Se borraron todos los `node_modules`, `.venv` y `.next`, y los `build`/`dist` que eran salidas de
    compilación, en `~/Documents`, `~/tesisMestrado`, `~/StudioProjects` y `~/ia368_ros2_ws`.
    Se pasó de 2.4 GB a 45 GB libres.
  - **No** se tocaron los `build`/`dist` versionados en git (`lionide-fork`, `SDK-para-Flutter`),
    porque son código fuente.
  - Quedó un `node_modules` de root sin borrar (requiere sudo):
    `Documents/DATAPATH/Google AI Studio/Proyecto-Spacial-Understanding/starter-applets/spatial/node_modules`.
  - Para retomar cualquier otro proyecto hay que reinstalar sus dependencias
    (`npm install`, `uv sync`, etc.).
- Creado `requirements.txt` en la raíz.
- **Pendiente:** el kernel no aparecía en el editor y se va a reiniciar el editor para que lo detecte.
  Después hay que correr `linear-learner-houses-LOCAL.ipynb` de punta a punta.

- El notebook falló en `sts.get_caller_identity()` con `InvalidClientTokenId`: la access key de
  `~/.aws/credentials` (…LFH6) ya no era válida. Se creó una nueva en IAM (usuario `Kevin-Inofuente`,
  …PJ2Z) y la región por defecto de `~/.aws/config` pasó a `us-east-2`. Las credenciales están verificadas.
  Falta desactivar o borrar la clave vieja en IAM.
- El bucket se cambió a `bucket-sagemaker-problema-regresion-modelo-linear-learner` y se borró el
  bucket vacío `bucket-sagemaker-problema-regresion-linear-learner`. El notebook LOCAL corrió completo hasta
  el deploy: el endpoint `linear-learner-houses-local-k2` quedó **InService** (~20:20). **Hay que borrarlo al terminar.**
- Ojo: si se edita un `.ipynb` en disco mientras está abierto en VS Code, no se puede guardar ("Overwrite" pisa el cambio).
  Se arregla con *File: Revert File*.

- App Streamlit desplegada en **ECS Fargate clásico** (us-east-2). Recursos creados:
  - ECR `precios-casas-streamlit:v1` (imagen linux/amd64).
  - Roles IAM: `precios-casas-ecs-execution-role` y `precios-casas-ecs-task-role` (este último solo tiene
    `sagemaker:InvokeEndpoint` sobre el endpoint k2).
  - Security groups `precios-casas-alb-sg` (80 abierto a internet) y `precios-casas-task-sg` (8501 solo desde el ALB).
  - ALB `precios-casas-alb`, target group `precios-casas-tg` (health check `/_stcore/health`), listener HTTP:80.
  - Log group `/ecs/precios-casas-streamlit` (7 días de retención). Cluster `default`. Servicio `precios-casas-streamlit` (1 tarea, 0.5 vCPU / 1 GB).
  - Service-linked roles de ECS, ELB y autoescalado (no cuestan nada; se dejan).
  - URL: http://precios-casas-alb-1822204858.us-east-2.elb.amazonaws.com
- Se intentó ECS Express Mode y falló con "Role is not valid". El error era de **zsh**: `$ACC:role` aplica el
  modificador `:r`. Hay que usar `${ACC}:role`.
- Slides de arquitectura y costos: `Slides_Sesion1_Arquitectura_y_Costos_AWS.html`. Costos en Ohio: endpoint
  US$0.24/h; con todo encendido, unos US$0.31/h (~US$224/mes).
- **Pendiente al terminar la clase:** borrar el servicio de ECS (antes desired-count 0), el ALB, el target group,
  los security groups, el log group, el repo de ECR, la task definition, los roles `precios-casas-*` y el endpoint.

## Pendientes / ideas
- Si el kernel sigue sin aparecer: en VS Code, *Select Kernel → Python Environments →
  MLOps-AWS-Regresion-Houses*, o *Jupyter Kernel → Python (MLOps-AWS-Regresion-Houses)*.
- Opcional: quitar kernels viejos de Jupyter (`yolo26`, `sintese-*`, `unicamp-*`, `modulo1-sesion1`).
- Opcional: limpiar unos 25 GB más de cachés (Chrome, uv, Gradle, pnpm, Docker build cache).

## LLM en SageMaker (`AWS-Desarrollo-App-con-LLM-de-Sagemaker`)
- Skill del proyecto `/aws-sagemaker-qwen3-4b-deploy` (`.claude/skills/aws-sagemaker-qwen3-4b-deploy/`), pensada también
  para los alumnos: despliega Qwen3-4B de JumpStart (`huggingface-reasoning-qwen3-4b` v1.46.1, contenedor LMI/vLLM)
  en `ml.g5.xlarge` (~US$1.41/h) o `ml.g6.xlarge` (~US$1.13/h), con `check` / `deploy` / `test` / `delete`.
- Cuenta <ACCOUNT_ID>: cuota **1** de cada GPU `g5`/`g6`/`g6e`/`g7` para endpoints en us-east-2 y us-east-1.
  En **us-east-1** una SCP de la organización bloquea SageMaker, así que hay que usar us-east-2.
- El default de JumpStart para ese modelo es `ml.g6e.12xlarge` (~US$13/h): siempre hay que pasar `instance_type`.
