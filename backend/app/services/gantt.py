from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.time import db_datetime, local_timezone, utc_datetime
from ..models import ActivityGanttCache, ActivityRollup, LLMRun, Window, WindowStatus
from ..schemas import ActivityGanttBlock, ActivityGanttResponse
from .analysis import parse_activity_analysis
from .llm import LLMGanttComposerPayload, LLMService, LLMServiceError, LLMTimeoutError


GANTT_LANES = {"deep", "meetings", "comms", "breaks"}
GANTT_COMPOSER_VERSION = "gantt-composer-v7"
GANTT_VISUAL_TONES = ("base", "warm", "peach", "amber", "soft")
MEETING_EVIDENCE_KEYWORDS = (
    "standup meeting",
    "standup call",
    "video call",
    "voice call",
    "zoom",
    "teams meeting",
    "microsoft teams meeting",
    "teams call",
    "google meet",
    "meet.google",
    "slack huddle",
    "discord voice",
    "calendar invite",
    "attendee",
    "1:1",
    "one-on-one",
)


@dataclass(frozen=True)
class GanttModeConfig:
    base_level: str
    challengers: tuple[tuple[str, bool], ...]
    threshold: float
    exceptional_threshold: float | None = None
    context_levels: tuple[str, ...] = ()


GANTT_MODES: dict[str, GanttModeConfig] = {
    "1h": GanttModeConfig(base_level="5m", challengers=(("1m", False),), threshold=58, context_levels=("15m",)),
    "4h": GanttModeConfig(base_level="15m", challengers=(("5m", False),), threshold=64, context_levels=("1h",)),
    "day": GanttModeConfig(base_level="1h", challengers=(("15m", False), ("5m", True)), threshold=70, exceptional_threshold=86, context_levels=("4h",)),
    "week": GanttModeConfig(base_level="4h", challengers=(("1h", False), ("15m", True)), threshold=76, exceptional_threshold=90, context_levels=("1d",)),
}
GANTT_PROVISIONAL_WINDOW_MODES = {"4h"}
FINAL_GANTT_CACHE_STATUSES = {"processed", "empty"}
MIN_LLM_GANTT_ACTIVITY_BLOCKS = 3
MIN_LLM_GANTT_ACTIVITY_COVERAGE = 0.35
FALLBACK_GANTT_RETRY_AFTER_SECONDS = 600


@dataclass
class SourceBlock:
    id: str
    level: str
    start: datetime
    end: datetime
    headline: str
    summary: str
    dominant_goal: str
    project: str
    activity_type: str
    focus_state: str
    confidence: float
    source_count: int
    evidence_text: str


@dataclass
class GanttRun:
    id: str
    source_level: str
    source_ids: list[str]
    start: datetime
    end: datetime
    label: str
    summary: str
    project: str
    activity_type: str
    focus_state: str
    dominant_goal: str
    confidence: float
    consecutive_count: int
    evidence_text: str
    priority_score: float = 0.0
    reason: str = ""
    lane: str = ""
    is_marker: bool = False

    @property
    def duration_seconds(self) -> float:
        return max(1.0, (self.end - self.start).total_seconds())


@dataclass
class CandidateContext:
    candidate_id: str
    candidate: GanttRun
    parent: GanttRun
    start: datetime
    end: datetime
    duration_fraction: float
    exceptional: bool


def is_valid_gantt_mode(mode: str) -> bool:
    return mode in GANTT_MODES


