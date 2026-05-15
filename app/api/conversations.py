from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import current_user_id, db_session
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_repo import MessageRepository
from app.schemas.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationRead,
    ConversationUpdate,
)
from app.schemas.message import MessageCreate, MessageList, MessageRead
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> ConversationRead:
    repo = ConversationRepository(session)
    conversation = await repo.create(user_id=user_id, title=payload.title)
    return ConversationRead.model_validate(conversation)


@router.get("", response_model=ConversationList)
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> ConversationList:
    repo = ConversationRepository(session)
    items, total = await repo.list_by_user(user_id=user_id, limit=limit, offset=offset)
    return ConversationList(
        items=[ConversationRead.model_validate(c) for c in items],
        total=total,
    )


@router.get("/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> ConversationRead:
    repo = ConversationRepository(session)
    conversation = await repo.get(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationRead.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> ConversationRead:
    repo = ConversationRepository(session)
    conversation = await repo.update_title(conversation_id, user_id, payload.title)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationRead.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> Response:
    repo = ConversationRepository(session)
    deleted = await repo.soft_delete(conversation_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> MessageList:
    conv_repo = ConversationRepository(session)
    conversation = await conv_repo.get(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    msg_repo = MessageRepository(session)
    items, total = await msg_repo.list_by_conversation(
        conversation_id, limit=limit, offset=offset
    )
    return MessageList(
        items=[MessageRead.model_validate(m) for m in items],
        total=total,
    )


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: MessageCreate,
    session: AsyncSession = Depends(db_session),
    user_id: str = Depends(current_user_id),
) -> StreamingResponse:
    conv_repo = ConversationRepository(session)
    conversation = await conv_repo.get(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    chat = ChatService()
    return StreamingResponse(
        chat.stream_chat(conversation_id, user_id, payload.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
