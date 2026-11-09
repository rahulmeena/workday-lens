from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.time import db_datetime, local_day_bounds_utc, local_timezone, local_today, utc_datetime
from ..models import ActivityGanttCache, ActivityRollup, Event, EventType, LLMRun, Message, Policy, Window, WindowStatus
from ..schemas import (
    ActivityBreakdownItem,
    ActivityDashboardResponse,
    ActivityDashboardSummary,
    ActivitySegment,
    ActivityWindow,
    PaginatedResponse,
    ViolationItem,
    ViolationListResponse,
    WindowDetailResponse,
)
from .analysis import activity_type_label, focus_state_label, parse_activity_analysis
from .llm import DayStoryPayload, DayStoryResult, llm_service


DASHBOARD_STORY_CACHE_MODE = "dashboard-story"
DASHBOARD_STORY_CACHE_VERSION = "dashboard-story-v2"
DASHBOARD_STORY_4H_LIMIT = 4
DASHBOARD_STORY_1H_LIMIT = 6


@dataclass
class BufferState:
    session_id: str
    started_at: datetime
    last_seen_at: datetime
    message_ids: List[int] = field(default_factory=list)
    token_estimate: int = 0


class WindowAssembler:
    def __init__(self) -> None:
        self._buffers: Dict[str, BufferState] = {}
        self._lock = asyncio.Lock()

    async def add_message(self, db: Session, message: Message) -> list[str]:
        new_windows: list[str] = []
        async with self._lock:
            buffer = self._buffers.get(message.session_id)
            if buffer and (message.captured_at - buffer.started_at).total_seconds() >= settings.window_max_seconds:
                finalized = await self._finalize_buffer(db, buffer)
                if finalized:
                    new_windows.append(finalized)
                buffer = None
            if buffer is None:
                buffer = BufferState(
                    session_id=message.session_id,
                    started_at=message.captured_at,
                    last_seen_at=message.captured_at,
                )
                self._buffers[message.session_id] = buffer
            buffer.message_ids.append(message.id)
            buffer.last_seen_at = message.captured_at
            buffer.token_estimate += self._estimate_tokens(message.text)
            duration = (buffer.last_seen_at - buffer.started_at).total_seconds()
            should_close = False
            if duration >= settings.window_max_seconds:
                should_close = True
            elif duration >= settings.window_min_seconds and len(buffer.message_ids) > 1:
                should_close = True
            if should_close:
                finalized = await self._finalize_buffer(db, buffer)
                if finalized:
                    new_windows.append(finalized)
        return new_windows

    async def flush_all(self, db: Session) -> list[str]:
        queued: list[str] = []
        async with self._lock:
            for buffer in list(self._buffers.values()):
                finalized = await self._finalize_buffer(db, buffer)
                if finalized:
                    queued.append(finalized)
            self._buffers.clear()
        return queued

    async def _finalize_buffer(self, db: Session, buffer: BufferState) -> str | None:
        if not buffer.message_ids:
            self._buffers.pop(buffer.session_id, None)
            return None
        window = Window(
            session_id=buffer.session_id,
            started_at=buffer.started_at,
            ended_at=buffer.last_seen_at,
            token_count=buffer.token_estimate,
            status=WindowStatus.QUEUED,
        )
        db.add(window)
        db.flush()
        stmt = update(Message).where(Message.id.in_(buffer.message_ids)).values(window_id=window.id)
        db.execute(stmt)
        db.flush()
        self._buffers.pop(buffer.session_id, None)
        return window.id

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text.split()))


