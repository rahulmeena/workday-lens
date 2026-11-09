from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .core.config import settings
from .api.v1.router import router as api_router
from .db import SessionLocal, init_db
from .models import Window, WindowStatus
from .services.llm import llm_service
from .services.queue import queue
from .services.window import WindowAssembler
from .worker import build_processor

app = FastAPI(title="WFH Security API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.api_cors_origins) or ["*"],
    allow_origin_regex=settings.api_cors_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

assembler = WindowAssembler()
processor = build_processor(queue, llm_service)


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
    await processor.stop()


async def _enqueue_backlog() -> None:
    session = SessionLocal()
    try:
        stmt = select(Window.id).where(Window.status == WindowStatus.QUEUED)
        for window_id in session.scalars(stmt):
            queue.put_nowait(window_id)
    finally:
        session.close()


app.include_router(api_router)
