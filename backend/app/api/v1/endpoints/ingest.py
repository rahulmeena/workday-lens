from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ....db import get_session
from ....models import Message
from ....schemas import MessageIn
from ....services.queue import queue
from ....services.window import WindowAssembler

router = APIRouter(prefix="/messages", tags=["messages"])


def get_assembler() -> WindowAssembler:
    from ....main import assembler

    return assembler


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def ingest_message(
    payload: MessageIn,
    db: Session = Depends(get_session),
    buffer: WindowAssembler = Depends(get_assembler),
) -> Response:
    captured_at = payload.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    message = Message(
        session_id=payload.session_id,
        source=payload.source,
        text=payload.text,
        captured_at=captured_at,
    )
    db.add(message)
    db.flush()
    window_ids = await buffer.add_message(db, message)
    db.commit()
    for window_id in window_ids:
        queue.put_nowait(window_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)
