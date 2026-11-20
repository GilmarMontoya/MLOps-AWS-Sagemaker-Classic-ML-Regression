#!/usr/bin/env bash
# Instala y registra el AWS MCP Server en Claude Code (macOS / Linux).
# Uso: bash install.sh [--region us-east-1] [--endpoint-region us-east-1] [--profile default] [--read-only]
set -euo pipefail

REGION=""
ENDPOINT_REGION="us-east-1"
PROFILE=""
READ_ONLY=0
SERVER_NAME="aws"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)          REGION="$2"; shift 2 ;;
    --endpoint-region) ENDPOINT_REGION="$2"; shift 2 ;;
    --profile)         PROFILE="$2"; shift 2 ;;
    --read-only)       READ_ONLY=1; shift ;;
    --name)            SERVER_NAME="$2"; shift 2 ;;
    -h|--help)         sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 1 ;;
  esac
done

if [[ "$ENDPOINT_REGION" != "us-east-1" && "$ENDPOINT_REGION" != "eu-central-1" ]]; then
  echo "ERROR: --endpoint-region debe ser us-east-1 o eu-central-1 (recibido: $ENDPOINT_REGION)" >&2
  exit 1
fi

ok()   { printf '  \033[32m✔\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✘\033[0m %s\n' "$1" >&2; }

echo "==> Paso 0: prerequisitos"

if ! command -v uv >/dev/null 2>&1; then
  fail "uv no está instalado."
  echo "     Instálalo con:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "     Luego reabre la terminal y vuelve a ejecutar este script."
  exit 1
fi
ok "uv $(uv --version | awk '{print $2}')"

command -v claude >/dev/null 2>&1 || { fail "Claude Code (claude) no está en el PATH."; exit 1; }
ok "claude $(claude --version 2>/dev/null | head -1)"

AWS_ARGS=()
[[ -n "$PROFILE" ]] && AWS_ARGS+=(--profile "$PROFILE")

if ! command -v aws >/dev/null 2>&1; then
  fail "AWS CLI no está instalada — https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  exit 1
fi

if ! IDENTITY="$(aws "${AWS_ARGS[@]+"${AWS_ARGS[@]}"}" sts get-caller-identity --query Arn --output text 2>&1)"; then
  fail "No hay credenciales AWS válidas:"
  echo "     $IDENTITY"
  echo "     Ejecuta 'aws configure' (o 'aws sso login') y reintenta."
  exit 1
fi
ok "Credenciales AWS: $IDENTITY"

# Región de operación: --region > región del perfil > us-east-1
if [[ -z "$REGION" ]]; then
  REGION="$(aws "${AWS_ARGS[@]+"${AWS_ARGS[@]}"}" configure get region 2>/dev/null || true)"
  [[ -z "$REGION" ]] && REGION="us-east-1"
fi
ok "Región de operación: $REGION"
ok "Endpoint MCP: $ENDPOINT_REGION"

echo "==> Paso 1: precalentando la caché de uvx (evita el timeout de 30 s)"
if uvx mcp-proxy-for-aws-cli@latest --help >/dev/null 2>&1; then
  ok "Proxy descargado y cacheado"
else
  fail "No se pudo descargar mcp-proxy-for-aws-cli. ¿Hay conexión / proxy corporativo?"
  exit 1
fi

echo "==> Paso 2: registrando el servidor con alcance de usuario"
ENDPOINT="https://aws-mcp.${ENDPOINT_REGION}.api.aws/mcp"

JSON="$(ENDPOINT="$ENDPOINT" REGION="$REGION" PROFILE="$PROFILE" READ_ONLY="$READ_ONLY" python3 -c '
import json, os
args = ["mcp-proxy-for-aws-cli@latest", os.environ["ENDPOINT"],
        "--metadata", "AWS_REGION=" + os.environ["REGION"]]
if os.environ.get("PROFILE"):
    args += ["--profile", os.environ["PROFILE"]]
if os.environ["READ_ONLY"] == "1":
    args.append("--read-only")
print(json.dumps({"command": "uvx", "args": args}))
')"

claude mcp remove "$SERVER_NAME" -s user >/dev/null 2>&1 || true
claude mcp add-json "$SERVER_NAME" --scope user "$JSON"

echo "==> Paso 3: verificando"
if claude mcp get "$SERVER_NAME" 2>&1 | grep -q "✔ Connected"; then
  ok "Servidor '$SERVER_NAME' conectado"
else
  fail "El servidor quedó registrado pero no conecta. Revisa: claude mcp get $SERVER_NAME"
  exit 1
fi

[[ "$READ_ONLY" == "1" ]] && echo "  (modo solo-lectura activo)"

cat <<EOF

Listo. Reinicia Claude Code para que carguen las tools.
Después las verás como mcp__aws__* y '/mcp' mostrará '$SERVER_NAME' conectado.
EOF
