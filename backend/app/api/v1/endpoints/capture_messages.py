from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....core.time import utc_datetime
from ....db import get_session
from ....models import Message
from ....schemas import CaptureMessageItem, CaptureMessageListResponse

router = APIRouter(prefix="/capture/messages", tags=["capture"])


@router.get("", response_model=CaptureMessageListResponse)
def list_capture_messages(
    limit: int = Query(200, ge=1, le=500),
    after_id: int | None = Query(None, ge=0),
    source: str | None = Query(None, min_length=1, max_length=128),
    q: str | None = Query(None, min_length=1, max_length=256),
    db: Session = Depends(get_session),
) -> CaptureMessageListResponse:
    filters = []
    if after_id is not None:
        filters.append(Message.id > after_id)
    if source:
        filters.append(Message.source.ilike(f"%{source}%"))
    if q:
        filters.append(Message.text.ilike(f"%{q}%"))

    stmt = select(Message)
    for condition in filters:
        stmt = stmt.where(condition)

    if after_id is None:
        stmt = stmt.order_by(Message.id.desc()).limit(limit + 1)
        rows = list(db.scalars(stmt))
        has_more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
    else:
        stmt = stmt.order_by(Message.id.asc()).limit(limit + 1)
        rows = list(db.scalars(stmt))
        has_more = len(rows) > limit
        rows = rows[:limit]

    return CaptureMessageListResponse(
        data=[_message_item(message) for message in rows],
        latest_id=rows[-1].id if rows else after_id,
        has_more=has_more,
    )


def _message_item(message: Message) -> CaptureMessageItem:
    return CaptureMessageItem(
        id=message.id,
        session_id=message.session_id,
        source=message.source,
        text=message.text,
        captured_at=utc_datetime(message.captured_at),
        window_id=message.window_id,
    )
