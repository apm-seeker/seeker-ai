from datetime import datetime, timezone

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.db.models import Message
from app.utils.ids import new_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def db_messages_to_langchain(rows: list[Message]) -> list[BaseMessage]:
    """Replay stored DB messages as a LangChain message list, in insertion order."""
    result: list[BaseMessage] = []
    for row in rows:
        if row.role == "user":
            result.append(HumanMessage(content=row.content or ""))
        elif row.role == "assistant":
            result.append(
                AIMessage(
                    content=row.content or "",
                    tool_calls=row.tool_calls or [],
                )
            )
        elif row.role == "tool":
            result.append(
                ToolMessage(
                    content=row.content or "",
                    tool_call_id=row.tool_call_id or "",
                    name=row.tool_name,
                )
            )
        elif row.role == "system":
            result.append(SystemMessage(content=row.content or ""))
    return result


def langchain_message_to_db(
    message: BaseMessage, conversation_id: str, model: str | None = None
) -> Message | None:
    """Convert a single LangChain message to a DB Message row.

    Returns None for SystemMessage (system prompts are rendered per-request and not persisted).
    """
    if isinstance(message, SystemMessage):
        return None

    base = {
        "id": new_id(),
        "conversation_id": conversation_id,
        "content": _content_to_text(message.content),
        "created_at": _utcnow(),
        "model": model,
    }

    if isinstance(message, HumanMessage):
        return Message(**base, role="user")

    if isinstance(message, AIMessage):
        tool_calls = _normalize_tool_calls(message.tool_calls)
        token_usage = _extract_usage(message)
        return Message(
            **base,
            role="assistant",
            tool_calls=tool_calls or None,
            token_usage=token_usage,
        )

    if isinstance(message, ToolMessage):
        return Message(
            **base,
            role="tool",
            tool_call_id=getattr(message, "tool_call_id", None),
            tool_name=getattr(message, "name", None),
        )

    return None


def _content_to_text(content) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else None
    return str(content)


def _normalize_tool_calls(tool_calls) -> list[dict]:
    if not tool_calls:
        return []
    normalized: list[dict] = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            normalized.append(
                {
                    "id": tc.get("id"),
                    "name": tc.get("name"),
                    "args": tc.get("args"),
                }
            )
    return normalized


def _extract_usage(message: AIMessage) -> dict | None:
    usage = getattr(message, "usage_metadata", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return {k: v for k, v in usage.items() if v is not None}
    try:
        return dict(usage)
    except Exception:
        return None
