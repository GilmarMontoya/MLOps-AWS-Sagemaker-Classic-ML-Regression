from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from sagemaker_llm.client import SageMakerChatClient


def build_agent(
    base_url: str,
    model_name: str,
    model_provider: str,
    api_key: str,
    temperature: float,
    system_prompt: str,
    sagemaker_endpoint_name: str = "",
    aws_region: str = "us-east-1",
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    hide_thinking: bool = True,
):
    if model_provider == "sagemaker":
        return SageMakerChatClient(
            endpoint_name=sagemaker_endpoint_name,
            region=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            temperature=temperature,
            system_prompt=system_prompt,
            hide_thinking=hide_thinking,
        )

    llm = init_chat_model(
        model=model_name,
        model_provider=model_provider,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
    )
    return create_agent(
        model=llm,
        tools=[],
        system_prompt=system_prompt,
    )


def to_lc_messages(history: list[dict]) -> list[BaseMessage]:
    return [
        HumanMessage(content=m["content"]) if m["role"] == "user"
        else AIMessage(content=m["content"])
        for m in history
    ]


def run_turn(agent, history: list[dict]) -> str:
    result = agent.invoke({"messages": to_lc_messages(history)})
    return result["messages"][-1].content
