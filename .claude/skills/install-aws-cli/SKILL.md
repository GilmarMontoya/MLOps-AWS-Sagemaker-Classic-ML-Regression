---
name: install-aws-cli
description: Instala la AWS CLI v2 (la línea de comandos oficial de Amazon Web Services) detectando automáticamente el sistema operativo — macOS, Linux (x86_64 / ARM), WSL o Windows — y la deja configurada con credenciales (aws configure o aws configure sso) y verificada con aws sts get-caller-identity. Incluye la preparación de una cuenta de AWS recién creada (no usar root, usuario IAM / Identity Center, access keys, alerta de presupuesto). Úsala cuando el usuario pida instalar la CLI de AWS, cuando un comando falle con "aws - command not found", o cuando mencione "instalar aws cli", "no tengo aws", "awscli", "configurar credenciales de AWS", "aws configure", "acabo de crear mi cuenta de AWS", o escriba /install-aws-cli.
---

Instala y configura la **AWS CLI v2** en la máquina del usuario. Sigue estos pasos **en orden** y no los saltes.

> Usa siempre la **v2**. La v1 (`pip install awscli`) está obsoleta y no sirve para SSO ni para las herramientas nuevas (AgentCore, CDK, etc.).

## Paso 1 — ¿Ya está instalada?

```bash
aws --version
```

- **Si responde `aws-cli/2.x.x ...`**: ya está instalada. Muestra la versión y la ruta (`which aws`, o `where aws` en Windows) y **salta al Paso 5** (credenciales).
- **Si responde `aws-cli/1.x.x`**: es la v1. Desinstálala (`pip uninstall awscli`) y continúa al Paso 2.
- **Si dice `command not found` / `no se reconoce`**: continúa al Paso 2.

## Paso 2 — Detectar el sistema operativo y la arquitectura

```bash
uname -s; uname -m
```

| `uname -s` | `uname -m` | Sistema | Instalador |
|---|---|---|---|
| `Darwin` | `arm64` / `x86_64` | macOS (el `.pkg` sirve para ambos) | `.pkg` oficial o Homebrew |
| `Linux` | `x86_64` | Linux / WSL Intel-AMD | zip `awscli-exe-linux-x86_64` |
| `Linux` | `aarch64` | Linux / WSL ARM (Graviton, Raspberry Pi 64) | zip `awscli-exe-linux-aarch64` |
| `MINGW*`, `MSYS*`, `CYGWIN*` | — | Windows (Git Bash) | MSI o winget |
| el comando falla | — | Windows (PowerShell/CMD nativo) | MSI o winget |

## Paso 3 — Instalar

> Casi todos los instaladores piden **contraseña de administrador** (`sudo` o UAC). Claude no puede escribir esa contraseña: pídele al usuario que ejecute el comando él mismo con el prefijo `!` en el prompt (ej. `! sudo installer -pkg AWSCLIV2.pkg -target /`) o en su propia terminal.

### macOS

**Opción A — Instalador oficial (recomendado):**

```bash
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "/tmp/AWSCLIV2.pkg"
sudo installer -pkg /tmp/AWSCLIV2.pkg -target /
rm /tmp/AWSCLIV2.pkg
```

Instala en `/usr/local/aws-cli` y crea el enlace `/usr/local/bin/aws`. También se puede hacer doble clic en el `.pkg` descargado y seguir el asistente gráfico.

**Opción B — Homebrew** (solo si `which brew` responde y el usuario ya lo usa; pregúntale cuál prefiere):

```bash
brew install awscli
```

No mezcles ambas: si ya hay una instalada por un método, no instales la otra (quedarían dos `aws` en el PATH).

### Linux (incluye WSL)

Requisitos: `curl` y `unzip` (`sudo apt install -y curl unzip` en Debian/Ubuntu, `sudo dnf install -y curl unzip` en Fedora/Amazon Linux).

**x86_64:**

```bash
cd /tmp
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf awscliv2.zip aws
```

**ARM (aarch64):**

```bash
cd /tmp
curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf awscliv2.zip aws
```

**Sin sudo** (máquinas compartidas o sin permisos de admin) — instala solo para el usuario:

```bash
./aws/install -i ~/.local/aws-cli -b ~/.local/bin
```

Y asegúrate de que `~/.local/bin` esté en el PATH.

**Actualizar** una instalación existente: repite la descarga y usa

```bash
sudo ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update
```

No uses `apt install awscli` / `snap`: suelen traer versiones viejas (a veces la v1).

### Windows

**Opción A — winget (PowerShell, Windows 10/11):**

```powershell
winget install -e --id Amazon.AWSCLI
```

**Opción B — MSI oficial** (abre el asistente gráfico):

```powershell
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi
```

Instalación silenciosa (requiere PowerShell **como administrador**):

```powershell
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi /qn
```

