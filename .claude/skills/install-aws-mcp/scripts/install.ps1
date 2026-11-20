<#
.SYNOPSIS
  Instala y registra el AWS MCP Server en Claude Code (Windows).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1 -Region us-east-1 -ReadOnly
#>
[CmdletBinding()]
param(
    [string]$Region,
    [ValidateSet("us-east-1", "eu-central-1")]
    [string]$EndpointRegion = "us-east-1",
    [string]$AwsProfile,
    [switch]$ReadOnly,
    [string]$Name = "aws"
)

$ErrorActionPreference = "Stop"

function Ok   ($m) { Write-Host "  [OK] $m"   -ForegroundColor Green }
function Fail ($m) { Write-Host "  [X]  $m"   -ForegroundColor Red }

Write-Host "==> Paso 0: prerequisitos"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv no esta instalado."
    Write-Host '       Instalalo con:  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"'
    Write-Host "       Luego reabre PowerShell y vuelve a ejecutar este script."
    exit 1
}
Ok "uv $((uv --version) -split ' ' | Select-Object -Index 1)"

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Fail "Claude Code (claude) no esta en el PATH."
    exit 1
}
Ok "claude encontrado"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Fail "AWS CLI no esta instalada - https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
}

$awsArgs = @()
if ($AwsProfile) { $awsArgs += @("--profile", $AwsProfile) }

$identity = & aws @awsArgs sts get-caller-identity --query Arn --output text 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail "No hay credenciales AWS validas:"
    Write-Host "       $identity"
    Write-Host "       Ejecuta 'aws configure' (o 'aws sso login') y reintenta."
    exit 1
}
Ok "Credenciales AWS: $identity"

# Region de operacion: -Region > region del perfil > us-east-1
if (-not $Region) {
    $Region = (& aws @awsArgs configure get region 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $Region) { $Region = "us-east-1" }
}
$Region = $Region.Trim()
Ok "Region de operacion: $Region"
Ok "Endpoint MCP: $EndpointRegion"

Write-Host "==> Paso 1: precalentando la cache de uvx (evita el timeout de 30 s)"
& uvx mcp-proxy-for-aws-cli@latest --help *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "No se pudo descargar mcp-proxy-for-aws-cli. Hay conexion / proxy corporativo?"
    exit 1
}
Ok "Proxy descargado y cacheado"

Write-Host "==> Paso 2: registrando el servidor con alcance de usuario"
$endpoint = "https://aws-mcp.$EndpointRegion.api.aws/mcp"

$argList = @("mcp-proxy-for-aws-cli@latest", $endpoint, "--metadata", "AWS_REGION=$Region")
if ($AwsProfile)  { $argList += @("--profile", $AwsProfile) }
if ($ReadOnly) { $argList += "--read-only" }

# ConvertTo-Json con -Compress para que el JSON pase limpio como un solo argumento
$json = [ordered]@{ command = "uvx"; args = $argList } | ConvertTo-Json -Compress

& claude mcp remove $Name -s user *> $null
& claude mcp add-json $Name --scope user $json
if ($LASTEXITCODE -ne 0) { Fail "Fallo el registro del servidor."; exit 1 }

Write-Host "==> Paso 3: verificando"
$status = & claude mcp get $Name 2>&1 | Out-String
if ($status -match "Connected") {
    Ok "Servidor '$Name' conectado"
} else {
    Fail "El servidor quedo registrado pero no conecta. Revisa: claude mcp get $Name"
    exit 1
}

if ($ReadOnly) { Write-Host "  (modo solo-lectura activo)" }

Write-Host ""
Write-Host "Listo. Reinicia Claude Code para que carguen las tools."
Write-Host "Despues las veras como mcp__aws__* y '/mcp' mostrara '$Name' conectado."