class GanttReadService:
    def __init__(self, db: Session, llm_service: LLMService) -> None:
        self.db = db
        self.llm_service = llm_service

    def activity_gantt(self, mode: str, start: datetime, end: datetime) -> ActivityGanttResponse:
        config = GANTT_MODES[mode]
        start = utc_datetime(start)
        end = utc_datetime(end)
        source_levels = self._source_levels(config)
        rollup_sources = self._source_rollups(source_levels, start, end)
        use_window_sources = "1m" in source_levels
        window_sources = self._source_windows(start, end) if use_window_sources else []
        source_signature = self._source_signature(mode, start, end, rollup_sources, window_sources)
        cached = self._cached_response(mode, start, end, source_signature)
        if cached:
            response = cached
        else:
            response = self._build_response(mode, config, start, end, rollup_sources, window_sources, source_signature)
            self._store_cache(response, source_signature)
        if not use_window_sources and self._should_add_provisional_windows(mode, start, end):
            provisional_windows = self._source_windows(start, end)
            response = self._with_provisional_windows(response, mode, start, end, provisional_windows)
        return response

    def cached_activity_gantt(self, mode: str, start: datetime, end: datetime) -> ActivityGanttResponse | None:
        start = utc_datetime(start)
        end = utc_datetime(end)
        cache = self._find_cache(mode, start, end)
        response = self._response_from_cache(cache) if cache else None
        if response and self._should_add_provisional_windows(mode, start, end):
            response = self._with_provisional_windows(response, mode, start, end, self._source_windows(start, end))
        return response

    def refresh_activity_gantt_cache(self, mode: str, start: datetime, end: datetime) -> ActivityGanttResponse:
        config = GANTT_MODES[mode]
        start = utc_datetime(start)
        end = utc_datetime(end)
        existing_cache = self._find_cache(mode, start, end)
        source_levels = self._source_levels(config)
        use_window_sources = "1m" in source_levels
        rollup_sources = self._source_rollups(source_levels, start, end)
        window_sources = self._source_windows(start, end) if use_window_sources else []
        source_signature = self._source_signature(mode, start, end, rollup_sources, window_sources)
        cached = self._cached_response(mode, start, end, source_signature, final_only=True)
        if cached:
            return cached
        response = self._build_response(mode, config, start, end, rollup_sources, window_sources, source_signature)
        if response.status == "empty" and existing_cache:
            existing_response = self._response_from_cache(existing_cache)
            if existing_response and self._has_activity_blocks(existing_response):
                return existing_response
        self._store_cache(response, source_signature)
        return response

    def should_defer_uncached_gantt(self, mode: str, start: datetime, end: datetime) -> bool:
        return mode == "day" and self._is_active_range(utc_datetime(start), utc_datetime(end))

    def blank_activity_gantt(self, mode: str, start: datetime, end: datetime) -> ActivityGanttResponse:
        return self._response(mode, utc_datetime(start), utc_datetime(end), "empty", "local-gantt-composer", [])

    def _source_levels(self, config: GanttModeConfig) -> list[str]:
        levels = self._display_source_levels(config)
        for level in config.context_levels:
            if level not in levels:
                levels.append(level)
        return levels

    def _display_source_levels(self, config: GanttModeConfig) -> list[str]:
        levels = [config.base_level]
        for level, _exceptional in config.challengers:
            if level not in levels:
                levels.append(level)
        return levels

    def _source_rollups(self, levels: list[str], start: datetime, end: datetime) -> list[ActivityRollup]:
        rollup_levels = [level for level in levels if level != "1m"]
        if not rollup_levels:
            return []
        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level.in_(rollup_levels),
                ActivityRollup.started_at < db_datetime(end),
                ActivityRollup.ended_at > db_datetime(start),
                ActivityRollup.status == WindowStatus.PROCESSED,
            )
            .order_by(ActivityRollup.level.asc(), ActivityRollup.started_at.asc())
        )
        return list(self.db.scalars(stmt))

    def _source_windows(self, start: datetime, end: datetime) -> list[Window]:
        stmt = (
            select(Window)
            .options(selectinload(Window.runs), selectinload(Window.messages))
            .where(
                Window.started_at < db_datetime(end),
                Window.ended_at > db_datetime(start),
                Window.status.in_((WindowStatus.PROCESSED, WindowStatus.VIOLATION)),
            )
            .order_by(Window.started_at.asc())
        )
        return [window for window in self.db.scalars(stmt) if self._latest_window_run(window)]

    def _should_add_provisional_windows(self, mode: str, start: datetime, end: datetime) -> bool:
        return mode in GANTT_PROVISIONAL_WINDOW_MODES and self._is_active_range(start, end)

    def _has_activity_blocks(self, response: ActivityGanttResponse) -> bool:
        return any(not block.is_gap for block in response.blocks)

    def _source_signature(
        self,
        mode: str,
        start: datetime,
        end: datetime,
        rollups: list[ActivityRollup],
        windows: list[Window],
    ) -> str:
        parts = [GANTT_COMPOSER_VERSION, mode, start.isoformat(), end.isoformat()]
        for source in sorted(rollups, key=lambda item: (item.level, item.started_at, item.id)):
            updated = utc_datetime(source.updated_at).isoformat() if source.updated_at else ""
            parts.append(f"{source.level}:{source.id}:{updated}:{source.status}:{source.source_count}")
        for window in sorted(windows, key=lambda item: (item.started_at, item.id)):
            latest_run = self._latest_window_run(window)
            created = utc_datetime(latest_run.created_at).isoformat() if latest_run and latest_run.created_at else ""
            run_id = latest_run.id if latest_run else ""
            parts.append(f"1m:{window.id}:{window.status}:{run_id}:{created}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _cached_response(
        self,
        mode: str,
        start: datetime,
        end: datetime,
        source_signature: str,
        *,
        final_only: bool = False,
    ) -> ActivityGanttResponse | None:
        cache = self._find_cache(mode, start, end)
        if not cache or cache.source_signature != source_signature or not cache.payload_json:
            return None
        response = self._response_from_cache(cache)
        if (
            final_only
            and response
            and response.status not in FINAL_GANTT_CACHE_STATUSES
            and self._fallback_retry_due(cache)
        ):
            return None
        return response

    def _fallback_retry_due(self, cache: ActivityGanttCache) -> bool:
        if not cache.updated_at:
            return True
        updated_at = utc_datetime(cache.updated_at)
        return (datetime.now(timezone.utc) - updated_at).total_seconds() >= FALLBACK_GANTT_RETRY_AFTER_SECONDS

    def _response_from_cache(self, cache: ActivityGanttCache) -> ActivityGanttResponse | None:
        try:
            payload = json.loads(cache.payload_json)
            return ActivityGanttResponse.model_validate(payload)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    def _find_cache(self, mode: str, start: datetime, end: datetime) -> ActivityGanttCache | None:
        stmt = select(ActivityGanttCache).where(
            ActivityGanttCache.mode == mode,
            ActivityGanttCache.started_at == db_datetime(start),
            ActivityGanttCache.ended_at == db_datetime(end),
        )
        return self.db.scalars(stmt).first()

    def _store_cache(self, response: ActivityGanttResponse, source_signature: str) -> None:
        start = utc_datetime(response.captured_from)
        end = utc_datetime(response.captured_to)
        cache = self._find_cache(response.mode, start, end)
        payload = json.dumps(response.model_dump(mode="json"), ensure_ascii=True)
        if not cache:
            cache = ActivityGanttCache(
                mode=response.mode,
                started_at=db_datetime(start),
                ended_at=db_datetime(end),
            )
            self.db.add(cache)
        cache.source_signature = source_signature
        cache.status = response.status
        cache.model_name = response.model_name or ""
        cache.payload_json = payload
        self.db.commit()

    def _build_response(
        self,
        mode: str,
        config: GanttModeConfig,
        start: datetime,
        end: datetime,
        rollups: list[ActivityRollup],
        windows: list[Window],
        source_signature: str,
    ) -> ActivityGanttResponse:
        by_level = self._source_blocks_by_level(rollups, windows, start, end)
        source_runs = self._composer_source_runs(config, by_level)
        context_runs = self._composer_context_runs(config, by_level)
        status = "processed" if source_runs else "empty"
        model_name = "local-gantt-composer"
        raw_blocks: list[dict[str, Any]] = []

        if source_runs:
            try:
                result = self.llm_service.compose_gantt_sync(
                    LLMGanttComposerPayload(
                        mode=mode,
                        started_at=start.isoformat(),
                        ended_at=end.isoformat(),
                        sources=[self._run_payload(run) for run in source_runs],
                        contexts=[self._run_payload(run) for run in context_runs],
                    )
                )
                if result.model_name == "fake-gantt-composer":
                    status = "fallback"
                    model_name = "local-gantt-composer-fallback"
                    raw_blocks = self._local_composer_payloads(source_runs, context_runs, config)
                elif not result.blocks:
                    status = "fallback"
                    model_name = "local-gantt-composer-fallback"
                    raw_blocks = self._local_composer_payloads(source_runs, context_runs, config)
                else:
                    raw_blocks = result.blocks
                    model_name = result.model_name
            except (LLMServiceError, LLMTimeoutError, RuntimeError):
                status = "fallback"
                model_name = "local-gantt-composer-fallback"
                raw_blocks = self._local_composer_payloads(source_runs, context_runs, config)

        blocks = self._composer_payloads_to_blocks(mode, start, end, raw_blocks, source_runs)
        if status == "processed" and self._composer_blocks_are_sparse(blocks, source_runs):
            print(
                f"[Gantt] LLM composer output too sparse for {mode}; "
                "using local composer fallback"
            )
            status = "fallback"
            model_name = "local-gantt-composer-fallback"
            raw_blocks = self._local_composer_payloads(source_runs, context_runs, config)
            blocks = self._composer_payloads_to_blocks(mode, start, end, raw_blocks, source_runs)
        if source_signature and not source_runs:
            status = "empty"
        return self._response(mode, start, end, status, model_name, blocks)

    def _with_provisional_windows(
        self,
        response: ActivityGanttResponse,
        mode: str,
        start: datetime,
        end: datetime,
        windows: list[Window],
    ) -> ActivityGanttResponse:
        if not windows:
            return response
        by_level = self._source_blocks_by_level([], windows, start, end)
        provisional_runs = self._provisional_display_runs(mode, by_level.get("1m", []))
        if not provisional_runs:
            return response

        existing_payloads = [self._payload_from_existing_block(block) for block in response.blocks if not block.is_gap]
        existing_runs = [self._run_from_existing_block(block) for block in response.blocks if not block.is_gap]
        provisional_runs = self._uncovered_provisional_runs(provisional_runs, existing_runs)
        if not provisional_runs:
            return response
        provisional_payloads = [self._provisional_payload_from_run(run) for run in provisional_runs]
        blocks = self._composer_payloads_to_blocks(
            mode,
            start,
            end,
            [*existing_payloads, *provisional_payloads],
            [*existing_runs, *provisional_runs],
        )
        if not blocks:
            return response
        return self._response(
            mode,
            start,
            end,
            "provisional" if response.status == "empty" else "partial",
            self._provisional_model_name(response.model_name),
            blocks,
        )

    def _payload_from_existing_block(self, block: ActivityGanttBlock) -> dict[str, Any]:
        return {
            "from": utc_datetime(block.captured_from).isoformat(),
            "to": utc_datetime(block.captured_to).isoformat(),
            "lane": block.lane,
            "label": block.label,
            "summary": block.summary,
            "project": block.project,
            "source_ids": self._unique_strings([block.id, *block.source_ids]),
            "is_gap": False,
            "reason": block.reason,
            "evidence": block.evidence,
            "visual_group": block.visual_group,
            "visual_tone": block.visual_tone,
        }

    def _run_from_existing_block(self, block: ActivityGanttBlock) -> GanttRun:
        return GanttRun(
            id=block.id,
            source_level=block.source_level,
            source_ids=block.source_ids,
            start=utc_datetime(block.captured_from),
            end=utc_datetime(block.captured_to),
            label=block.label,
            summary=block.summary,
            project=block.project,
            activity_type=block.activity_type,
            focus_state=block.focus_state,
            dominant_goal=block.reason,
            confidence=block.priority_score / 100,
            consecutive_count=max(1, len(block.source_ids)),
            evidence_text=block.evidence,
            priority_score=block.priority_score,
            reason=block.reason,
            lane=block.lane,
            is_marker=block.is_marker,
        )

    def _provisional_payload_from_run(self, run: GanttRun) -> dict[str, Any]:
        payload = self._local_payload_from_run(run)
        payload["reason"] = "Recent processed window shown while hierarchy summaries catch up."
        return payload

    def _provisional_display_runs(self, mode: str, blocks: list[SourceBlock]) -> list[GanttRun]:
        runs = self._merge_runs(blocks)
        return self._merge_display_runs(runs, [])

    def _uncovered_provisional_runs(self, provisional_runs: list[GanttRun], existing_runs: list[GanttRun]) -> list[GanttRun]:
        if not existing_runs:
            return provisional_runs
        covered = [(run.start, run.end) for run in existing_runs]
        uncovered: list[GanttRun] = []
        for run in provisional_runs:
            for index, (piece_start, piece_end) in enumerate(self._subtract_intervals(run.start, run.end, covered), start=1):
                uncovered.append(replace(run, id=f"{run.id}-provisional-part-{index}", start=piece_start, end=piece_end))
        return uncovered

    def _provisional_model_name(self, model_name: str | None) -> str:
        base = model_name or "local-gantt-composer"
        if "provisional-windows" in base:
            return base
        return f"{base}+provisional-windows"

    def _source_blocks_by_level(
        self,
        rollups: list[ActivityRollup],
        windows: list[Window],
        range_start: datetime,
        range_end: datetime,
    ) -> dict[str, list[SourceBlock]]:
        by_level: dict[str, list[SourceBlock]] = {}
        for rollup in rollups:
            analysis = parse_activity_analysis(rollup.summary_text)
            start = max(utc_datetime(rollup.started_at), range_start)
            end = min(utc_datetime(rollup.ended_at), range_end)
            if end <= start:
                continue
            block = SourceBlock(
                id=rollup.id,
                level=rollup.level,
                start=start,
                end=end,
                headline=str(analysis["headline"]),
                summary=str(analysis["summary"]),
                dominant_goal=str(analysis.get("dominant_goal") or analysis["goal"]),
                project=str(analysis["project"]),
                activity_type=str(analysis["activity_type"]),
                focus_state=str(analysis["focus_state"]),
                confidence=float(analysis["confidence"]),
                source_count=rollup.source_count,
                evidence_text=self._compact_text(rollup.summary_text, 900),
            )
            by_level.setdefault(block.level, []).append(block)
        for window in windows:
            latest_run = self._latest_window_run(window)
            if not latest_run:
                continue
            analysis = parse_activity_analysis(latest_run.summary_text, fallback_excerpt="")
            start = max(utc_datetime(window.started_at), range_start)
            end = min(utc_datetime(window.ended_at), range_end)
            if end <= start:
                continue
            block = SourceBlock(
                id=window.id,
                level="1m",
                start=start,
                end=end,
                headline=str(analysis["headline"]),
                summary=str(analysis["summary"]),
                dominant_goal=str(analysis.get("dominant_goal") or analysis["goal"]),
                project=str(analysis["project"]),
                activity_type=str(analysis["activity_type"]),
                focus_state=str(analysis["focus_state"]),
                confidence=float(latest_run.confidence if latest_run else analysis["confidence"]),
                source_count=1,
                evidence_text=self._window_evidence(window, latest_run),
            )
            by_level.setdefault(block.level, []).append(block)
        for blocks in by_level.values():
            blocks.sort(key=lambda item: item.start)
        return by_level

    def _latest_window_run(self, window: Window) -> LLMRun | None:
        return max(window.runs, key=lambda run: run.created_at) if window.runs else None

    def _merge_runs(self, blocks: list[SourceBlock]) -> list[GanttRun]:
        runs: list[GanttRun] = []
        for block in blocks:
            if runs and self._can_join(runs[-1], block):
                current = runs[-1]
                current.end = max(current.end, block.end)
                current.source_ids.append(block.id)
                current.summary = self._join_summary(current.summary, block.summary)
                current.evidence_text = self._join_summary(current.evidence_text, block.evidence_text)
                current.confidence = max(current.confidence, block.confidence)
                current.consecutive_count += 1
                continue
            runs.append(
                GanttRun(
                    id=block.id,
                    source_level=block.level,
                    source_ids=[block.id],
                    start=block.start,
                    end=block.end,
                    label=block.headline,
                    summary=block.summary,
                    project=block.project,
                    activity_type=block.activity_type,
                    focus_state=block.focus_state,
                    dominant_goal=block.dominant_goal,
                    confidence=block.confidence,
                    consecutive_count=1,
                    evidence_text=block.evidence_text,
                    priority_score=50.0,
                    reason="Dominant parent block.",
                    lane=self._lane_for(
                        block.activity_type,
                        block.headline,
                        block.summary,
                        block.project,
                        block.dominant_goal,
                        block.evidence_text,
                    ),
                )
            )
        return runs

    def _can_join(self, current: GanttRun, block: SourceBlock) -> bool:
        adjacent = abs((block.start - current.end).total_seconds()) <= 60
        if not adjacent:
            return False
        return self._task_key_run(current) == self._task_key_block(block)

    def _task_key_run(self, run: GanttRun) -> str:
        return self._task_key(run.project, run.activity_type, run.dominant_goal, run.label)

    def _task_key_block(self, block: SourceBlock) -> str:
        return self._task_key(block.project, block.activity_type, block.dominant_goal, block.headline)

    def _task_key(self, project: str, activity_type: str, goal: str, headline: str) -> str:
        goal_words = " ".join((goal or headline or "").lower().split()[:8])
        return "|".join([project.lower().strip() or "general work", activity_type, goal_words])

    def _join_summary(self, current: str, incoming: str) -> str:
        if not incoming or incoming in current:
            return current
        if len(current) > 220:
            return current
        return f"{current} {incoming}"

    def _first_available_runs(self, config: GanttModeConfig, by_level: dict[str, list[SourceBlock]]) -> list[GanttRun]:
        for level in [config.base_level, *(level for level, _exceptional in config.challengers)]:
            runs = self._merge_runs(by_level.get(level, []))
            if runs:
                return runs
        return []

    def _composer_source_runs(self, config: GanttModeConfig, by_level: dict[str, list[SourceBlock]]) -> list[GanttRun]:
        runs: list[GanttRun] = []
        for level in self._display_source_levels(config):
            runs.extend(self._merge_runs(by_level.get(level, [])))
        level_order = {level: index for index, level in enumerate(self._display_source_levels(config))}
        return sorted(runs, key=lambda item: (item.start, level_order.get(item.source_level, 99), item.end))

    def _composer_context_runs(self, config: GanttModeConfig, by_level: dict[str, list[SourceBlock]]) -> list[GanttRun]:
        runs: list[GanttRun] = []
        for level in config.context_levels:
            runs.extend(self._merge_runs(by_level.get(level, [])))
        level_order = {level: index for index, level in enumerate(config.context_levels)}
        return sorted(runs, key=lambda item: (item.start, level_order.get(item.source_level, 99), item.end))

    def _local_composer_payloads(
        self,
        source_runs: list[GanttRun],
        context_runs: list[GanttRun],
        config: GanttModeConfig,
    ) -> list[dict[str, Any]]:
        base_runs = [run for run in source_runs if run.source_level == config.base_level]
        if not base_runs:
            base_runs = [run for run in source_runs if run.source_level == self._display_source_levels(config)[0]]
        meeting_overrides = [
            run
            for run in source_runs
            if run.source_level != config.base_level
            and self._strict_lane_for(run.activity_type, run.label, run.summary, run.project, run.dominant_goal, run.evidence_text) == "meetings"
        ]
        blockers = [(run.start, run.end) for run in meeting_overrides]
        visible_runs: list[GanttRun] = []
        for base in base_runs:
            for index, (piece_start, piece_end) in enumerate(self._subtract_intervals(base.start, base.end, blockers), start=1):
                visible_runs.append(replace(base, id=f"{base.id}-composer-part-{index}", start=piece_start, end=piece_end))
        visible_runs.extend(meeting_overrides)
        visible_runs = self._merge_display_runs(sorted(visible_runs, key=lambda item: (item.start, item.end)), context_runs)
        return [self._local_payload_from_run(run, self._context_for_run(run, context_runs)) for run in visible_runs]

    def _merge_display_runs(self, runs: list[GanttRun], context_runs: list[GanttRun]) -> list[GanttRun]:
        merged: list[GanttRun] = []
        for run in runs:
            if merged and self._can_join_display_runs(merged[-1], run, context_runs):
                current = merged[-1]
                current.end = max(current.end, run.end)
                current.source_ids.extend(source_id for source_id in run.source_ids if source_id not in current.source_ids)
                current.summary = self._join_summary(current.summary, run.summary)
                current.evidence_text = self._join_summary(current.evidence_text, run.evidence_text)
                current.consecutive_count += run.consecutive_count
                current.confidence = max(current.confidence, run.confidence)
                continue
            merged.append(run)
        return merged

    def _can_join_display_runs(self, current: GanttRun, incoming: GanttRun, context_runs: list[GanttRun]) -> bool:
        adjacent = abs((incoming.start - current.end).total_seconds()) <= 5 * 60
        if not adjacent:
            return False
        current_lane = self._strict_lane_for(current.activity_type, current.label, current.summary, current.project, current.dominant_goal, current.evidence_text)
        incoming_lane = self._strict_lane_for(incoming.activity_type, incoming.label, incoming.summary, incoming.project, incoming.dominant_goal, incoming.evidence_text)
        if current_lane != incoming_lane:
            return False
        if current_lane == "meetings":
            return self._task_key_run(current) == self._task_key_run(incoming)
        if (current.project or "").strip().lower() != (incoming.project or "").strip().lower():
            return False
        if self._task_key_run(current) == self._task_key_run(incoming):
            return True
        current_context = self._context_for_run(current, context_runs)
        incoming_context = self._context_for_run(incoming, context_runs)
        return bool(current_context and incoming_context and current_context.id == incoming_context.id)

    def _context_for_run(self, run: GanttRun, context_runs: list[GanttRun]) -> GanttRun | None:
        best: tuple[float, GanttRun] | None = None
        for context in context_runs:
            overlap = (min(run.end, context.end) - max(run.start, context.start)).total_seconds()
            if overlap <= 0:
                continue
            if best is None or overlap > best[0]:
                best = (overlap, context)
        return best[1] if best else None

    def _local_payload_from_run(self, run: GanttRun, context: GanttRun | None = None) -> dict[str, Any]:
        lane = self._strict_lane_for(run.activity_type, run.label, run.summary, run.project, run.dominant_goal, run.evidence_text)
        use_context = bool(
            context
            and lane != "meetings"
            and (context.project or "").strip().lower() == (run.project or "").strip().lower()
            and run.consecutive_count > 1
        )
        label = context.label if use_context and context else run.label
        summary = context.summary if use_context and context else run.summary
        project = context.project if use_context and context and context.project else run.project or "General work"
        reason = (
            f"Local composer fallback merged consecutive source blocks using {context.source_level} context."
            if use_context and context
            else "Local composer fallback merged adjacent source blocks and used strict lane evidence."
        )
        evidence = self._join_summary(context.evidence_text, run.evidence_text) if use_context and context else run.evidence_text
        visual_group = self._visual_group_for(run, context)
        return {
            "from": run.start.isoformat(),
            "to": run.end.isoformat(),
            "lane": lane,
            "label": label,
            "summary": summary,
            "project": project,
            "source_ids": [run.id, *run.source_ids],
            "is_gap": False,
            "reason": reason,
            "evidence": self._compact_text(evidence or summary, 320),
            "visual_group": visual_group,
            "visual_tone": self._visual_tone_for(visual_group, lane),
        }

    def _composer_payloads_to_blocks(
        self,
        mode: str,
        range_start: datetime,
        range_end: datetime,
        payloads: list[dict[str, Any]],
        source_runs: list[GanttRun],
    ) -> list[ActivityGanttBlock]:
        source_by_id: dict[str, GanttRun] = {}
        for run in source_runs:
            source_by_id[run.id] = run
            for source_id in run.source_ids:
                source_by_id[source_id] = run

        gap_fill_end = self._gap_fill_end(range_start, range_end)
        suppress_tail_gaps = self._is_active_range(range_start, range_end)
        normalized: list[dict[str, Any]] = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            source_ids = self._string_list(payload.get("source_ids"))
            source_refs = [source_by_id[source_id] for source_id in source_ids if source_id in source_by_id]
            derived_start = min((run.start for run in source_refs), default=None)
            derived_end = max((run.end for run in source_refs), default=None)
            block_start = self._parse_time(payload.get("from") or payload.get("captured_from")) or derived_start
            block_end = self._parse_time(payload.get("to") or payload.get("captured_to")) or derived_end
            is_gap = bool(payload.get("is_gap"))
            if block_start is None or block_end is None:
                continue
            block_start = max(utc_datetime(block_start), range_start)
            block_end = min(utc_datetime(block_end), range_end)
            if is_gap:
                if block_start >= gap_fill_end:
                    continue
                block_end = min(block_end, gap_fill_end)
            if block_end <= block_start:
                continue

            lane = str(payload.get("lane") or "").lower()
            if is_gap:
                lane = "breaks"
            elif lane not in GANTT_LANES:
                lane = self._lane_from_sources(source_refs)
            if lane not in GANTT_LANES:
                lane = "deep"

            label = "Away from keyboard" if is_gap else (self._clean_text(payload.get("label")) or "Work block")
            project = self._clean_text(payload.get("project")) or ("" if is_gap else self._project_from_sources(source_refs))
            summary = self._clean_text(payload.get("summary")) or (
                "No analyzed activity was captured for this past interval." if is_gap else self._summary_from_sources(source_refs)
            )
            reason = self._clean_text(payload.get("reason")) or (
                "Composer identified an uncovered chart interval." if is_gap else "Composed from source evidence."
            )
            evidence = self._clean_text(payload.get("evidence") or payload.get("evidence_summary")) or self._evidence_from_sources(source_refs)
            visual_group = self._canonical_visual_group(
                self._clean_text(payload.get("visual_group")),
                source_refs,
                project,
                label,
            ) if not is_gap else "away"
            visual_tone = self._clean_text(payload.get("visual_tone")).lower()
            if is_gap:
                visual_tone = "neutral"
            elif visual_tone not in GANTT_VISUAL_TONES:
                visual_tone = self._visual_tone_for(visual_group, lane)
            normalized.append(
                {
                    "start": block_start,
                    "end": block_end,
                    "lane": lane,
                    "label": label[:96],
                    "summary": summary[:420],
                    "project": project[:96],
                    "source_ids": self._unique_strings(source_ids),
                    "reason": reason[:280],
                    "evidence": evidence[:420],
                    "is_gap": is_gap,
                    "source_refs": source_refs,
                    "visual_group": visual_group[:96],
                    "visual_tone": visual_tone,
                }
            )

        normalized.sort(key=lambda item: (item["start"], item["end"], item["is_gap"]))
        latest_activity_end = max(
            (item["end"] for item in normalized if not item["is_gap"] and item["start"] < gap_fill_end),
            default=range_start,
        )
        if suppress_tail_gaps:
            filtered: list[dict[str, Any]] = []
            for item in normalized:
                if not item["is_gap"]:
                    filtered.append(item)
                    continue
                if item["start"] >= latest_activity_end:
                    continue
                if item["end"] > latest_activity_end:
                    item = {**item, "end": latest_activity_end}
                if item["end"] > item["start"]:
                    filtered.append(item)
            normalized = filtered
        effective_gap_fill_end = latest_activity_end if suppress_tail_gaps else gap_fill_end
        blocks: list[ActivityGanttBlock] = []
        cursor = range_start
        for item in normalized:
            block_start = max(item["start"], cursor)
            block_end = item["end"]
            if block_end <= block_start:
                continue
            if block_start > cursor and cursor < effective_gap_fill_end:
                gap_end = min(block_start, effective_gap_fill_end)
                if gap_end > cursor:
                    blocks.append(self._gap_block(mode, len(blocks) + 1, cursor, gap_end))
            item["start"] = block_start
            blocks.append(self._activity_block_from_normalized(mode, len(blocks) + 1, item))
            cursor = block_end
        if cursor < effective_gap_fill_end:
            blocks.append(self._gap_block(mode, len(blocks) + 1, cursor, effective_gap_fill_end))
        return blocks

    def _composer_blocks_are_sparse(self, blocks: list[ActivityGanttBlock], source_runs: list[GanttRun]) -> bool:
        if not source_runs:
            return False
        activity_blocks = [block for block in blocks if not block.is_gap]
        if len(source_runs) >= MIN_LLM_GANTT_ACTIVITY_BLOCKS and len(activity_blocks) < MIN_LLM_GANTT_ACTIVITY_BLOCKS:
            return True
        source_start = min(run.start for run in source_runs)
        source_end = max(run.end for run in source_runs)
        source_span_seconds = max(1.0, (source_end - source_start).total_seconds())
        if source_span_seconds < 3600:
            return False
        covered_seconds = self._merged_interval_seconds(
            (utc_datetime(block.captured_from), utc_datetime(block.captured_to))
            for block in activity_blocks
        )
        return (covered_seconds / source_span_seconds) < MIN_LLM_GANTT_ACTIVITY_COVERAGE

    def _merged_interval_seconds(self, intervals: Any) -> float:
        sorted_intervals = sorted(
            ((start, end) for start, end in intervals if end > start),
            key=lambda item: item[0],
        )
        if not sorted_intervals:
            return 0.0
        merged_seconds = 0.0
        current_start, current_end = sorted_intervals[0]
        for start, end in sorted_intervals[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
                continue
            merged_seconds += (current_end - current_start).total_seconds()
            current_start, current_end = start, end
        merged_seconds += (current_end - current_start).total_seconds()
        return merged_seconds

    def _activity_block_from_normalized(self, mode: str, index: int, item: dict[str, Any]) -> ActivityGanttBlock:
        source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), list) else []
        lane = str(item["lane"])
        is_gap = bool(item["is_gap"])
        return ActivityGanttBlock(
            id=f"{mode}-composer-{index}",
            lane=lane,
            captured_from=item["start"],
            captured_to=item["end"],
            label=str(item["label"]),
            summary=str(item["summary"]),
            project=str(item["project"]),
            activity_type=self._activity_type_for_block(lane, source_refs, is_gap),
            focus_state=self._focus_state_for_block(lane, source_refs, is_gap),
            source_level="gap" if is_gap else self._source_level_for_block(source_refs),
            source_ids=list(item["source_ids"]),
            priority_score=self._display_priority(lane, item["start"], item["end"], is_gap),
            reason=str(item["reason"]),
            is_marker=False,
            is_gap=is_gap,
            evidence=str(item["evidence"]),
            visual_group=str(item["visual_group"]),
            visual_tone=str(item["visual_tone"]),
        )

    def _gap_block(self, mode: str, index: int, start: datetime, end: datetime) -> ActivityGanttBlock:
        return ActivityGanttBlock(
            id=f"{mode}-gap-{index}",
            lane="breaks",
            captured_from=start,
            captured_to=end,
            label="Away from keyboard",
            summary="No analyzed activity was captured for this past interval.",
            project="",
            activity_type="break",
            focus_state="idle",
            source_level="gap",
            source_ids=[],
            priority_score=8.0,
            reason="Composer filled uncovered past chart time. This means uncaptured or unanalyzed activity, not a confirmed break.",
            is_marker=False,
            is_gap=True,
            evidence="No source evidence covered this past interval.",
            visual_group="away",
            visual_tone="neutral",
        )

    def _candidate_contexts(
        self,
        config: GanttModeConfig,
        base_runs: list[GanttRun],
        by_level: dict[str, list[SourceBlock]],
    ) -> list[CandidateContext]:
        contexts: list[CandidateContext] = []
        counter = 1
        for level, exceptional in config.challengers:
            for candidate in self._merge_runs(by_level.get(level, [])):
                for parent in base_runs:
                    start = max(candidate.start, parent.start)
                    end = min(candidate.end, parent.end)
                    if end <= start:
                        continue
                    contexts.append(
                        CandidateContext(
                            candidate_id=f"c{counter}",
                            candidate=candidate,
                            parent=parent,
                            start=start,
                            end=end,
                            duration_fraction=(end - start).total_seconds() / parent.duration_seconds,
                            exceptional=exceptional,
                        )
                    )
                    counter += 1
        return contexts

    def _candidate_payload(self, context: CandidateContext) -> dict[str, Any]:
        return {
            "candidate_id": context.candidate_id,
            "duration_fraction": round(context.duration_fraction, 4),
            "consecutive_child_count": context.candidate.consecutive_count,
            "exceptional": context.exceptional,
            "parent": self._run_payload(context.parent),
            "candidate": self._run_payload(context.candidate),
        }

    def _run_payload(self, run: GanttRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "level": run.source_level,
            "from": run.start.isoformat(),
            "to": run.end.isoformat(),
            "time_range": self._format_range(run.start, run.end),
            "headline": run.label,
            "summary": run.summary,
            "dominant_goal": run.dominant_goal,
            "project": run.project,
            "activity_type": run.activity_type,
            "focus_state": run.focus_state,
            "lane": run.lane or self._lane_for(run.activity_type, run.label, run.summary, run.project, run.dominant_goal, run.evidence_text),
            "confidence": run.confidence,
            "source_ids": run.source_ids,
            "source_count": len(run.source_ids),
            "evidence": self._compact_text(run.evidence_text or run.summary, 900),
        }

    def _fallback_decisions(self, candidates: list[CandidateContext]) -> dict[str, dict[str, Any]]:
        decisions: dict[str, dict[str, Any]] = {}
        for context in candidates:
            lane = context.candidate.lane or self._lane_for(
                context.candidate.activity_type,
                context.candidate.label,
                context.candidate.summary,
                context.candidate.project,
                context.candidate.dominant_goal,
            )
            same_task = self._task_key_run(context.candidate) == self._task_key_run(context.parent)
            significance = 0.42 + min(0.3, context.duration_fraction * 0.55)
            disruption = 0.32 + min(0.34, context.duration_fraction * 0.65)
            if lane == "meetings":
                significance += 0.26
                disruption += 0.32
            elif context.candidate.activity_type in {"communication", "admin"}:
                significance += 0.12
                disruption += 0.18
            if context.candidate.focus_state in {"switching", "blocked"}:
                disruption += 0.12
            if same_task:
                disruption -= 0.22
            decisions[context.candidate_id] = {
                "significance": max(0.0, min(1.0, significance)),
                "disruption": max(0.0, min(1.0, disruption)),
                "same_task": same_task,
                "lane": lane,
                "display_label": context.candidate.label,
                "reason": "Ranked by local duration, activity, focus, and interruption heuristics.",
            }
        return decisions

    def _promotions(
        self,
        config: GanttModeConfig,
        candidates: list[CandidateContext],
        decisions: dict[str, dict[str, Any]],
    ) -> list[GanttRun]:
        promoted: list[tuple[CandidateContext, GanttRun]] = []
        for context in candidates:
            decision = decisions.get(context.candidate_id)
            if not decision:
                continue
            score = self._priority_score(context, decision)
            threshold = config.exceptional_threshold if context.exceptional and config.exceptional_threshold is not None else config.threshold
            if score < threshold:
                continue
            lane = str(decision.get("lane") or context.candidate.lane or "deep")
            if lane not in GANTT_LANES:
                lane = context.candidate.lane or "deep"
            is_marker = self._is_marker(context, lane, score, threshold)
            promoted.append(
                (
                    context,
                    replace(
                        context.candidate,
                        id=f"{context.candidate_id}-{context.candidate.id}",
                        start=context.start,
                        end=context.end,
                        label=str(decision.get("display_label") or context.candidate.label),
                        priority_score=round(score, 2),
                        reason=str(decision.get("reason") or "Promoted by Gantt ranker."),
                        lane=lane,
                        is_marker=is_marker,
                    ),
                )
            )

        selected: list[GanttRun] = []
        occupied: list[tuple[datetime, datetime]] = []
        for _context, run in sorted(promoted, key=lambda item: item[1].priority_score, reverse=True):
            if not run.is_marker and any(self._overlaps(run.start, run.end, start, end) for start, end in occupied):
                continue
            selected.append(run)
            if not run.is_marker:
                occupied.append((run.start, run.end))
        return sorted(selected, key=lambda item: (item.start, item.end, item.priority_score))

    def _priority_score(self, context: CandidateContext, decision: dict[str, Any]) -> float:
        significance = self._float(decision.get("significance"), 0.5)
        disruption = self._float(decision.get("disruption"), 0.5)
        lane = str(decision.get("lane") or context.candidate.lane or "")
        duration_component = math.sqrt(max(0.0, min(1.0, context.duration_fraction)))
        score = 100 * ((0.42 * significance) + (0.36 * disruption) + (0.22 * duration_component))
        score += min(12, 3 * context.candidate.consecutive_count)
        if lane == "meetings":
            score += 10
        elif context.candidate.activity_type in {"communication", "admin"}:
            score += 5
        if bool(decision.get("same_task")):
            score -= 35
        if context.exceptional:
            score -= 12
        return max(0.0, score)

    def _is_marker(self, context: CandidateContext, lane: str, score: float, threshold: float) -> bool:
        return context.candidate.consecutive_count == 1 and lane != "meetings" and score < threshold + 14

    def _resolved_blocks(self, base_runs: list[GanttRun], promotions: list[GanttRun]) -> list[ActivityGanttBlock]:
        blockers = [(run.start, run.end) for run in promotions if not run.is_marker]
        visible_runs: list[GanttRun] = []
        for base in base_runs:
            for index, (start, end) in enumerate(self._subtract_intervals(base.start, base.end, blockers), start=1):
                visible_runs.append(replace(base, id=f"{base.id}-part-{index}", start=start, end=end))
        visible_runs.extend(promotions)
        visible_runs.sort(key=lambda item: (item.start, item.end, item.lane, item.priority_score))
        return self._runs_to_blocks(visible_runs)

    def _subtract_intervals(
        self,
        start: datetime,
        end: datetime,
        intervals: list[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        pieces = [(start, end)]
        for cut_start, cut_end in sorted(intervals):
            next_pieces: list[tuple[datetime, datetime]] = []
            for piece_start, piece_end in pieces:
                if not self._overlaps(piece_start, piece_end, cut_start, cut_end):
                    next_pieces.append((piece_start, piece_end))
                    continue
                if piece_start < cut_start:
                    next_pieces.append((piece_start, min(cut_start, piece_end)))
                if cut_end < piece_end:
                    next_pieces.append((max(cut_end, piece_start), piece_end))
            pieces = [(piece_start, piece_end) for piece_start, piece_end in next_pieces if piece_end > piece_start]
        return pieces

    def _runs_to_blocks(self, runs: list[GanttRun]) -> list[ActivityGanttBlock]:
        blocks: list[ActivityGanttBlock] = []
        for run in runs:
            lane = run.lane or self._lane_for(run.activity_type, run.label, run.summary, run.project, run.dominant_goal)
            visual_group = self._visual_group_for(run)
            blocks.append(
                ActivityGanttBlock(
                    id=run.id,
                    lane=lane if lane in GANTT_LANES else "deep",
                    captured_from=run.start,
                    captured_to=run.end,
                    label=run.label,
                    summary=run.summary,
                    project=run.project,
                    activity_type=run.activity_type,
                    focus_state=run.focus_state,
                    source_level=run.source_level,
                    source_ids=run.source_ids,
                    priority_score=run.priority_score,
                    reason=run.reason,
                    is_marker=run.is_marker,
                    is_gap=False,
                    evidence=self._compact_text(run.evidence_text or run.summary, 420),
                    visual_group=visual_group,
                    visual_tone=self._visual_tone_for(visual_group, lane),
                )
            )
        return blocks

    def _response(
        self,
        mode: str,
        start: datetime,
        end: datetime,
        status: str,
        model_name: str,
        blocks: list[ActivityGanttBlock],
    ) -> ActivityGanttResponse:
        return ActivityGanttResponse(
            mode=mode,
            captured_from=start,
            captured_to=end,
            status=status,
            model_name=model_name,
            generated_at=datetime.now(timezone.utc),
            blocks=blocks,
        )

    def _window_evidence(self, window: Window, latest_run: LLMRun | None) -> str:
        message_lines: list[str] = []
        for message in sorted(window.messages, key=lambda item: item.captured_at):
            text = self._clean_text(message.text)
            if text:
                message_lines.append(text)
            if len(" ".join(message_lines)) > 700:
                break
        summary_text = latest_run.summary_text if latest_run else ""
        transcript = " | ".join(message_lines)
        return self._compact_text(f"{summary_text} Transcript: {transcript}", 900)

    def _strict_lane_for(
        self,
        activity_type: str,
        headline: str,
        summary: str,
        project: str,
        goal: str,
        evidence: str = "",
    ) -> str:
        haystack = f"{headline} {summary} {project} {goal} {evidence}".lower()
        if activity_type in {"break", "offline", "other"}:
            return "breaks"
        if activity_type in {"communication", "admin", "review"} and any(keyword in haystack for keyword in MEETING_EVIDENCE_KEYWORDS):
            return "meetings"
        if activity_type in {"communication", "admin"}:
            return "comms"
        return "deep"

    def _lane_for(self, activity_type: str, headline: str, summary: str, project: str, goal: str, evidence: str = "") -> str:
        return self._strict_lane_for(activity_type, headline, summary, project, goal, evidence)

    def _parse_time(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return utc_datetime(value)
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return utc_datetime(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            return None

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return self._unique_strings(str(item) for item in value if str(item).strip())
        if isinstance(value, str):
            return self._unique_strings(item.strip() for item in value.split(",") if item.strip())
        return []

    def _unique_strings(self, values: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _lane_from_sources(self, sources: list[GanttRun]) -> str:
        for run in sources:
            lane = self._strict_lane_for(run.activity_type, run.label, run.summary, run.project, run.dominant_goal, run.evidence_text)
            if lane == "meetings":
                return "meetings"
        for run in sources:
            lane = run.lane or self._strict_lane_for(run.activity_type, run.label, run.summary, run.project, run.dominant_goal, run.evidence_text)
            if lane in GANTT_LANES:
                return lane
        return "deep"

    def _gap_fill_end(self, range_start: datetime, range_end: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        if now <= range_start:
            return range_start
        if now < range_end:
            return now
        return range_end

    def _is_active_range(self, range_start: datetime, range_end: datetime) -> bool:
        now = datetime.now(timezone.utc)
        return range_start < now < range_end

    def _visual_group_for(self, run: GanttRun, context: GanttRun | None = None) -> str:
        context_text = ""
        if context:
            context_text = f"{context.project} {context.label} {context.summary} {context.dominant_goal}"
        canonical = self._canonical_workstream(
            f"{run.project} {run.label} {run.summary} {run.dominant_goal} {run.evidence_text} {context_text}",
            run.project or (context.project if context else ""),
        )
        if canonical:
            return canonical
        return self._compact_text(run.project or run.dominant_goal or run.label or "General work", 96)

    def _visual_group_from_sources(self, sources: list[GanttRun], project: str, label: str) -> str:
        source_text = " ".join(
            f"{run.project} {run.label} {run.summary} {run.dominant_goal} {run.evidence_text}"
            for run in sources
        )
        canonical = self._canonical_workstream(f"{project} {label} {source_text}", project)
        if canonical:
            return canonical
        if sources:
            projects = [run.project for run in sources if run.project]
            if projects:
                return self._compact_text(max(set(projects), key=projects.count), 96)
        return self._compact_text(project or label or "General work", 96)

    def _canonical_visual_group(self, suggested: str, sources: list[GanttRun], project: str, label: str) -> str:
        source_text = " ".join(
            f"{run.project} {run.label} {run.summary} {run.dominant_goal} {run.evidence_text}"
            for run in sources
        )
        canonical = self._canonical_workstream(f"{suggested} {project} {label} {source_text}", project)
        if canonical:
            return canonical
        return self._compact_text(suggested or self._visual_group_from_sources(sources, project, label), 96)

    def _canonical_workstream(self, text: str, project: str = "") -> str:
        haystack = f"{project} {text}".lower()
        if "workday lens" in haystack or ("workday" in haystack and "lens" in haystack):
            return "Workday Lens"
        clean_project = self._clean_text(project)
        if clean_project and clean_project.lower() not in {"general work", "unknown", "none"}:
            return self._compact_text(clean_project, 96)
        return ""

    def _visual_tone_for(self, visual_group: str, lane: str) -> str:
        if lane == "breaks":
            return "neutral"
        seed = f"{lane}:{visual_group or 'General work'}".encode("utf-8")
        digest = hashlib.sha256(seed).hexdigest()
        return GANTT_VISUAL_TONES[int(digest[:8], 16) % len(GANTT_VISUAL_TONES)]

    def _project_from_sources(self, sources: list[GanttRun]) -> str:
        for run in sources:
            if run.project:
                return run.project
        return "General work"

    def _summary_from_sources(self, sources: list[GanttRun]) -> str:
        summary = ""
        for run in sources:
            summary = self._join_summary(summary, run.summary) if summary else run.summary
            if len(summary) > 380:
                break
        return summary or "Composed from source activity."

    def _evidence_from_sources(self, sources: list[GanttRun]) -> str:
        evidence = ""
        for run in sources:
            evidence = self._join_summary(evidence, run.evidence_text or run.summary) if evidence else (run.evidence_text or run.summary)
            if len(evidence) > 380:
                break
        return self._compact_text(evidence, 420)

    def _activity_type_for_block(self, lane: str, sources: list[GanttRun], is_gap: bool) -> str:
        if is_gap or lane == "breaks":
            return "break"
        if lane in {"meetings", "comms"}:
            return "communication"
        for run in sources:
            if run.activity_type:
                return run.activity_type
        return "deep_work"

    def _focus_state_for_block(self, lane: str, sources: list[GanttRun], is_gap: bool) -> str:
        if is_gap or lane == "breaks":
            return "idle"
        if lane == "meetings":
            return "switching"
        for run in sources:
            if run.focus_state:
                return run.focus_state
        return "focused" if lane == "deep" else "steady"

    def _source_level_for_block(self, sources: list[GanttRun]) -> str:
        levels = self._unique_strings(run.source_level for run in sources if run.source_level)
        if not levels:
            return "composed"
        if len(levels) == 1:
            return levels[0]
        return "+".join(levels[:3])

    def _display_priority(self, lane: str, start: datetime, end: datetime, is_gap: bool) -> float:
        if is_gap:
            return 8.0
        duration_minutes = max(1.0, (end - start).total_seconds() / 60)
        if lane == "meetings":
            return min(99.0, 86.0 + min(10.0, duration_minutes / 12))
        if lane == "comms":
            return min(82.0, 58.0 + min(16.0, duration_minutes / 20))
        if lane == "breaks":
            return 28.0
        return min(88.0, 66.0 + min(18.0, duration_minutes / 30))

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())

    def _compact_text(self, value: Any, limit: int) -> str:
        text = self._clean_text(value)
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "..."

    def _format_range(self, start: datetime, end: datetime) -> str:
        local_start = utc_datetime(start).astimezone(local_timezone())
        local_end = utc_datetime(end).astimezone(local_timezone())
        return f"{local_start:%Y-%m-%d %H:%M}-{local_end:%H:%M}"

    def _overlaps(self, start: datetime, end: datetime, other_start: datetime, other_end: datetime) -> bool:
        return start < other_end and end > other_start

    def _float(self, value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default
