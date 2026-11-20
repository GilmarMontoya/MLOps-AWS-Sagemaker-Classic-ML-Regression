# App de chat con el LLM de SageMaker

```bash
conda activate MLOps-AWS-Regresion-Houses
cd AWS-Consumo-del-LLM-en-Sagemaker
cp .env.example .env        # opcional: si no pones keys, usa ~/.aws
streamlit run app_frontend_de_consumo_llm.py
```

- Endpoint por defecto: `qwen3-4b-g5` (us-east-2). Se cambia en el `.env` o en la barra lateral.
- Opciones: temperatura, máx. tokens, razonamiento on/off (`/no_think`), mostrar el `<think>` y streaming.
- Si sale "Acceso denegado por una SCP de la organización", la app está bien: es la cuenta la que tiene
  bloqueado `sagemaker:InvokeEndpoint`.

## Docker local

```bash
docker build -t llm-chat-streamlit .
docker run --rm -p 8501:8501 -v ~/.aws:/root/.aws:ro -e AWS_REGION=us-east-2 \
  -e SAGEMAKER_ENDPOINT_NAME=qwen3-4b-g5 llm-chat-streamlit
```

## ECS Fargate

Con la skill `/aws-ecs-fargate-streamlit-deploy`:

```bash
APP_NAME=llm-chat APP_DIR=AWS-Consumo-del-LLM-en-Sagemaker ENDPOINT_NAME=qwen3-4b-g5 \
  bash .claude/skills/aws-ecs-fargate-streamlit-deploy/scripts/desplegar.sh
```
