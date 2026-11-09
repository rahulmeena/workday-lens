from __future__ import annotations

import asyncio
from collections import Counter
import json
from dataclasses import dataclass
import re
import time
from threading import Lock
from typing import Any, Dict, List

from ..core.config import settings
from ..models import WindowStatus
from .analysis import normalize_activity_analysis


_JSON_RESPONSE_SCHEMA = {
    'name': 'wfhs_activity_analysis',
    'schema': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'headline': {
                'type': 'string',
                'description': 'Short title for the current work segment'
            },
            'summary': {
                'type': 'string',
                'description': 'Short explanation of what the user appears to be doing'
            },
            'goal': {
                'type': 'string',
                'description': 'Likely goal or deliverable the user is trying to complete'
            },
            'project': {
                'type': 'string',
                'description': 'Project, initiative, or workstream if it can be inferred'
            },
            'activity_type': {
                'type': 'string',
                'enum': ['deep_work', 'planning', 'research', 'review', 'communication', 'admin', 'break', 'other']
            },
            'focus_state': {
                'type': 'string',
                'enum': ['focused', 'steady', 'switching', 'blocked', 'idle']
            },
            'next_step': {
                'type': 'string',
                'description': 'Likely next meaningful step after this segment'
            },
            'confidence': {
                'type': 'number',
                'minimum': 0,
                'maximum': 1,
                'description': 'Confidence score between 0 and 1'
            }
        },
        'required': ['headline', 'summary', 'activity_type', 'focus_state'],
    },
}


_MOUSE_HOVER_RE = re.compile(
    r"\[mouse hover\s+appName=(?P<app>.*?)\s+"
    r"x=(?P<x>-?\d+)\s+y=(?P<y>-?\d+)\s+"
    r"location=(?P<left>-?\d+),(?P<top>-?\d+),(?P<width>\d+)x(?P<height>\d+)\]"
)
_MOUSE_ACTION_RE = re.compile(r"\[mouse action\]\s+(?P<payload>\{.*\})")
_TRANSCRIPT_TIMESTAMP_RE = re.compile(r"^\[(?P<timestamp>[^\]]+)\]\s+")
_SCROLL_ACTIONS = {"scrollUp", "scrollDown", "scrollLeft", "scrollRight", "scrollStop"}


class LLMServiceError(Exception):
    pass


class LLMTimeoutError(LLMServiceError):
    pass


@dataclass
class LLMWindowPayload:
    window_id: str
    session_id: str
    text: str
    policy: str | None
    examples: List[str]
    context_summaries: List[str]


@dataclass
class LLMResult:
    summary: str
    verdict: WindowStatus
    confidence: float
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    model_name: str
    analysis_payload: Dict[str, Any]


@dataclass
class DayStoryPayload:
    day: str
    total_segments: int
    segments: List[Dict[str, Any]]