También se puede descargar `https://awscli.amazonaws.com/AWSCLIV2.msi` desde el navegador y hacer doble clic.

Se instala en `C:\Program Files\Amazon\AWSCLIV2\`. Para actualizar, se repite la misma instalación.

## Paso 4 — Verificar la instalación

```bash
aws --version
```

Debe responder `aws-cli/2.x.x Python/3.x ...`.

- **macOS / Linux:** si dice `command not found` justo después de instalar, ejecuta `hash -r` o abre una terminal nueva. Si se instaló sin sudo, revisa que `~/.local/bin` esté en el PATH.
- **Windows:** **cierra y vuelve a abrir** la terminal (PowerShell, CMD o Git Bash); el PATH nuevo no se aplica a las ventanas ya abiertas.

## Paso 5 — Preparar la cuenta (solo si es nueva)

Si el usuario acaba de crear su cuenta de AWS, explícale esto **antes** de configurar credenciales:

1. **No usar el usuario root** para el día a día. Activar **MFA** en root (Consola → nombre de la cuenta → Security credentials).
2. Crear una identidad de trabajo, una de dos:
   - **IAM Identity Center (recomendado):** crear usuario + permission set `AdministratorAccess` → se usará con `aws configure sso`.
   - **Usuario IAM clásico:** IAM → Users → Create user → adjuntar `AdministratorAccess` → pestaña *Security credentials* → **Create access key** (caso de uso "Command Line Interface"). Descargar el `.csv`; la secret key solo se muestra una vez.
3. **Alerta de presupuesto:** Billing → Budgets → *Create budget* (plantilla "Zero spend" o "Monthly cost", ej. 10 USD).

## Paso 6 — Configurar credenciales

> **Nunca** le pidas al usuario que pegue su Access Key o Secret Key en el chat, y no leas ni imprimas `~/.aws/credentials`. Que ejecute él mismo el comando interactivo con el prefijo `!` (ej. `! aws configure`) para que las claves vayan directo al archivo.

**Con access keys (usuario IAM):**

```bash
aws configure
```

Pide 4 datos: `AWS Access Key ID`, `AWS Secret Access Key`, `Default region name` (ej. `us-east-1`) y `Default output format` (`json`).

Para tener varias cuentas sin pisar la anterior, usa un perfil con nombre:

```bash
aws configure --profile mi-cuenta
export AWS_PROFILE=mi-cuenta        # macOS/Linux
$env:AWS_PROFILE = "mi-cuenta"      # Windows PowerShell
```

**Con IAM Identity Center (SSO):**

```bash
aws configure sso
```

Pide el *SSO start URL* (`https://<algo>.awsapps.com/start`), la región del Identity Center, y abre el navegador para autorizar. Cuando la sesión expire: `aws sso login --profile <perfil>`.

Ver qué perfiles existen (sin mostrar secretos):

```bash
aws configure list-profiles
aws configure list            # muestra solo los últimos 4 caracteres de la key
```

## Paso 7 — Verificar las credenciales

```bash
aws sts get-caller-identity
```

Debe devolver un JSON con `UserId`, `Account` (12 dígitos) y `Arn`. Confirma con el usuario que:

- **`Account`** es la cuenta que espera (muy común: el perfil `default` aún apunta a una cuenta anterior).
- **`Arn`** termina en `:user/<nombre>` o `:assumed-role/...`, **no** en `:root`.

Si va a usar servicios regionales (Bedrock, AgentCore, etc.), confirma la región:

```bash
aws configure get region
```

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `aws: command not found` tras instalar | PATH no recargado | Terminal nueva / `hash -r` |
| `aws-cli/1.x` | Quedó la v1 de pip | `pip uninstall awscli` y reinstalar v2 |
| Dos versiones distintas según la terminal | brew + pkg, o pip + v2 | `which -a aws` y desinstalar la sobrante |
| `Unable to locate credentials` | Falta `aws configure` o `AWS_PROFILE` apunta a un perfil inexistente | Paso 6 |
| `InvalidClientTokenId` / `SignatureDoesNotMatch` | Key mal copiada o desactivada | Crear una access key nueva en IAM y repetir `aws configure` |
| `The SSO session ... has expired` | Token SSO vencido | `aws sso login --profile <perfil>` |
| `ExpiredToken` | Variables `AWS_SESSION_TOKEN` viejas en el entorno | `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN` |
| Error de reloj / `RequestTimeTooSkewed` | Hora del sistema desfasada (frecuente en WSL) | Sincronizar la hora (`sudo hwclock -s` en WSL) |

## Notas

- La AWS CLI v2 es **un binario autocontenido**: trae su propio Python, no depende del Python del sistema ni de `uv`.
- Se instala **una vez por computadora**, no por proyecto. Las credenciales viven en `~/.aws/` (`%USERPROFILE%\.aws\` en Windows) y sirven para todos los proyectos.
- Documentación oficial: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
