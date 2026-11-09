from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.time import db_datetime, local_timezone, utc_datetime
from ..models import ActivityRollup, LLMRun, Window, WindowStatus
from ..schemas import ActivityRollupItem, ActivitySegment
from .analysis import (
    activity_type_label,
    build_context_summary,
    focus_state_label,
    parse_activity_analysis,
    serialize_activity_analysis,
)
from .llm import llm_service


ROLLUP_LEVELS = ("5m", "15m", "1h", "4h", "1d", "1w")
ROLLUP_SECONDS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
}
ROLLUP_CHILD_LEVEL = {
    "15m": "5m",
    "1h": "15m",
    "4h": "1h",
    "1d": "4h",
    "1w": "1d",
}
ROLLUP_PARENT_LEVEL = {child: parent for parent, child in ROLLUP_CHILD_LEVEL.items()}
COMPLETE_STATUSES = {WindowStatus.PROCESSED, WindowStatus.VIOLATION}
INCOMPLETE_STATUSES = {WindowStatus.QUEUED, WindowStatus.PROCESSING, WindowStatus.PENDING_LLM}
STALE_PROCESSING_AFTER = timedelta(minutes=15)
RAW_TRANSCRIPT_CHARS_PER_LIMIT_UNIT = 8


@dataclass
class RollupSourceBundle:
    items: list[dict[str, Any]]
    raw_transcript: str = ""
    context_summaries: list[str] = field(default_factory=list)
    source_updated_at: datetime | None = None


def is_valid_rollup_level(level: str) -> bool:
    return level in ROLLUP_LEVELS


