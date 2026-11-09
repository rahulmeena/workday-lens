from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core.config import settings
from .core.time import local_timezone, utc_datetime
from .db import SessionLocal
from .models import Event, EventType, LLMRun, Message, Policy, Window, WindowStatus
from .services.llm import LLMResult, LLMService, LLMServiceError, LLMTimeoutError, LLMWindowPayload
from .services.analysis import build_context_summary, serialize_activity_analysis
from .services.queue import WindowQueue


@dataclass
class WorkerStats:
    processed: int = 0
    violations: int = 0
    pending: int = 0
    failures: int = 0
    last_run: Optional[datetime] = None


class WindowProcessor:
    def __init__(self, queue: WindowQueue, llm_service: LLMService) -> None:
        self.queue = queue
        self.llm_service = llm_service
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task[None]] = None
        self.stats = WorkerStats()

    async def start(self) -> None:
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                window_id = await asyncio.wait_for(self.queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue
            try:
                await self._process_window(window_id)
            finally:
                self.queue.task_done()

    async def _process_window(self, window_id: str) -> None:
        print(f"[Worker] Processing window {window_id}")
        session: Session = SessionLocal()
        try:
            window = session.get(Window, window_id)
            if not window:
                print(f"[Worker] Window {window_id} not found; skipping")
                return
            window.status = WindowStatus.PROCESSING
            session.commit()  # release SQLite write lock before awaiting LLM
            session.refresh(window)
            transcript = self._load_transcript(session, window_id)
            if not transcript:
                print(f"[Worker] Window {window_id} has no transcript; marking processed")
                window.status = WindowStatus.PROCESSED
                session.commit()
                self.stats.processed += 1
                self.stats.last_run = datetime.now(timezone.utc)
                return
            policies = self._active_policies(session)
            context = self._recent_summaries(session, window)
            payload = LLMWindowPayload(
                window_id=window.id,
                session_id=window.session_id,
                text=transcript,
                policy=None,
                examples=[],
                context_summaries=context,
            )
            try:
                result = await self.llm_service.evaluate_window(payload)
            except LLMTimeoutError:
                window.status = WindowStatus.PENDING_LLM
                window.retry_count += 1
                session.commit()
                self.stats.pending += 1
                self.stats.last_run = datetime.now(timezone.utc)
                print(f"[Worker] LLM timeout for window {window_id}; retry_count={window.retry_count}")
                return
            except LLMServiceError as exc:
                window.status = WindowStatus.PENDING_LLM
                window.retry_count += 1
                session.commit()
                self.stats.failures += 1
                self.stats.last_run = datetime.now(timezone.utc)
                print(f"[Worker] LLM failure for window {window_id}; retry_count={window.retry_count}; error={exc}")
                return
            self._persist_run(session, window, result)
            session.commit()
            print(f"[Worker] Window {window_id} processed; verdict={result.verdict}; tokens={result.prompt_tokens + result.completion_tokens}")
            self.stats.processed += 1
            if result.verdict == WindowStatus.VIOLATION:
                self.stats.violations += 1
            self.stats.last_run = datetime.now(timezone.utc)
        finally:
            session.close()

    def _persist_run(self, session: Session, window: Window, result: LLMResult) -> None:
        run = LLMRun(
            window_id=window.id,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
            latency_ms=result.latency_ms,
            verdict=result.verdict,
            confidence=result.confidence,
            summary_text=serialize_activity_analysis(result.analysis_payload),
            model_name=result.model_name,
        )
        session.add(run)
        existing_violation_events = [event for event in window.events if event.type == EventType.VIOLATION]
        if result.verdict == WindowStatus.VIOLATION:
            window.status = WindowStatus.VIOLATION
            if existing_violation_events:
                for event in existing_violation_events:
                    event.title = "Policy violation detected"
                    event.detail = result.summary
            else:
                event = Event(
                    window_id=window.id,
                    type=EventType.VIOLATION,
                    title="Policy violation detected",
                    detail=result.summary,
                )
                session.add(event)
        else:
            window.status = WindowStatus.PROCESSED
            for event in existing_violation_events:
                session.delete(event)

    def _load_transcript(self, session: Session, window_id: str) -> str:
        stmt = (
            select(Message.captured_at, Message.text)
            .where(Message.window_id == window_id)
            .order_by(Message.captured_at.asc())
        )
        rows = session.execute(stmt).all()
        return "\n".join(
            line
            for captured_at, text in rows
            for line in self._timestamped_transcript_lines(text, captured_at)
        )

    def _timestamped_transcript_lines(self, text: str, captured_at: datetime) -> list[str]:
        timestamp = self._local_transcript_timestamp(captured_at)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        return [f"[{timestamp}] {line}" for line in lines]

    def _local_transcript_timestamp(self, captured_at: datetime) -> str:
        local_captured_at = utc_datetime(captured_at).astimezone(local_timezone())
        return f"{local_captured_at:%Y-%m-%d %H:%M:%S}"

    def _recent_summaries(self, session: Session, window: Window) -> list[str]:
        stmt = (
            select(LLMRun.summary_text)
            .join(Window, LLMRun.window_id == Window.id)
            .where(Window.session_id == window.session_id, LLMRun.window_id != window.id)
            .order_by(LLMRun.created_at.desc())
            .limit(settings.context_summary_limit)
        )
        return [build_context_summary(summary_text) for summary_text in session.scalars(stmt)]

    def _active_policies(self, session: Session) -> list[Policy]:
        stmt = (
            select(Policy)
            .where(Policy.active.is_(True))
            .order_by(Policy.created_at.asc())
        )
        return list(session.scalars(stmt))

    def _combine_policy_text(self, policies: list[Policy]) -> str | None:
        lines: list[str] = []
        for idx, policy in enumerate(policies, start=1):
            text = (policy.text or "").strip()
            if text:
                lines.append(f"{idx}. {text}")
        return "\n".join(lines) if lines else None

    def _collect_policy_examples(self, policies: list[Policy]) -> list[str]:
        examples: list[str] = []
        for idx, policy in enumerate(policies, start=1):
            for example in self._policy_examples(policy):
                examples.append(f"Rule {idx}: {example}")
        return examples

    def _policy_examples(self, policy: Policy) -> list[str]:
        if not policy.examples_json:
            return []
        return [line for line in policy.examples_json.splitlines() if line]


processor: WindowProcessor | None = None


def build_processor(queue: WindowQueue, llm_service: LLMService) -> WindowProcessor:
    global processor
    processor = WindowProcessor(queue, llm_service)
    return processor
