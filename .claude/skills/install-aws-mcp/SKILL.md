---
name: install-aws-mcp
description: Instala el AWS MCP Server (servidor remoto gestionado por AWS) en Claude Code usando el puente mcp-proxy-for-aws-cli con uvx, y lo registra con alcance de usuario (--scope user) para que las tools mcp__aws__* estén disponibles en todos los proyectos. Incluye precalentado de la caché de uvx para evitar el timeout de 30 s, verificación de credenciales AWS, scripts para macOS/Linux y Windows, modo solo-lectura para clases, y solución de problemas. Use when the user asks to "instalar el MCP de AWS", "configurar AWS MCP", "conectar Claude Code con AWS", "no aparecen las tools de AWS", "el MCP de AWS da timeout", "mcp-proxy-for-aws", "aws-mcp", or types /install-aws-mcp.
---

# Instalar el AWS MCP Server en Claude Code (global)

Objetivo: dejar el **AWS MCP Server** disponible en **todas** las sesiones y proyectos de Claude Code, autenticado con las credenciales AWS de la máquina.

## Qué es y por qué necesita un proxy

El AWS MCP Server es un servidor **remoto y gestionado por AWS** (GA desde 2026). No se instala nada del servidor en la máquina: vive en `https://aws-mcp.<region>.api.aws/mcp`.

El problema: la especificación MCP autentica con **OAuth 2.1**, pero ese endpoint usa **IAM / SigV4**. Ningún cliente MCP sabe firmar con SigV4 por su cuenta.

La solución: `mcp-proxy-for-aws-cli`, un puente que corre local, toma las credenciales AWS del equipo (perfil, variables de entorno o rol) y firma cada petición. Es lo único que se instala, y `uvx` lo hace sin ensuciar el sistema.

```
Claude Code  ──stdio──>  mcp-proxy-for-aws-cli (local, firma SigV4)  ──HTTPS──>  aws-mcp.us-east-1.api.aws
```

**Usa el paquete `mcp-proxy-for-aws-cli`, no `mcp-proxy-for-aws`.** El primero es la distribución CLI con todo el árbol de dependencias congelado a versiones probadas; el segundo es la librería para importar desde Python y trae rangos abiertos. Muchos ejemplos (incluido el post de anuncio de AWS) citan el segundo: es un error para este uso.

## Prerequisitos

| Requisito | Cómo comprobarlo | Si falta |
|---|---|---|
| `uv` / `uvx` | `uv --version` | https://docs.astral.sh/uv/getting-started/installation/ |
| Python 3.10 – 3.14 | `python3 --version` | `uv python install 3.12` (uv lo resuelve solo) |
| AWS CLI configurado | `aws sts get-caller-identity` | `aws configure` o SSO: `aws sso login` |
| Región por defecto | `aws configure get region` | `aws configure set region us-east-1` |
| Claude Code | `claude --version` | https://docs.anthropic.com/claude-code |