def bucket_bounds_for(value: datetime, level: str) -> tuple[datetime, datetime]:
    local_value = utc_datetime(value).astimezone(local_timezone())
    if level == "5m":
        start_local = local_value.replace(minute=(local_value.minute // 5) * 5, second=0, microsecond=0)
    elif level == "15m":
        start_local = local_value.replace(minute=(local_value.minute // 15) * 15, second=0, microsecond=0)
    elif level == "1h":
        start_local = local_value.replace(minute=0, second=0, microsecond=0)
    elif level == "4h":
        start_local = local_value.replace(hour=(local_value.hour // 4) * 4, minute=0, second=0, microsecond=0)
    elif level == "1d":
        start_local = local_value.replace(hour=0, minute=0, second=0, microsecond=0)
    elif level == "1w":
        day_start = local_value.replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = day_start - timedelta(days=day_start.weekday())
    else:
        raise ValueError(f"Unsupported rollup level: {level}")
    end_local = start_local + timedelta(seconds=ROLLUP_SECONDS[level])
    return utc_datetime(start_local), utc_datetime(end_local)


def previous_bucket_bounds(start: datetime, level: str) -> tuple[datetime, datetime]:
    previous_start = utc_datetime(start) - timedelta(seconds=ROLLUP_SECONDS[level])
    return previous_start, utc_datetime(start)


def rollup_item_from_model(rollup: ActivityRollup) -> ActivityRollupItem:
    analysis = parse_activity_analysis(rollup.summary_text)
    started_at = utc_datetime(rollup.started_at)
    ended_at = utc_datetime(rollup.ended_at)
    seconds = max(0, int((ended_at - started_at).total_seconds()))
    return ActivityRollupItem(
        id=rollup.id,
        level=rollup.level,
        captured_from=started_at,
        captured_to=ended_at,
        duration_minutes=max(1, (seconds + 59) // 60),
        status=rollup.status,
        headline=str(analysis["headline"]),
        summary=str(analysis["summary"]),
        dominant_goal=str(analysis.get("dominant_goal") or analysis["goal"]),
        project=str(analysis["project"]),
        activity_type=str(analysis["activity_type"]),
        activity_label=activity_type_label(str(analysis["activity_type"])),
        focus_state=str(analysis["focus_state"]),
        focus_label=focus_state_label(str(analysis["focus_state"])),
        secondary_goals=list(analysis.get("secondary_goals") or []),
        important_intervals=list(analysis.get("important_intervals") or []),
        ignored_noise=str(analysis.get("ignored_noise") or "") or None,
        confidence=float(analysis["confidence"]),
        source_count=rollup.source_count,
        model_name=rollup.model_name or None,
        prompt_tokens=rollup.prompt_tokens,
        completion_tokens=rollup.completion_tokens,
        total_tokens=rollup.total_tokens,
        latency_ms=rollup.latency_ms,
    )


class RollupBuildService:
    def __init__(self, db: Session):
        self.db = db

    def queue_ready_for_window(self, window: Window) -> list[str]:
        queued: list[str] = []
        for start, end in self._candidate_bounds(window.started_at, "5m"):
            rollup_id = self.queue_ready_bucket("5m", start, end)
            if rollup_id:
                queued.append(rollup_id)
        return queued

    def queue_ready_for_rollup(self, rollup: ActivityRollup) -> list[str]:
        parent_level = ROLLUP_PARENT_LEVEL.get(rollup.level)
        if not parent_level:
            return []
        queued: list[str] = []
        for start, end in self._candidate_bounds(rollup.started_at, parent_level):
            rollup_id = self.queue_ready_bucket(
                parent_level,
                start,
                end,
                force=self._is_current_partial_bucket(parent_level, start, end),
            )
            if rollup_id:
                queued.append(rollup_id)
        return queued

    def queue_ready_bucket(self, level: str, start: datetime, end: datetime, *, force: bool = False) -> str | None:
        if not settings.rollup_enabled(level):
            return None
        if utc_datetime(end) > datetime.now(timezone.utc) and not self._allows_partial_current_bucket(level, start):
            return None

        bundle = self.source_bundle(level, start, end)
        if not bundle or not bundle.items:
            return None

        source_count = len(bundle.items)
        rollup = self._find_rollup(level, start, end)
        if rollup:
            if rollup.status == WindowStatus.PROCESSING and not self._is_stale_processing(rollup):
                return None
            if rollup.status == WindowStatus.QUEUED:
                return None
            if not force and rollup.status in COMPLETE_STATUSES and self._rollup_matches_bundle(
                rollup,
                bundle,
                source_count,
            ):
                return None
            rollup.status = WindowStatus.QUEUED
            rollup.source_count = source_count
            rollup.retry_count = 0
            self.db.flush()
            return rollup.id

        rollup = ActivityRollup(
            level=level,
            started_at=db_datetime(start),
            ended_at=db_datetime(end),
            status=WindowStatus.QUEUED,
            source_count=source_count,
        )
        self.db.add(rollup)
        self.db.flush()
        return rollup.id

    def source_bundle(self, level: str, start: datetime, end: datetime) -> RollupSourceBundle | None:
        if level == "5m":
            bundle = self._window_source_bundle(start, end)
        else:
            child_level = ROLLUP_CHILD_LEVEL[level]
            if not settings.rollup_enabled(child_level):
                return None
            bundle = self._rollup_source_bundle(level, child_level, start, end)
        return self._with_context_summaries(bundle, level, start)

    def queue_ready_parents_for_existing_rollups(self) -> list[str]:
        queued: list[str] = []
        stmt = (
            select(ActivityRollup)
            .where(ActivityRollup.status.in_(COMPLETE_STATUSES))
            .order_by(ActivityRollup.started_at.asc())
        )
        for rollup in self.db.scalars(stmt):
            queued.extend(self.queue_ready_for_rollup(rollup))
        return queued

    def queue_range(self, level: str, start: datetime, end: datetime, *, mode: str = "all") -> list[str]:
        queued: list[str] = []
        seen: set[str] = set()

        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level == level,
                ActivityRollup.started_at >= db_datetime(start),
                ActivityRollup.started_at < db_datetime(end),
            )
            .order_by(ActivityRollup.started_at.asc())
        )
        if mode == "pending":
            stmt = stmt.where(ActivityRollup.status == WindowStatus.PENDING_LLM)

        for rollup in self.db.scalars(stmt):
            if rollup.status == WindowStatus.PROCESSING and not self._is_stale_processing(rollup):
                continue
            rollup.status = WindowStatus.QUEUED
            rollup.retry_count = 0
            self.db.flush()
            queued.append(rollup.id)
            seen.add(rollup.id)

        if mode == "all":
            for bucket_start, bucket_end in self._bucket_ranges_in_range(level, start, end):
                rollup_id = self.queue_ready_bucket(level, bucket_start, bucket_end)
                if rollup_id and rollup_id not in seen:
                    queued.append(rollup_id)
                    seen.add(rollup_id)

        return queued

    def _is_stale_processing(self, rollup: ActivityRollup) -> bool:
        updated_at = rollup.updated_at or rollup.created_at or rollup.started_at
        return utc_datetime(updated_at) <= datetime.now(timezone.utc) - STALE_PROCESSING_AFTER

    def invalidate_parent_rollups(self, level: str, start: datetime, end: datetime) -> int:
        parent_levels: list[str] = []
        parent_level = ROLLUP_PARENT_LEVEL.get(level)
        while parent_level:
            parent_levels.append(parent_level)
            parent_level = ROLLUP_PARENT_LEVEL.get(parent_level)
        if not parent_levels:
            return 0
        result = self.db.execute(
            delete(ActivityRollup).where(
                ActivityRollup.level.in_(parent_levels),
                ActivityRollup.started_at < db_datetime(end),
                ActivityRollup.ended_at > db_datetime(start),
            )
        )
        self.db.flush()
        return int(result.rowcount or 0)

    def _window_source_bundle(self, start: datetime, end: datetime) -> RollupSourceBundle | None:
        if self._has_incomplete_windows(start, end):
            return None
        windows = self._windows_with_summaries(start, end)
        if not windows:
            return None
        items = []
        for window, run in windows:
            analysis = parse_activity_analysis(run.summary_text, fallback_excerpt=self._window_excerpt(window))
            items.append(
                {
                    "id": window.id,
                    "time_range": self._format_range(window.started_at, window.ended_at),
                    "headline": analysis["headline"],
                    "summary": analysis["summary"],
                    "dominant_goal": analysis.get("dominant_goal") or analysis["goal"],
                    "project": analysis["project"],
                    "activity_type": analysis["activity_type"],
                    "focus_state": analysis["focus_state"],
                    "confidence": analysis["confidence"],
                }
            )
        source_updated_at = max(
            (run.created_at for _window, run in windows if run.created_at),
            default=None,
        )
        return RollupSourceBundle(
            items=items,
            raw_transcript=self._raw_transcript_from_windows(windows, settings.rollup_5m_raw_token_limit),
            source_updated_at=source_updated_at,
        )

    def _rollup_source_bundle(self, level: str, child_level: str, start: datetime, end: datetime) -> RollupSourceBundle | None:
        if level in {"1d", "1w"}:
            child_rollups = self._completed_child_rollups(child_level, start, end)
            if not child_rollups:
                return None
            return self._source_bundle_from_rollups(child_rollups)

        required_ranges = self._active_child_ranges(child_level, start, end, parent_level=level)
        if not required_ranges:
            return None
        child_rollups = []
        for child_start, child_end in required_ranges:
            rollup = self._find_rollup(child_level, child_start, child_end)
            if not rollup or rollup.status not in COMPLETE_STATUSES:
                return None
            child_rollups.append(rollup)
        return self._source_bundle_from_rollups(child_rollups)

    def _source_bundle_from_rollups(self, child_rollups: list[ActivityRollup]) -> RollupSourceBundle:
        items = []
        for rollup in child_rollups:
            analysis = parse_activity_analysis(rollup.summary_text)
            items.append(
                {
                    "id": rollup.id,
                    "time_range": self._format_range(rollup.started_at, rollup.ended_at),
                    "headline": analysis["headline"],
                    "summary": analysis["summary"],
                    "dominant_goal": analysis.get("dominant_goal") or analysis["goal"],
                    "project": analysis["project"],
                    "activity_type": analysis["activity_type"],
                    "focus_state": analysis["focus_state"],
                    "confidence": analysis["confidence"],
                    "source_count": rollup.source_count,
                }
            )
        source_updated_at = max(
            (
                rollup.updated_at or rollup.created_at
                for rollup in child_rollups
                if rollup.updated_at or rollup.created_at
            ),
            default=None,
        )
        return RollupSourceBundle(items=items, source_updated_at=source_updated_at)

    def _with_context_summaries(
        self,
        bundle: RollupSourceBundle | None,
        level: str,
        start: datetime,
    ) -> RollupSourceBundle | None:
        if bundle is None:
            return None
        bundle.context_summaries = self._recent_rollup_context_summaries(level, start)
        return bundle

    def _recent_rollup_context_summaries(self, level: str, start: datetime) -> list[str]:
        limit = settings.rollup_context_summary_limit(level)
        if limit <= 0:
            return []
        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level == level,
                ActivityRollup.ended_at <= db_datetime(start),
                ActivityRollup.status.in_(COMPLETE_STATUSES),
            )
            .order_by(ActivityRollup.ended_at.desc())
            .limit(limit)
        )
        summaries: list[str] = []
        for rollup in self.db.scalars(stmt):
            time_range = self._format_range(rollup.started_at, rollup.ended_at)
            summaries.append(f"{time_range} | {build_context_summary(rollup.summary_text)}")
        return summaries

    def _completed_child_rollups(self, child_level: str, start: datetime, end: datetime) -> list[ActivityRollup]:
        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level == child_level,
                ActivityRollup.started_at >= db_datetime(start),
                ActivityRollup.started_at < db_datetime(end),
                ActivityRollup.status.in_(COMPLETE_STATUSES),
            )
            .order_by(ActivityRollup.started_at.asc())
        )
        return list(self.db.scalars(stmt))

    def _allows_partial_current_bucket(self, level: str, start: datetime) -> bool:
        return level in {"1d", "1w"} and utc_datetime(start) <= datetime.now(timezone.utc)

    def _is_current_partial_bucket(self, level: str, start: datetime, end: datetime) -> bool:
        now = datetime.now(timezone.utc)
        return self._allows_partial_current_bucket(level, start) and utc_datetime(start) <= now < utc_datetime(end)

    def _rollup_matches_bundle(
        self,
        rollup: ActivityRollup,
        bundle: RollupSourceBundle,
        source_count: int,
    ) -> bool:
        if rollup.source_count != source_count:
            return False
        if not bundle.source_updated_at:
            return True
        rollup_updated_at = rollup.updated_at or rollup.created_at or rollup.started_at
        return utc_datetime(bundle.source_updated_at) <= utc_datetime(rollup_updated_at)

    def _bucket_ranges_in_range(self, level: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        ranges: list[tuple[datetime, datetime]] = []
        bucket_start, bucket_end = bucket_bounds_for(start, level)
        final_end = utc_datetime(end)
        while bucket_end <= utc_datetime(start):
            bucket_start = bucket_end
            bucket_end = bucket_start + timedelta(seconds=ROLLUP_SECONDS[level])
        while bucket_start < final_end:
            ranges.append((bucket_start, bucket_end))
            bucket_start = bucket_end
            bucket_end = bucket_start + timedelta(seconds=ROLLUP_SECONDS[level])
        return ranges

    def _active_child_ranges(
        self,
        child_level: str,
        start: datetime,
        end: datetime,
        *,
        parent_level: str | None = None,
    ) -> list[tuple[datetime, datetime]]:
        ranges: list[tuple[datetime, datetime]] = []
        cursor = utc_datetime(start)
        final_end = utc_datetime(end)
        child_delta = timedelta(seconds=ROLLUP_SECONDS[child_level])
        parent_is_partial = bool(parent_level and self._is_current_partial_bucket(parent_level, start, end))
        now = datetime.now(timezone.utc)
        while cursor < final_end:
            child_end = min(cursor + child_delta, final_end)
            if (
                parent_is_partial
                and child_end > now
                and not self._is_current_partial_bucket(child_level, cursor, child_end)
            ):
                cursor = child_end
                continue
            if self._has_completed_window_evidence(cursor, child_end):
                ranges.append((cursor, child_end))
            cursor = child_end
        return ranges

    def _candidate_bounds(self, anchor: datetime, level: str) -> list[tuple[datetime, datetime]]:
        current = bucket_bounds_for(anchor, level)
        previous = previous_bucket_bounds(current[0], level)
        return [previous, current]

    def _find_rollup(self, level: str, start: datetime, end: datetime) -> ActivityRollup | None:
        stmt = select(ActivityRollup).where(
            ActivityRollup.level == level,
            ActivityRollup.started_at == db_datetime(start),
            ActivityRollup.ended_at == db_datetime(end),
        )
        return self.db.scalars(stmt).first()

    def _has_completed_window_evidence(self, start: datetime, end: datetime) -> bool:
        stmt = (
            select(func.count())
            .select_from(LLMRun)
            .join(Window, LLMRun.window_id == Window.id)
            .where(
                Window.started_at >= db_datetime(start),
                Window.started_at < db_datetime(end),
                Window.status.in_(COMPLETE_STATUSES),
            )
        )
        return bool(self.db.scalar(stmt) or 0)

    def _has_incomplete_windows(self, start: datetime, end: datetime) -> bool:
        stmt = (
            select(func.count())
            .select_from(Window)
            .where(
                Window.started_at >= db_datetime(start),
                Window.started_at < db_datetime(end),
                Window.status.in_(INCOMPLETE_STATUSES),
            )
        )
        return bool(self.db.scalar(stmt) or 0)

    def _windows_with_summaries(self, start: datetime, end: datetime) -> list[tuple[Window, LLMRun]]:
        stmt = (
            select(Window)
            .where(
                Window.started_at >= db_datetime(start),
                Window.started_at < db_datetime(end),
                Window.status.in_(COMPLETE_STATUSES),
            )
            .order_by(Window.started_at.asc())
        )
        results: list[tuple[Window, LLMRun]] = []
        for window in self.db.scalars(stmt):
            latest_run = max(window.runs, key=lambda run: run.created_at) if window.runs else None
            if latest_run:
                results.append((window, latest_run))
        return results

    def _raw_transcript_from_windows(self, windows: list[tuple[Window, LLMRun]], word_limit: int) -> str:
        if word_limit <= 0:
            return ""
        blocks: list[str] = []
        used_words = 0
        omitted = 0
        ordered_windows = sorted(windows, key=lambda item: item[0].started_at)
        for index, (window, _run) in enumerate(ordered_windows):
            block = self._raw_transcript_block(window)
            if not block:
                continue
            block_words = self._word_count(block)
            if blocks and used_words + block_words > word_limit:
                omitted = len(ordered_windows) - index
                break
            if not blocks and block_words > word_limit:
                blocks.append(self._clip_words(block, word_limit))
                omitted = len(ordered_windows) - index - 1
                used_words = word_limit
                break
            blocks.append(block)
            used_words += block_words
        if omitted > 0:
            blocks.append(
                f"[{omitted} later 1m raw transcript block(s) omitted due to the 5m raw transcript token limit; use their 1m summaries above.]"
            )
        return "\n\n".join(blocks)

    def _raw_transcript_block(self, window: Window) -> str:
        lines = [
            line
            for message in sorted(window.messages, key=lambda item: item.captured_at)
            for line in self._timestamped_transcript_lines(message.text, message.captured_at)
        ]
        if not lines:
            return ""
        compacted = llm_service.compact_transcript_for_prompt("\n".join(lines))
        return "\n".join(
            [
                f"1m raw transcript {self._format_range(window.started_at, window.ended_at)}:",
                compacted,
            ]
        )

    def _word_count(self, text: str) -> int:
        return max(len(text.split()), len(text) // RAW_TRANSCRIPT_CHARS_PER_LIMIT_UNIT)

    def _clip_words(self, text: str, word_limit: int) -> str:
        char_limit = max(1000, word_limit * RAW_TRANSCRIPT_CHARS_PER_LIMIT_UNIT)
        words = text.split()
        if len(words) <= word_limit and len(text) <= char_limit:
            return text
        if len(words) > word_limit:
            clipped = " ".join(words[:word_limit])
        else:
            clipped = text
        if len(clipped) > char_limit:
            clipped = clipped[:char_limit].rstrip()
        return clipped + "\n[raw transcript clipped at the 5m raw transcript token limit]"

    def _window_excerpt(self, window: Window) -> str:
        ordered = sorted(window.messages, key=lambda msg: msg.captured_at)
        return "\n".join(msg.text for msg in ordered[:5])

    def _timestamped_transcript_lines(self, text: str, captured_at: datetime) -> list[str]:
        timestamp = self._local_transcript_timestamp(captured_at)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return [f"[{timestamp}] {line}" for line in lines]

    def _local_transcript_timestamp(self, captured_at: datetime) -> str:
        local_captured_at = utc_datetime(captured_at).astimezone(local_timezone())
        return f"{local_captured_at:%H:%M:%S}"

    def _format_range(self, start: datetime, end: datetime) -> str:
        local_start = utc_datetime(start).astimezone(local_timezone())
        local_end = utc_datetime(end).astimezone(local_timezone())
        if local_start.date() != local_end.date():
            return f"{local_start:%Y-%m-%d %H:%M}-{local_end:%Y-%m-%d %H:%M}"
        return f"{local_start:%Y-%m-%d %H:%M}-{local_end:%H:%M}"


class RollupReadService:
    def __init__(self, db: Session):
        self.db = db

    def list_rollups(self, level: str, start: datetime, end: datetime) -> list[ActivityRollupItem]:
        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level == level,
                ActivityRollup.started_at >= db_datetime(start),
                ActivityRollup.started_at < db_datetime(end),
            )
            .order_by(ActivityRollup.started_at.asc())
        )
        return [rollup_item_from_model(rollup) for rollup in self.db.scalars(stmt)]

    def children(self, rollup_id: str) -> tuple[ActivityRollupItem, list[ActivityRollupItem | ActivitySegment]]:
        rollup = self.db.get(ActivityRollup, rollup_id)
        if not rollup:
            raise ValueError("Rollup not found")
        parent = rollup_item_from_model(rollup)
        if rollup.level == "5m":
            return parent, self._window_children(rollup)
        child_level = ROLLUP_CHILD_LEVEL[rollup.level]
        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level == child_level,
                ActivityRollup.started_at >= rollup.started_at,
                ActivityRollup.started_at < rollup.ended_at,
            )
            .order_by(ActivityRollup.started_at.asc())
        )
        return parent, [rollup_item_from_model(child) for child in self.db.scalars(stmt)]

    def _window_children(self, rollup: ActivityRollup) -> list[ActivitySegment]:
        stmt = (
            select(Window)
            .where(
                Window.started_at >= rollup.started_at,
                Window.started_at < rollup.ended_at,
            )
            .order_by(Window.started_at.asc())
        )
        return [self._segment_from_window(window) for window in self.db.scalars(stmt)]

    def _segment_from_window(self, window: Window) -> ActivitySegment:
        latest_run = max(window.runs, key=lambda run: run.created_at) if window.runs else None
        excerpt = "\n".join(msg.text for msg in sorted(window.messages, key=lambda msg: msg.captured_at)[:5])
        analysis = parse_activity_analysis(latest_run.summary_text if latest_run else "", fallback_excerpt=excerpt)
        if latest_run:
            analysis["confidence"] = latest_run.confidence
        started_at = utc_datetime(window.started_at)
        ended_at = utc_datetime(window.ended_at)
        seconds = max(0, int((ended_at - started_at).total_seconds()))
        return ActivitySegment(
            window_id=window.id,
            captured_from=started_at,
            captured_to=ended_at,
            duration_minutes=max(1, (seconds + 59) // 60),
            status=window.status if window.status in INCOMPLETE_STATUSES else latest_run.verdict if latest_run else window.status,
            headline=str(analysis["headline"]),
            summary=str(analysis["summary"]),
            goal=str(analysis["goal"]),
            project=str(analysis["project"]),
            activity_type=str(analysis["activity_type"]),
            activity_label=activity_type_label(str(analysis["activity_type"])),
            focus_state=str(analysis["focus_state"]),
            focus_label=focus_state_label(str(analysis["focus_state"])),
            next_step=str(analysis["next_step"]),
            raw_excerpt=excerpt,
            confidence=float(analysis["confidence"]),
            model_name=latest_run.model_name if latest_run else None,
            prompt_tokens=latest_run.prompt_tokens if latest_run else 0,
            completion_tokens=latest_run.completion_tokens if latest_run else 0,
            total_tokens=latest_run.total_tokens if latest_run else 0,
            latency_ms=latest_run.latency_ms if latest_run else 0,
        )


def persist_rollup_result(rollup: ActivityRollup, result: Any) -> None:
    rollup.prompt_tokens = result.prompt_tokens
    rollup.completion_tokens = result.completion_tokens
    rollup.total_tokens = result.prompt_tokens + result.completion_tokens
    rollup.latency_ms = result.latency_ms
    rollup.confidence = result.confidence
    rollup.summary_text = serialize_activity_analysis(result.analysis_payload)
    rollup.model_name = result.model_name
    rollup.status = WindowStatus.PROCESSED
