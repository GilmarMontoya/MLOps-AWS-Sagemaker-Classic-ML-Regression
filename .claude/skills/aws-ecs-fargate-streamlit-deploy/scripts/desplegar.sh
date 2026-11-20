#!/usr/bin/env bash
# Despliega la app Streamlit de consumo en ECS Fargate (clásico) detrás de un ALB.
# Uso (desde la raíz del repo):  bash .claude/skills/aws-ecs-fargate-streamlit-deploy/scripts/desplegar.sh
# Se puede volver a correr: lo que ya existe lo reutiliza y actualiza el servicio con la imagen nueva.
set -euo pipefail

# --- Configuración (se puede cambiar con variables de entorno) -----------------
REGION="${REGION:-us-east-2}"
APP_NAME="${APP_NAME:-precios-casas}"
APP_DIR="${APP_DIR:-AWS-Consumo-del-Modelo-ML-Regresion}"
ENDPOINT_NAME="${ENDPOINT_NAME:-linear-learner-houses-local-k2}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
CONTAINER_PORT=8501
CPU=512
MEMORY=1024

REPO_NAME="${APP_NAME}-streamlit"
SERVICE_NAME="${APP_NAME}-streamlit"
CLUSTER="default"
EXEC_ROLE="${APP_NAME}-ecs-execution-role"
TASK_ROLE="${APP_NAME}-ecs-task-role"
SG_ALB_NAME="${APP_NAME}-alb-sg"
SG_TASK_NAME="${APP_NAME}-task-sg"
ALB_NAME="${APP_NAME}-alb"
TG_NAME="${APP_NAME}-tg"
LOG_GROUP="/ecs/${APP_NAME}-streamlit"
STATE_FILE="${HOME}/.aws-ecs-${APP_NAME}.env"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

paso() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✔ %s\033[0m\n' "$*"; }

# --- 0. Requisitos ---------------------------------------------------------------
paso "0. Verificando requisitos"
command -v aws >/dev/null || { echo "Falta AWS CLI v2"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker no está corriendo: abre Docker Desktop"; exit 1; }
ACC="$(aws sts get-caller-identity --query Account --output text)" || { echo "Credenciales inválidas: aws configure"; exit 1; }
[ -f "${APP_DIR}/Dockerfile" ] || { echo "No existe ${APP_DIR}/Dockerfile (copia templates/Dockerfile)"; exit 1; }
EP_STATUS="$(aws sagemaker describe-endpoint --endpoint-name "${ENDPOINT_NAME}" --region "${REGION}" --query EndpointStatus --output text 2>/dev/null || echo NO_EXISTE)"
ok "Región ${REGION} · endpoint ${ENDPOINT_NAME}: ${EP_STATUS}"
[ "${EP_STATUS}" = "InService" ] || echo "    ⚠ El endpoint no está InService: la app abrirá pero no podrá predecir."

# --- 1. Service-linked roles (solo la primera vez en la cuenta) -------------------
paso "1. Roles vinculados al servicio (ECS, ELB, autoescalado)"
for svc in ecs.amazonaws.com elasticloadbalancing.amazonaws.com ecs.application-autoscaling.amazonaws.com; do
  aws iam create-service-linked-role --aws-service-name "${svc}" >/dev/null 2>&1 && ok "creado para ${svc}" || ok "ya existe para ${svc}"
done

# --- 2. ECR + imagen linux/amd64 -------------------------------------------------
paso "2. Imagen Docker (linux/amd64) → ECR"
REGISTRY="${ACC}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${REPO_NAME}:${IMAGE_TAG}"
aws ecr describe-repositories --repository-names "${REPO_NAME}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${REPO_NAME}" --region "${REGION}" \
       --image-scanning-configuration scanOnPush=true >/dev/null
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${REGISTRY}" >/dev/null
docker buildx build --platform linux/amd64 -t "${IMAGE}" --push "${APP_DIR}"
ok "imagen ${REPO_NAME}:${IMAGE_TAG} subida"

# --- 3. Roles IAM -----------------------------------------------------------------
paso "3. Roles IAM (ejecución + tarea con solo InvokeEndpoint)"
cat > "${TMP}/trust.json" <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
for role in "${EXEC_ROLE}" "${TASK_ROLE}"; do
  aws iam get-role --role-name "${role}" >/dev/null 2>&1 \
    || { aws iam create-role --role-name "${role}" --assume-role-policy-document "file://${TMP}/trust.json" >/dev/null; ok "creado ${role}"; NEW_ROLES=1; }
done
aws iam attach-role-policy --role-name "${EXEC_ROLE}" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
cat > "${TMP}/invoke.json" <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sagemaker:InvokeEndpoint",
 "Resource":"arn:aws:sagemaker:${REGION}:${ACC}:endpoint/${ENDPOINT_NAME}"}]}