class WindowReadService:
    def __init__(self, db: Session):
        self.db = db

    def employee_activity(self, limit: int = 20, cursor: str | None = None, status: WindowStatus | None = None) -> PaginatedResponse:
        stmt: Select = select(Window).order_by(Window.started_at.desc()).limit(limit + 1)
        if status:
            stmt = stmt.where(Window.status == status)
        if cursor:
            stmt = stmt.where(Window.started_at < db_datetime(datetime.fromisoformat(cursor)))
        windows = self.db.scalars(stmt).all()
        next_cursor = None
        if len(windows) > limit:
            next_cursor = utc_datetime(windows[-1].started_at).isoformat()
            windows = windows[:limit]
        data = []
        for window in windows:
            analysis, latest_run = self._window_analysis(window)
            confidence = latest_run.confidence if latest_run else analysis["confidence"]
            verdict = latest_run.verdict if latest_run else window.status
            excerpt = self._load_excerpt(window)
            data.append(
                ActivityWindow(
                    id=window.id,
                    captured_from=utc_datetime(window.started_at),
                    captured_to=utc_datetime(window.ended_at),
                    raw_excerpt=excerpt,
                    llm_summary=analysis["summary"],
                    verdict=verdict,
                    confidence=confidence,
                )
            )
        return PaginatedResponse(data=data, next_cursor=next_cursor)

    def activity_dashboard(self, day: date | None = None) -> ActivityDashboardResponse:
        target_day = day or local_today()
        windows = self._windows_for_day(target_day)
        segments: list[ActivitySegment] = []
        breakdown_minutes: dict[str, int] = defaultdict(int)
        breakdown_segments: dict[str, int] = defaultdict(int)
        project_minutes: dict[str, int] = defaultdict(int)
        project_segments: dict[str, int] = defaultdict(int)
        total_minutes = 0
        focused_minutes = 0
        activity_switches = 0
        longest_focus_block_minutes = 0
        pending_windows = 0
        active_projects: set[str] = set()
        previous_signature: tuple[str, str] | None = None

        for window in windows:
            segment = self._segment_from_window(window)
            segments.append(segment)
            total_minutes += segment.duration_minutes
            breakdown_minutes[segment.activity_type] += segment.duration_minutes
            breakdown_segments[segment.activity_type] += 1
            project_minutes[segment.project] += segment.duration_minutes
            project_segments[segment.project] += 1
            if segment.project != "General work":
                active_projects.add(segment.project)
            if segment.focus_state == "focused":
                focused_minutes += segment.duration_minutes
                longest_focus_block_minutes = max(longest_focus_block_minutes, segment.duration_minutes)
            if segment.status in {WindowStatus.QUEUED, WindowStatus.PROCESSING, WindowStatus.PENDING_LLM}:
                pending_windows += 1
            signature = (segment.activity_type, segment.project)
            if previous_signature and signature != previous_signature:
                activity_switches += 1
            previous_signature = signature

        if not active_projects and segments:
            active_projects.add("General work")

        current_intent = segments[-1] if segments else None
        day_story = self._day_story(target_day, segments)
        breakdown = self._build_breakdown(breakdown_minutes, breakdown_segments, use_activity_labels=True)
        project_breakdown = self._build_breakdown(project_minutes, project_segments, use_activity_labels=False)
        summary = ActivityDashboardSummary(
            total_tracked_minutes=total_minutes,
            focused_minutes=focused_minutes,
            activity_switches=activity_switches,
            active_projects=len(active_projects),
            captured_windows=len(segments),
            pending_windows=pending_windows,
            longest_focus_block_minutes=longest_focus_block_minutes,
        )
        return ActivityDashboardResponse(
            date=target_day,
            summary=summary,
            current_intent=current_intent,
            story_headline=day_story["headline"] if day_story else None,
            story_summary=day_story["summary"] if day_story else None,
            story_model_name=day_story["model_name"] if day_story else None,
            breakdown=breakdown,
            project_breakdown=project_breakdown,
            segments=segments,
        )

    def _load_excerpt(self, window: Window) -> str:
        ordered = sorted(window.messages, key=lambda msg: msg.captured_at)
        texts = [msg.text for msg in ordered[:5]]
        return "\n".join(texts)

    def violation_feed(self, limit: int = 20, cursor: str | None = None) -> ViolationListResponse:
        stmt: Select = (
            select(Event)
            .where(Event.type == EventType.VIOLATION)
            .order_by(Event.created_at.desc())
            .limit(limit + 1)
        )
        if cursor:
            stmt = stmt.where(Event.created_at < db_datetime(datetime.fromisoformat(cursor)))
        events = self.db.scalars(stmt).all()
        next_cursor = None
        if len(events) > limit:
            next_cursor = utc_datetime(events[-1].created_at).isoformat()
            events = events[:limit]
        items = [
            ViolationItem(
                window_id=event.window_id,
                captured_from=utc_datetime(event.window.started_at),
                captured_to=utc_datetime(event.window.ended_at),
                title=event.title,
                detail=event.detail,
                created_at=utc_datetime(event.created_at),
            )
            for event in events
        ]
        return ViolationListResponse(data=items, next_cursor=next_cursor)

    def window_detail(self, window_id: str) -> WindowDetailResponse:
        window = self.db.get(Window, window_id)
        if not window:
            raise ValueError("Window not found")
        ordered_messages = sorted(window.messages, key=lambda msg: msg.captured_at)
        messages = [msg.text for msg in ordered_messages]
        analysis, latest_run = self._window_analysis(window)
        return WindowDetailResponse(
            window_id=window.id,
            session_id=window.session_id,
            started_at=utc_datetime(window.started_at),
            ended_at=utc_datetime(window.ended_at),
            status=window.status,
            token_count=window.token_count,
            messages=messages,
            summary=analysis["summary"] if latest_run else None,
            verdict=latest_run.verdict if latest_run else None,
            confidence=latest_run.confidence if latest_run else None,
            model_name=latest_run.model_name if latest_run else None,
            latency_ms=latest_run.latency_ms if latest_run else None,
        )

    def count_pending(self) -> int:
        stmt = select(func.count()).select_from(Window).where(Window.status == WindowStatus.PENDING_LLM)
        return self.db.scalar(stmt) or 0

    def violations_today(self) -> int:
        day_start_utc, day_end_utc = local_day_bounds_utc(local_today())
        stmt = select(func.count()).select_from(Event).where(
            Event.type == EventType.VIOLATION,
            Event.created_at >= db_datetime(day_start_utc),
            Event.created_at < db_datetime(day_end_utc),
        )
        return self.db.scalar(stmt) or 0

    def _windows_for_day(self, target_day: date) -> list[Window]:
        day_start_utc, day_end_utc = local_day_bounds_utc(target_day)
        if target_day == local_today():
            day_end_utc = min(day_end_utc, utc_datetime(datetime.now(local_timezone())))
        stmt = (
            select(Window)
            .where(
                Window.started_at >= db_datetime(day_start_utc),
                Window.started_at < db_datetime(day_end_utc),
            )
            .order_by(Window.started_at.asc())
        )
        return list(self.db.scalars(stmt))

    def _window_analysis(self, window: Window) -> tuple[dict[str, str | float], LLMRun | None]:
        latest_run = max(window.runs, key=lambda run: run.created_at) if window.runs else None
        excerpt = self._load_excerpt(window)
        analysis = parse_activity_analysis(
            latest_run.summary_text if latest_run else "",
            fallback_excerpt=excerpt,
        )
        if latest_run:
            analysis["confidence"] = latest_run.confidence
        return analysis, latest_run

    def _segment_from_window(self, window: Window) -> ActivitySegment:
        analysis, latest_run = self._window_analysis(window)
        excerpt = self._load_excerpt(window)
        duration_minutes = self._duration_minutes(window)
        status = (
            window.status
            if window.status in {WindowStatus.QUEUED, WindowStatus.PROCESSING, WindowStatus.PENDING_LLM}
            else latest_run.verdict if latest_run else window.status
        )
        return ActivitySegment(
            window_id=window.id,
            captured_from=utc_datetime(window.started_at),
            captured_to=utc_datetime(window.ended_at),
            duration_minutes=duration_minutes,
            status=status,
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

    def _duration_minutes(self, window: Window) -> int:
        started_at = utc_datetime(window.started_at)
        ended_at = utc_datetime(window.ended_at)
        seconds = max(0, int((ended_at - started_at).total_seconds()))
        return max(1, (seconds + 59) // 60)

    def _day_story(self, target_day: date, segments: list[ActivitySegment]) -> dict[str, str] | None:
        story_sources = self._dashboard_story_sources(target_day)
        if settings.dashboard_story_llm_enabled and story_sources:
            dashboard_story = self._cached_or_build_dashboard_story(target_day, story_sources)
            if dashboard_story:
                return dashboard_story

        day_rollup = self._latest_rollup("1d", *local_day_bounds_utc(target_day))
        if day_rollup:
            return self._story_from_rollup(day_rollup)
        if story_sources:
            return self._quick_source_story(story_sources)
        return None

    def _latest_rollup(self, level: str, start: datetime, end: datetime) -> ActivityRollup | None:
        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level == level,
                ActivityRollup.started_at >= db_datetime(start),
                ActivityRollup.started_at < db_datetime(end),
                ActivityRollup.status == WindowStatus.PROCESSED,
            )
            .order_by(ActivityRollup.updated_at.desc(), ActivityRollup.created_at.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    def _rollups_for_story(self, level: str, start: datetime, end: datetime) -> list[ActivityRollup]:
        stmt = (
            select(ActivityRollup)
            .where(
                ActivityRollup.level == level,
                ActivityRollup.started_at >= db_datetime(start),
                ActivityRollup.started_at < db_datetime(end),
                ActivityRollup.status == WindowStatus.PROCESSED,
            )
            .order_by(ActivityRollup.started_at.asc())
        )
        return list(self.db.scalars(stmt))

    def _story_from_rollup(self, rollup: ActivityRollup) -> dict[str, str]:
        analysis = parse_activity_analysis(rollup.summary_text)
        return {
            "headline": str(analysis["headline"]),
            "summary": str(analysis["summary"]),
            "model_name": rollup.model_name or "activity-rollup",
        }

    def _dashboard_story_sources(self, target_day: date) -> list[dict[str, Any]]:
        day_start_utc, day_end_utc = local_day_bounds_utc(target_day)
        day_rollup = self._latest_rollup("1d", day_start_utc, day_end_utc)
        if day_rollup:
            four_hour_sources = [
                self._story_source_from_rollup(rollup, target_day)
                for rollup in self._rollups_for_story("4h", day_start_utc, day_end_utc)
            ]
            selected_four_hour_sources = self._select_story_sources(four_hour_sources, DASHBOARD_STORY_4H_LIMIT)
            latest_four_hour_end = max(
                (source.get("_ended_at") for source in selected_four_hour_sources if isinstance(source.get("_ended_at"), datetime)),
                default=None,
            )
            one_hour_rollups = self._rollups_for_story("1h", day_start_utc, day_end_utc)
            if latest_four_hour_end:
                one_hour_rollups = [
                    rollup
                    for rollup in one_hour_rollups
                    if utc_datetime(rollup.ended_at) <= utc_datetime(latest_four_hour_end)
                ]
            else:
                one_hour_rollups = []
            one_hour_sources = [self._story_source_from_rollup(rollup, target_day) for rollup in one_hour_rollups]
            return [
                self._story_source_from_rollup(day_rollup, target_day, role="anchor"),
                *selected_four_hour_sources,
                *self._select_story_sources(one_hour_sources, DASHBOARD_STORY_1H_LIMIT),
            ]

        one_hour_sources = [
            self._story_source_from_rollup(rollup, target_day)
            for rollup in self._rollups_for_story("1h", day_start_utc, day_end_utc)
        ]
        return self._select_story_sources(one_hour_sources, DASHBOARD_STORY_1H_LIMIT)

    def _story_source_from_rollup(
        self,
        rollup: ActivityRollup,
        target_day: date,
        *,
        role: str = "support",
    ) -> dict[str, Any]:
        analysis = parse_activity_analysis(rollup.summary_text)
        started_at = utc_datetime(rollup.started_at)
        ended_at = utc_datetime(rollup.ended_at)
        seconds = max(0, int((ended_at - started_at).total_seconds()))
        summary_hash = hashlib.sha256((rollup.summary_text or "").encode("utf-8")).hexdigest()[:16]
        updated_at = rollup.updated_at or rollup.created_at or rollup.started_at
        updated = utc_datetime(updated_at).isoformat() if updated_at else ""
        source_count = int(rollup.source_count or 0)
        return {
            "id": rollup.id,
            "source_level": rollup.level,
            "source_role": role,
            "time_range": self._story_source_time_range(rollup.level, started_at, ended_at, target_day),
            "headline": str(analysis["headline"]),
            "summary": str(analysis["summary"]),
            "dominant_goal": str(analysis.get("dominant_goal") or analysis["goal"]),
            "project": str(analysis["project"]),
            "activity_type": str(analysis["activity_type"]),
            "activity_label": activity_type_label(str(analysis["activity_type"])),
            "focus_state": str(analysis["focus_state"]),
            "focus_label": focus_state_label(str(analysis["focus_state"])),
            "confidence": float(analysis["confidence"]),
            "source_count": source_count,
            "duration_minutes": max(1, (seconds + 59) // 60),
            "_started_at": started_at,
            "_ended_at": ended_at,
            "_signature": f"{rollup.level}:{rollup.id}:{updated}:{rollup.status.value}:{source_count}:{summary_hash}",
        }

    def _story_source_time_range(self, level: str, start: datetime, end: datetime, target_day: date) -> str:
        if level == "1d":
            return "Day so far" if target_day == local_today() else f"{target_day.strftime('%b')} {target_day.day}"
        return f"{self._story_time(start)}-{self._story_time(end)}"

    def _select_story_sources(self, sources: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if len(sources) <= limit:
            return sorted(sources, key=self._story_source_sort_key)

        selected: dict[str, dict[str, Any]] = {}

        def keep(source: dict[str, Any] | None) -> None:
            if source:
                selected[str(source["id"])] = source

        ordered = sorted(sources, key=self._story_source_sort_key)
        keep(ordered[0])
        keep(ordered[-1])
        keep(
            max(
                (
                    source
                    for source in sources
                    if source.get("activity_type") == "deep_work" or source.get("focus_state") == "focused"
                ),
                key=self._story_source_score,
                default=None,
            )
        )
        keep(
            max(
                (source for source in sources if source.get("activity_type") in {"communication", "admin"}),
                key=self._story_source_score,
                default=None,
            )
        )
        for source in sorted(sources, key=self._story_source_score, reverse=True):
            keep(source)
            if len(selected) >= limit:
                break

        return sorted(selected.values(), key=self._story_source_sort_key)[:limit]

    def _story_source_score(self, source: dict[str, Any]) -> float:
        points = float(source.get("duration_minutes") or 0)
        if source.get("activity_type") == "deep_work":
            points += 60
        elif source.get("activity_type") in {"communication", "admin"}:
            points += 30
        if source.get("focus_state") == "focused":
            points += 20
        if source.get("project") != "General work":
            points += 10
        points += min(10, float(source.get("source_count") or 0))
        return points

    def _story_source_sort_key(self, source: dict[str, Any]) -> datetime:
        started_at = source.get("_started_at")
        return utc_datetime(started_at) if isinstance(started_at, datetime) else datetime.min.replace(tzinfo=local_timezone())

    def _cached_or_build_dashboard_story(self, target_day: date, sources: list[dict[str, Any]]) -> dict[str, str] | None:
        day_start_utc, day_end_utc = local_day_bounds_utc(target_day)
        source_signature = self._dashboard_story_signature(target_day, sources)
        cached = self._cached_dashboard_story(day_start_utc, day_end_utc, source_signature)
        if cached:
            return cached

        result = llm_service.summarize_day_story_sync(
            DayStoryPayload(
                day=target_day.isoformat(),
                total_segments=len(sources),
                segments=sources,
            )
        )
        if result:
            story = {
                "headline": result.headline,
                "summary": result.summary,
                "model_name": result.model_name,
            }
            self._store_dashboard_story(day_start_utc, day_end_utc, source_signature, story, result)
            return story

        story = self._quick_source_story(sources)
        self._store_dashboard_story(day_start_utc, day_end_utc, source_signature, story, None)
        return story

    def _dashboard_story_signature(self, target_day: date, sources: list[dict[str, Any]]) -> str:
        parts = [
            DASHBOARD_STORY_CACHE_VERSION,
            settings.llm_provider,
            settings.dashboard_story_model,
            "fake" if settings.fake_llm_mode else "live",
            "key" if settings.openai_api_key_configured() else "no-key",
            target_day.isoformat(),
        ]
        parts.extend(str(source.get("_signature") or source.get("id") or "") for source in sources)
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _cached_dashboard_story(self, start: datetime, end: datetime, source_signature: str) -> dict[str, str] | None:
        cache = self._find_dashboard_story_cache(start, end)
        if not cache or cache.source_signature != source_signature or not cache.payload_json:
            return None
        try:
            payload = json.loads(cache.payload_json)
        except (json.JSONDecodeError, TypeError):
            return None
        headline = str(payload.get("headline") or "").strip() if isinstance(payload, dict) else ""
        summary = str(payload.get("summary") or "").strip() if isinstance(payload, dict) else ""
        model_name = str(payload.get("model_name") or cache.model_name or "").strip() if isinstance(payload, dict) else ""
        if not headline or not summary:
            return None
        return {
            "headline": headline,
            "summary": summary,
            "model_name": model_name or "dashboard-story-cache",
        }

    def _find_dashboard_story_cache(self, start: datetime, end: datetime) -> ActivityGanttCache | None:
        stmt = select(ActivityGanttCache).where(
            ActivityGanttCache.mode == DASHBOARD_STORY_CACHE_MODE,
            ActivityGanttCache.started_at == db_datetime(start),
            ActivityGanttCache.ended_at == db_datetime(end),
        )
        return self.db.scalars(stmt).first()

    def _store_dashboard_story(
        self,
        start: datetime,
        end: datetime,
        source_signature: str,
        story: dict[str, str],
        result: DayStoryResult | None,
    ) -> None:
        cache = self._find_dashboard_story_cache(start, end)
        if not cache:
            cache = ActivityGanttCache(
                mode=DASHBOARD_STORY_CACHE_MODE,
                started_at=db_datetime(start),
                ended_at=db_datetime(end),
            )
            self.db.add(cache)
        model_name = story.get("model_name") or "local-dashboard-story"
        cache.source_signature = source_signature
        cache.status = "processed" if result else "fallback"
        cache.model_name = model_name
        cache.prompt_tokens = result.prompt_tokens if result else 0
        cache.completion_tokens = result.completion_tokens if result else 0
        cache.total_tokens = (result.prompt_tokens + result.completion_tokens) if result else 0
        cache.latency_ms = result.latency_ms if result else 0
        cache.payload_json = json.dumps(
            {
                "headline": story.get("headline") or "",
                "summary": story.get("summary") or "",
                "model_name": model_name,
                "generated_at": datetime.now(local_timezone()).isoformat(),
            },
            ensure_ascii=True,
        )
        self.db.commit()

    def _quick_source_story(self, sources: list[dict[str, Any]]) -> dict[str, str]:
        story_sources = [source for source in sources if source.get("source_level") != "1d"] or sources
        focus_sources = [
            source
            for source in story_sources
            if source.get("activity_type") == "deep_work" or source.get("focus_state") == "focused"
        ]
        coordination = [source for source in story_sources if source.get("activity_type") in {"communication", "admin"}]
        strongest = max(story_sources, key=self._story_source_score)
        deepest = max(focus_sources, key=self._story_source_score, default=None)
        coordination_minutes = sum(int(source.get("duration_minutes") or 0) for source in coordination)
        focus_source = deepest or strongest
        headline = str(focus_source.get("headline") or "Day story building")
        if deepest:
            summary = (
                f"The strongest focus stretch was {deepest.get('time_range', 'earlier in the day')} on "
                f"{deepest.get('headline', 'a core task')}. "
                f"Coordination took {self._format_minutes(coordination_minutes)}, with the rest of the day grouped around the main thread."
            )
        else:
            summary = (
                f"The day currently centers on {strongest.get('headline', 'one main thread')}, with shorter supporting activity around "
                f"{strongest.get('project') or 'General work'}."
            )
        return {
            "headline": headline,
            "summary": summary,
            "model_name": "local-dashboard-summary",
        }

    def _story_time(self, value: datetime) -> str:
        local_value = utc_datetime(value).astimezone(local_timezone())
        hour = local_value.hour % 12 or 12
        suffix = "am" if local_value.hour < 12 else "pm"
        return f"{hour}:{local_value.minute:02d}{suffix}"

    def _format_minutes(self, minutes: int) -> str:
        if minutes <= 0:
            return "almost no time"
        hours, remainder = divmod(minutes, 60)
        if hours and remainder:
            return f"{hours}h {remainder}m"
        if hours:
            return f"{hours}h"
        return f"{remainder}m"

    def _build_breakdown(
        self,
        minutes_map: dict[str, int],
        segments_map: dict[str, int],
        *,
        use_activity_labels: bool,
    ) -> list[ActivityBreakdownItem]:
        items = []
        for key, minutes in sorted(minutes_map.items(), key=lambda item: (-item[1], item[0])):
            label = activity_type_label(key) if use_activity_labels else key
            items.append(
                ActivityBreakdownItem(
                    label=label,
                    minutes=minutes,
                    segments=segments_map.get(key, 0),
                )
            )
        return items


class WindowReanalysisService:
    def __init__(self, db: Session):
        self.db = db

    def queue_day(self, target_day: date) -> list[str]:
        day_start_utc, day_end_utc = local_day_bounds_utc(target_day)
        window_ids, _ = self.queue_range(day_start_utc, day_end_utc, mode="all")
        return window_ids

    def queue_range(self, start: datetime, end: datetime, *, mode: str = "all") -> tuple[list[str], int]:
        stmt = (
            select(Window)
            .where(
                Window.started_at >= db_datetime(start),
                Window.started_at < db_datetime(end),
            )
            .order_by(Window.started_at.asc())
        )
        if mode == "pending":
            stmt = stmt.where(Window.status == WindowStatus.PENDING_LLM)
        windows = list(self.db.scalars(stmt))
        for window in windows:
            window.status = WindowStatus.QUEUED
            window.retry_count = 0
        result = self.db.execute(
            delete(ActivityRollup).where(
                ActivityRollup.started_at < db_datetime(end),
                ActivityRollup.ended_at > db_datetime(start),
            )
        )
        self.db.flush()
        return [window.id for window in windows], int(result.rowcount or 0)


class PolicyService:
    def __init__(self, db: Session):
        self.db = db

    def list_policies(self, include_inactive: bool = False) -> list[Policy]:
        stmt = select(Policy)
        if not include_inactive:
            stmt = stmt.where(Policy.active.is_(True))
        stmt = stmt.order_by(Policy.created_at.asc())
        return self.db.scalars(stmt).all()

    def get_active_policy(self) -> Policy | None:
        stmt = select(Policy).where(Policy.active.is_(True)).order_by(Policy.updated_at.desc()).limit(1)
        return self.db.scalars(stmt).first()

    def create_policy(self, text: str, examples: list[str] | None) -> Policy:
        policy = Policy(text=text, examples_json=self._serialize_examples(examples), active=True)
        self.db.add(policy)
        self.db.flush()
        return policy

    def update_policy(
        self,
        policy_id: str,
        text: str | None,
        examples: list[str] | None,
        active: bool | None,
    ) -> Policy:
        policy = self.db.get(Policy, policy_id)
        if not policy:
            raise ValueError("Policy not found")
        if text is not None:
            policy.text = text
        if examples is not None:
            policy.examples_json = self._serialize_examples(examples)
        if active is not None:
            policy.active = active
        self.db.flush()
        return policy

    def archive_policy(self, policy_id: str) -> Policy | None:
        policy = self.db.get(Policy, policy_id)
        if not policy:
            return None
        policy.active = False
        self.db.flush()
        return policy

    @staticmethod
    def _serialize_examples(examples: list[str] | None) -> str | None:
        if not examples:
            return None
        filtered = [line.strip() for line in examples if line and line.strip()]
        return "\n".join(filtered) if filtered else None