El proxy **no pide credenciales aparte**: usa la cadena estándar de AWS (perfil de `~/.aws/credentials`, variables `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, o rol IAM). Sin credenciales válidas el server arranca pero toda tool falla.

> **Permisos IAM:** desde la GA no hace falta ningún permiso especial para *usar* el servidor. Cada tool corre bajo la identidad que autoriza, con **sus políticas IAM actuales** — el servidor no otorga ningún permiso extra. Si el usuario no puede crear un bucket con la CLI, tampoco podrá por el MCP.

## Procedimiento (ejecútalo paso a paso)

### Paso 0: Comprobar prerequisitos

```bash
uv --version && claude --version
aws sts get-caller-identity
aws configure get region
```

Si `get-caller-identity` falla, detente y pide al usuario que configure sus credenciales (en Claude Code puede escribir `! aws configure`). No sigas sin eso.

### Paso 1: Precalentar la caché de `uvx` — no te saltes este paso

Claude Code espera **30 segundos** a que un servidor MCP conecte. La primera ejecución de `uvx` descarga y resuelve el paquete, lo que puede tardar más y hace que el servidor aparezca como *failed / timeout*. Ejecútalo una vez a mano para dejarlo cacheado:

```bash
uvx mcp-proxy-for-aws-cli@latest --help
```

Tras esto, los arranques siguientes tardan ~2 s.

### Paso 2: Registrar el servidor con alcance de usuario

`--scope user` lo guarda en `~/.claude.json`, así aplica a **todos los proyectos**.

macOS / Linux:
```bash
claude mcp remove aws -s user 2>/dev/null   # limpia un registro previo si existe
claude mcp add-json aws --scope user \
  '{"command":"uvx","args":["mcp-proxy-for-aws-cli@latest","https://aws-mcp.us-east-1.api.aws/mcp","--metadata","AWS_REGION=us-east-1"]}'
```

Windows (PowerShell). Las comillas simples no funcionan igual, usa comillas dobles escapadas o un here-string:
```powershell
claude mcp remove aws -s user 2>$null
$json = '{"command":"uvx","args":["mcp-proxy-for-aws-cli@latest","https://aws-mcp.us-east-1.api.aws/mcp","--metadata","AWS_REGION=us-east-1"]}'
claude mcp add-json aws --scope user $json
```

`uvx` en Windows es `uvx.exe`, un ejecutable real — **no** necesita el envoltorio `cmd /c` que sí requieren los `.cmd` de npm.

### Paso 3: Verificar

```bash
claude mcp get aws
```

Salida esperada: `Scope: User config (available in all your projects)` y `Status: ✔ Connected`.

### Paso 4: Reiniciar Claude Code

Las tools de un servidor nuevo se cargan al iniciar la sesión. Pide al usuario que cierre y reabra `claude`. Después aparecen como `mcp__aws__*` y `/mcp` muestra `aws` conectado.

## Elegir endpoint y región

Son **dos cosas distintas** y confundirlas es el error más común:

- **El endpoint** decide a qué servidor MCP te conectas. Solo hay dos:
  - `https://aws-mcp.us-east-1.api.aws/mcp` — US East (N. Virginia)
  - `https://aws-mcp.eu-central-1.api.aws/mcp` — Europa (Frankfurt)
- **`--metadata AWS_REGION=<region>`** decide en qué región operan tus llamadas AWS. Puede ser cualquier región. Si se omite, por defecto es `us-east-1`.

Es válido y común conectarse al endpoint de Virginia y operar sobre `sa-east-1`, por ejemplo.

## Modo solo-lectura (recomendado para clases)

Añade `--read-only` a los args para deshabilitar toda tool que pueda escribir. Deja disponible la documentación y las consultas, pero bloquea `run_script` y `get_presigned_url`:

```bash
claude mcp add-json aws --scope user \
  '{"command":"uvx","args":["mcp-proxy-for-aws-cli@latest","https://aws-mcp.us-east-1.api.aws/mcp","--metadata","AWS_REGION=us-east-1","--read-only"]}'
```

Para un grupo de alumnos con credenciales reales esto evita que un prompt ambiguo cree recursos que cuestan dinero. La defensa de verdad, de todos modos, es una política IAM restrictiva — `--read-only` es una bandera del cliente y cualquiera puede quitarla.

## Qué tools expone (verificado contra el servidor en vivo)

| Tool | Solo lectura | Para qué |
|---|---|---|
| `aws___search_documentation` | sí | Busca en la documentación AWS. Devuelve fragmentos literales de página, no resúmenes |
| `aws___read_documentation` | sí | Trae una página completa de docs como markdown |
| `aws___retrieve_skill` | sí | Recupera una "skill" de AWS (workflows y referencias). El `skill_name` sale de `search_documentation`, no se inventa |
| `aws___list_regions` | sí | Lista todas las regiones AWS |
| `aws___get_regional_availability` | sí | Qué servicios/recursos existen en qué regiones (máx. 10 regiones) |
| `aws___get_tasks` | sí | Consulta el estado de tareas largas devueltas con `status: working` |
| `aws___run_script` | **no** | Ejecuta Python en un sandbox con acceso a la API de AWS vía `call_boto3` |
| `aws___get_presigned_url` | **no** | Genera URLs prefirmadas de S3 para subir/bajar archivos (máx. 5 GB) |

> **Ojo:** el post de anuncio de AWS menciona una tool `call_aws` que ejecuta comandos de la CLI. **Ese nombre no existe en el servidor actual.** Las llamadas a la API se hacen con `aws___run_script`. Si un tutorial te dice `call_aws`, está desactualizado.

### Cómo se llama a la API de AWS realmente

Dentro de `aws___run_script` el sandbox expone una única función asíncrona (sin red hacia fuera salvo esta):

```python
r = await call_boto3(
    service_name='sts',
    operation_name='GetCallerIdentity',   # PascalCase, nombre de la operación de la API
    region_name='us-east-1',              # opcional
    params={},                            # opcional
)
print(r)
```

**`operation_name` va en PascalCase**, como en la documentación de la API — no en snake_case como los métodos de boto3. `get_caller_identity` falla con `OperationNotFoundError`; `GetCallerIdentity` funciona.

## Scripts automáticos

En `scripts/` de esta skill hay dos scripts que hacen los pasos 0 a 3:

- `scripts/install.sh` — macOS / Linux: `bash scripts/install.sh`
- `scripts/install.ps1` — Windows: `powershell -ExecutionPolicy Bypass -File scripts/install.ps1`

Ambos aceptan las mismas opciones, con la sintaxis propia de cada shell:

| Qué hace | bash (`install.sh`) | PowerShell (`install.ps1`) |
|---|---|---|
| Región de operación | `--region sa-east-1` | `-Region sa-east-1` |
| Endpoint MCP | `--endpoint-region eu-central-1` | `-EndpointRegion eu-central-1` |
| Perfil AWS | `--profile alumno` | `-AwsProfile alumno` |
| Modo solo-lectura | `--read-only` | `-ReadOnly` |
| Nombre del server | `--name aws` | `-Name aws` |

Sin opciones, ambos detectan la región del perfil AWS activo y caen a `us-east-1` si no hay ninguna.

Si el usuario prefiere, ejecútalos en lugar de los pasos manuales y muéstrale la salida final.

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `Status: ✗ Failed to connect` con timeout | La caché de `uvx` estaba fría y la descarga superó los 30 s | Ejecutar el paso 1 y volver a registrar |
| `-32602: Invalid request parameters` (`NoRegionError`) | El perfil no tiene región configurada | `aws configure set region us-east-1` o exportar `AWS_REGION` |
| Las tools fallan con `ExpiredToken` / `InvalidClientTokenId` | Credenciales vencidas (típico con SSO) | `aws sso login` y reiniciar Claude Code |
| `AccessDeniedException` en una operación | La identidad IAM no tiene ese permiso | Es correcto: el MCP no otorga permisos. Ajustar la política IAM |
| `ThrottlingException: Too many tokens per day` | Cuota diaria de la cuenta agotada (aplica a Bedrock) | Esperar al reinicio de cuota o subirla en Service Quotas |
| `OperationNotFoundError: get_caller_identity` | `operation_name` en snake_case | Usar PascalCase: `GetCallerIdentity` |
| `command not found: uvx` | `uv` no está en el PATH | Reabrir la terminal, o usar la ruta absoluta (`~/.local/bin/uvx`) |
| Windows: falla el `add-json` | El shell rompió el JSON con comillas simples | Guardar el JSON en una variable como en el paso 2 |
| Quiero apuntar a otra cuenta | — | Añadir `"--profile","<perfil>"` a los args, o varios perfiles para poder cambiar por llamada |
| Registré el server pero Claude Code no lo ve | La sesión corre con otro `CLAUDE_CONFIG_DIR` | Ver "Perfiles de Claude Code" más abajo |

### Perfiles de Claude Code (`CLAUDE_CONFIG_DIR`)

Claude Code guarda los servidores MCP de alcance de usuario en `<CLAUDE_CONFIG_DIR>/.claude.json`, y por defecto `CLAUDE_CONFIG_DIR` es `~/.claude`. Quien tenga varios perfiles (por ejemplo uno personal y otro corporativo) tiene **una configuración independiente por perfil**: registrar el server en uno no lo hace visible en el otro.

Comprueba bajo qué perfil corre la sesión:

```bash
echo "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
```

Para registrarlo en un perfil concreto, antepón la variable:

```bash
CLAUDE_CONFIG_DIR="$HOME/.claude" claude mcp add-json aws --scope user '...'
```

Lo mismo aplica a las skills: cada perfil lee **sus** skills de `<CLAUDE_CONFIG_DIR>/skills/`. Una skill en `~/.claude/skills/` no se carga en una sesión que corre con otro `CLAUDE_CONFIG_DIR`; hay que copiarla (o enlazarla) al directorio del perfil activo.

### Varias cuentas AWS a la vez

El proxy permite cambiar de perfil por llamada. El primero es el predeterminado:

```bash
claude mcp add-json aws --scope user \
  '{"command":"uvx","args":["mcp-proxy-for-aws-cli@latest","https://aws-mcp.us-east-1.api.aws/mcp","--profile","prod-readonly","dev","--metadata","AWS_REGION=us-east-1"]}'
```

El agente puede entonces pasar `aws_profile` en cualquier tool para enrutar esa llamada por otra cuenta.

## Desinstalar

```bash
claude mcp remove aws -s user
uv cache clean mcp-proxy-for-aws-cli   # opcional, libera la caché
```

No hay nada más que borrar: el servidor es remoto y el proxy nunca se instaló de forma permanente.

## Referencias

- Anuncio de GA: https://aws.amazon.com/blogs/aws/the-aws-mcp-server-is-now-generally-available/
- Documentación del servidor: https://docs.aws.amazon.com/aws-mcp/latest/userguide/getting-started-aws-mcp-server.html
- Repositorio del proxy: https://github.com/aws/mcp-proxy-for-aws
- Paquete CLI: https://pypi.org/project/mcp-proxy-for-aws-cli/
- IAM para MCP gestionados: https://aws.amazon.com/blogs/security/understanding-iam-for-managed-aws-mcp-servers/
