from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ....db import get_session
from ....schemas import CaptureEventBatchIn, CaptureEventIn, CaptureIngestResponse
from ....services.capture import DEFAULT_MACOS_SESSION_ID, message_from_capture_event
from ....services.queue import queue
from ....services.window import WindowAssembler

router = APIRouter(prefix="/capture/events", tags=["capture"])


def get_assembler() -> WindowAssembler:
    from ....main import assembler

    return assembler


@router.post("", response_model=CaptureIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_capture_event(
    payload: CaptureEventIn,
    response: Response,
    db: Session = Depends(get_session),
    buffer: WindowAssembler = Depends(get_assembler),
) -> CaptureIngestResponse:
    return await _ingest_events([payload], response=response, db=db, buffer=buffer)


@router.post("/batch", response_model=CaptureIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_capture_event_batch(
    payload: CaptureEventBatchIn,
    response: Response,
    db: Session = Depends(get_session),
    buffer: WindowAssembler = Depends(get_assembler),
) -> CaptureIngestResponse:
    return await _ingest_events(payload.events, response=response, db=db, buffer=buffer)


async def _ingest_events(
    events: list[CaptureEventIn],
    *,
    response: Response,
    db: Session,
    buffer: WindowAssembler,
) -> CaptureIngestResponse:
    queued_window_ids: list[str] = []
    stored_messages = 0
    for event in sorted(events, key=lambda item: item.captured_at):
        message = message_from_capture_event(event, session_id=DEFAULT_MACOS_SESSION_ID)
        db.add(message)
        db.flush()
        stored_messages += 1
        queued_window_ids.extend(await buffer.add_message(db, message))
    db.commit()
    for window_id in queued_window_ids:
        queue.put_nowait(window_id)
    response.headers["X-Workday-Lens-Capture-Schema"] = "workday_lens_capture_event.v1"
    return CaptureIngestResponse(
        accepted_events=len(events),
        stored_messages=stored_messages,
        queued_windows=len(queued_window_ids),
    )
