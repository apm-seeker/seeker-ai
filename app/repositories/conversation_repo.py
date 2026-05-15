from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation
from app.utils.ids import new_id


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: str, title: str | None = None) -> Conversation:
        now = _now()
        conversation = Conversation(
            id=new_id(),
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get(self, conversation_id: str, user_id: str) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.archived_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[Conversation], int]:
        base = select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.archived_at.is_(None),
        )
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        page_stmt = (
            base.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
        )
        rows = (await self.session.execute(page_stmt)).scalars().all()
        return list(rows), int(total)

    async def update_title(
        self, conversation_id: str, user_id: str, title: str
    ) -> Conversation | None:
        conversation = await self.get(conversation_id, user_id)
        if conversation is None:
            return None
        conversation.title = title
        conversation.updated_at = _now()
        await self.session.flush()
        return conversation

    async def soft_delete(self, conversation_id: str, user_id: str) -> bool:
        stmt = (
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.archived_at.is_(None),
            )
            .values(archived_at=_now())
        )
        result = await self.session.execute(stmt)
        return (result.rowcount or 0) > 0

    async def touch(self, conversation_id: str) -> None:
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=_now())
        )
        await self.session.execute(stmt)
