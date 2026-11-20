---
name: aws-sagemaker-qwen3-4b-deploy
description: Despliega el LLM Qwen3-4B (SageMaker JumpStart, contenedor LMI/vLLM con formato OpenAI chat) en un endpoint de tiempo real de Amazon SageMaker sobre una sola GPU barata (ml.g5.xlarge por defecto, ml.g6.xlarge como alternativa), lo prueba, lo conecta a la app de AWS-Desarrollo-App-con-LLM-de-Sagemaker y lo BORRA al terminar. Verifica antes la cuenta, la región (us-east-2; us-east-1 puede estar bloqueada por SCP), la cuota de GPU para endpoints y el rol de ejecución. Evita la trampa del default de JumpStart (ml.g6e.12xlarge, ~US$13/h). Use when the user (o un alumno) asks to "desplegar Qwen", "desplegar el LLM en SageMaker", "levantar el endpoint del LLM", "Qwen3-4B", "qué LLM puedo desplegar con mi cuota", "conectar la app al endpoint de SageMaker", "borrar el endpoint de Qwen", "cuánto me está costando el endpoint", or types /aws-sagemaker-qwen3-4b-deploy.
---

# Desplegar Qwen3-4B en SageMaker (Módulo 3 · Sesión 1)

Esta skill la usan el profesor y los alumnos, cada uno en **su propia cuenta de AWS**. Todo pasa por un único
script ya probado. **No escribas otro código de despliegue.**

```
.claude/skills/aws-sagemaker-qwen3-4b-deploy/scripts/qwen3_endpoint.py
```

| Dato | Valor |
|---|---|
| Modelo | `huggingface-reasoning-qwen3-4b` v`1.46.1` (JumpStart, sin EULA ni licencia que aceptar) |
| Contenedor | LMI 18 (vLLM). Recibe `{"messages": [...], "max_tokens", "temperature"}` y devuelve `choices[0].message.content` |
| Instancia | `ml.g5.xlarge` (A10G 24 GB, **~US$1.41/h**) · alternativa `ml.g6.xlarge` (L4 24 GB, ~US$1.13/h) |
| Región | `us-east-2` |
| Endpoint | `qwen3-4b-g5` (se cambia con `--name`) |

> **Regla de oro:** el endpoint **cobra por hora mientras esté `InService`**, aunque nadie lo use, y no se apaga
> solo. Antes de desplegar, dile al usuario el costo por hora. Al terminar la sesión, siempre ejecuta el Paso 6.

## Cómo ejecutar el script

Ruta del script relativa a la raíz del proyecto: `S=.claude/skills/aws-sagemaker-qwen3-4b-deploy/scripts/qwen3_endpoint.py`.

Necesita un Python con `sagemaker>=2.257,<3` y `boto3`. Lo tiene el entorno del curso:
`conda activate MLOps-AWS-Regresion-Houses` (o `pip install -r requirements.txt` de la raíz). Si `import sagemaker`
falla o es v3, instala `pip install "sagemaker>=2.257,<3"`. **No uses la v3**, porque no trae `JumpStartModel` v2.

Las credenciales salen de `aws configure`, no del `.env`. Si no hay credenciales, usa la skill `/install-aws-cli`.

## Paso 1 — Verificar la cuenta (gratis)

```bash
python $S check                 # agrega --instance ml.g6.xlarge si vas a usar esa
```

Revisa cuenta (que no sea root), acceso a SageMaker en la región, cuota de la instancia para endpoints,
endpoints ya encendidos y rol de ejecución. Debe terminar en `LISTO para desplegar.` Si no:

| Lo que dice `check` | Qué hacer |
|---|---|
| Cuota = 0 | Si sugiere otra instancia con cuota, usa esa. Si no, pide el aumento con el comando que imprime (tarda horas o días). En las cuentas nuevas, la cuota de GPU para endpoints arranca en 0. |
| `bloquea SageMaker ... (SCP)` | Es una política de la organización. Usa `--region us-east-2`. No intentes saltarla. |
| No hay rol de ejecución | Paso 2. |
| Ya usas N instancias y la cuota es N | Otro endpoint ocupa la GPU. Pregúntale al usuario si lo borra. |
| Endpoints encendidos | Avísale al usuario que esos también le cobran. |

## Paso 2 — Rol de ejecución (solo si falta)

Pide confirmación al usuario, porque crea un recurso de IAM. Después ejecuta:

```bash
python $S crear-rol
```

Crea `SageMakerQwen3ExecutionRole` con confianza en `sagemaker.amazonaws.com` y la política
`AmazonSageMakerFullAccess`. Si ya existe un `AmazonSageMaker-ExecutionRole*` (por ejemplo, porque se creó un dominio
de SageMaker Studio), el script usa ese y no crea nada.

## Paso 3 — Desplegar (cobra desde aquí)

Antes de desplegar, confirma con el usuario la instancia y el costo por hora. Tarda **unos 8–15 minutos**: lánzalo
**en segundo plano** (`run_in_background`), porque supera el timeout normal de Bash.

