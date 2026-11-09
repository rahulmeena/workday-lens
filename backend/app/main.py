from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from .core.config import settings
from .api.v1.router import router as api_router
from .db import SessionLocal, init_db
from .models import ActivityRollup, Window, WindowStatus
from .services.llm import llm_service
from .services.local_qwen import local_qwen_service
from .services.queue import queue, rollup_queue
from .services.rollup import RollupBuildService
from .services.window import WindowAssembler
from .worker import build_processor

app = FastAPI(title="Workday Lens API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.api_cors_origins) or ["*"],
    allow_origin_regex=settings.api_cors_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

assembler = WindowAssembler()
processor = build_processor(queue, rollup_queue, llm_service)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    await _enqueue_backlog()
    await processor.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    session = SessionLocal()
    try:
        queued = await assembler.flush_all(session)
        session.commit()
        # Any queues returned here remain queued for next startup cycle
    finally:
        session.close()
    local_qwen_service.stop()
    await processor.stop()


async def _enqueue_backlog() -> None:
    session = SessionLocal()
    try:
        # A startup means any previous in-flight worker was interrupted.
        session.execute(
            update(Window)
            .where(Window.status == WindowStatus.PROCESSING)
            .values(status=WindowStatus.QUEUED)
        )
        session.execute(
            update(ActivityRollup)
            .where(ActivityRollup.status == WindowStatus.PROCESSING)
            .values(status=WindowStatus.QUEUED)
        )
        stmt = select(Window.id).where(Window.status == WindowStatus.QUEUED).order_by(Window.started_at.asc())
        for window_id in session.scalars(stmt):
            queue.put_nowait(window_id)
        rollup_stmt = (
            select(ActivityRollup.id)
            .where(ActivityRollup.status == WindowStatus.QUEUED)
            .order_by(ActivityRollup.started_at.asc(), ActivityRollup.level.asc())
        )
        for rollup_id in session.scalars(rollup_stmt):
            rollup_queue.put_nowait(rollup_id)
        for rollup_id in RollupBuildService(session).queue_ready_parents_for_existing_rollups():
            rollup_queue.put_nowait(rollup_id)
        session.commit()
    finally:
        session.close()


app.include_router(api_router)
