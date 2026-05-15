from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["user", "assistant", "tool", "system"]


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: MessageRole
    content: str | None
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    tool_name: str | None
    created_at: datetime


class MessageList(BaseModel):
    items: list[MessageRead]
    total: int