EOF
aws iam put-role-policy --role-name "${TASK_ROLE}" --policy-name invocar-endpoint-sagemaker \
  --policy-document "file://${TMP}/invoke.json"
ok "rol de tarea limitado a endpoint/${ENDPOINT_NAME}"
[ "${NEW_ROLES:-0}" = "1" ] && { echo "    (esperando 15 s a que IAM propague los roles nuevos)"; sleep 15; }

# --- 4. Red: VPC por defecto + security groups -----------------------------------
paso "4. Security groups"
VPC="$(aws ec2 describe-vpcs --region "${REGION}" --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
[ "${VPC}" != "None" ] || { echo "La región no tiene VPC por defecto"; exit 1; }
SUBNETS="$(aws ec2 describe-subnets --region "${REGION}" --filters Name=vpc-id,Values="${VPC}" Name=default-for-az,Values=true \
  --query 'Subnets[].SubnetId' --output text)"
SUBNETS_CSV="$(echo ${SUBNETS} | tr ' ' ',')"

sg_id() { aws ec2 describe-security-groups --region "${REGION}" --filters Name=vpc-id,Values="${VPC}" Name=group-name,Values="$1" \
  --query 'SecurityGroups[0].GroupId' --output text; }
SG_ALB="$(sg_id "${SG_ALB_NAME}")"
if [ "${SG_ALB}" = "None" ]; then
  SG_ALB="$(aws ec2 create-security-group --region "${REGION}" --group-name "${SG_ALB_NAME}" --vpc-id "${VPC}" \
    --description "ALB ${APP_NAME}: HTTP 80 desde internet" --query GroupId --output text)"
  aws ec2 authorize-security-group-ingress --region "${REGION}" --group-id "${SG_ALB}" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
fi
SG_TASK="$(sg_id "${SG_TASK_NAME}")"
if [ "${SG_TASK}" = "None" ]; then
  SG_TASK="$(aws ec2 create-security-group --region "${REGION}" --group-name "${SG_TASK_NAME}" --vpc-id "${VPC}" \
    --description "Tarea ${APP_NAME}: ${CONTAINER_PORT} solo desde el ALB" --query GroupId --output text)"
  aws ec2 authorize-security-group-ingress --region "${REGION}" --group-id "${SG_TASK}" --protocol tcp \
    --port "${CONTAINER_PORT}" --source-group "${SG_ALB}" >/dev/null
fi
ok "SG ALB ${SG_ALB} · SG tarea ${SG_TASK}"

# --- 5. Logs ---------------------------------------------------------------------
paso "5. CloudWatch Logs"
aws logs create-log-group --region "${REGION}" --log-group-name "${LOG_GROUP}" 2>/dev/null || true
aws logs put-retention-policy --region "${REGION}" --log-group-name "${LOG_GROUP}" --retention-in-days 7
ok "${LOG_GROUP} (7 días)"

# --- 6. ALB + target group + listener --------------------------------------------
paso "6. Application Load Balancer"
ALB_ARN="$(aws elbv2 describe-load-balancers --region "${REGION}" --names "${ALB_NAME}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || true)"
if [ -z "${ALB_ARN}" ] || [ "${ALB_ARN}" = "None" ]; then
  ALB_ARN="$(aws elbv2 create-load-balancer --region "${REGION}" --name "${ALB_NAME}" --type application --scheme internet-facing \
    --subnets ${SUBNETS} --security-groups "${SG_ALB}" --tags Key=proyecto,Value="${APP_NAME}" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)"
fi
aws elbv2 modify-load-balancer-attributes --region "${REGION}" --load-balancer-arn "${ALB_ARN}" \
  --attributes Key=idle_timeout.timeout_seconds,Value=300 >/dev/null

TG_ARN="$(aws elbv2 describe-target-groups --region "${REGION}" --names "${TG_NAME}" --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)"
if [ -z "${TG_ARN}" ] || [ "${TG_ARN}" = "None" ]; then
  TG_ARN="$(aws elbv2 create-target-group --region "${REGION}" --name "${TG_NAME}" --protocol HTTP --port "${CONTAINER_PORT}" \
    --vpc-id "${VPC}" --target-type ip --health-check-path /_stcore/health --health-check-interval-seconds 15 \
    --healthy-threshold-count 2 --query 'TargetGroups[0].TargetGroupArn' --output text)"
fi
aws elbv2 modify-target-group-attributes --region "${REGION}" --target-group-arn "${TG_ARN}" --attributes \
  Key=deregistration_delay.timeout_seconds,Value=15 Key=stickiness.enabled,Value=true Key=stickiness.type,Value=lb_cookie >/dev/null

