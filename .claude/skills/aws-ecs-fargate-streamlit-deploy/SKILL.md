---
name: aws-ecs-fargate-streamlit-deploy
description: Despliega la app Streamlit de consumo (AWS-Consumo-del-Modelo-ML-Regresion) en Amazon ECS Fargate "clásico" por CLI — imagen Docker linux/amd64 en ECR, Application Load Balancer + target group + security groups, task definition y servicio con 1 tarea, rol IAM de tarea con SOLO sagemaker:InvokeEndpoint (sin access keys en el contenedor) — para que consuma el endpoint de SageMaker desde una URL pública. Incluye verificación, costos, solución de errores reales (zsh `$VAR:role`, DNS en caché de macOS, imagen arm64, Role is not valid) y el BORRADO completo en orden. Use when a student asks to "desplegar la app", "subir el Streamlit a AWS", "publicar la app de consumo", "ECS Fargate", "darle una URL pública a la app", "borrar la app de ECS", "cuánto cuesta la app en ECS", or types /aws-ecs-fargate-streamlit-deploy.
---

# Desplegar la app Streamlit en ECS Fargate (clásico)

Probado el 2026-11-19 en `us-east-2` con la app de `AWS-Consumo-del-Modelo-ML-Regresion/`, que consume el
endpoint `linear-learner-houses-local-k2` (predijo ~US$224k para una casa real de US$221.9k).

```
Usuario ─HTTP:80─► ALB ─8501─► Fargate (Streamlit, 0.5 vCPU / 1 GB)
                                  │ rol IAM de la tarea (solo InvokeEndpoint)
                                  ▼
                       SageMaker endpoint (ya desplegado por el notebook)
```

> **Regla de oro:** todo esto cobra por hora mientras exista (~US$0.07/h la app + US$0.24/h el endpoint
> `ml.m4.xlarge`). Al terminar la clase: **Paso 6 (borrar)**.

## Cómo trabajar con esta skill

- Usa los scripts de `scripts/`: están probados y ya evitan los errores de abajo. Córrelos con `bash`
  (no con `zsh`), desde la raíz del repo.
- Antes de cada paso que crea recursos, dile al alumno qué se va a crear y cuánto cuesta.
- No leas ni imprimas el `.env` (tiene credenciales). Para saber si las credenciales sirven usa
  `aws sts get-caller-identity`.
- No escribas el ID de la cuenta en archivos que se suban a git.

## Paso 0 — Requisitos (verifícalos, no los asumas)

```bash
aws --version                                   # AWS CLI v2
aws sts get-caller-identity --query Arn         # credenciales válidas (si falla: aws configure)
aws configure get region                        # debe ser la región del endpoint (us-east-2)
docker info --format '{{.ServerVersion}}'       # Docker Desktop ABIERTO
aws sagemaker describe-endpoint --endpoint-name <ENDPOINT> --region us-east-2 --query EndpointStatus
```

- El endpoint tiene que estar en `InService`. Si no existe, primero hay que correr el notebook
  `linear-learner-houses-LOCAL.ipynb` hasta la celda del deploy.
- El usuario IAM necesita permisos de ECS, ECR, EC2 (security groups), ELB, IAM y CloudWatch Logs
  (`AdministratorAccess` basta en una cuenta de práctica).

## Paso 1 — La app no debe pedir access keys

En la nube la app usa el **rol IAM de la tarea**. Comprueba que el backend cree la sesión de boto3 sin
keys cuando no se las pasan, y que el frontend no tenga campos de credenciales:

```python
# app_backend_de_consumo_linear.py
if aws_access_key_id and aws_secret_access_key:
    self.boto_session = boto3.Session(aws_access_key_id=..., aws_secret_access_key=..., region_name=region_name)
else:
    self.boto_session = boto3.Session(region_name=region_name)   # laptop: .env / ~/.aws · ECS: rol de la tarea
```

La app lee `AWS_REGION` y `SAGEMAKER_ENDPOINT_NAME` de variables de entorno (el script las inyecta).

## Paso 2 — Dockerfile y .dockerignore

