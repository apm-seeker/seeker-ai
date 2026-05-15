from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[Message], int]:
        base = select(Message).where(Message.conversation_id == conversation_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        page_stmt = (
            base.order_by(Message.created_at.asc()).limit(limit).offset(offset)
        )
        rows = (await self.session.execute(page_stmt)).scalars().all()
        return list(rows), int(total)

    async def add(self, message: Message) -> Message:
        self.session.add(message)
        await self.session.flush()
        return message

    async def add_all(self, messages: list[Message]) -> list[Message]:
        self.session.add_all(messages)
        await self.session.flush()
        return messages
