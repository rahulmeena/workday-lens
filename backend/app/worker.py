from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .core.config import settings
from .core.time import local_timezone, utc_datetime
from .db import SessionLocal
from .models import ActivityRollup, Event, EventType, LLMRun, Message, Policy, Window, WindowStatus
from .services.llm import LLMResult, LLMRollupPayload, LLMService, LLMServiceError, LLMTimeoutError, LLMWindowPayload
from .services.analysis import build_context_summary, serialize_activity_analysis
from .services.queue import WindowQueue
from .services.rollup import RollupBuildService, persist_rollup_result


def _positive_int_from_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


WINDOW_WORKER_CONCURRENCY_ENV = "WFHS_WINDOW_WORKER_CONCURRENCY"
ROLLUP_WORKER_CONCURRENCY = _positive_int_from_env("WFHS_ROLLUP_WORKER_CONCURRENCY", 1)


def _window_worker_concurrency() -> int:
    if os.getenv(WINDOW_WORKER_CONCURRENCY_ENV):
        return _positive_int_from_env(WINDOW_WORKER_CONCURRENCY_ENV, 4)
    if settings.runtime().llm_provider == "local_qwen35_4b":
        return 1
    return 4


@dataclass
class WorkerStats:
    processed: int = 0
    violations: int = 0
    pending: int = 0
    failures: int = 0
    last_run: Optional[datetime] = None