Si la carpeta de la app no los tiene, copia las plantillas de `templates/` (`Dockerfile`,
`dockerignore` → `.dockerignore`). Puntos clave:
- `.dockerignore` excluye `.env`: **las credenciales nunca van dentro de la imagen**.
- Streamlit escucha en `0.0.0.0:8501` con `--server.headless=true`.
- `requirements.txt` de la app NO necesita el SDK `sagemaker` (solo boto3), así la imagen pesa menos.

## Paso 3 — Desplegar

```bash
bash .claude/skills/aws-ecs-fargate-streamlit-deploy/scripts/desplegar.sh
```

Variables opcionales (con sus valores por defecto):

| Variable | Default |
|---|---|
| `REGION` | `us-east-2` |
| `APP_NAME` | `precios-casas` (prefijo de todos los recursos) |
| `APP_DIR` | `AWS-Consumo-del-Modelo-ML-Regresion` |
| `ENDPOINT_NAME` | `linear-learner-houses-local-k2` |
| `IMAGE_TAG` | `v1` |

Ejemplo para un alumno con otro endpoint: `APP_NAME=casas-ana ENDPOINT_NAME=mi-endpoint bash .../desplegar.sh`.
Si dos alumnos comparten cuenta, cada uno tiene que usar **un `APP_NAME` distinto**.

Qué crea, en orden (y se puede volver a correr: lo que ya existe lo reutiliza):
1. Roles vinculados al servicio de ECS, ELB y autoescalado (solo la primera vez en la cuenta; gratis).
2. Repo de ECR, `docker buildx --platform linux/amd64` y push. Tu Mac es ARM; sin `linux/amd64` la tarea
   falla con `exec format error`. Tarda 2–5 min.
3. Rol de ejecución (`AmazonECSTaskExecutionRolePolicy`) y rol de tarea (inline: solo
   `sagemaker:InvokeEndpoint` sobre ESE endpoint).
4. Security groups: el del ALB abre el 80 a internet; el de la tarea abre el 8501 solo desde el SG del ALB.
5. Log group `/ecs/<APP_NAME>-streamlit` (7 días de retención).
6. ALB internet-facing en las subnets públicas de la VPC por defecto, target group `ip:8501` con
   health check `/_stcore/health`, cookies de sesión (stickiness) e idle timeout de 300 s (para el WebSocket
   de Streamlit), y listener HTTP:80.
7. Cluster `default`, task definition Fargate (0.5 vCPU / 1 GB, X86_64) y servicio con 1 tarea y
   `assignPublicIp=ENABLED`. La IP pública es para bajar la imagen de ECR sin NAT Gateway, que costaría
   unos US$33 al mes.
8. Espera a que el servicio quede estable y el target `healthy`, y prueba `/_stcore/health`.

Al final imprime la **URL** (`http://<alb>.us-east-2.elb.amazonaws.com`) y guarda los IDs en
`~/.aws-ecs-<APP_NAME>.env` (fuera del repo) para el borrado.

## Paso 4 — Probar

1. Abre la URL. Sube `prueba-una-casa.csv` → **Generar Predicciones**. Debe dar ~224,454.
2. Logs de la tarea: `aws logs tail /ecs/<APP_NAME>-streamlit --follow --region us-east-2`.
3. Si la app abre pero predecir falla con `AccessDenied`, el rol de la tarea apunta a otro endpoint:
   revisa `ENDPOINT_NAME`.

## Paso 5 — Actualizar la app (nueva versión)

```bash
IMAGE_TAG=v2 bash .claude/skills/aws-ecs-fargate-streamlit-deploy/scripts/desplegar.sh
```
Construye y sube `:v2`, registra una nueva revisión de la task definition y hace `update-service`
(rolling deploy: la tarea nueva entra antes de que salga la vieja).

## Paso 6 — BORRAR todo (al terminar la clase)

```bash
bash .claude/skills/aws-ecs-fargate-streamlit-deploy/scripts/borrar.sh
```

