#!/usr/bin/env bash
# Borra TODO lo que creó desplegar.sh, en el orden correcto. NO borra el endpoint de SageMaker.
# Uso (desde la raíz del repo):  bash .claude/skills/aws-ecs-fargate-streamlit-deploy/scripts/borrar.sh
set -uo pipefail   # sin -e: si algo ya no existe, seguimos con lo demás

REGION="${REGION:-us-east-2}"
APP_NAME="${APP_NAME:-precios-casas}"
ENDPOINT_NAME="${ENDPOINT_NAME:-linear-learner-houses-local-k2}"

SERVICE_NAME="${APP_NAME}-streamlit"
REPO_NAME="${APP_NAME}-streamlit"
CLUSTER="default"
EXEC_ROLE="${APP_NAME}-ecs-execution-role"
TASK_ROLE="${APP_NAME}-ecs-task-role"
ALB_NAME="${APP_NAME}-alb"
TG_NAME="${APP_NAME}-tg"
LOG_GROUP="/ecs/${APP_NAME}-streamlit"
STATE_FILE="${HOME}/.aws-ecs-${APP_NAME}.env"

paso() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✔ %s\033[0m\n' "$*"; }

echo "Se va a borrar la app '${APP_NAME}' en ${REGION}: servicio ECS, ALB, target group, security groups,"
echo "task definitions, repo ECR '${REPO_NAME}' (con sus imágenes), log group y roles ${APP_NAME}-ecs-*."
read -r -p "¿Continuar? (escribe 'si'): " RESP
[ "${RESP}" = "si" ] || { echo "Cancelado."; exit 0; }

# --- 1. Servicio ECS ----------------------------------------------------------------
paso "1. Servicio ECS"
if aws ecs describe-services --region "${REGION}" --cluster "${CLUSTER}" --services "${SERVICE_NAME}" \
     --query 'services[?status==`ACTIVE`].serviceName' --output text 2>/dev/null | grep -q .; then
  aws ecs update-service --region "${REGION}" --cluster "${CLUSTER}" --service "${SERVICE_NAME}" --desired-count 0 >/dev/null
  aws ecs delete-service --region "${REGION}" --cluster "${CLUSTER}" --service "${SERVICE_NAME}" --force >/dev/null
  aws ecs wait services-inactive --region "${REGION}" --cluster "${CLUSTER}" --services "${SERVICE_NAME}"
  ok "servicio borrado"
else ok "no había servicio"; fi

# --- 2. ALB, listener y target group --------------------------------------------------
paso "2. Load balancer y target group"
ALB_ARN="$(aws elbv2 describe-load-balancers --region "${REGION}" --names "${ALB_NAME}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || true)"
if [ -n "${ALB_ARN}" ] && [ "${ALB_ARN}" != "None" ]; then
  aws elbv2 delete-load-balancer --region "${REGION}" --load-balancer-arn "${ALB_ARN}"
  aws elbv2 wait load-balancers-deleted --region "${REGION}" --load-balancer-arns "${ALB_ARN}"
  ok "ALB borrado"
else ok "no había ALB"; fi
TG_ARN="$(aws elbv2 describe-target-groups --region "${REGION}" --names "${TG_NAME}" --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)"
if [ -n "${TG_ARN}" ] && [ "${TG_ARN}" != "None" ]; then
  aws elbv2 delete-target-group --region "${REGION}" --target-group-arn "${TG_ARN}" && ok "target group borrado"
else ok "no había target group"; fi

# --- 3. Security groups (primero el de la tarea, que referencia al del ALB) ----------
paso "3. Security groups (pueden tardar 1–2 min en liberarse)"
VPC="$(aws ec2 describe-vpcs --region "${REGION}" --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
for name in "${APP_NAME}-task-sg" "${APP_NAME}-alb-sg"; do
  SG="$(aws ec2 describe-security-groups --region "${REGION}" --filters Name=vpc-id,Values="${VPC}" Name=group-name,Values="${name}" \
    --query 'SecurityGroups[0].GroupId' --output text)"
  [ "${SG}" = "None" ] && { ok "no había ${name}"; continue; }
  for i in $(seq 1 12); do
    if aws ec2 delete-security-group --region "${REGION}" --group-id "${SG}" 2>/dev/null; then ok "${name} borrado"; break; fi
    [ "${i}" = 12 ] && echo "    ⚠ No se pudo borrar ${name} (${SG}); reintenta en unos minutos." || sleep 15
  done
done

# --- 4. Task definitions, ECR, logs ----------------------------------------------------
paso "4. Task definitions, ECR y logs"
for td in $(aws ecs list-task-definitions --region "${REGION}" --family-prefix "${SERVICE_NAME}" --query 'taskDefinitionArns[]' --output text); do
  aws ecs deregister-task-definition --region "${REGION}" --task-definition "${td}" >/dev/null
done
TDS="$(aws ecs list-task-definitions --region "${REGION}" --family-prefix "${SERVICE_NAME}" --status INACTIVE --query 'taskDefinitionArns[]' --output text)"
[ -n "${TDS}" ] && aws ecs delete-task-definitions --region "${REGION}" --task-definitions ${TDS} >/dev/null 2>&1
ok "task definitions desregistradas"
aws ecr delete-repository --region "${REGION}" --repository-name "${REPO_NAME}" --force >/dev/null 2>&1 && ok "repo ECR borrado" || ok "no había repo ECR"
aws logs delete-log-group --region "${REGION}" --log-group-name "${LOG_GROUP}" 2>/dev/null && ok "log group borrado" || ok "no había log group"

# --- 5. Roles IAM -----------------------------------------------------------------------
paso "5. Roles IAM"
if aws iam get-role --role-name "${EXEC_ROLE}" >/dev/null 2>&1; then
  aws iam detach-role-policy --role-name "${EXEC_ROLE}" --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy 2>/dev/null
  aws iam delete-role --role-name "${EXEC_ROLE}" && ok "${EXEC_ROLE} borrado"
fi
if aws iam get-role --role-name "${TASK_ROLE}" >/dev/null 2>&1; then
  aws iam delete-role-policy --role-name "${TASK_ROLE}" --policy-name invocar-endpoint-sagemaker 2>/dev/null
  aws iam delete-role --role-name "${TASK_ROLE}" && ok "${TASK_ROLE} borrado"
fi
rm -f "${STATE_FILE}"

# --- 6. Recordatorio del endpoint ---------------------------------------------------
paso "6. Endpoint de SageMaker (este script NO lo borra)"
EP="$(aws sagemaker describe-endpoint --endpoint-name "${ENDPOINT_NAME}" --region "${REGION}" --query EndpointStatus --output text 2>/dev/null || echo NO_EXISTE)"
if [ "${EP}" = "NO_EXISTE" ]; then ok "${ENDPOINT_NAME}: ya no existe"
else echo "    ⚠ ${ENDPOINT_NAME} sigue ${EP} (~US\$0.24/h). Bórralo con la última celda del notebook (delete_endpoint())."; fi

printf '\n\033[1;32mListo: la app ya no genera costos.\033[0m (El cluster "default" vacío y los service-linked roles no cobran.)\n'
