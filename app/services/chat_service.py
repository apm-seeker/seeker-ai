import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.config import get_settings
from app.db.models import Message
from app.db.session import get_session_factory
from app.llm.graph import build_graph
from app.llm.message_mapper import (
    db_messages_to_langchain,
    langchain_message_to_db,
)
from app.llm.prompts import now_ms, render_system_prompt
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_repo import MessageRepository
from app.utils.ids import new_id

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _row_to_dict(row: Message) -> dict[str, Any]:
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "tool_calls": row.tool_calls,
        "tool_call_id": row.tool_call_id,
        "tool_name": row.tool_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class ChatService:
    async def stream_chat(
        self, conversation_id: str, user_id: str, user_content: str
    ) -> AsyncIterator[str]:
        factory = get_session_factory()
        settings = get_settings()
        model_name = settings.llm_model

        async with factory() as session:
            conv_repo = ConversationRepository(session)
            msg_repo = MessageRepository(session)
            errored = False

            try:
                conversation = await conv_repo.get(conversation_id, user_id)
                if conversation is None:
                    yield _sse("error", {"detail": "conversation not found"})
                    return

                user_row = Message(
                    id=new_id(),
                    conversation_id=conversation_id,
                    role="user",
                    content=user_content,
                    created_at=_utcnow(),
                )
                await msg_repo.add(user_row)
                await session.commit()
                yield _sse("user_message", _row_to_dict(user_row))

                history_rows, _ = await msg_repo.list_by_conversation(
                    conversation_id, limit=200, offset=0
                )
                history_lc: list[BaseMessage] = db_messages_to_langchain(
                    history_rows
                )

                system_msg = SystemMessage(content=render_system_prompt(now_ms()))
                initial_state = {"messages": [system_msg, *history_lc]}

                graph = build_graph()

                async for update in graph.astream(
                    initial_state, stream_mode="updates"
                ):
                    if not isinstance(update, dict):
                        continue
                    for node_name, node_state in update.items():
                        new_messages = _extract_new_messages(node_state)
                        for msg in new_messages:
                            row = langchain_message_to_db(
                                msg, conversation_id, model=model_name
                            )
                            if row is None:
                                continue
                            await msg_repo.add(row)
                            await session.commit()
                            event_name = (
                                "tool_message" if row.role == "tool" else "ai_message"
                            )
                            yield _sse(event_name, _row_to_dict(row))
            except Exception as exc:  # noqa: BLE001
                errored = True
                logger.exception("chat stream failed for conv %s", conversation_id)
                yield _sse(
                    "error",
                    {"detail": f"{type(exc).__name__}: {exc}"},
                )
            finally:
                try:
                    await conv_repo.touch(conversation_id)
                    await session.commit()
                except Exception:  # noqa: BLE001
                    logger.warning("failed to touch conversation %s", conversation_id)

            if not errored:
                yield _sse("done", {})


def _extract_new_messages(node_state: Any) -> list[BaseMessage]:
    if not isinstance(node_state, dict):
        return []
    raw = node_state.get("messages")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, BaseMessage)]
    if isinstance(raw, BaseMessage):
        return [raw]
    return []