```bash
python $S deploy --env-file AWS-Desarrollo-App-con-LLM-de-Sagemaker/.env
#   --instance ml.g6.xlarge     si se usa la L4
#   --name qwen3-4b-<iniciales>  si el alumno quiere otro nombre
```

- El script **siempre** pasa `instance_type`. Si se omite, JumpStart usa `ml.g6e.12xlarge` (~US$13/h, 4 GPUs).
  Solo acepta las instancias baratas de su tabla `PRECIOS`.
- `--env-file` escribe en el `.env` de la app `MODEL_PROVIDER=sagemaker`, `SAGEMAKER_ENDPOINT_NAME` y
  `AWS_REGION`, y no imprime el resto del archivo. Ese `.env` tiene secretos: **no lo abras con cat/Read**.
- Imprime el estado cada 30 s: `Creating` … `InService`. Si queda en `Failed`, muestra `FailureReason` (Solución de problemas).

## Paso 4 — Probar

```bash
python $S test
python $S test "Explícame qué es un endpoint de SageMaker en dos frases"
```

La primera llamada puede tardar unos segundos más. Qwen3 **razona antes de responder** (un bloque `<think>…</think>`):
el script lo quita al mostrar la respuesta y usa `max_tokens=1024` para que el razonamiento no se coma la respuesta.
Para respuestas rápidas sin razonamiento, agrega `/no_think` al final del mensaje del usuario (es un switch del chat template de Qwen3).

## Paso 5 — Conectar la app de chat

App: `AWS-Desarrollo-App-con-LLM-de-Sagemaker/` (Streamlit + LangChain). Su cliente `sagemaker_llm/client.py` ya
habla este formato y quita el `<think>` con `strip_thinking`.

1. Si no se usó `--env-file`, en el `.env` de la app deben quedar `MODEL_PROVIDER=sagemaker`,
   `SAGEMAKER_ENDPOINT_NAME=<endpoint>` y `AWS_REGION=us-east-2`. El alumno también pone ahí sus
   `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, o los deja vacíos y boto3 usa `aws configure`.
2. Instalar y correr: `cd AWS-Desarrollo-App-con-LLM-de-Sagemaker && pip install -r requirements.txt && streamlit run app.py`.
3. Prueba rápida sin la UI: `python sagemaker_llm/prueba_qwen.py` (lee el mismo `.env`).

La app tiene `us-east-1` como región por defecto. Si el `.env` no define `AWS_REGION`, sale el error
`Could not find endpoint`.

## Paso 6 — Borrar (obligatorio al terminar)

Muestra cuánto lleva gastado y pide confirmación nombrando cuenta, región y endpoint:

```bash
python $S status
python $S delete --yes
```

`delete` borra los **tres** recursos (endpoint, endpoint config y model) y lista lo que sigue encendido en la región.
Si el alumno no recuerda el nombre, `status` sin endpoint existente lista los que están vivos.
Ejecuta `python $S status --region us-east-1`, u otra región, si cree que desplegó en otro lado.

## Reporte final al usuario

Incluye nombre del endpoint, región, instancia, costo por hora, si el `.env` de la app quedó actualizado y el comando
exacto para borrar. Si decide dejarlo encendido, recuérdale cuánto cuesta por día (~US$34 en g5.xlarge) y sugiérele una
alerta de presupuesto en AWS Budgets.

## Solución de problemas

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `ResourceLimitExceeded` | Cuota 0, o la GPU está ocupada por otro endpoint | `check`; pedir aumento, usar `ml.g6.xlarge` o borrar el otro endpoint |
| `explicit deny in a service control policy` | La organización bloquea esa región | `--region us-east-2` |
| `Failed` con un error de rol o S3 | El rol no tiene permisos o es de otra cuenta | `crear-rol` y redesplegar (`delete --yes` primero) |
| `Failed` con CUDA out of memory | Instancia sin GPU suficiente | Solo `g5`/`g6`; no usar CPU |
| `El endpoint ... ya existe` | Hay un despliegue anterior | `status`; `test` si está `InService`, `delete --yes` si está `Failed` |
| La respuesta sale vacía o cortada | El `<think>` consumió los `max_tokens` | Subir `max_tokens` o usar `/no_think` |
| `Could not find endpoint` desde la app | `AWS_REGION` del `.env` distinta a la del endpoint | `AWS_REGION=us-east-2` |
| `ModuleNotFoundError: sagemaker.jumpstart` o error de v3 | SDK v3 instalado | `pip install "sagemaker>=2.257,<3"` |
| Factura inesperada | Endpoint olvidado `InService` | Paso 6 en todas las regiones |

## Otros modelos

Para otro modelo de JumpStart (por ejemplo `huggingface-reasoning-qwen3-1-7b` o `huggingface-reasoning-qwen3-8b`), solo
cambia `MODEL_ID`/`MODEL_VERSION` en el script **después de verificar** con el SDK que el id existe, que la instancia
está en `instance_types.retrieve(model_id=...)` y que el contenedor acepta `messages`. No inventes ids.
