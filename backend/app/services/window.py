from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.time import db_datetime, local_day_bounds_utc, local_today, utc_datetime
from ..models import Event, EventType, LLMRun, Message, Policy, Window, WindowStatus
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
from .llm import DayStoryPayload, llm_service


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
            elif buffer.token_estimate >= settings.window_token_limit:
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
        )

    def _duration_minutes(self, window: Window) -> int:
        started_at = utc_datetime(window.started_at)
        ended_at = utc_datetime(window.ended_at)
        seconds = max(0, int((ended_at - started_at).total_seconds()))
        return max(1, (seconds + 59) // 60)

    def _day_story(self, target_day: date, segments: list[ActivitySegment]) -> dict[str, str] | None:
        if not segments or not settings.dashboard_story_llm_enabled:
            return None
        story_segments = self._story_segments_for_summary(segments)
        payload = DayStoryPayload(
            day=target_day.isoformat(),
            total_segments=len(segments),
            segments=[
                {
                    "time_range": f"{self._story_time(segment.captured_from)}-{self._story_time(segment.captured_to)}",
                    "headline": segment.headline,
                    "summary": segment.summary,
                    "project": segment.project,
                    "activity_label": segment.activity_label,
                    "activity_type": segment.activity_type,
                    "duration_minutes": segment.duration_minutes,
                }
                for segment in story_segments
            ],
        )
        result = llm_service.summarize_day_story_sync(payload)
        if not result:
            return None
        return {
            "headline": result.headline,
            "summary": result.summary,
            "model_name": result.model_name,
        }

    def _story_time(self, value: datetime) -> str:
        hour = value.hour % 12 or 12
        suffix = "am" if value.hour < 12 else "pm"
        return f"{hour}:{value.minute:02d}{suffix}"

    def _story_segments_for_summary(self, segments: list[ActivitySegment]) -> list[ActivitySegment]:
        limit = max(1, settings.dashboard_story_segment_limit)
        if len(segments) <= limit:
            return segments

        def score(segment: ActivitySegment) -> int:
            points = segment.duration_minutes
            if segment.activity_type == "deep_work":
                points += 60
            elif segment.activity_type in {"communication", "admin"}:
                points += 30
            if segment.focus_state == "focused":
                points += 20
            if segment.project != "General work":
                points += 10
            return points

        selected: dict[str, ActivitySegment] = {}

        def keep(segment: ActivitySegment | None) -> None:
            if segment:
                selected[segment.window_id] = segment

        keep(segments[0])
        keep(segments[-1])
        keep(max((segment for segment in segments if segment.activity_type == "deep_work"), key=score, default=None))
        keep(
            max(
                (segment for segment in segments if segment.activity_type in {"communication", "admin"}),
                key=score,
                default=None,
            )
        )

        for segment in sorted(segments, key=score, reverse=True):
            keep(segment)
            if len(selected) >= limit:
                break

        return sorted(selected.values(), key=lambda segment: segment.captured_from)[:limit]

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
        stmt = (
            select(Window)
            .where(
                Window.started_at >= db_datetime(day_start_utc),
                Window.started_at < db_datetime(day_end_utc),
            )
            .order_by(Window.started_at.asc())
        )
        windows = list(self.db.scalars(stmt))
        for window in windows:
            window.status = WindowStatus.QUEUED
            window.retry_count = 0
        self.db.flush()
        return [window.id for window in windows]


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
