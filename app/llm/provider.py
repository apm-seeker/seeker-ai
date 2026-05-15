from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.config import get_settings

_llm: BaseChatModel | None = None


def build_llm() -> BaseChatModel:
    global _llm
    if _llm is None:
        settings = get_settings()
        _llm = init_chat_model(settings.llm_model, temperature=0)
    return _llm


def reset_llm() -> None:
    global _llm
    _llm = None
