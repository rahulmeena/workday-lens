from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ....core.config import settings
from ....core.time import local_day_bounds_utc
from ....db import SessionLocal, get_session
from ....models import WindowStatus
from ....schemas import (
    ActivityDashboardResponse,
    ActivityGanttResponse,
    ActivityLLMDebugResponse,
    ActivityReprocessRequest,
    ActivityReprocessResponse,
    ActivityRollupChildrenResponse,
    ActivityRollupListResponse,
    PaginatedResponse,
)
from ....services.gantt import GanttReadService, is_valid_gantt_mode
from ....services.llm import llm_service
from ....services.llm_debug import LLMDebugService
from ....services.local_qwen import LOCAL_QWEN_PROVIDER, local_qwen_service
from ....services.queue import queue, rollup_queue
from ....services.rollup import RollupBuildService, RollupReadService, is_valid_rollup_level
from ....services.window import WindowReadService, WindowReanalysisService

router = APIRouter(tags=["activity"])


@router.get("/employee/activity", response_model=PaginatedResponse)
def get_activity(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    status: WindowStatus | None = Query(None),
    db: Session = Depends(get_session),
) -> PaginatedResponse:
    service = WindowReadService(db)
    return service.employee_activity(limit=limit, cursor=cursor, status=status)


@router.get("/activity/dashboard", response_model=ActivityDashboardResponse)
def get_activity_dashboard(
    day: date | None = Query(None),
    db: Session = Depends(get_session),
) -> ActivityDashboardResponse:
    service = WindowReadService(db)
    return service.activity_dashboard(day=day)


@router.get("/activity/debug/llm", response_model=ActivityLLMDebugResponse)
def get_activity_llm_debug(
    level: str = Query(...),
    item_id: str = Query(..., alias="id"),
    db: Session = Depends(get_session),
) -> ActivityLLMDebugResponse:
    if level != "1m" and not is_valid_rollup_level(level):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported activity level.",
        )
    try:
        return LLMDebugService(db).card_trace(level, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/activity/gantt", response_model=ActivityGanttResponse)
def get_activity_gantt(
    background_tasks: BackgroundTasks,
    mode: str = Query(...),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_session),
) -> ActivityGanttResponse:
    if not is_valid_gantt_mode(mode):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported Gantt mode.",
        )
    if not from_time or not to_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide from/to range.",
        )
    if to_time <= from_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The Gantt range must end after it starts.",
        )
    service = GanttReadService(db, llm_service)
    cached = service.cached_activity_gantt(mode, from_time, to_time)
    if cached:
        background_tasks.add_task(refresh_activity_gantt_cache, mode, from_time, to_time)
        return cached
    if service.should_defer_uncached_gantt(mode, from_time, to_time):
        background_tasks.add_task(refresh_activity_gantt_cache, mode, from_time, to_time)
        return service.blank_activity_gantt(mode, from_time, to_time)
    return service.activity_gantt(mode, from_time, to_time)


def refresh_activity_gantt_cache(mode: str, from_time: datetime, to_time: datetime) -> None:
    session = SessionLocal()
    try:
        GanttReadService(session, llm_service).refresh_activity_gantt_cache(mode, from_time, to_time)
    finally:
        session.close()


@router.post("/activity/reprocess", response_model=ActivityReprocessResponse)
async def reprocess_activity(
    payload: ActivityReprocessRequest,
    db: Session = Depends(get_session),
) -> ActivityReprocessResponse:
    runtime = settings.runtime()
    if runtime.llm_provider == "openai" and not runtime.fake_llm_mode and not settings.openai_api_key_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configure an OpenAI API key or enable fake mode before reprocessing activity.",
        )
    if runtime.llm_provider == LOCAL_QWEN_PROVIDER and not runtime.fake_llm_mode and not local_qwen_service.status().get("ready"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prepare the local Qwen model before reprocessing activity.",
        )
    if payload.to_time <= payload.from_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The reprocess range must end after it starts.",
        )

    if payload.level == "1m":
        window_ids, invalidated_rollups = WindowReanalysisService(db).queue_range(
            payload.from_time,
            payload.to_time,
            mode=payload.mode,
        )
        db.commit()
        for window_id in window_ids:
            await queue.put(window_id)
        return ActivityReprocessResponse(
            level=payload.level,
            mode=payload.mode,
            queued_windows=len(window_ids),
            invalidated_rollups=invalidated_rollups,
        )

    if not is_valid_rollup_level(payload.level):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported reprocess level.",
        )

    builder = RollupBuildService(db)
    rollup_ids = builder.queue_range(payload.level, payload.from_time, payload.to_time, mode=payload.mode)
    invalidated_rollups = builder.invalidate_parent_rollups(payload.level, payload.from_time, payload.to_time) if rollup_ids else 0
    db.commit()
    for rollup_id in rollup_ids:
        await rollup_queue.put(rollup_id)
    return ActivityReprocessResponse(
        level=payload.level,
        mode=payload.mode,
        queued_rollups=len(rollup_ids),
        invalidated_rollups=invalidated_rollups,
    )


@router.get("/activity/rollups", response_model=ActivityRollupListResponse)
def get_activity_rollups(
    level: str = Query(...),
    day: date | None = Query(None),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_session),
) -> ActivityRollupListResponse:
    if not is_valid_rollup_level(level):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported rollup level.",
        )
    if day:
        start, end = local_day_bounds_utc(day)
    elif from_time and to_time:
        start, end = from_time, to_time
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either day or from/to range.",
        )
    service = RollupReadService(db)
    return ActivityRollupListResponse(level=level, data=service.list_rollups(level, start, end))


@router.get("/activity/rollups/{rollup_id}/children", response_model=ActivityRollupChildrenResponse)
def get_activity_rollup_children(
    rollup_id: str,
    db: Session = Depends(get_session),
) -> ActivityRollupChildrenResponse:
    service = RollupReadService(db)
    try:
        parent, children = service.children(rollup_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ActivityRollupChildrenResponse(parent=parent, children=children)
