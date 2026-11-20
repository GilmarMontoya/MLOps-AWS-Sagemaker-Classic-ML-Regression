import os

import streamlit as st
from dotenv import load_dotenv

from agent import build_agent, run_turn

load_dotenv()

DEFAULT_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
DEFAULT_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")
DEFAULT_MODEL = os.getenv("MODEL_NAME", "google/gemma-4-e2b")
DEFAULT_API_KEY = os.getenv("API_KEY", "lm-studio")
DEFAULT_TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
DEFAULT_SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Eres un asistente útil y conciso. Responde en español.",
)
DEFAULT_SAGEMAKER_ENDPOINT = os.getenv("SAGEMAKER_ENDPOINT_NAME", "")
DEFAULT_AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

PROVIDERS = ["openai", "sagemaker"]

st.set_page_config(page_title="Agente Conversacional", page_icon="🤖")
st.title("🤖 Agente Conversacional — LMStudio / SageMaker")

with st.sidebar:
    st.header("Configuración")
    st.caption("Valores cargados desde `.env` — puedes sobrescribirlos aquí.")

    try:
        default_provider_idx = PROVIDERS.index(DEFAULT_PROVIDER)
    except ValueError:
        default_provider_idx = 0
    model_provider = st.selectbox(
        "Model provider (SDK/protocolo)",
        PROVIDERS,
        index=default_provider_idx,
        help=(
            "Selecciona el cliente/protocolo con el que se hablará al servidor, "
            "no el vendor del modelo. `openai` = API compatible con OpenAI "
            "(LMStudio, Ollama, vLLM…). `sagemaker` = invoke_endpoint de AWS."
        ),
    )

    temperature = st.slider("Temperatura", 0.0, 1.5, DEFAULT_TEMPERATURE, 0.1)
    system_prompt = st.text_area(
        "Prompt del sistema",
        value=DEFAULT_SYSTEM_PROMPT,
        height=120,
    )

    if model_provider == "sagemaker":
        sagemaker_endpoint_name = st.text_input(
            "SageMaker Endpoint",
            value=DEFAULT_SAGEMAKER_ENDPOINT,
        )
        aws_region = st.text_input("AWS Region", value=DEFAULT_AWS_REGION)
        show_thinking = st.checkbox(
            "Mostrar razonamiento (<think>)",
            value=False,
            help="Qwen3 incluye su cadena de razonamiento. Actívalo para verla.",
        )
        base_url, model_name, api_key = "", "", ""
    else:
        base_url = st.text_input("Base URL", value=DEFAULT_BASE_URL)
        model_name = st.text_input("Modelo", value=DEFAULT_MODEL)
        api_key = st.text_input("API key", value=DEFAULT_API_KEY, type="password")
        sagemaker_endpoint_name, aws_region = "", ""
        show_thinking = False

    if st.button("🗑️ Limpiar conversación"):
        st.session_state.messages = []
        st.rerun()


@st.cache_resource(show_spinner=False)
def get_agent(
    base_url: str,
    model_name: str,
    model_provider: str,
    api_key: str,
    temperature: float,
    system_prompt: str,
    sagemaker_endpoint_name: str,
    aws_region: str,
    hide_thinking: bool,
):
    return build_agent(
        base_url=base_url,
        model_name=model_name,
        model_provider=model_provider,
        api_key=api_key,
        temperature=temperature,
        system_prompt=system_prompt,
        sagemaker_endpoint_name=sagemaker_endpoint_name,
        aws_region=aws_region,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        hide_thinking=hide_thinking,
    )


agent = get_agent(
    base_url,
    model_name,
    model_provider,
    api_key,
    temperature,
    system_prompt,
    sagemaker_endpoint_name,
    aws_region,
    not show_thinking,
)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Escribe tu mensaje..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                response = run_turn(agent, st.session_state.messages)
            except Exception as e:
                response = f"⚠️ Error al llamar al modelo: {e}"
            st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
