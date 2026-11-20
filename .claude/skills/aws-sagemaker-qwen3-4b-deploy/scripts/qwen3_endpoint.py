"""
Despliega, prueba y borra Qwen3-4B (SageMaker JumpStart) en un endpoint de tiempo real.

Usa las credenciales de `aws configure` (cadena estándar de boto3), no las del .env.

Uso (desde cualquier carpeta, con el entorno que tiene sagemaker<3):
    python qwen3_endpoint.py check                     # cuenta, región, cuota, rol, endpoints vivos
    python qwen3_endpoint.py crear-rol                 # solo si `check` dice que no hay rol
    python qwen3_endpoint.py deploy [--instance ml.g5.xlarge] [--name qwen3-4b-g5] [--env-file RUTA/.env]
    python qwen3_endpoint.py status [--name qwen3-4b-g5]
    python qwen3_endpoint.py test [--name qwen3-4b-g5] ["pregunta"]
    python qwen3_endpoint.py delete --yes [--name qwen3-4b-g5]

Todos aceptan --region (por defecto us-east-2).
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
DEFAULT_REGION = "us-east-2"
MODEL_ID = "huggingface-reasoning-qwen3-4b"
MODEL_VERSION = "1.46.1"  # fijada: contenedor LMI (vLLM), formato OpenAI chat
DEFAULT_INSTANCE = "ml.g5.xlarge"
DEFAULT_ENDPOINT = "qwen3-4b-g5"
ROLE_NAME = "SageMakerQwen3ExecutionRole"

# USD/hora en us-east-2 (AWS Pricing API, 2026-11). En otras regiones varía.
PRECIOS = {
    "ml.g6.xlarge": 1.13,   # NVIDIA L4 24 GB, la más barata
    "ml.g5.xlarge": 1.41,   # NVIDIA A10G 24 GB, la recomendada
    "ml.g6.2xlarge": 1.53,
    "ml.g5.2xlarge": 1.82,
}
# JumpStart usa ml.g6e.12xlarge (~13 USD/h) si no se indica la instancia.
# Por eso este script NUNCA deja la instancia en blanco y rechaza las que no están aquí.

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def sesion(region: str) -> boto3.Session:
    return boto3.Session(region_name=region)


def ok(msg):
    print(f"  [OK]    {msg}")


def warn(msg):
    print(f"  [AVISO] {msg}")


def fail(msg):
    print(f"  [ERROR] {msg}")


def buscar_rol(iam) -> str | None:
    """Devuelve el ARN de un rol de ejecución de SageMaker de la cuenta, o None."""
    candidatos = []
    for page in iam.get_paginator("list_roles").paginate():
        for r in page["Roles"]:
            if r["RoleName"] == ROLE_NAME or r["RoleName"].startswith("AmazonSageMaker-ExecutionRole"):
                candidatos.append(r)
    if not candidatos:
        return None
    # Preferimos el nuestro; si no, el más reciente de SageMaker.
    candidatos.sort(key=lambda r: (r["RoleName"] != ROLE_NAME, -r["CreateDate"].timestamp()))
    return candidatos[0]["Arn"]


def cuota_endpoint(region: str, instance: str) -> tuple[float | None, str | None]:
    sq = sesion(region).client("service-quotas")
    nombre = f"{instance} for endpoint usage"
    for page in sq.get_paginator("list_service_quotas").paginate(ServiceCode="sagemaker"):
        for q in page["Quotas"]:
            if q["QuotaName"] == nombre:
                return q["Value"], q["QuotaCode"]
    return None, None


def endpoint_existe(sm, name: str) -> dict | None:
    try:
        return sm.describe_endpoint(EndpointName=name)
    except ClientError as e:
        if "Could not find endpoint" in str(e):
            return None
        raise


def actualizar_env(path: Path, valores: dict) -> None:
    """Escribe/reemplaza claves en un .env sin imprimir su contenido."""
    lineas = path.read_text().splitlines() if path.exists() else []
    pendientes = dict(valores)
    for i, linea in enumerate(lineas):
        clave = linea.split("=", 1)[0].strip()
        if clave in pendientes:
            lineas[i] = f"{clave}={pendientes.pop(clave)}"
    lineas += [f"{k}={v}" for k, v in pendientes.items()]
    path.write_text("\n".join(lineas) + "\n")


# ---------------------------------------------------------------------------
# Subcomandos
# ---------------------------------------------------------------------------
def cmd_check(a) -> int:
    s = sesion(a.region)
    errores = 0
    print(f"\n== Verificación para Qwen3-4B en {a.region} ({a.instance}) ==\n")

    ident = s.client("sts").get_caller_identity()
    if ident["Arn"].endswith(":root"):
        fail("Estás usando el usuario ROOT. Crea un usuario IAM y configúralo con `aws configure`.")
        errores += 1
    else:
        ok(f"Cuenta {ident['Account']} · {ident['Arn'].split('/')[-1]}")

    sm = s.client("sagemaker")
    try:
        vivos = sm.list_endpoints()["Endpoints"]
        ok(f"SageMaker accesible en {a.region}")
        if vivos:
            warn("Endpoints encendidos ahora (cada uno cobra por hora):")
            for e in vivos:
                print(f"            - {e['EndpointName']} ({e['EndpointStatus']})")
    except ClientError as e:
        if "service control policy" in str(e):
            fail(f"Tu organización bloquea SageMaker en {a.region} (SCP). Usa --region us-east-2.")
        else:
            fail(f"No se pudo listar endpoints: {e}")
        return 1

    valor, codigo = cuota_endpoint(a.region, a.instance)
    if valor is None:
        warn(f"No encontré la cuota de '{a.instance} for endpoint usage' en {a.region}.")
    elif valor < 1:
        fail(f"Cuota de {a.instance} para endpoints = {valor:g}. Pide aumento (tarda horas o días):")
        print(f"            aws service-quotas request-service-quota-increase --service-code sagemaker "
              f"--quota-code {codigo} --desired-value 1 --region {a.region}")
        alternativas = [i for i in PRECIOS if i != a.instance and (cuota_endpoint(a.region, i)[0] or 0) >= 1]
        if alternativas:
            print(f"            O usa una instancia con cuota: --instance {alternativas[0]}")
        errores += 1
    else:
        ok(f"Cuota de {a.instance} para endpoints = {valor:g}")
        en_uso = sum(1 for e in vivos if _instancia_de(sm, e["EndpointName"]) == a.instance)
        if en_uso >= valor:
            fail(f"Ya usas {en_uso} {a.instance} en otros endpoints y la cuota es {valor:g}. Borra uno primero.")
            errores += 1

    rol = buscar_rol(s.client("iam"))
    if rol:
        ok(f"Rol de ejecución: {rol.split('/')[-1]}")
    else:
        fail(f"No hay rol de ejecución de SageMaker. Créalo con: python qwen3_endpoint.py crear-rol")
        errores += 1

    precio = PRECIOS.get(a.instance)
    print(f"\n  Costo: ~US${precio}/hora mientras el endpoint esté InService (aunque nadie lo use).")
    print(f"         ~US${precio * 24:.0f} si se queda encendido un día entero.\n")
    print("  LISTO para desplegar." if errores == 0 else f"  Hay {errores} problema(s) que resolver antes de desplegar.")
    return 0 if errores == 0 else 1


def _instancia_de(sm, endpoint_name: str) -> str | None:
    try:
        cfg = sm.describe_endpoint(EndpointName=endpoint_name)["EndpointConfigName"]
        return sm.describe_endpoint_config(EndpointConfigName=cfg)["ProductionVariants"][0].get("InstanceType")
    except (ClientError, KeyError, IndexError):
        return None


def cmd_crear_rol(a) -> int:
    iam = sesion(a.region).client("iam")
    existente = buscar_rol(iam)
    if existente:
        print(f"Ya existe un rol utilizable: {existente}")
        return 0
    confianza = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "sagemaker.amazonaws.com"},
                       "Action": "sts:AssumeRole"}],
    }
    r = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(confianza),
                        Description="Rol de ejecución para el endpoint Qwen3-4B (curso MLOps)")
    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonSageMakerFullAccess")
    print(f"Rol creado: {r['Role']['Arn']}")
    print("Esperando 15 s a que IAM lo propague...")
    time.sleep(15)
    return 0


def cmd_deploy(a) -> int:
    if a.instance not in PRECIOS:
        print(f"Instancia {a.instance} no permitida. Usa una de: {', '.join(PRECIOS)}")
        return 1
    s = sesion(a.region)
    sm = s.client("sagemaker")
    if endpoint_existe(sm, a.name):
        print(f"El endpoint '{a.name}' ya existe. Usa `status`, o bórralo con `delete --yes` antes de redesplegar.")
        return 1
    rol = buscar_rol(s.client("iam"))
    if not rol:
        print("No hay rol de ejecución. Corre primero: python qwen3_endpoint.py crear-rol")
        return 1

    import sagemaker  # import tardío: tarda y solo hace falta aquí
    from sagemaker.jumpstart.model import JumpStartModel

    if int(sagemaker.__version__.split(".")[0]) >= 3:
        print(f"Tienes sagemaker {sagemaker.__version__}. Este script necesita la v2: pip install 'sagemaker<3'")
        return 1

    print(f"Desplegando {MODEL_ID} v{MODEL_VERSION} en {a.instance} ({a.region}) como '{a.name}'")
    print(f"Costo: ~US${PRECIOS[a.instance]}/hora desde que quede InService.\n")
    model = JumpStartModel(
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        role=rol,
        instance_type=a.instance,
        sagemaker_session=sagemaker.Session(boto_session=s),
    )
    model.deploy(
        initial_instance_count=1,
        instance_type=a.instance,  # obligatorio: el default de JumpStart es ml.g6e.12xlarge
        endpoint_name=a.name,
        wait=False,
    )

    inicio = time.time()
    while True:
        d = sm.describe_endpoint(EndpointName=a.name)
        estado = d["EndpointStatus"]
        print(f"  [{int(time.time() - inicio) // 60:02d} min] {estado}", flush=True)
        if estado == "InService":
            break
        if estado == "Failed":
            print(f"\nFALLÓ: {d.get('FailureReason')}")
            print("Borra los restos con: python qwen3_endpoint.py delete --yes")
            return 1
        time.sleep(30)

    if a.env_file:
        actualizar_env(Path(a.env_file), {
            "MODEL_PROVIDER": "sagemaker",
            "SAGEMAKER_ENDPOINT_NAME": a.name,
            "AWS_REGION": a.region,
        })
        print(f"\nActualizado {a.env_file}: MODEL_PROVIDER, SAGEMAKER_ENDPOINT_NAME, AWS_REGION")

    print(f"\nEndpoint '{a.name}' InService en {a.region} · {a.instance} · ~US${PRECIOS[a.instance]}/h")
    print("Probar:  python qwen3_endpoint.py test")
    print("BORRAR:  python qwen3_endpoint.py delete --yes   (¡al terminar!)")
    return 0


def cmd_status(a) -> int:
    sm = sesion(a.region).client("sagemaker")
    d = endpoint_existe(sm, a.name)
    if not d:
        print(f"No existe '{a.name}' en {a.region}.")
        vivos = sm.list_endpoints()["Endpoints"]
        for e in vivos:
            print(f"  Encendido: {e['EndpointName']} ({e['EndpointStatus']})")
        return 0
    inst = _instancia_de(sm, a.name)
    horas = (datetime.now(timezone.utc) - d["CreationTime"]).total_seconds() / 3600
    precio = PRECIOS.get(inst)
    print(f"{a.name}: {d['EndpointStatus']} · {inst} · {a.region}")
    print(f"Creado hace {horas:.1f} h" + (f" · gastado aprox. US${horas * precio:.2f}" if precio else ""))
    if d.get("FailureReason"):
        print(f"Motivo del fallo: {d['FailureReason']}")
    return 0


def cmd_test(a) -> int:
    rt = sesion(a.region).client("sagemaker-runtime")
    pregunta = a.pregunta or "¿Cuál es la capital de Francia? Responde en una sola frase."
    payload = {
        "messages": [
            {"role": "system", "content": "Eres un asistente útil y conciso. Responde en español."},
            {"role": "user", "content": pregunta},
        ],
        "max_tokens": 1024,  # Qwen3 piensa antes de responder; con poco margen se corta
        "temperature": 0.7,
    }
    t0 = time.time()
    r = rt.invoke_endpoint(EndpointName=a.name, ContentType="application/json",
                           Body=json.dumps(payload).encode("utf-8"))
    body = json.loads(r["Body"].read())
    texto = body["choices"][0]["message"]["content"] or ""
    print(f"Pregunta:  {pregunta}")
    print(f"Respuesta: {THINK_RE.sub('', texto).strip()}")
    uso = body.get("usage", {})
    print(f"\n({time.time() - t0:.1f} s · {uso.get('prompt_tokens', '?')} tokens de entrada, "
          f"{uso.get('completion_tokens', '?')} de salida)")
    return 0


def cmd_delete(a) -> int:
    sm = sesion(a.region).client("sagemaker")
    d = endpoint_existe(sm, a.name)
    if not d:
        print(f"No existe '{a.name}' en {a.region}. Nada que borrar.")
        return 0
    if not a.yes:
        print(f"Esto borra '{a.name}' en {a.region}. Repite con --yes para confirmar.")
        return 1
    cfg = d["EndpointConfigName"]
    modelos = [v["ModelName"] for v in sm.describe_endpoint_config(EndpointConfigName=cfg)["ProductionVariants"]]
    sm.delete_endpoint(EndpointName=a.name)
    print(f"Borrado endpoint: {a.name}  (deja de cobrar)")
    sm.delete_endpoint_config(EndpointConfigName=cfg)
    print(f"Borrada config:   {cfg}")
    for m in modelos:
        sm.delete_model(ModelName=m)
        print(f"Borrado modelo:   {m}")
    restantes = [e["EndpointName"] for e in sm.list_endpoints()["Endpoints"]]
    print(f"\nEndpoints que siguen en {a.region}: {restantes or 'ninguno'}")
    return 0


# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description="Qwen3-4B en SageMaker (JumpStart)")
    p.add_argument("--region", default=DEFAULT_REGION)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check")
    c.add_argument("--instance", default=DEFAULT_INSTANCE)
    sub.add_parser("crear-rol")
    dp = sub.add_parser("deploy")
    dp.add_argument("--instance", default=DEFAULT_INSTANCE)
    dp.add_argument("--name", default=DEFAULT_ENDPOINT)
    dp.add_argument("--env-file", help="Ruta a un .env donde escribir SAGEMAKER_ENDPOINT_NAME y AWS_REGION")
    st = sub.add_parser("status")
    st.add_argument("--name", default=DEFAULT_ENDPOINT)
    t = sub.add_parser("test")
    t.add_argument("--name", default=DEFAULT_ENDPOINT)
    t.add_argument("pregunta", nargs="?")
    de = sub.add_parser("delete")
    de.add_argument("--name", default=DEFAULT_ENDPOINT)
    de.add_argument("--yes", action="store_true")

    a = p.parse_args()
    return {
        "check": cmd_check, "crear-rol": cmd_crear_rol, "deploy": cmd_deploy,
        "status": cmd_status, "test": cmd_test, "delete": cmd_delete,
    }[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