class WindowProcessor:
    def __init__(self, queue: WindowQueue, rollup_queue: WindowQueue, llm_service: LLMService) -> None:
        self.queue = queue
        self.rollup_queue = rollup_queue
        self.llm_service = llm_service
        self._stop_event = asyncio.Event()
        self._window_tasks: list[asyncio.Task[None]] = []
        self._rollup_tasks: list[asyncio.Task[None]] = []
        self.stats = WorkerStats()

    async def start(self) -> None:
        if not self._window_tasks:
            self._stop_event.clear()
            window_worker_count = _window_worker_concurrency()
            self._window_tasks = [
                asyncio.create_task(self._run_windows(index + 1))
                for index in range(window_worker_count)
            ]
            self._rollup_tasks = [
                asyncio.create_task(self._run_rollups(index + 1))
                for index in range(ROLLUP_WORKER_CONCURRENCY)
            ]
            print(
                f"[Worker] Started {len(self._window_tasks)} window worker(s) "
                f"and {len(self._rollup_tasks)} rollup worker(s)"
            )

    async def stop(self) -> None:
        if not self._window_tasks and not self._rollup_tasks:
            return
        self._stop_event.set()
        tasks = [*self._window_tasks, *self._rollup_tasks]
        if tasks:
            await asyncio.gather(*tasks)
        self._window_tasks = []
        self._rollup_tasks = []

    async def _run_windows(self, worker_index: int) -> None:
        while not self._stop_event.is_set():
            try:
                window_id = await asyncio.wait_for(self.queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue
            try:
                await self._process_window(window_id, worker_index=worker_index)
            finally:
                self.queue.task_done()

    async def _run_rollups(self, worker_index: int) -> None:
        while not self._stop_event.is_set():
            try:
                rollup_id = await asyncio.wait_for(self.rollup_queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue
            try:
                await self._process_rollup(rollup_id, worker_index=worker_index)
            finally:
                self.rollup_queue.task_done()

    async def _process_window(self, window_id: str, *, worker_index: int) -> None:
        print(f"[Worker:{worker_index}] Processing window {window_id}")
        session: Session = SessionLocal()
        try:
            window = self._claim_window(session, window_id)
            if not window:
                print(f"[Worker:{worker_index}] Window {window_id} not queued; skipping")
                return
            transcript = self._load_transcript(session, window_id)
            if not transcript:
                print(f"[Worker:{worker_index}] Window {window_id} has no transcript; marking processed")
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
                print(f"[Worker:{worker_index}] LLM timeout for window {window_id}; retry_count={window.retry_count}")
                return
            except LLMServiceError as exc:
                window.status = WindowStatus.PENDING_LLM
                window.retry_count += 1
                session.commit()
                self.stats.failures += 1
                self.stats.last_run = datetime.now(timezone.utc)
                print(f"[Worker:{worker_index}] LLM failure for window {window_id}; retry_count={window.retry_count}; error={exc}")
                return
            self._persist_run(session, window, result)
            session.commit()
            rollup_ids = RollupBuildService(session).queue_ready_for_window(window)
            session.commit()
            for rollup_id in rollup_ids:
                self.rollup_queue.put_nowait(rollup_id)
            print(f"[Worker:{worker_index}] Window {window_id} processed; verdict={result.verdict}; tokens={result.prompt_tokens + result.completion_tokens}")
            self.stats.processed += 1
            if result.verdict == WindowStatus.VIOLATION:
                self.stats.violations += 1
            self.stats.last_run = datetime.now(timezone.utc)
        finally:
            session.close()

    def _claim_window(self, session: Session, window_id: str) -> Window | None:
        result = session.execute(
            update(Window)
            .where(Window.id == window_id, Window.status == WindowStatus.QUEUED)
            .values(status=WindowStatus.PROCESSING)
        )
        session.commit()  # release SQLite write lock before awaiting LLM
        if int(result.rowcount or 0) != 1:
            session.rollback()
            return None
        window = session.get(Window, window_id)
        if window:
            session.refresh(window)
        return window

    async def _process_rollup(self, rollup_id: str, *, worker_index: int) -> None:
        print(f"[RollupWorker:{worker_index}] Processing rollup {rollup_id}")
        session: Session = SessionLocal()
        try:
            rollup = self._claim_rollup(session, rollup_id)
            if not rollup:
                print(f"[RollupWorker:{worker_index}] Rollup {rollup_id} not queued; skipping")
                return
            builder = RollupBuildService(session)
            bundle = builder.source_bundle(rollup.level, rollup.started_at, rollup.ended_at)
            if not bundle or not bundle.items:
                rollup.status = WindowStatus.PENDING_LLM
                session.commit()
                print(f"[RollupWorker:{worker_index}] Rollup {rollup_id} no longer has ready sources; parking")
                return
            rollup.source_count = len(bundle.items)
            payload = LLMRollupPayload(
                rollup_id=rollup.id,
                level=rollup.level,
                started_at=utc_datetime(rollup.started_at).isoformat(),
                ended_at=utc_datetime(rollup.ended_at).isoformat(),
                source_items=bundle.items,
                raw_transcript=bundle.raw_transcript,
                context_summaries=bundle.context_summaries,
            )
            try:
                result = await self.llm_service.evaluate_rollup(payload)
            except LLMTimeoutError:
                rollup.status = WindowStatus.PENDING_LLM
                rollup.retry_count += 1
                session.commit()
                self.stats.pending += 1
                self.stats.last_run = datetime.now(timezone.utc)
                print(f"[RollupWorker:{worker_index}] LLM timeout for rollup {rollup_id}; retry_count={rollup.retry_count}")
                return
            except LLMServiceError as exc:
                rollup.status = WindowStatus.PENDING_LLM
                rollup.retry_count += 1
                session.commit()
                self.stats.failures += 1
                self.stats.last_run = datetime.now(timezone.utc)
                print(f"[RollupWorker:{worker_index}] LLM failure for rollup {rollup_id}; retry_count={rollup.retry_count}; error={exc}")
                return
            persist_rollup_result(rollup, result)
            session.commit()
            parent_ids = RollupBuildService(session).queue_ready_for_rollup(rollup)
            session.commit()
            for parent_id in parent_ids:
                self.rollup_queue.put_nowait(parent_id)
            print(f"[RollupWorker:{worker_index}] Rollup {rollup_id} processed; level={rollup.level}; sources={rollup.source_count}")
            self.stats.processed += 1
            self.stats.last_run = datetime.now(timezone.utc)
        finally:
            session.close()

    def _claim_rollup(self, session: Session, rollup_id: str) -> ActivityRollup | None:
        result = session.execute(
            update(ActivityRollup)
            .where(ActivityRollup.id == rollup_id, ActivityRollup.status == WindowStatus.QUEUED)
            .values(status=WindowStatus.PROCESSING)
        )
        session.commit()
        if int(result.rowcount or 0) != 1:
            session.rollback()
            return None
        rollup = session.get(ActivityRollup, rollup_id)
        if rollup:
            session.refresh(rollup)
        return rollup

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
        return f"{local_captured_at:%H:%M:%S}"

    def _recent_summaries(self, session: Session, window: Window) -> list[str]:
        stmt = (
            select(LLMRun.summary_text)
            .join(Window, LLMRun.window_id == Window.id)
            .where(
                Window.session_id == window.session_id,
                LLMRun.window_id != window.id,
                Window.started_at < window.started_at,
            )
            .order_by(Window.started_at.desc(), LLMRun.created_at.desc())
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


def build_processor(queue: WindowQueue, rollup_queue: WindowQueue, llm_service: LLMService) -> WindowProcessor:
    global processor
    processor = WindowProcessor(queue, rollup_queue, llm_service)
    return processor
