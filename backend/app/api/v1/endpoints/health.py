from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ....db import get_session
from ....schemas import HealthResponse, MetricsResponse
from ....services.queue import queue, rollup_queue
from ....services.window import WindowReadService
from ....worker import processor

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


@router.get("/metrics", response_model=MetricsResponse)
def metrics(db: Session = Depends(get_session)) -> MetricsResponse:
    service = WindowReadService(db)
    pending = service.count_pending()
    violations_today = service.violations_today()
    last_run = processor.stats.last_run if processor else None
    return MetricsResponse(
        queue_depth=queue.qsize() + rollup_queue.qsize(),
        pending_windows=pending,
        violations_today=violations_today,
        last_worker_run=last_run,
    )