@dataclass
class DayStoryResult:
    headline: str
    summary: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class LLMService:
    def __init__(self) -> None:
        self._client = None
        self._client_signature: tuple[bool, str] | None = None
        self._client_lock = Lock()
        self.reload_from_settings()

    def reload_from_settings(self) -> None:
        signature = (settings.fake_llm_mode, settings.openai_api_key)
        with self._client_lock:
            if signature == self._client_signature:
                return
            self._client = self._build_client(settings.openai_api_key, settings.fake_llm_mode)
            self._client_signature = signature
        if self._client:
            print(f"[LLM] OpenAI client initialized (model={settings.llm_model})")
        else:
            mode = "fake" if settings.fake_llm_mode else "disabled"
            print(f"[LLM] Using {mode} LLM mode; requests will not reach OpenAI")

    def _build_client(self, api_key: str, fake_llm_mode: bool):
        if fake_llm_mode:
            return None
        try:
            from openai import AsyncOpenAI
        except ImportError:  # pragma: no cover
            return None
        if not api_key:
            return None
        return AsyncOpenAI(api_key=api_key)

    async def evaluate_window(self, payload: LLMWindowPayload) -> LLMResult:
        self.reload_from_settings()
        prompt = self._build_prompt(payload)
        print(f"[LLM] Evaluating window {payload.window_id} (session={payload.session_id})")
        if settings.fake_llm_mode:
            print('[LLM] Using fake LLM path')
            return await self._fake_response(payload, prompt)
        if not self._client:
            raise LLMServiceError("OpenAI API key is not configured.")
        start = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._client.responses.create(
                    model=settings.llm_model,
                    input=prompt,
                    reasoning={"effort": "medium"},
                    text={"verbosity": "low"},
                ),
                timeout=settings.llm_timeout_seconds,
            )
            print(f"[LLM] Raw response: {response.model_dump_json(indent=2) if hasattr(response, 'model_dump_json') else response}")
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] OpenAI timeout for window {payload.window_id}")
            raise LLMTimeoutError("LLM timed out") from exc
        except Exception as exc:  # pragma: no cover
            print(f"[LLM] OpenAI call failed for window {payload.window_id}: {exc}")
            raise LLMServiceError("LLM call failed") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        print(f"[LLM] OpenAI call succeeded in {latency_ms} ms for window {payload.window_id}")
        content = getattr(response, "output_text", None)
        if not content:
            try:
                content = response.output[0].content[0].text  # type: ignore[attr-defined]
            except Exception:
                content = ""
        parsed_payload = self._extract_structured_payload(content)
        analysis_payload = normalize_activity_analysis(
            parsed_payload,
            fallback_text=content,
            transcript=payload.text,
        )
        verdict = WindowStatus.PROCESSED
        confidence = analysis_payload["confidence"]
        summary_text = analysis_payload["summary"]
        usage = getattr(response, "usage", None)
        prompt_tokens = 0
        completion_tokens = 0
        if usage is not None:
            if isinstance(usage, dict):
                prompt_tokens = int(usage.get('input_tokens') or usage.get('prompt_tokens') or 0)
                completion_tokens = int(usage.get('output_tokens') or usage.get('completion_tokens') or 0)
            else:
                prompt_tokens = int(getattr(usage, 'input_tokens', getattr(usage, 'prompt_tokens', 0)) or 0)
                completion_tokens = int(getattr(usage, 'output_tokens', getattr(usage, 'completion_tokens', 0)) or 0)
        return LLMResult(
            summary=summary_text,
            verdict=verdict,
            confidence=confidence,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            model_name=settings.llm_model,
            analysis_payload=analysis_payload,
        )

    def summarize_day_story_sync(self, payload: DayStoryPayload) -> DayStoryResult | None:
        if not payload.segments:
            return None
        try:
            return asyncio.run(self.summarize_day_story(payload))
        except Exception as exc:
            print(f"[LLM] Day story summarization failed for {payload.day}: {exc}")
            if settings.fake_llm_mode:
                return self._fake_day_story(payload)
            return None

    async def summarize_day_story(self, payload: DayStoryPayload) -> DayStoryResult:
        self.reload_from_settings()
        prompt = self._build_day_story_prompt(payload)
        if settings.fake_llm_mode or not settings.dashboard_story_llm_enabled:
            return self._fake_day_story(payload, prompt=prompt)
        if not self._client:
            raise LLMServiceError("OpenAI API key is not configured.")
        start = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._client.responses.create(
                    model=settings.dashboard_story_model,
                    input=prompt,
                    reasoning={"effort": "medium"},
                    text={"verbosity": "low"},
                ),
                timeout=settings.llm_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] Day story OpenAI timeout for {payload.day}")
            raise LLMTimeoutError("Day story LLM timed out") from exc
        except Exception as exc:  # pragma: no cover
            print(f"[LLM] Day story OpenAI call failed for {payload.day}: {exc}")
            raise LLMServiceError("Day story LLM call failed") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        content = getattr(response, "output_text", None)
        if not content:
            try:
                content = response.output[0].content[0].text  # type: ignore[attr-defined]
            except Exception:
                content = ""
        story = self._extract_day_story_payload(content, payload.segments)
        usage = getattr(response, "usage", None)
        prompt_tokens = 0
        completion_tokens = 0
        if usage is not None:
            if isinstance(usage, dict):
                prompt_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
            else:
                prompt_tokens = int(getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0)
                completion_tokens = int(getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0)
        return DayStoryResult(
            headline=story["headline"],
            summary=story["summary"],
            model_name=settings.dashboard_story_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    def _extract_structured_payload(self, raw_text: str) -> Dict[str, Any] | None:
        raw_text = raw_text.strip() if raw_text else ""
        if not raw_text:
            return None
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _extract_day_story_payload(self, raw_text: str, segments: List[Dict[str, Any]]) -> Dict[str, str]:
        parsed = self._extract_structured_payload(raw_text) or {}
        headline = self._clean_story_text(parsed.get("headline")) if isinstance(parsed, dict) else ""
        summary = self._clean_story_text(parsed.get("summary")) if isinstance(parsed, dict) else ""
        if not headline or not summary:
            fallback = self._fake_day_story_from_segments(segments)
            return {
                "headline": headline or fallback["headline"],
                "summary": summary or fallback["summary"],
            }
        return {
            "headline": headline,
            "summary": summary,
        }

    def _clean_story_text(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.strip().split())

    async def _fake_response(self, payload: LLMWindowPayload, prompt: str) -> LLMResult:
        await asyncio.sleep(0)
        print(f"[LLM] Fake LLM evaluating window {payload.window_id}")
        analysis_payload = self._fake_analysis(payload.text)
        summary = analysis_payload["summary"]
        latency_ms = 5
        tokens = max(1, len(prompt.split()))
        result = LLMResult(
            summary=summary,
            verdict=WindowStatus.PROCESSED,
            confidence=analysis_payload["confidence"],
            prompt_tokens=tokens,
            completion_tokens=len(summary.split()),
            latency_ms=latency_ms,
            model_name="fake-llm",
            analysis_payload=analysis_payload,
        )
        print(
            f"[LLM] Fake LLM result for window {payload.window_id}: "
            f"activity_type={analysis_payload['activity_type']}, "
            f"focus_state={analysis_payload['focus_state']}"
        )
        return result

    def _fake_day_story(self, payload: DayStoryPayload, *, prompt: str = "") -> DayStoryResult:
        story = self._fake_day_story_from_segments(payload.segments)
        tokens = max(1, len(prompt.split())) if prompt else max(1, len(payload.segments) * 18)
        return DayStoryResult(
            headline=story["headline"],
            summary=story["summary"],
            model_name="fake-day-story-llm",
            prompt_tokens=tokens,
            completion_tokens=len(story["summary"].split()) + len(story["headline"].split()),
            latency_ms=5,
        )

    def _fake_day_story_from_segments(self, segments: List[Dict[str, Any]]) -> Dict[str, str]:
        if not segments:
            return {
                "headline": "Day story pending",
                "summary": "There is not enough analyzed activity yet to build a day-level summary.",
            }
        deep_work = [segment for segment in segments if segment.get("activity_type") == "deep_work"]
        meetings = [segment for segment in segments if segment.get("activity_type") in {"communication", "admin"}]
        deepest = max(deep_work, key=lambda segment: int(segment.get("duration_minutes") or 0), default=None)
        total_meeting_minutes = sum(int(segment.get("duration_minutes") or 0) for segment in meetings)
        if deepest:
            headline = deepest.get("headline") or "Strongest focus block"
            summary = (
                f"The strongest focus stretch was {deepest.get('time_range', 'earlier in the day')} on "
                f"{deepest.get('headline', 'a core task')}. Coordination took {self._format_minutes(total_meeting_minutes)}, "
                "leaving the rest of the day to cluster around that main thread."
            )
            return {
                "headline": str(headline),
                "summary": summary,
            }
        top = max(segments, key=lambda segment: int(segment.get("duration_minutes") or 0))
        return {
            "headline": str(top.get("headline") or "The day centered on one dominant thread"),
            "summary": (
                f"Most captured activity pointed toward {top.get('headline', 'one primary thread')}, "
                f"with shorter supporting stretches around it between {top.get('time_range', 'the captured hours')}."
            ),
        }

    def _fake_analysis(self, text: str) -> Dict[str, Any]:
        lowered = text.lower()
        activity_type = "deep_work"
        if any(keyword in lowered for keyword in ("meet", "meeting", "call", "zoom", "sync")):
            activity_type = "communication"
        elif any(keyword in lowered for keyword in ("review", "diff", "pull request", "pr ", "feedback")):
            activity_type = "review"
        elif any(keyword in lowered for keyword in ("research", "investigate", "search", "read", "docs", "documentation")):
            activity_type = "research"
        elif any(keyword in lowered for keyword in ("plan", "roadmap", "timeline", "organize", "todo", "task list")):
            activity_type = "planning"
        elif any(keyword in lowered for keyword in ("email", "slack", "message", "reply", "follow up")):
            activity_type = "communication"
        elif any(keyword in lowered for keyword in ("invoice", "timesheet", "expense", "calendar", "scheduling")):
            activity_type = "admin"
        elif any(keyword in lowered for keyword in ("break", "lunch", "coffee", "walk")):
            activity_type = "break"
        focus_state = "focused"
        if any(keyword in lowered for keyword in ("error", "issue", "blocked", "stuck", "fail", "problem")):
            focus_state = "blocked"
        elif activity_type in {"communication", "admin"}:
            focus_state = "switching"
        elif activity_type == "break":
            focus_state = "idle"
        elif len(text.split()) < 10:
            focus_state = "steady"
        summary = self._summarize_text(text)
        headline = {
            "deep_work": "Making progress on a core task",
            "planning": "Organizing the next chunk of work",
            "research": "Reading and collecting context",
            "review": "Reviewing existing work or feedback",
            "communication": "Coordinating with other people",
            "admin": "Handling operational work",
            "break": "Paused away from active work",
        }.get(activity_type, "Moving through general work")
        return normalize_activity_analysis(
            {
                "headline": headline,
                "summary": summary,
                "goal": self._goal_from_type(activity_type),
                "project": self._project_hint(text),
                "activity_type": activity_type,
                "focus_state": focus_state,
                "next_step": self._next_step_from_type(activity_type),
                "confidence": 0.56 if activity_type == "other" else 0.68,
            },
            transcript=text,
        )

    def _summarize_text(self, text: str) -> str:
        words = text.split()
        if len(words) <= 28:
            return text.strip() or "Captured activity without enough detail to summarize."
        return " ".join(words[:28]) + "..."

    def _project_hint(self, text: str) -> str:
        lowered = text.lower()
        if "security" in lowered:
            return "Security work"
        if "design" in lowered or "ui" in lowered:
            return "Product and design"
        if "api" in lowered or "backend" in lowered or "frontend" in lowered:
            return "Product engineering"
        if "sales" in lowered or "customer" in lowered:
            return "Customer work"
        return "General work"

    def _goal_from_type(self, activity_type: str) -> str:
        goals = {
            "deep_work": "Push the main deliverable closer to done.",
            "planning": "Clarify the path for the next work block.",
            "research": "Find the missing information needed to proceed.",
            "review": "Evaluate current work and decide what changes next.",
            "communication": "Align with others and move shared work forward.",
            "admin": "Keep support tasks from piling up.",
            "break": "Recharge briefly before resuming work.",
        }
        return goals.get(activity_type, "Advance the current workstream.")

    def _next_step_from_type(self, activity_type: str) -> str:
        steps = {
            "deep_work": "Stay with the task until the next visible milestone.",
            "planning": "Convert the plan into one concrete next action.",
            "research": "Turn the gathered context into a decision or draft.",
            "review": "Capture the requested changes and move back into execution.",
            "communication": "Record the decision and return to focused work.",
            "admin": "Close the loop and clear the next routine item.",
            "break": "Resume with the clearest open task.",
        }
        return steps.get(activity_type, "Clarify the next step and continue.")

    def _format_minutes(self, minutes: int) -> str:
        if minutes <= 0:
            return "almost no time"
        hours, remainder = divmod(minutes, 60)
        if hours and remainder:
            return f"{hours}h {remainder}m"
        if hours:
            return f"{hours}h"
        return f"{remainder}m"

    def _build_mouse_hover_context(self, transcript: str) -> List[str]:
        hover_events: list[dict[str, Any]] = []
        for line in transcript.splitlines():
            event = self._parse_mouse_hover_line(line)
            if event:
                hover_events.append(event)
        if not hover_events:
            return []

        app_counts = Counter(str(event["app"]) for event in hover_events)
        rect_counts = Counter(
            (
                str(event["app"]),
                int(event["left"]),
                int(event["top"]),
                int(event["width"]),
                int(event["height"]),
            )
            for event in hover_events
        )
        lines = [
            f"{len(hover_events)} mouse hover events were captured across {self._format_hover_counts(app_counts)}.",
            (
                "A hover tag means pointer context: appName is the app under the cursor; "
                "x/y is the pointer coordinate; location is the hovered UI object's "
                "left,top,widthxheight rectangle."
            ),
        ]

        repeated_regions: list[str] = []
        for (app, left, top, width, height), count in rect_counts.most_common(5):
            repeated_regions.append(
                f"{app} {left},{top},{width}x{height} "
                f"({self._hover_region_size_label(width, height)}, {count}x)"
            )
        if repeated_regions:
            lines.append("Most repeated hover regions: " + "; ".join(repeated_regions) + ".")

        sequence = self._condense_hover_app_sequence(hover_events)
        if sequence:
            lines.append("Condensed app movement sequence: " + " -> ".join(sequence) + ".")
        return lines

    def _compact_mouse_event_transcript(self, transcript: str) -> str:
        lines: list[str] = []
        hover_run: list[dict[str, Any]] = []
        scroll_run: list[dict[str, Any]] = []

        def flush_hover_run() -> None:
            if not hover_run:
                return
            if len(hover_run) == 1:
                lines.append(str(hover_run[0]["line"]))
            else:
                lines.append(self._format_hover_run_summary(hover_run))
            hover_run.clear()

        def flush_scroll_run() -> None:
            if not scroll_run:
                return
            if len(scroll_run) == 1:
                lines.append(str(scroll_run[0]["line"]))
            else:
                lines.append(self._format_scroll_run_summary(scroll_run))
            scroll_run.clear()

        for line in transcript.splitlines():
            hover_event = self._parse_mouse_hover_line(line)
            if hover_event:
                flush_scroll_run()
                hover_run.append(hover_event)
                continue
            action_event = self._parse_mouse_action_line(line)
            if action_event and self._is_scroll_action_event(action_event):
                flush_hover_run()
                scroll_run.append(action_event)
                continue
            flush_hover_run()
            flush_scroll_run()
            lines.append(line)
        flush_hover_run()
        flush_scroll_run()
        return "\n".join(lines)

    def _build_mouse_action_context(self, transcript: str) -> List[str]:
        action_events: list[dict[str, Any]] = []
        for line in transcript.splitlines():
            event = self._parse_mouse_action_line(line)
            if event:
                action_events.append(event)
        if not action_events:
            return []

        action_counts = Counter(str(event.get("action") or "unknown") for event in action_events)
        lines = [
            f"{len(action_events)} mouse action events were captured: {self._format_hover_counts(action_counts)}.",
            (
                "Mouse action tags are ordered input metadata; the transcript line timestamp is the event time. "
                "action names the click, release, scroll direction, or scrollStop; x/y is the pointer coordinate. "
                "Screenshot file paths and capture status are intentionally omitted from the text transcript."
            ),
        ]

        sequence = self._condense_mouse_action_sequence(action_events)
        if sequence:
            lines.append("Condensed mouse action sequence: " + " -> ".join(sequence) + ".")

        return lines

    def _parse_mouse_action_line(self, line: str) -> dict[str, Any] | None:
        match = _MOUSE_ACTION_RE.search(line)
        if not match:
            return None
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        timestamp_match = _TRANSCRIPT_TIMESTAMP_RE.match(line)
        payload = dict(payload)
        payload["line"] = line
        payload["timestamp"] = timestamp_match.group("timestamp") if timestamp_match else ""
        return payload

    def _is_scroll_action_event(self, event: dict[str, Any]) -> bool:
        return str(event.get("action") or "") in _SCROLL_ACTIONS

    def _format_scroll_run_summary(self, scroll_events: list[dict[str, Any]]) -> str:
        first_timestamp = str(scroll_events[0].get("timestamp") or "")
        last_timestamp = str(scroll_events[-1].get("timestamp") or "")
        if first_timestamp and last_timestamp and first_timestamp != last_timestamp:
            timestamp = f"[{first_timestamp} - {last_timestamp}]"
        elif first_timestamp:
            timestamp = f"[{first_timestamp}]"
        else:
            timestamp = "[mouse scroll run]"

        action_counts = Counter(
            str(event.get("action") or "unknown")
            for event in scroll_events
            if str(event.get("action") or "") != "scrollStop"
        )
        if not action_counts:
            action_counts = Counter(str(event.get("action") or "unknown") for event in scroll_events)
        return (
            f"{timestamp} [mouse scroll summary: {len(scroll_events)} consecutive events; "
            f"actions: {self._format_hover_counts(action_counts)}; "
            f"pointer path: {self._format_hover_pointer_path(scroll_events)}]"
        )

    def _condense_mouse_action_sequence(self, action_events: list[dict[str, Any]], limit: int = 16) -> list[str]:
        sequence: list[str] = []
        for event in action_events:
            action = str(event.get("action") or "unknown")
            x = event.get("x")
            y = event.get("y")
            if isinstance(x, int) and isinstance(y, int):
                action = f"{action}@{x},{y}"
            sequence.append(action)
        if len(sequence) <= limit:
            return sequence
        head_count = max(1, limit - 3)
        return sequence[:head_count] + ["..."] + sequence[-2:]

    def _parse_mouse_hover_line(self, line: str) -> dict[str, Any] | None:
        match = _MOUSE_HOVER_RE.search(line)
        if not match:
            return None
        event = match.groupdict()
        timestamp_match = _TRANSCRIPT_TIMESTAMP_RE.match(line)
        try:
            return {
                "line": line,
                "timestamp": timestamp_match.group("timestamp") if timestamp_match else "",
                "app": event["app"].strip() or "unknown",
                "x": int(event["x"]),
                "y": int(event["y"]),
                "left": int(event["left"]),
                "top": int(event["top"]),
                "width": int(event["width"]),
                "height": int(event["height"]),
            }
        except (TypeError, ValueError):
            return None

    def _format_hover_run_summary(self, hover_events: list[dict[str, Any]]) -> str:
        first_timestamp = str(hover_events[0].get("timestamp") or "")
        last_timestamp = str(hover_events[-1].get("timestamp") or "")
        if first_timestamp and last_timestamp and first_timestamp != last_timestamp:
            timestamp = f"[{first_timestamp} - {last_timestamp}]"
        elif first_timestamp:
            timestamp = f"[{first_timestamp}]"
        else:
            timestamp = "[mouse hover run]"

        app_counts = Counter(str(event["app"]) for event in hover_events)
        rect_counts = Counter(
            (
                str(event["app"]),
                int(event["left"]),
                int(event["top"]),
                int(event["width"]),
                int(event["height"]),
            )
            for event in hover_events
        )
        regions = []
        for (app, left, top, width, height), count in rect_counts.most_common(3):
            regions.append(
                f"{app} {left},{top},{width}x{height} "
                f"({self._hover_region_size_label(width, height)}, {count}x)"
            )
        region_text = "; ".join(regions) if regions else "unknown"
        return (
            f"{timestamp} [mouse hover summary: {len(hover_events)} consecutive events; "
            f"apps: {self._format_hover_counts(app_counts)}; "
            f"regions: {region_text}; "
            f"pointer path: {self._format_hover_pointer_path(hover_events)}]"
        )

    def _format_hover_counts(self, counts: Counter[str], limit: int = 5) -> str:
        top = counts.most_common(limit)
        summary = ", ".join(f"{app} ({count})" for app, count in top)
        remaining = sum(count for _, count in counts.most_common()[limit:])
        if remaining:
            summary = f"{summary}, other ({remaining})"
        return summary or "unknown apps"

    def _hover_region_size_label(self, width: int, height: int) -> str:
        area = width * height
        if width <= 80 and height <= 80:
            return "small target/icon"
        if height <= 90 and width >= 300:
            return "toolbar/taskbar strip"
        if area >= 400_000:
            return "large window/content area"
        return "UI region"

    def _condense_hover_app_sequence(self, hover_events: list[dict[str, Any]], limit: int = 12) -> list[str]:
        sequence: list[str] = []
        previous = ""
        for event in hover_events:
            app = str(event["app"])
            if app == previous:
                continue
            sequence.append(app)
            previous = app
        if len(sequence) <= limit:
            return sequence
        head_count = max(1, limit - 2)
        return sequence[:head_count] + ["..."] + sequence[-1:]

    def _format_hover_pointer_path(self, hover_events: list[dict[str, Any]], limit: int = 6) -> str:
        points = [f"{int(event['x'])},{int(event['y'])}" for event in hover_events]
        if len(points) <= limit:
            return " -> ".join(points)
        head_count = max(1, limit - 3)
        return " -> ".join(points[:head_count] + ["..."] + points[-2:])

    def _build_prompt(self, payload: LLMWindowPayload) -> str:
        parts = [
            "System Instruction: Analyze a personal work-activity transcript.",
            "Infer what the person is trying to do, what outcome they are working toward, and how focused the work appears.",
            "Screen Reader Context:",
            (
                "The transcript is captured from NVDA, a Windows screen reader. "
                "Most non-hover lines are what NVDA would speak out loud or echo from user input."
            ),
            (
                "NVDA often announces accessible names, roles, states, landmarks, window titles, "
                "menu items, dialogs, controls, typed characters, and shortcut keys."
            ),
            (
                "Use screen-reader semantics such as button, slider, edit, document, window, "
                "dialog, menu, landmark, collapsed, pressed, selected, and focus changes to infer "
                "what UI element the user is on and what action they are trying to take."
            ),
        ]
        if payload.context_summaries:
            parts.append("Recent Work Context:")
            parts.extend(payload.context_summaries)
        hover_context = self._build_mouse_hover_context(payload.text)
        if hover_context:
            parts.append("Mouse Hover Context:")
            parts.extend(hover_context)
        action_context = self._build_mouse_action_context(payload.text)
        if action_context:
            parts.append("Mouse Action Context:")
            parts.extend(action_context)
        compacted_transcript = self._compact_mouse_event_transcript(payload.text)
        parts.append("Current NVDA Transcript (each line starts with the local captured-at timestamp or timestamp range):")
        parts.append(compacted_transcript)
        parts.append(
            "Output rules:\n"
            "- Focus on work intent, not compliance or policy.\n"
            "- Use message timestamps to understand pacing, pauses, and task transitions inside the window.\n"
            "- Make the final classification after combining NVDA utterances, keypress echoes, mouse actions, hover metadata, app changes, and recent context.\n"
            "- Treat mouse hover tags as visual pointer metadata, not spoken or typed text.\n"
            "- Treat mouse action tags as user input metadata, not spoken or typed text.\n"
            "- For mouse actions, use the transcript line timestamp as the event time; event ids and internal timestamps are intentionally omitted from the tag.\n"
            "- Use click/release action names, scroll direction, coordinates, and nearby NVDA labels to infer what the user targeted.\n"
            "- Consecutive scroll ticks may be compacted into mouse scroll summary lines; treat them as navigation through visible content.\n"
            "- Screenshot paths and capture status are omitted from mouse action tags; future image inputs should be analyzed only when attached separately.\n"
            "- Treat mouse hover summary lines as compacted replacements for consecutive hover-only bursts.\n"
            "- Pair hover tags with nearby NVDA labels to infer what UI element the user inspected or targeted.\n"
            "- Use appName and repeated hover rectangles to recognize app switches, taskbar/tray usage, menus, dialogs, toolbars, and content areas.\n"
            "- Down-weight rapid repeated hover tags when they only show cursor movement; up-weight them when the app, target size, or nearby labels reveal intent.\n"
            "- Keep headline and summary concrete and user-facing.\n"
            "- Use project=\"General work\" when the workstream is unclear.\n"
            "- activity_type must be one of: deep_work, planning, research, review, communication, admin, break, other.\n"
            "- focus_state must be one of: focused, steady, switching, blocked, idle.\n"
            "- next_step should describe the likely next meaningful action in one sentence.\n"
            "- confidence should be between 0 and 1."
        )
        parts.append(
            "Respond strictly in JSON with keys: headline, summary, goal, project, activity_type, "
            "focus_state, next_step, confidence."
        )
        return "\n".join(parts)

    def _build_day_story_prompt(self, payload: DayStoryPayload) -> str:
        segment_lines = []
        for index, segment in enumerate(payload.segments, start=1):
            segment_lines.append(
                f"{index}. {segment['time_range']} | {segment['activity_label']} | {segment['project']} | "
                f"{segment['headline']} | {segment['summary']}"
            )
        return "\n".join(
            [
                f"System Instruction: Summarize a single workday into one headline and one short insight for {payload.day}.",
                "You are summarizing already-analyzed work segments into a calmer, higher-level day story.",
                "Focus on the main thread of the day, not every individual segment.",
                f"These {len(payload.segments)} segments are a representative slice of {payload.total_segments} analyzed segments.",
                "Keep the headline under 12 words.",
                "Keep the summary to 1-2 sentences and make it easy to scan in a dashboard.",
                "Mention the strongest focus period or the main coordination pattern when possible.",
                "Respond strictly in JSON with keys: headline, summary.",
                "Segments:",
                *segment_lines,
            ]
        )


llm_service = LLMService()