El orden importa. El script hace:
1. Baja el servicio a 0 tareas y lo borra.
2. Borra el ALB, espera a que desaparezca y luego borra el target group.
3. Borra el SG de la tarea y después el del ALB. Si falla con `DependencyViolation`, espera 1–2 minutos
   a que se liberen las interfaces de red; el script reintenta solo.
4. Desregistra las task definitions, borra el repo de ECR, el log group y los roles `<APP_NAME>-ecs-*`.
5. No borra el endpoint de SageMaker. Ese se borra desde la última celda del notebook
   (`delete_endpoint()`). El script te recuerda si sigue encendido.

Verificación final: `aws elbv2 describe-load-balancers --region us-east-2` y
`aws ecs list-services --cluster default --region us-east-2` no deben listar nada del `APP_NAME`.

## Costos (us-east-2, on-demand, consultados 2026-11-19)

| Recurso | Precio | US$/h |
|---|---|---|
| Fargate 0.5 vCPU / 1 GB | $0.04048/vCPU-h + $0.004445/GB-h | 0.0247 |
| ALB | $0.0225/h + LCU ($0.008/LCU-h) | 0.0225 |
| IPv4 públicas (~3 del ALB + 1 de la tarea) | $0.005/IP-h | ~0.020 |
| ECR (~0.2 GB), CloudWatch Logs | centavos al mes | ~0 |
| **App total** | | **~0.07** (~US$49/mes) |
| Endpoint SageMaker `ml.m4.xlarge` | $0.24/h | 0.24 |

## Errores reales y solución

| Síntoma | Causa | Solución |
|---|---|---|
| `Role is not valid` al registrar la task definition o crear el servicio | En **zsh**, `arn:aws:iam::$ACC:role/...` aplica el modificador `:r` y el ARN queda `...<cuenta>ole/...` | Usa `${ACC}:role` o corre los scripts con `bash`. Antes de culpar a AWS, mira el ARN o el JSON que de verdad mandas |
| `MalformedPolicyDocument ... legacy parsing` | Lo mismo con `$ACC:endpoint` (`:e`) | `${ACC}`, o escribe el JSON en un archivo y pásalo con `file://` |
| La tarea arranca y muere con `exec format error` | Imagen arm64 (Mac M1/M2/M3) | `docker buildx build --platform linux/amd64` |
| `curl: Could not resolve host` aunque el target está `healthy` | macOS guardó en caché el "no existe" porque consultaste el DNS del ALB antes de que se propagara | `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`, o espera unos minutos, o prueba desde el celular |
| Target `unhealthy` | Mal el health check o el puerto | Health check `/_stcore/health`, puerto 8501, SG de la tarea con el 8501 abierto desde el SG del ALB |
| `CannotPullContainerError` | La tarea no tiene salida a internet | `assignPublicIp=ENABLED` y subnets públicas |
| `InvalidClientTokenId` | Access key vieja o borrada | Crea una nueva en IAM, corre `aws configure` y actualiza también el `.env` si lo usas en local |
| `AllAccessDisabled` en S3 | El bucket es de otra cuenta | Usa un bucket de tu cuenta |
| La app abre pero no predice; en los logs aparece `AccessDenied` en `InvokeEndpoint` | El rol de la tarea tiene otro endpoint o otra región | Vuelve a correr `desplegar.sh` con el `ENDPOINT_NAME` correcto (actualiza la política) |
| La app se desconecta o se recarga sola | Streamlit usa WebSocket | Idle timeout del ALB de 300 s y stickiness activada (el script ya lo configura) |

## Para producción (mencionar, no hacer en clase)

- HTTPS: dominio propio + certificado de ACM + listener 443 (y redirigir el 80 al 443).
- Login: Cognito en el ALB.
- Tareas en subnets privadas con NAT Gateway o VPC endpoints (ECR, Logs, SageMaker runtime).
- Alternativa más simple: **ECS Express Mode** (`aws ecs create-express-gateway-service`), que crea el ALB,
  los SG y el autoescalado por ti. Necesita además un *infrastructure role* con
  `AmazonECSInfrastructureRoleforExpressGatewayServices`.
- App Runner está cerrado a clientes nuevos desde el 30-abr-2026.
