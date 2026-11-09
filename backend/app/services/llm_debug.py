from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.time import local_timezone, utc_datetime
from ..models import ActivityRollup, LLMRun, Message, Window
from ..schemas import ActivityLLMDebugResponse
from .analysis import build_context_summary
from .llm import LLMRollupPayload, LLMWindowPayload, llm_service
from .rollup import RollupBuildService


class LLMDebugService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def card_trace(self, level: str, item_id: str) -> ActivityLLMDebugResponse:
        if level == "1m":
            return self._window_trace(item_id)
        return self._rollup_trace(level, item_id)

    def _window_trace(self, window_id: str) -> ActivityLLMDebugResponse:
        window = self.db.get(Window, window_id)
        if not window:
            raise ValueError("Window not found")
        latest_run = max(window.runs, key=lambda run: run.created_at) if window.runs else None
        transcript = self._window_transcript(window_id)
        payload = LLMWindowPayload(
            window_id=window.id,
            session_id=window.session_id,
            text=transcript,
            policy=None,
            examples=[],
            context_summaries=self._recent_window_summaries(window),
        )
        notes = [
            "Prompt text is reconstructed lazily from the current prompt builder and saved activity data.",
            "Stored response is the structured activity analysis saved after the LLM run.",
        ]
        if latest_run and self._window_would_chunk(payload):
            notes.append(
                "This window exceeds the current 1m token limit, so the reconstructed prompt shows ordered chunk prompts. "
                "Intermediate chunk responses are not stored; the response shown is the final merged card result."
            )
        return ActivityLLMDebugResponse(
            id=window.id,
            level="1m",
            captured_from=utc_datetime(window.started_at),
            captured_to=utc_datetime(window.ended_at),
            model_name=latest_run.model_name if latest_run else None,
            prompt_text=llm_service.debug_window_prompt_text(payload) if transcript else "",
            response_text=latest_run.summary_text if latest_run else "",
            prompt_tokens=latest_run.prompt_tokens if latest_run else 0,
            completion_tokens=latest_run.completion_tokens if latest_run else 0,
            total_tokens=latest_run.total_tokens if latest_run else 0,
            latency_ms=latest_run.latency_ms if latest_run else 0,
            notes=notes,
        )

    def _rollup_trace(self, level: str, rollup_id: str) -> ActivityLLMDebugResponse:
        rollup = self.db.get(ActivityRollup, rollup_id)
        if not rollup:
            raise ValueError("Rollup not found")
        if rollup.level != level:
            raise ValueError("Rollup level does not match the requested card")
        bundle = RollupBuildService(self.db).source_bundle(rollup.level, rollup.started_at, rollup.ended_at)
        notes = [
            "Prompt text is reconstructed lazily from the current prompt builder and saved activity data.",
            "Stored response is the structured rollup analysis saved after the LLM run.",
        ]
        prompt_text = ""
        if bundle and bundle.items:
            payload = LLMRollupPayload(
                rollup_id=rollup.id,
                level=rollup.level,
                started_at=utc_datetime(rollup.started_at).isoformat(),
                ended_at=utc_datetime(rollup.ended_at).isoformat(),
                source_items=bundle.items,
                raw_transcript=bundle.raw_transcript,
                context_summaries=bundle.context_summaries,
            )
            prompt_text = llm_service.debug_rollup_prompt_text(payload)
        else:
            notes.append("The rollup source bundle could not be reconstructed from currently available child data.")
        return ActivityLLMDebugResponse(
            id=rollup.id,
            level=rollup.level,
            captured_from=utc_datetime(rollup.started_at),
            captured_to=utc_datetime(rollup.ended_at),
            model_name=rollup.model_name or None,
            prompt_text=prompt_text,
            response_text=rollup.summary_text,
            prompt_tokens=rollup.prompt_tokens,
            completion_tokens=rollup.completion_tokens,
            total_tokens=rollup.total_tokens,
            latency_ms=rollup.latency_ms,
            notes=notes,
        )

    def _window_transcript(self, window_id: str) -> str:
        stmt = (
            select(Message.captured_at, Message.text)
            .where(Message.window_id == window_id)
            .order_by(Message.captured_at.asc())
        )
        rows = self.db.execute(stmt).all()
        return "\n".join(
            line
            for captured_at, text in rows
            for line in self._timestamped_transcript_lines(text, captured_at)
        )

    def _timestamped_transcript_lines(self, text: str, captured_at: datetime) -> list[str]:
        timestamp = self._local_transcript_timestamp(captured_at)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return [f"[{timestamp}] {line}" for line in lines]

    def _local_transcript_timestamp(self, captured_at: datetime) -> str:
        local_captured_at = utc_datetime(captured_at).astimezone(local_timezone())
        return f"{local_captured_at:%H:%M:%S}"

    def _recent_window_summaries(self, window: Window) -> list[str]:
        stmt = (
            select(LLMRun.summary_text)
            .join(Window, LLMRun.window_id == Window.id)
            .where(Window.session_id == window.session_id, LLMRun.window_id != window.id)
            .order_by(LLMRun.created_at.desc())
            .limit(settings.context_summary_limit)
        )
        return [build_context_summary(summary_text) for summary_text in self.db.scalars(stmt)]

    def _window_would_chunk(self, payload: LLMWindowPayload) -> bool:
        return len(payload.text.split()) > max(1, int(settings.window_token_limit * 0.8))
