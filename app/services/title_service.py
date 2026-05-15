import asyncio
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.db.session import get_session_factory
from app.llm.provider import build_llm
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_repo import MessageRepository

logger = logging.getLogger(__name__)

_TITLE_SYSTEM = "You generate short Korean conversation titles for an APM assistant."

_TITLE_PROMPT = """다음은 대화의 첫 부분입니다. 핵심 주제를 5~20자 한국어 명사구로 요약한 제목 한 줄만 출력하세요. 따옴표, 구두점, 접두어(예: '제목:')를 붙이지 마세요.

---
{conversation}
---

제목:"""

_MAX_TITLE_LEN = 60

_background_tasks: set[asyncio.Task] = set()


def schedule_title_generation(conversation_id: str, user_id: str) -> None:
    task = asyncio.create_task(_generate_title_if_missing(conversation_id, user_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _generate_title_if_missing(conversation_id: str, user_id: str) -> None:
    factory = get_session_factory()
    try:
        async with factory() as session:
            conv_repo = ConversationRepository(session)
            msg_repo = MessageRepository(session)

            conversation = await conv_repo.get(conversation_id, user_id)
            if conversation is None or conversation.title:
                return

            rows, _ = await msg_repo.list_by_conversation(
                conversation_id, limit=6, offset=0
            )
            has_user = any(r.role == "user" and r.content for r in rows)
            has_assistant = any(r.role == "assistant" and r.content for r in rows)
            if not (has_user and has_assistant):
                return

            transcript_lines: list[str] = []
            for r in rows:
                if r.role == "user" and r.content:
                    transcript_lines.append(f"User: {r.content.strip()[:400]}")
                elif r.role == "assistant" and r.content:
                    transcript_lines.append(f"Assistant: {r.content.strip()[:400]}")
            transcript = "\n".join(transcript_lines)

            prompt = _TITLE_PROMPT.format(conversation=transcript)
            llm = build_llm()
            response = await llm.ainvoke(
                [
                    SystemMessage(content=_TITLE_SYSTEM),
                    HumanMessage(content=prompt),
                ]
            )
            title = _extract_title(getattr(response, "content", response))
            if not title:
                return

            await conv_repo.update_title(conversation_id, user_id, title)
            await session.commit()
            logger.info(
                "generated title for conversation %s: %s", conversation_id, title
            )
    except Exception:
        logger.exception("title generation failed for %s", conversation_id)


def _extract_title(content: Any) -> str:
    text = _content_to_text(content)
    if not text:
        return ""
    first_line = text.strip().split("\n", 1)[0].strip()
    for q in ('"', "'", "「", "」", "『", "』", "“", "”"):
        first_line = first_line.strip(q)
    if first_line.lower().startswith("title:"):
        first_line = first_line.split(":", 1)[1].strip()
    if first_line.startswith("제목:"):
        first_line = first_line.split(":", 1)[1].strip()
    if len(first_line) > _MAX_TITLE_LEN:
        first_line = first_line[:_MAX_TITLE_LEN]
    return first_line


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return ""