LISTENERS="$(aws elbv2 describe-listeners --region "${REGION}" --load-balancer-arn "${ALB_ARN}" --query 'length(Listeners)' --output text)"
[ "${LISTENERS}" != "0" ] || aws elbv2 create-listener --region "${REGION}" --load-balancer-arn "${ALB_ARN}" --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn="${TG_ARN}" >/dev/null
DNS="$(aws elbv2 describe-load-balancers --region "${REGION}" --load-balancer-arns "${ALB_ARN}" --query 'LoadBalancers[0].DNSName' --output text)"
ok "ALB ${ALB_NAME} → ${DNS}"

# --- 7. Task definition + servicio -----------------------------------------------
paso "7. Task definition y servicio ECS"
aws ecs describe-clusters --region "${REGION}" --clusters "${CLUSTER}" --query 'clusters[?status==`ACTIVE`].clusterName' --output text | grep -q . \
  || aws ecs create-cluster --region "${REGION}" --cluster-name "${CLUSTER}" >/dev/null

cat > "${TMP}/taskdef.json" <<EOF
{
  "family": "${SERVICE_NAME}",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "${CPU}",
  "memory": "${MEMORY}",
  "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
  "executionRoleArn": "arn:aws:iam::${ACC}:role/${EXEC_ROLE}",
  "taskRoleArn": "arn:aws:iam::${ACC}:role/${TASK_ROLE}",
  "containerDefinitions": [{
    "name": "streamlit",
    "image": "${IMAGE}",
    "essential": true,
    "portMappings": [{"containerPort": ${CONTAINER_PORT}, "protocol": "tcp"}],
    "environment": [
      {"name": "AWS_REGION", "value": "${REGION}"},
      {"name": "SAGEMAKER_ENDPOINT_NAME", "value": "${ENDPOINT_NAME}"}
    ],
    "logConfiguration": {"logDriver": "awslogs", "options": {
      "awslogs-group": "${LOG_GROUP}", "awslogs-region": "${REGION}", "awslogs-stream-prefix": "ecs"}}
  }]
}
EOF
TD_ARN="$(aws ecs register-task-definition --region "${REGION}" --cli-input-json "file://${TMP}/taskdef.json" \
  --query 'taskDefinition.taskDefinitionArn' --output text)"
ok "task definition ${TD_ARN##*/}"

SVC_STATUS="$(aws ecs describe-services --region "${REGION}" --cluster "${CLUSTER}" --services "${SERVICE_NAME}" \
  --query 'services[0].status' --output text 2>/dev/null || echo None)"
if [ "${SVC_STATUS}" = "ACTIVE" ]; then
  aws ecs update-service --region "${REGION}" --cluster "${CLUSTER}" --service "${SERVICE_NAME}" \
    --task-definition "${TD_ARN}" --desired-count 1 --force-new-deployment >/dev/null
  ok "servicio actualizado (rolling deploy)"
else
  aws ecs create-service --region "${REGION}" --cluster "${CLUSTER}" --service-name "${SERVICE_NAME}" \
    --task-definition "${TD_ARN}" --desired-count 1 --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS_CSV}],securityGroups=[${SG_TASK}],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=${TG_ARN},containerName=streamlit,containerPort=${CONTAINER_PORT}" \
    --health-check-grace-period-seconds 60 >/dev/null
  ok "servicio creado"
fi

cat > "${STATE_FILE}" <<EOF
REGION=${REGION}
APP_NAME=${APP_NAME}
ALB_ARN=${ALB_ARN}
TG_ARN=${TG_ARN}
SG_ALB=${SG_ALB}
SG_TASK=${SG_TASK}
DNS=${DNS}
EOF

# --- 8. Esperar y verificar ------------------------------------------------------
paso "8. Esperando a que el servicio quede estable (2–5 min)"
aws ecs wait services-stable --region "${REGION}" --cluster "${CLUSTER}" --services "${SERVICE_NAME}"
for _ in $(seq 1 20); do
  STATE="$(aws elbv2 describe-target-health --region "${REGION}" --target-group-arn "${TG_ARN}" \
    --query 'TargetHealthDescriptions[0].TargetHealth.State' --output text)"
  [ "${STATE}" = "healthy" ] && break; sleep 10
done
ok "target: ${STATE}"
IP="$(dig +short @8.8.8.8 "${DNS}" | head -1 || true)"
if [ -n "${IP}" ]; then
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "${DNS}:80:${IP}" "http://${DNS}/_stcore/health" || true)"
  ok "health check vía DNS público: HTTP ${CODE}"
fi

printf '\n\033[1;32mApp publicada:\033[0m http://%s\n' "${DNS}"
echo "Si tu Mac dice 'no se puede resolver', limpia la caché de DNS:"
echo "  sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder"
echo "IDs guardados en ${STATE_FILE}. Para borrar todo:"
echo "  bash .claude/skills/aws-ecs-fargate-streamlit-deploy/scripts/borrar.sh"
