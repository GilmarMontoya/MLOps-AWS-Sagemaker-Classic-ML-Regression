"""
Interfaz de chat en Streamlit para el LLM (Qwen3-4B) desplegado en SageMaker.

Ejecutar:
    streamlit run app_frontend_de_consumo_llm.py
"""
import os
import time

import streamlit as st
from dotenv import load_dotenv

from app_backend_de_consumo_llm import ClienteLLMSageMaker, explicar_error, separar_razonamiento

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
SAGEMAKER_ENDPOINT_NAME = os.getenv("SAGEMAKER_ENDPOINT_NAME", "qwen3-4b-g5")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID") or None
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY") or None
SYSTEM_PROMPT_DEFAULT = os.getenv("SYSTEM_PROMPT", "Eres un asistente útil y conciso. Responde en español.")

st.set_page_config(page_title="Chat con Qwen3 en SageMaker", page_icon="💬", layout="centered")


@st.cache_resource
def obtener_cliente(endpoint: str, region: str) -> ClienteLLMSageMaker:
    return ClienteLLMSageMaker(endpoint, region, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)


# ---------------------------------------------------------------- barra lateral
with st.sidebar:
    st.header("⚙️ Configuración")
    endpoint = st.text_input("Endpoint de SageMaker", SAGEMAKER_ENDPOINT_NAME)
    region = st.text_input("Región", AWS_REGION)
    system_prompt = st.text_area("System prompt", SYSTEM_PROMPT_DEFAULT, height=100)
    temperature = st.slider("Temperatura", 0.0, 1.5, 0.7, 0.05)
    max_tokens = st.slider("Máx. tokens de salida", 128, 4096, 1024, 128,
                           help="Qwen3 piensa antes de responder: con poco margen la respuesta se corta.")
    pensar = st.toggle("Razonamiento (thinking)", value=True,
                       help="Si lo apagas, se añade /no_think al mensaje y Qwen3 responde directo (más rápido).")
    mostrar_razonamiento = st.toggle("Mostrar el razonamiento", value=True, disabled=not pensar)
    usar_stream = st.toggle("Streaming", value=True,
                            help="Muestra la respuesta a medida que se genera (invoke_endpoint_with_response_stream).")
    st.divider()
    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.mensajes = []
        st.rerun()
    st.caption(f"Endpoint `{endpoint}` · `{region}`\n\n"
               "En ECS la app usa el rol IAM de la tarea; en la laptop, `~/.aws` o el `.env`.")

# ---------------------------------------------------------------- historial
st.title("💬 Chat con Qwen3-4B")
st.caption("LLM desplegado en un endpoint de Amazon SageMaker (contenedor LMI / vLLM).")

if "mensajes" not in st.session_state:
    st.session_state.mensajes = []  # [{"role", "content", "razonamiento", "meta"}]

for m in st.session_state.mensajes:
    with st.chat_message(m["role"]):
        if m.get("razonamiento") and mostrar_razonamiento:
            with st.expander("🧠 Razonamiento"):
                st.markdown(m["razonamiento"])
        st.markdown(m["content"])
        if m.get("meta"):
            st.caption(m["meta"])

# ---------------------------------------------------------------- nuevo mensaje
pregunta = st.chat_input("Escribe tu mensaje…")
if pregunta:
    st.session_state.mensajes.append({"role": "user", "content": pregunta})
    with st.chat_message("user"):
        st.markdown(pregunta)

    historial = [{"role": m["role"], "content": m["content"]} for m in st.session_state.mensajes]
    cliente = obtener_cliente(endpoint, region)
    kwargs = dict(system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature, pensar=pensar)

    with st.chat_message("assistant"):
        try:
            if usar_stream:
                caja_razonamiento = st.empty()
                caja_respuesta = st.empty()
                crudo, t0 = "", time.time()
                for trozo in cliente.responder_stream(historial, **kwargs):
                    crudo += trozo
                    razonamiento, texto = separar_razonamiento(crudo)
                    if razonamiento and mostrar_razonamiento:
                        caja_razonamiento.info(f"🧠 {razonamiento}")
                    caja_respuesta.markdown(texto + " ▌")
                razonamiento, texto = separar_razonamiento(crudo)
                caja_razonamiento.empty()
                if razonamiento and mostrar_razonamiento:
                    with caja_razonamiento.container():
                        with st.expander("🧠 Razonamiento"):
                            st.markdown(razonamiento)
                caja_respuesta.markdown(texto or "_(sin respuesta: sube el máximo de tokens)_")
                meta = f"{time.time() - t0:.1f} s · streaming"
            else:
                with st.spinner("Pensando…"):
                    r = cliente.responder(historial, **kwargs)
                razonamiento, texto = r.razonamiento, r.texto
                if razonamiento and mostrar_razonamiento:
                    with st.expander("🧠 Razonamiento"):
                        st.markdown(razonamiento)
                st.markdown(texto or "_(sin respuesta: sube el máximo de tokens)_")
                meta = (f"{r.segundos:.1f} s · {r.uso.get('prompt_tokens', '?')} tokens de entrada, "
                        f"{r.uso.get('completion_tokens', '?')} de salida")
            st.caption(meta)
            st.session_state.mensajes.append(
                {"role": "assistant", "content": texto, "razonamiento": razonamiento, "meta": meta})
        except Exception as e:  # noqa: BLE001 — se muestra al usuario en vez de romper la app
            st.error(explicar_error(e))
            # Se quita el mensaje del usuario para que pueda reintentar sin duplicarlo en el historial
            st.session_state.mensajes.pop()
