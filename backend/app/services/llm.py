from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from dataclasses import dataclass, field
import re
import time
from threading import Lock
from typing import Any, Dict, List

from ..core.config import settings
from ..core.time import local_timezone
from ..models import WindowStatus
from .analysis import normalize_activity_analysis
from .local_qwen import LOCAL_QWEN_DISPLAY_MODEL, LOCAL_QWEN_PROVIDER, local_qwen_service


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

_GANTT_VISUAL_TONES = {"base", "warm", "peach", "amber", "soft"}
LONG_FORM_LLM_TIMEOUT_SECONDS = 120
GANTT_REASONING_EFFORT = "low"


_MOUSE_HOVER_RE = re.compile(
    r"\[mouse hover[^\]]*?\s(?:appName|app)=(?P<app>.*?)\s+"
    r"x=(?P<x>-?\d+)\s+y=(?P<y>-?\d+)\s+"
    r"(?:location|element_location)=(?P<left>-?\d+),(?P<top>-?\d+),(?P<width>\d+)x(?P<height>\d+)",
)
_MOUSE_ACTION_RE = re.compile(r"\[mouse action\]\s+(?P<payload>\{.*\})")
_TRANSCRIPT_TIMESTAMP_RE = re.compile(r"^\[(?P<timestamp>[^\]]+)\]\s+")
_SCROLL_ACTIONS = {"scrollUp", "scrollDown", "scrollLeft", "scrollRight", "scrollStop"}
_MOUSE_ACTION_LLM_FIELDS = (
    "action",
    "x",
    "y",
)
_PROMPT_CHARS_PER_LIMIT_UNIT = 8


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
class LLMRollupPayload:
    rollup_id: str
    level: str
    started_at: str
    ended_at: str
    source_items: List[Dict[str, Any]]
    raw_transcript: str = ""
    context_summaries: List[str] = field(default_factory=list)


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


@dataclass
class LLMGanttPayload:
    mode: str
    started_at: str
    ended_at: str
    candidates: List[Dict[str, Any]]


@dataclass
class LLMGanttResult:
    decisions: Dict[str, Dict[str, Any]]
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass
class LLMGanttComposerPayload:
    mode: str
    started_at: str
    ended_at: str
    sources: List[Dict[str, Any]]
    contexts: List[Dict[str, Any]]


@dataclass
class LLMGanttComposerResult:
    blocks: List[Dict[str, Any]]
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class LLMService:
    def __init__(self) -> None:
        self._client = None
        self._client_signature: tuple[bool, str, str] | None = None
        self._client_lock = Lock()
        self.reload_from_settings()

    def reload_from_settings(self) -> None:
        runtime = settings.runtime()
        signature = (runtime.fake_llm_mode, runtime.llm_provider, settings.openai_api_key)
        with self._client_lock:
            if signature == self._client_signature:
                return
            self._client = self._build_client(settings.openai_api_key, runtime.fake_llm_mode, runtime.llm_provider)
            self._client_signature = signature
        if self._client:
            print(f"[LLM] OpenAI client initialized (model={settings.llm_model})")
        else:
            mode = "fake" if runtime.fake_llm_mode else runtime.llm_provider
            print(f"[LLM] Using {mode} LLM mode; requests will not reach OpenAI")

    def _build_client(self, api_key: str, fake_llm_mode: bool, provider: str):
        if fake_llm_mode or provider != "openai":
            return None
        try:
            from openai import AsyncOpenAI
        except ImportError:  # pragma: no cover
            return None
        if not api_key:
            return None
        return AsyncOpenAI(api_key=api_key)

    async def evaluate_window(self, payload: LLMWindowPayload) -> LLMResult:
        if self._using_local_qwen():
            return await self._evaluate_window_local_qwen(payload)
        chunks = self._chunk_transcript(payload.text, settings.window_token_limit)
        if len(chunks) <= 1:
            return await self._evaluate_window_once(payload)
        print(
            f"[LLM] Window {payload.window_id} exceeded token threshold; "
            f"splitting into {len(chunks)} ordered chunk calls"
        )
        results: list[LLMResult] = []
        for index, chunk in enumerate(chunks, start=1):
            chunk_payload = LLMWindowPayload(
                window_id=f"{payload.window_id}:chunk-{index}",
                session_id=payload.session_id,
                text=chunk,
                policy=payload.policy,
                examples=payload.examples,
                context_summaries=[
                    *payload.context_summaries,
                    f"This is chunk {index} of {len(chunks)} from the same capture window; preserve local intent and timing.",
                ],
            )
            results.append(await self._evaluate_window_once(chunk_payload))
        return self._combine_chunk_results(payload, results)

    async def _evaluate_window_once(self, payload: LLMWindowPayload) -> LLMResult:
        self.reload_from_settings()
        prompt = self._build_prompt(payload)
        print(f"[LLM] Evaluating window {payload.window_id} (session={payload.session_id})")
        if settings.fake_llm_mode:
            print('[LLM] Using fake LLM path')
            return await self._fake_response(payload, prompt)
        if self._using_local_qwen():
            return await self._evaluate_window_local_qwen(payload)
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

    async def evaluate_rollup(self, payload: LLMRollupPayload) -> LLMResult:
        self.reload_from_settings()
        if self._using_local_qwen():
            return await self._evaluate_rollup_local_qwen(payload)
        prompt = self._build_rollup_prompt(payload)
        print(
            f"[LLM] Evaluating {payload.level} rollup {payload.rollup_id} "
            f"({payload.started_at} to {payload.ended_at})"
        )
        if settings.fake_llm_mode:
            return await self._fake_rollup_response(payload, prompt)
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
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] OpenAI timeout for rollup {payload.rollup_id}")
            raise LLMTimeoutError("Rollup LLM timed out") from exc
        except Exception as exc:  # pragma: no cover
            print(f"[LLM] OpenAI call failed for rollup {payload.rollup_id}: {exc}")
            raise LLMServiceError("Rollup LLM call failed") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
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
            transcript="\n".join(str(item.get("summary") or "") for item in payload.source_items),
        )
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
            summary=analysis_payload["summary"],
            verdict=WindowStatus.PROCESSED,
            confidence=analysis_payload["confidence"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            model_name=settings.llm_model,
            analysis_payload=analysis_payload,
        )

    def _using_local_qwen(self) -> bool:
        runtime = settings.runtime()
        return not runtime.fake_llm_mode and runtime.llm_provider == LOCAL_QWEN_PROVIDER

    async def _evaluate_window_local_qwen(self, payload: LLMWindowPayload) -> LLMResult:
        self.reload_from_settings()
        prompt = self._build_local_qwen_window_prompt(payload)
        print(f"[LLM] Evaluating window {payload.window_id} with local Qwen")
        try:
            completion = await asyncio.wait_for(
                asyncio.to_thread(local_qwen_service.complete_activity, prompt),
                timeout=local_qwen_service.timeout_seconds + 30,
            )
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] Local Qwen timeout for window {payload.window_id}")
            raise LLMTimeoutError("Local Qwen timed out") from exc
        except Exception as exc:
            print(f"[LLM] Local Qwen call failed for window {payload.window_id}: {exc}")
            raise LLMServiceError("Local Qwen call failed") from exc
        parsed_payload = self._extract_local_qwen_payload(completion.output_text)
        analysis_payload = normalize_activity_analysis(
            parsed_payload,
            fallback_text=completion.output_text,
            transcript=payload.text,
        )
        return LLMResult(
            summary=analysis_payload["summary"],
            verdict=WindowStatus.PROCESSED,
            confidence=analysis_payload["confidence"],
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            latency_ms=completion.latency_ms,
            model_name=LOCAL_QWEN_DISPLAY_MODEL,
            analysis_payload=analysis_payload,
        )

    async def _evaluate_rollup_local_qwen(self, payload: LLMRollupPayload) -> LLMResult:
        prompt = self._build_local_qwen_rollup_prompt(payload)
        print(
            f"[LLM] Evaluating {payload.level} rollup {payload.rollup_id} with local Qwen "
            f"({payload.started_at} to {payload.ended_at})"
        )
        try:
            completion = await asyncio.wait_for(
                asyncio.to_thread(local_qwen_service.complete_activity, prompt),
                timeout=local_qwen_service.timeout_seconds + 30,
            )
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] Local Qwen timeout for rollup {payload.rollup_id}")
            raise LLMTimeoutError("Local Qwen rollup timed out") from exc
        except Exception as exc:
            print(f"[LLM] Local Qwen call failed for rollup {payload.rollup_id}: {exc}")
            raise LLMServiceError("Local Qwen rollup call failed") from exc
        parsed_payload = self._extract_local_qwen_payload(completion.output_text)
        analysis_payload = normalize_activity_analysis(
            parsed_payload,
            fallback_text=completion.output_text,
            transcript="\n".join(str(item.get("summary") or "") for item in payload.source_items),
        )
        return LLMResult(
            summary=analysis_payload["summary"],
            verdict=WindowStatus.PROCESSED,
            confidence=analysis_payload["confidence"],
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            latency_ms=completion.latency_ms,
            model_name=LOCAL_QWEN_DISPLAY_MODEL,
            analysis_payload=analysis_payload,
        )

    def _extract_local_qwen_payload(self, raw_text: str) -> Dict[str, Any] | None:
        parsed = self._extract_structured_payload(raw_text)
        if parsed:
            return self._coerce_local_qwen_payload(parsed)
        decoder = json.JSONDecoder()
        cleaned = raw_text.strip()
        best: dict[str, Any] | None = None
        best_score = -1
        required = {
            "headline",
            "summary",
            "activity_type",
            "primary_app",
            "primary_project",
            "focus_level",
            "user_goal",
            "specific_task",
            "confidence",
        }
        for index, char in enumerate(cleaned):
            if char != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                score = sum(1 for key in required if key in candidate)
                if score >= best_score:
                    best = candidate
                    best_score = score
        return self._coerce_local_qwen_payload(best) if best is not None else None

    def _coerce_local_qwen_payload(self, parsed: Dict[str, Any] | None) -> Dict[str, Any]:
        if not isinstance(parsed, dict):
            return {}
        coerced = dict(parsed)
        aliases = {
            "goal": "user_goal",
            "project": "primary_project",
            "focus_state": "focus_level",
            "next_step": "specific_task",
            "app": "primary_app",
            "application": "primary_app",
        }
        for old_key, new_key in aliases.items():
            if old_key in coerced and new_key not in coerced:
                coerced[new_key] = coerced[old_key]
        coerced.setdefault("headline", "unknown")
        coerced.setdefault("summary", "unknown")
        coerced.setdefault("activity_type", "other")
        coerced.setdefault("primary_app", "unknown")
        coerced.setdefault("primary_project", "unknown")
        coerced.setdefault("productivity", "unknown")
        coerced.setdefault("focus_level", "unknown")
        coerced.setdefault("user_goal", "unknown")
        coerced.setdefault("specific_task", "unknown")
        coerced.setdefault("evidence", [])
        coerced.setdefault("uncertainty_notes", [])
        coerced.setdefault("unsupported_claim_count", 0)
        coerced.setdefault("contradicted_claim_count", 0)
        coerced.setdefault("over_specific_claim_count", 0)
        coerced.setdefault("uncertainty_count", 0)
        coerced.setdefault("unknown_fields", [])
        coerced.setdefault("evidence_coverage_score", 0)
        coerced.setdefault("confidence", 0.5)
        string_limits = {
            "headline": 100,
            "summary": 180,
            "primary_app": 100,
            "primary_project": 100,
            "user_goal": 100,
            "specific_task": 180,
        }
        for key, limit in string_limits.items():
            value = coerced.get(key)
            if isinstance(value, str) and len(value) > limit:
                coerced[key] = value[: max(0, limit - 3)].rstrip() + "..."
        for key in ("evidence", "uncertainty_notes", "unknown_fields"):
            value = coerced.get(key)
            if not isinstance(value, list):
                coerced[key] = []
                continue
            coerced[key] = [
                (item[:137].rstrip() + "...") if len(item) > 140 else item
                for item in value[:3]
                if isinstance(item, str)
            ]
        coerced["goal"] = coerced.get("user_goal")
        coerced["project"] = coerced.get("primary_project")
        coerced["focus_state"] = "steady" if coerced.get("focus_level") == "unknown" else coerced.get("focus_level")
        coerced["next_step"] = coerced.get("specific_task")
        return coerced

    def debug_window_prompt_text(self, payload: LLMWindowPayload) -> str:
        if self._using_local_qwen():
            return self._build_local_qwen_window_prompt(payload)
        chunks = self._chunk_transcript(payload.text, settings.window_token_limit)
        if len(chunks) <= 1:
            return self._build_prompt(payload)

        prompts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            chunk_payload = LLMWindowPayload(
                window_id=f"{payload.window_id}:chunk-{index}",
                session_id=payload.session_id,
                text=chunk,
                policy=payload.policy,
                examples=payload.examples,
                context_summaries=[
                    *payload.context_summaries,
                    f"This is chunk {index} of {len(chunks)} from the same capture window; preserve local intent and timing.",
                ],
            )
            prompts.append(
                "\n".join(
                    [
                        f"--- Reconstructed prompt chunk {index} of {len(chunks)} ---",
                        self._build_prompt(chunk_payload),
                    ]
                )
            )
        return "\n\n".join(prompts)

    def debug_rollup_prompt_text(self, payload: LLMRollupPayload) -> str:
        if self._using_local_qwen():
            return self._build_local_qwen_rollup_prompt(payload)
        return self._build_rollup_prompt(payload)

    def compact_transcript_for_prompt(self, transcript: str) -> str:
        return self._compact_mouse_event_transcript(transcript)

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
        if settings.fake_llm_mode or not settings.dashboard_story_llm_enabled:
            prompt = self._build_day_story_prompt(payload)
            return self._fake_day_story(payload, prompt=prompt)
        if self._using_local_qwen():
            return await self._summarize_day_story_local_qwen(payload)
        prompt = self._build_day_story_prompt(payload)
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
                timeout=max(settings.llm_timeout_seconds, LONG_FORM_LLM_TIMEOUT_SECONDS),
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

    async def _summarize_day_story_local_qwen(self, payload: DayStoryPayload) -> DayStoryResult:
        prompt = self._build_local_qwen_day_story_prompt(payload)
        print(f"[LLM] Evaluating day story {payload.day} with local Qwen")
        try:
            completion = await asyncio.wait_for(
                asyncio.to_thread(local_qwen_service.complete_activity, prompt),
                timeout=local_qwen_service.timeout_seconds + 30,
            )
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] Local Qwen timeout for day story {payload.day}")
            raise LLMTimeoutError("Local Qwen day story timed out") from exc
        except Exception as exc:
            print(f"[LLM] Local Qwen day story call failed for {payload.day}: {exc}")
            raise LLMServiceError("Local Qwen day story call failed") from exc
        parsed_payload = self._extract_local_qwen_payload(completion.output_text)
        story = self._extract_day_story_payload(
            json.dumps(parsed_payload or {}, ensure_ascii=True),
            payload.segments,
        )
        return DayStoryResult(
            headline=story["headline"],
            summary=story["summary"],
            model_name=LOCAL_QWEN_DISPLAY_MODEL,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            latency_ms=completion.latency_ms,
        )

    def rank_gantt_sync(self, payload: LLMGanttPayload) -> LLMGanttResult:
        return asyncio.run(self.rank_gantt(payload))

    async def rank_gantt(self, payload: LLMGanttPayload) -> LLMGanttResult:
        self.reload_from_settings()
        prompt = self._build_gantt_prompt(payload)
        if settings.fake_llm_mode or self._using_local_qwen():
            return self._fake_gantt_rankings(payload, prompt)
        if not self._client:
            raise LLMServiceError("OpenAI API key is not configured.")
        start = time.perf_counter()
        timeout_seconds = max(settings.llm_timeout_seconds, LONG_FORM_LLM_TIMEOUT_SECONDS)
        print(
            f"[LLM] Gantt ranking OpenAI call starting for {payload.mode} view "
            f"(candidates={len(payload.candidates)}, timeout={timeout_seconds}s)"
        )
        try:
            response = await asyncio.wait_for(
                self._client.responses.create(
                    model=settings.llm_model,
                    input=prompt,
                    reasoning={"effort": GANTT_REASONING_EFFORT},
                    text={"verbosity": "low"},
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] Gantt ranking timeout for {payload.mode} view")
            raise LLMTimeoutError("Gantt ranking LLM timed out") from exc
        except Exception as exc:  # pragma: no cover
            print(f"[LLM] Gantt ranking OpenAI call failed for {payload.mode}: {exc}")
            raise LLMServiceError("Gantt ranking LLM call failed") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        content = getattr(response, "output_text", None)
        if not content:
            try:
                content = response.output[0].content[0].text  # type: ignore[attr-defined]
            except Exception:
                content = ""
        decisions = self._extract_gantt_decisions(content, payload.candidates)
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
        return LLMGanttResult(
            decisions=decisions,
            model_name=settings.llm_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    def compose_gantt_sync(self, payload: LLMGanttComposerPayload) -> LLMGanttComposerResult:
        return asyncio.run(self.compose_gantt(payload))

    async def compose_gantt(self, payload: LLMGanttComposerPayload) -> LLMGanttComposerResult:
        self.reload_from_settings()
        prompt = self._build_gantt_composer_prompt(payload)
        if settings.fake_llm_mode or self._using_local_qwen():
            return self._fake_gantt_composer(payload, prompt)
        if not self._client:
            raise LLMServiceError("OpenAI API key is not configured.")
        start = time.perf_counter()
        timeout_seconds = max(settings.llm_timeout_seconds, LONG_FORM_LLM_TIMEOUT_SECONDS)
        print(
            f"[LLM] Gantt composer OpenAI call starting for {payload.mode} view "
            f"(sources={len(payload.sources)}, contexts={len(payload.contexts)}, timeout={timeout_seconds}s)"
        )
        try:
            response = await asyncio.wait_for(
                self._client.responses.create(
                    model=settings.llm_model,
                    input=prompt,
                    reasoning={"effort": GANTT_REASONING_EFFORT},
                    text={"verbosity": "low"},
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:  # pragma: no cover
            print(f"[LLM] Gantt composer timeout for {payload.mode} view")
            raise LLMTimeoutError("Gantt composer LLM timed out") from exc
        except Exception as exc:  # pragma: no cover
            print(f"[LLM] Gantt composer OpenAI call failed for {payload.mode}: {exc}")
            raise LLMServiceError("Gantt composer LLM call failed") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        content = getattr(response, "output_text", None)
        if not content:
            try:
                content = response.output[0].content[0].text  # type: ignore[attr-defined]
            except Exception:
                content = ""
        blocks = self._extract_gantt_composer_blocks(content, payload.sources)
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
        print(f"[LLM] Gantt composer OpenAI call succeeded in {latency_ms} ms for {payload.mode} view")
        return LLMGanttComposerResult(
            blocks=blocks,
            model_name=settings.llm_model,
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

    def _extract_gantt_decisions(self, raw_text: str, candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        parsed = self._extract_structured_payload(raw_text) or {}
        raw_decisions = parsed.get("decisions") if isinstance(parsed, dict) else None
        fallback = self._fallback_gantt_decisions(candidates)
        if not isinstance(raw_decisions, list):
            return fallback
        allowed_lanes = {"deep", "meetings", "comms", "breaks"}
        decisions: Dict[str, Dict[str, Any]] = {}
        for item in raw_decisions:
            if not isinstance(item, dict):
                continue
            candidate_id = self._clean_story_text(item.get("candidate_id"))
            if not candidate_id:
                continue
            fallback_item = fallback.get(candidate_id, {})
            lane = self._clean_story_text(item.get("lane")).lower()
            if lane not in allowed_lanes:
                lane = str(fallback_item.get("lane") or "deep")
            label = self._clean_story_text(item.get("display_label")) or str(fallback_item.get("display_label") or "Important activity")
            reason = self._clean_story_text(item.get("reason")) or str(fallback_item.get("reason") or "Ranked by activity metadata.")
            decisions[candidate_id] = {
                "significance": self._bounded_float(item.get("significance"), fallback_item.get("significance", 0.5)),
                "disruption": self._bounded_float(item.get("disruption"), fallback_item.get("disruption", 0.5)),
                "same_task": bool(item.get("same_task", fallback_item.get("same_task", False))),
                "lane": lane,
                "display_label": label[:96],
                "reason": reason[:220],
            }
        for candidate_id, fallback_item in fallback.items():
            decisions.setdefault(candidate_id, fallback_item)
        return decisions

    def _extract_gantt_composer_blocks(self, raw_text: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        parsed = self._extract_structured_payload(raw_text) or {}
        raw_blocks = parsed.get("blocks") if isinstance(parsed, dict) else None
        if not isinstance(raw_blocks, list):
            return []

        allowed_lanes = {"deep", "meetings", "comms", "breaks"}
        source_by_id = {str(item.get("id")): item for item in sources if item.get("id")}
        blocks: List[Dict[str, Any]] = []
        for item in raw_blocks:
            if not isinstance(item, dict):
                continue
            raw_source_ids = item.get("source_ids")
            if isinstance(raw_source_ids, list):
                source_ids = [
                    self._clean_story_text(str(source_id))
                    for source_id in raw_source_ids
                    if self._clean_story_text(str(source_id))
                ]
            elif isinstance(raw_source_ids, str):
                source_ids = [source_id.strip() for source_id in raw_source_ids.split(",") if source_id.strip()]
            else:
                source_ids = []
            known_source_ids = [source_id for source_id in source_ids if source_id in source_by_id]
            source_hint = source_by_id.get(known_source_ids[0], {}) if known_source_ids else {}
            is_gap = bool(item.get("is_gap"))
            lane = self._clean_story_text(item.get("lane")).lower()
            if is_gap:
                lane = "breaks"
            elif lane not in allowed_lanes:
                activity_type = self._clean_story_text(item.get("activity_type")) or str(source_hint.get("activity_type") or "other")
                lane = self._gantt_lane_for(activity_type, source_hint or item)
            if lane not in allowed_lanes:
                lane = "deep"

            label = self._clean_story_text(item.get("label"))
            summary = self._clean_story_text(item.get("summary"))
            project = self._clean_story_text(item.get("project"))
            reason = self._clean_story_text(item.get("reason"))
            evidence = self._clean_story_text(item.get("evidence") or item.get("evidence_summary"))
            visual_group = self._clean_story_text(item.get("visual_group")) or (project or str(source_hint.get("project") or "General work"))
            visual_tone = self._clean_story_text(item.get("visual_tone")).lower()
            if visual_tone not in _GANTT_VISUAL_TONES:
                visual_tone = ""
            if not evidence:
                evidence = self._source_evidence_summary(known_source_ids, source_by_id)
            blocks.append(
                {
                    "from": self._clean_story_text(item.get("from") or item.get("captured_from")) or source_hint.get("from") or source_hint.get("captured_from"),
                    "to": self._clean_story_text(item.get("to") or item.get("captured_to")) or source_hint.get("to") or source_hint.get("captured_to"),
                    "lane": lane,
                    "label": ("Away from keyboard" if is_gap else (label or str(source_hint.get("headline") or "Work block")))[:96],
                    "summary": (summary or ("No analyzed activity was captured for this past interval." if is_gap else str(source_hint.get("summary") or "")))[:360],
                    "project": (project or ("" if is_gap else str(source_hint.get("project") or "General work")))[:96],
                    "source_ids": known_source_ids if known_source_ids else source_ids,
                    "is_gap": is_gap,
                    "reason": (reason or ("Composer identified an uncovered chart interval." if is_gap else "Composed from source evidence."))[:260],
                    "evidence": evidence[:320],
                    "visual_group": ("away" if is_gap else visual_group)[:96],
                    "visual_tone": "neutral" if is_gap else visual_tone,
                }
            )
        return blocks

    def _source_evidence_summary(self, source_ids: List[str], source_by_id: Dict[str, Dict[str, Any]]) -> str:
        snippets: list[str] = []
        for source_id in source_ids[:4]:
            source = source_by_id.get(source_id) or {}
            evidence = self._clean_story_text(source.get("evidence") or source.get("summary"))
            if evidence:
                snippets.append(evidence)
        return " | ".join(snippets)[:320]

    def _fallback_gantt_composer_blocks(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for source in sources:
            source_id = str(source.get("id") or "")
            activity_type = str(source.get("activity_type") or "other")
            lane = str(source.get("lane") or source.get("lane_hint") or self._gantt_lane_for(activity_type, source))
            if lane not in {"deep", "meetings", "comms", "breaks"}:
                lane = "deep"
            blocks.append(
                {
                    "from": source.get("from") or source.get("captured_from"),
                    "to": source.get("to") or source.get("captured_to"),
                    "lane": lane,
                    "label": str(source.get("headline") or "Work block")[:96],
                    "summary": str(source.get("summary") or "")[:360],
                    "project": str(source.get("project") or "General work")[:96],
                    "source_ids": [source_id] if source_id else [],
                    "is_gap": False,
                    "reason": "Local composer fallback kept this source block because the LLM composer was unavailable.",
                    "evidence": str(source.get("evidence") or source.get("summary") or "")[:320],
                    "visual_group": str(source.get("project") or "General work")[:96],
                    "visual_tone": "",
                }
            )
        return blocks

    def _fallback_gantt_decisions(self, candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        decisions: Dict[str, Dict[str, Any]] = {}
        for item in candidates:
            candidate_id = str(item.get("candidate_id") or "")
            if not candidate_id:
                continue
            candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
            parent = item.get("parent") if isinstance(item.get("parent"), dict) else {}
            activity_type = str(candidate.get("activity_type") or "other")
            focus_state = str(candidate.get("focus_state") or "steady")
            duration_fraction = self._bounded_float(item.get("duration_fraction"), 0.0)
            lane = str(candidate.get("lane") or self._gantt_lane_for(activity_type, candidate))
            same_task = (
                str(candidate.get("project") or "").lower() == str(parent.get("project") or "").lower()
                and activity_type == str(parent.get("activity_type") or "")
            )
            significance = 0.4 + min(0.28, duration_fraction * 0.5)
            disruption = 0.32 + min(0.35, duration_fraction * 0.65)
            if lane == "meetings":
                significance += 0.25
                disruption += 0.32
            elif activity_type in {"communication", "admin"}:
                significance += 0.14
                disruption += 0.2
            elif activity_type in {"deep_work", "research", "planning"}:
                significance += 0.15
            if focus_state in {"switching", "blocked"}:
                disruption += 0.14
            if same_task:
                disruption -= 0.22
            decisions[candidate_id] = {
                "significance": max(0.0, min(1.0, significance)),
                "disruption": max(0.0, min(1.0, disruption)),
                "same_task": same_task,
                "lane": lane if lane in {"deep", "meetings", "comms", "breaks"} else "deep",
                "display_label": str(candidate.get("headline") or "Important activity")[:96],
                "reason": "Ranked by duration, activity type, focus state, and interruption likelihood.",
            }
        return decisions

    def _gantt_lane_for(self, activity_type: str, item: Dict[str, Any]) -> str:
        text = " ".join(
            str(item.get(key) or "")
            for key in ("headline", "summary", "project", "dominant_goal", "goal", "evidence")
        ).lower()
        meeting_evidence = (
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
        if activity_type in {"break", "offline", "other"}:
            return "breaks"
        if activity_type in {"communication", "admin", "review"} and any(keyword in text for keyword in meeting_evidence):
            return "meetings"
        if activity_type in {"communication", "admin"}:
            return "comms"
        return "deep"

    def _bounded_float(self, value: Any, default: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            try:
                numeric = float(default)
            except (TypeError, ValueError):
                numeric = 0.0
        return max(0.0, min(1.0, numeric))

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

    async def _fake_rollup_response(self, payload: LLMRollupPayload, prompt: str) -> LLMResult:
        await asyncio.sleep(0)
        summaries = "\n".join(str(item.get("summary") or item.get("headline") or "") for item in payload.source_items)
        analysis_payload = self._fake_analysis(summaries or payload.raw_transcript)
        analysis_payload["headline"] = f"{payload.level} summary: {analysis_payload['headline']}"
        analysis_payload["dominant_goal"] = analysis_payload.get("dominant_goal") or analysis_payload["goal"]
        analysis_payload["important_intervals"] = [
            str(item.get("time_range") or "")
            for item in payload.source_items[:3]
            if item.get("time_range")
        ]
        analysis_payload["secondary_goals"] = []
        analysis_payload["ignored_noise"] = "Short side activity was ignored unless it changed the dominant intent."
        tokens = max(1, len(prompt.split()))
        return LLMResult(
            summary=analysis_payload["summary"],
            verdict=WindowStatus.PROCESSED,
            confidence=analysis_payload["confidence"],
            prompt_tokens=tokens,
            completion_tokens=len(analysis_payload["summary"].split()),
            latency_ms=5,
            model_name="fake-rollup-llm",
            analysis_payload=analysis_payload,
        )

    def _chunk_transcript(self, text: str, token_limit: int) -> list[str]:
        words = text.split()
        if not words:
            return [text]
        limit = max(100, int(token_limit * 0.8))
        char_limit = self._prompt_char_limit(limit)
        if len(words) <= limit and len(text) <= char_limit:
            return [text]
        chunks: list[str] = []
        current_lines: list[str] = []
        current_tokens = 0
        current_chars = 0
        for line in text.splitlines():
            line_tokens = max(1, len(line.split()))
            line_chars = len(line)
            if current_lines and (
                current_tokens + line_tokens > limit
                or current_chars + line_chars + 1 > char_limit
            ):
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_tokens = 0
                current_chars = 0
            if line_tokens > limit or line_chars > char_limit:
                if current_lines:
                    chunks.append("\n".join(current_lines))
                    current_lines = []
                    current_tokens = 0
                    current_chars = 0
                chunks.extend(self._split_large_transcript_line(line, limit, char_limit))
                continue
            current_lines.append(line)
            current_tokens += line_tokens
            current_chars += line_chars + (1 if current_lines else 0)
        if current_lines:
            chunks.append("\n".join(current_lines))
        return chunks or [text]

    def _prompt_char_limit(self, token_limit: int) -> int:
        return max(4000, token_limit * _PROMPT_CHARS_PER_LIMIT_UNIT)

    def _split_large_transcript_line(self, line: str, word_limit: int, char_limit: int) -> list[str]:
        match = _TRANSCRIPT_TIMESTAMP_RE.match(line)
        if match:
            timestamp = match.group("timestamp")
            body = line[match.end():]
            first_prefix = f"[{timestamp}] "
            continuation_prefix = f"[{timestamp}] [continued oversized message] "
        else:
            body = line
            first_prefix = ""
            continuation_prefix = "[continued oversized message] "

        parts: list[str] = []

        def prefix_for_next() -> str:
            return first_prefix if not parts else continuation_prefix

        def flush_words(buffer: list[str]) -> None:
            if not buffer:
                return
            parts.append(f"{prefix_for_next()}{' '.join(buffer)}")

        line_words = body.split()
        if len(line_words) > 1:
            buffer: list[str] = []
            buffer_chars = 0
            for word in line_words:
                available_chars = max(200, char_limit - len(prefix_for_next()))
                if len(word) > available_chars:
                    flush_words(buffer)
                    buffer = []
                    buffer_chars = 0
                    for index in range(0, len(word), available_chars):
                        parts.append(f"{prefix_for_next()}{word[index:index + available_chars]}")
                    continue

                next_chars = buffer_chars + len(word) + (1 if buffer else 0)
                if buffer and (len(buffer) + 1 > word_limit or next_chars > available_chars):
                    flush_words(buffer)
                    buffer = [word]
                    buffer_chars = len(word)
                    continue
                buffer.append(word)
                buffer_chars = next_chars
            flush_words(buffer)
            return parts or [line[:char_limit]]

        content = body.strip()
        if not content:
            return [line[:char_limit]]
        while content:
            prefix = prefix_for_next()
            available_chars = max(200, char_limit - len(prefix))
            parts.append(f"{prefix}{content[:available_chars]}")
            content = content[available_chars:]
        return parts

    def _combine_chunk_results(self, payload: LLMWindowPayload, results: list[LLMResult]) -> LLMResult:
        if not results:
            analysis_payload = normalize_activity_analysis(None, transcript=payload.text)
            return LLMResult(
                summary=analysis_payload["summary"],
                verdict=WindowStatus.PROCESSED,
                confidence=analysis_payload["confidence"],
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
                model_name=settings.llm_model,
                analysis_payload=analysis_payload,
            )
        weighted_activity: Counter[str] = Counter()
        weighted_focus: Counter[str] = Counter()
        for result in results:
            weight = max(1, result.prompt_tokens)
            weighted_activity[str(result.analysis_payload.get("activity_type") or "other")] += weight
            weighted_focus[str(result.analysis_payload.get("focus_state") or "steady")] += weight
        primary = max(results, key=lambda result: result.prompt_tokens)
        activity_type = weighted_activity.most_common(1)[0][0]
        focus_state = weighted_focus.most_common(1)[0][0]
        summaries = [str(result.analysis_payload.get("summary") or result.summary) for result in results]
        headlines = [str(result.analysis_payload.get("headline") or "") for result in results if result.analysis_payload.get("headline")]
        goals = [
            str(result.analysis_payload.get("dominant_goal") or result.analysis_payload.get("goal") or "")
            for result in results
            if result.analysis_payload.get("dominant_goal") or result.analysis_payload.get("goal")
        ]
        projects = Counter(
            str(result.analysis_payload.get("project") or "General work")
            for result in results
        )
        confidence = sum(result.confidence for result in results) / max(1, len(results))
        combined_summary = " ".join(summary for summary in summaries if summary)
        if len(combined_summary.split()) > 80:
            combined_summary = " ".join(combined_summary.split()[:80]) + "..."
        analysis_payload = normalize_activity_analysis(
            {
                "headline": headlines[0] if headlines else primary.analysis_payload.get("headline"),
                "summary": combined_summary,
                "goal": goals[0] if goals else primary.analysis_payload.get("goal"),
                "dominant_goal": goals[0] if goals else primary.analysis_payload.get("dominant_goal"),
                "project": projects.most_common(1)[0][0] if projects else "General work",
                "activity_type": activity_type,
                "focus_state": focus_state,
                "next_step": primary.analysis_payload.get("next_step"),
                "important_intervals": [
                    f"Chunk {index}: {result.analysis_payload.get('headline') or result.summary}"
                    for index, result in enumerate(results, start=1)
                ],
                "secondary_goals": goals[1:4],
                "ignored_noise": "Oversized transcript was split into ordered chunks and merged by dominant activity.",
                "confidence": confidence,
            },
            transcript=payload.text,
        )
        return LLMResult(
            summary=analysis_payload["summary"],
            verdict=WindowStatus.PROCESSED,
            confidence=analysis_payload["confidence"],
            prompt_tokens=sum(result.prompt_tokens for result in results),
            completion_tokens=sum(result.completion_tokens for result in results),
            latency_ms=sum(result.latency_ms for result in results),
            model_name=primary.model_name,
            analysis_payload=analysis_payload,
        )

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

    def _fake_gantt_rankings(self, payload: LLMGanttPayload, prompt: str) -> LLMGanttResult:
        decisions = self._fallback_gantt_decisions(payload.candidates)
        return LLMGanttResult(
            decisions=decisions,
            model_name="fake-gantt-ranker",
            prompt_tokens=max(1, len(prompt.split())),
            completion_tokens=max(1, len(decisions) * 14),
            latency_ms=5,
        )

    def _fake_gantt_composer(self, payload: LLMGanttComposerPayload, prompt: str) -> LLMGanttComposerResult:
        blocks = self._fallback_gantt_composer_blocks(payload.sources)
        return LLMGanttComposerResult(
            blocks=blocks,
            model_name="fake-gantt-composer",
            prompt_tokens=max(1, len(prompt.split())),
            completion_tokens=max(1, len(blocks) * 18),
            latency_ms=5,
        )

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
                lines.append(self._format_mouse_action_line_for_llm(scroll_run[0]))
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
            if action_event:
                lines.append(self._format_mouse_action_line_for_llm(action_event))
                continue
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
                "Rich capture metadata is stored with the raw message for future image analysis but stripped before "
                "the text-only LLM prompt."
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

    def _format_mouse_action_line_for_llm(self, event: dict[str, Any]) -> str:
        sanitized_payload = {
            key: event[key]
            for key in _MOUSE_ACTION_LLM_FIELDS
            if key in event and event[key] is not None
        }
        timestamp = str(event.get("timestamp") or "")
        prefix = f"[{timestamp}] " if timestamp else ""
        return (
            prefix
            + "[mouse action] "
            + json.dumps(sanitized_payload, ensure_ascii=False, separators=(",", ":"))
        )

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
            app = event["app"].strip().strip('"') or "unknown"
            return {
                "line": line,
                "timestamp": timestamp_match.group("timestamp") if timestamp_match else "",
                "app": app,
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

    def _build_local_qwen_window_prompt(self, payload: LLMWindowPayload) -> str:
        hover_context = self._build_mouse_hover_context(payload.text)
        action_context = self._build_mouse_action_context(payload.text)
        compacted_transcript = self._compact_mouse_event_transcript(payload.text)
        parts = [
            "System Instruction: Create a text-only Workday Lens activity summary from one minute of accessibility evidence.",
            (
                "Evidence model: transcript lines may contain focused UI text, typed text captured through accessibility, "
                "window/page titles, URLs/domains, document titles, roles/states, keyboard/mouse metadata, gestures, "
                "system-state metadata, and media timestamps. Treat titles as clues, not as the answer. Combine "
                "repeated low-level events into a human activity."
            ),
            (
                "Grounding rule: use only evidence in this minute. Do not assume the user's employer, project, app, "
                "or goal from common app names or familiar wording. Prefer unknown or General work when unsupported."
            ),
            (
                "Evidence priority: 1. active window/app labels, URL/domain, page/document title; "
                "2. focused text, typed text, selected controls, headings; 3. mouse hover/action context; "
                "4. repeated scroll/click metadata. Pointer coordinates are supporting evidence only."
            ),
            (
                "Separate the user's task from UI mechanics. Browser title plus scrolling usually means reviewing "
                "or reading that topic, not scrolling. Typed text/corrections mean drafting or editing the visible "
                "topic, not keyboard use. Preview/dashboard reloads/clicks often mean testing or reviewing UI. "
                "Media title/timestamps can mean watching or scrubbing that media topic."
            ),
            "Silent analysis checklist before writing JSON:",
            "- What concrete action is happening: reading, watching, writing, editing, searching, reviewing, navigating, testing, configuring, communicating, waiting, or switching?",
            "- What visible topic/object is strongest: document section, page title, repo/file, product, prompt, issue, feed item, video, table, settings panel, or search query?",
            "- Which app/site is active? Use the application name from a window title or explicit app evidence; keep project/topic separate from app.",
            "- What uncertainty should be carried into summary rather than hidden?",
            "Do not reveal this checklist.",
            "Generic examples of the desired abstraction level:",
            "- If evidence is mostly a browser page title plus scrolling, summarize as reviewing or reading that page/topic, not as 'scrolling'.",
            "- If evidence is typed characters and corrections, summarize as drafting or editing the visible message/document topic, not as keyboard use.",
            "- If evidence shows a local preview or dashboard plus reloads/clicks, summarize as testing or reviewing that UI, not as generic browsing.",
            "- If evidence shows a media title and repeated timestamps, summarize as watching or scrubbing that media topic.",
        ]
        if hover_context:
            parts.extend(["Mouse Hover Context:", *hover_context])
        if action_context:
            parts.extend(["Mouse Action Context:", *action_context])
        parts.extend(
            [
                "Current NVDA-style Accessibility Transcript:",
                compacted_transcript,
                "Task: summarize only this 1-minute window. Do not infer future intent.",
                "Return exactly one strict JSON object with these keys in this order:",
                "headline, summary, activity_type, primary_app, primary_project, productivity, focus_level, user_goal, specific_task, evidence, uncertainty_notes, unsupported_claim_count, contradicted_claim_count, over_specific_claim_count, uncertainty_count, unknown_fields, evidence_coverage_score, confidence.",
                (
                    "Enums: activity_type is one of deep_work, planning, research, review, communication, admin, break, other. "
                    "productivity is productive, neutral, unproductive, or unknown. focus_level is focused, steady, switching, blocked, idle, or unknown."
                ),
                "Writing rules:",
                "- headline: 5-12 words, human activity phrase, not a copied page/window/video/document title.",
                "- summary: 1-2 precise sentences. Include the strongest visible topic/object and any real uncertainty.",
                "- primary_app: short app/site/application name from explicit evidence; use unknown if unclear.",
                "- primary_project: explicit project/workstream/repo/product/document subject; otherwise General work or unknown.",
                "- user_goal and specific_task: evidence-backed and concise; do not invent future intent.",
                "- evidence: 1-3 short factual clues, prioritizing textual/window evidence over coordinates.",
                "- uncertainty_notes and unknown_fields: include important ambiguity instead of guessing.",
                "- confidence: 0.25-0.90, lower for scroll-only, title-only, idle-only, or fast app-switching windows.",
                (
                    "Classification hints: research=reading/searching/scanning information; review=checking or inspecting UI/output/content; "
                    "planning=writing instructions/plans/prompts; deep_work=sustained creating/building/editing; "
                    "communication=messages/prompts/feedback to another person or assistant; admin=settings/files/tool management."
                ),
                "Return JSON only. No markdown. No commentary.",
            ]
        )
        return "\n".join(parts)

    def _build_local_qwen_rollup_prompt(self, payload: LLMRollupPayload) -> str:
        source_lines = self._local_qwen_source_lines(payload.source_items)
        parts = [
            f"System Instruction: Aggregate child Workday Lens summaries into one grounded {payload.level} summary.",
            f"Period: {self._format_rollup_period(payload.started_at, payload.ended_at)}.",
            (
                "Child summaries are the evidence hierarchy and may contain mistakes. Preserve the dominant "
                "work pattern, chronology, uncertainty, and major task switches. Do not invent unsupported apps, "
                "projects, goals, or exact actions."
            ),
            "Child summaries:",
            *source_lines,
        ]
        if payload.level == "5m" and payload.raw_transcript:
            parts.extend(
                [
                    "Raw transcript evidence for this 5-minute bucket:",
                    self._compact_mouse_event_transcript(payload.raw_transcript),
                    "Use raw transcript only to recover missing app/topic clues or resolve ambiguity.",
                ]
            )
        parts.extend(
            [
                "Return exactly one strict JSON object with keys:",
                "headline, summary, activity_type, primary_app, primary_project, productivity, focus_level, user_goal, specific_task, evidence, uncertainty_notes, unsupported_claim_count, contradicted_claim_count, over_specific_claim_count, uncertainty_count, unknown_fields, evidence_coverage_score, confidence.",
                "Rollup guidance:",
                "- 5m: keep concrete task detail and merge repeated micro-actions.",
                "- 15m: name the main workstream and any clear secondary switch.",
                "- 1h/4h/1d: summarize broader objectives and focus pattern over tiny UI details.",
                "- Use child numbers only inside evidence, not in headline or summary.",
                "- Keep app and project separate; app is the container, project is the workstream/topic when explicit.",
                "- evidence, uncertainty_notes, and unknown_fields must contain at most 3 short strings each.",
                "Return JSON only. No markdown. No commentary.",
            ]
        )
        return "\n".join(parts)

    def _local_qwen_source_lines(self, source_items: list[dict[str, Any]]) -> list[str]:
        lines = []
        for index, item in enumerate(source_items, start=1):
            headline = str(item.get("headline") or "").strip()
            summary = str(item.get("summary") or "").strip()
            task = str(item.get("specific_task") or item.get("next_step") or "unknown").strip()
            goal = str(item.get("user_goal") or item.get("dominant_goal") or item.get("goal") or "unknown").strip()
            app = str(item.get("primary_app") or item.get("app") or "unknown").strip()
            project = str(item.get("primary_project") or item.get("project") or "unknown").strip()
            activity = str(item.get("activity_type") or "other").strip()
            focus = str(item.get("focus_level") or item.get("focus_state") or "unknown").strip()
            confidence = item.get("confidence")
            lines.append(
                (
                    f"{index}. {item.get('time_range')} | headline={headline or 'unknown'} | "
                    f"type={activity} focus={focus} confidence={confidence} | app={app} | "
                    f"project={project} | goal={goal} | task={task} | summary={summary or 'unknown'}"
                )
            )
        return lines or ["1. no child summaries available"]

    def _build_local_qwen_day_story_prompt(self, payload: DayStoryPayload) -> str:
        segment_lines = []
        for index, segment in enumerate(payload.segments, start=1):
            source_level = segment.get("source_level") or "segment"
            source_role = segment.get("source_role") or "support"
            segment_lines.append(
                (
                    f"{index}. {source_level} {source_role} | {segment.get('time_range')} | "
                    f"activity={segment.get('activity_label')} | project={segment.get('project')} | "
                    f"headline={segment.get('headline')} | summary={segment.get('summary')}"
                )
            )
        parts = [
            f"System Instruction: Create a dashboard day story for {payload.day} from already-analyzed Workday Lens rollup cards.",
            "Use the 1d anchor source as the overall frame when present. Use 4h and 1h support sources for chronology, strongest focus periods, and comms/admin patterns.",
            "This is a text-only local Qwen pass. Keep the story grounded in the supplied rollup cards and do not invent missing projects, employers, apps, meetings, or future intent.",
            "Write the headline and summary for the dashboard; fill the remaining required JSON fields conservatively.",
            "Headline must be under 12 words. Summary must be 1-2 concise sentences that are easy to scan.",
            f"These {len(payload.segments)} sources were selected for the dashboard-story pass.",
            "Segments:",
            *segment_lines,
            "Return exactly one strict JSON object with these keys in this order:",
            "headline, summary, activity_type, primary_app, primary_project, productivity, focus_level, user_goal, specific_task, evidence, uncertainty_notes, unsupported_claim_count, contradicted_claim_count, over_specific_claim_count, uncertainty_count, unknown_fields, evidence_coverage_score, confidence.",
            (
                "For day-story fields: activity_type should reflect the dominant day pattern; primary_app may be unknown; "
                "primary_project should be the strongest supported workstream or General work; evidence should cite up to 3 source clues."
            ),
            "Return JSON only. No markdown. No commentary.",
        ]
        return "\n".join(parts)

    def _build_prompt(self, payload: LLMWindowPayload) -> str:
        parts = [
            "System Instruction: Extract evidence from a short personal work-activity transcript.",
            (
                "This is a short-window evidence pass. Do not try to fully understand the user's whole project, "
                "habit, or long-term intention from this window alone."
            ),
            (
                "Capture concrete clues: visible app/context, UI action, accessible text, likely micro-intent, "
                "and whether the evidence is strong or ambiguous."
            ),
            "Accessibility Capture Context:",
            (
                "The transcript is generated from native macOS Accessibility APIs plus conservative pointer and "
                "command-key, gesture, and system-state metadata. It is a compact accessibility transcript, not a screen-reader clone."
            ),
            (
                "Accessibility events may include app names, bundle ids, window titles, roles, states, landmarks, "
                "menu items, dialogs, controls, focused elements, selected text, values, and command-key names."
            ),
            (
                "Use accessibility semantics such as button, slider, edit, document, window, "
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
        parts.append("Current Accessibility Transcript (each line starts with the local captured-at timestamp or timestamp range):")
        parts.append(compacted_transcript)
        parts.append(
            "Output rules:\n"
            "- Focus on evidence for work intent, not compliance or policy.\n"
            "- Be tentative when the window is too short to know the full project or reason.\n"
            "- Use summary to describe observed evidence plus the most likely immediate action.\n"
            "- Use goal for the immediate micro-goal, not a broad day-level goal.\n"
            "- Use message timestamps to understand pacing, pauses, and task transitions inside the window.\n"
            "- Make the final classification after combining accessibility events, command-key metadata, mouse actions, gesture metadata, system-state metadata, hover metadata, app changes, and recent context.\n"
            "- Treat mouse hover tags as visual pointer metadata, not spoken or typed text.\n"
            "- Treat mouse action tags as user input metadata, not spoken or typed text.\n"
            "- Treat gesture tags as high-level input metadata; desktopSwitch, zoom, smartZoom, swipe, and rotate actions can explain navigation or context changes without implying typed content.\n"
            "- Treat system tags as system context; screenLocked, screenUnlocked, displaySleep, displayWake, systemSleep, systemWake, screensaverStarted, and screensaverStopped can explain idle gaps or context changes without implying work content.\n"
            "- For mouse actions, use the transcript line timestamp as the event time; event ids and internal timestamps are intentionally omitted from the tag.\n"
            "- Use click/release action names, scroll direction, coordinates, and nearby accessibility labels to infer what the user targeted.\n"
            "- Consecutive scroll ticks may be compacted into mouse scroll summary lines; treat them as navigation through visible content.\n"
            "- Screenshot paths, screenshot status/reason, button/state, injected flags, wheel details, and image file details are stripped from the text transcript; future image inputs should be analyzed only when attached separately.\n"
            "- Treat mouse hover summary lines as compacted replacements for consecutive hover-only bursts.\n"
            "- Pair hover tags with nearby accessibility labels to infer what UI element the user inspected or targeted.\n"
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

    def _build_rollup_prompt(self, payload: LLMRollupPayload) -> str:
        source_lines = []
        for index, item in enumerate(payload.source_items, start=1):
            source_lines.append(
                f"{index}. {item.get('time_range', 'unknown time')} | "
                f"{item.get('activity_type', 'other')} / {item.get('focus_state', 'steady')} | "
                f"{item.get('project', 'General work')} | "
                f"goal: {item.get('dominant_goal') or item.get('goal') or 'unknown'} | "
                f"headline: {item.get('headline', '')} | summary: {item.get('summary', '')}"
            )
        strategy_lines = self._rollup_strategy_lines(payload.level)
        partial_lines = self._rollup_partial_lines(payload)
        parts = [
            f"System Instruction: Analyze a {payload.level} personal work-activity period.",
            f"Period: {self._format_rollup_period(payload.started_at, payload.ended_at)}.",
            *strategy_lines,
            *partial_lines,
            "Preserve concrete goals, projects, and important time intervals when the source supports them.",
        ]
        if payload.context_summaries:
            parts.extend(
                [
                    f"Recent prior {payload.level} context:",
                    *payload.context_summaries,
                    "Use this context only for continuity and labeling; the current source summaries are the evidence for this rollup.",
                ]
            )
        parts.extend(["Source summaries:", *source_lines])
        if payload.level == "5m" and payload.raw_transcript:
            parts.extend(
                [
                    "Raw accessibility transcript blocks included for this 5-minute bucket:",
                    payload.raw_transcript,
                    (
                        "The raw transcript may include only the earliest lower-level window blocks that fit the 5m raw transcript limit. "
                        "Use it only to validate or correct the lower-level evidence. "
                        "Do not infer a broad project from one isolated noisy utterance."
                    ),
                ]
            )
        parts.append(
            "Output rules:\n"
            "- headline: short user-facing title.\n"
            "- summary: 1-3 sentences describing what happened from start to end.\n"
            "- dominant_goal: the main goal or deliverable the user seemed to pursue.\n"
            "- project: project/workstream, or General work if unclear.\n"
            "- activity_type must be one of: deep_work, planning, research, review, communication, admin, break, other.\n"
            "- focus_state must be one of: focused, steady, switching, blocked, idle.\n"
            "- important_intervals: short list of meaningful time spans or turning points.\n"
            "- secondary_goals: short list of real but less dominant goals.\n"
            "- ignored_noise: short explanation of insignificant activity that was down-weighted.\n"
            "- confidence should be between 0 and 1."
        )
        parts.append(
            "Respond strictly in JSON with keys: headline, summary, dominant_goal, project, "
            "activity_type, focus_state, important_intervals, secondary_goals, ignored_noise, confidence."
        )
        return "\n".join(parts)

    def _format_rollup_period(self, started_at: str, ended_at: str) -> str:
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00")).astimezone(local_timezone())
            end = datetime.fromisoformat(ended_at.replace("Z", "+00:00")).astimezone(local_timezone())
        except ValueError:
            return f"{started_at} to {ended_at}"
        if start.date() == end.date():
            return f"{start:%Y-%m-%d %H:%M}-{end:%H:%M} local time"
        return f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} local time"

    def _rollup_partial_lines(self, payload: LLMRollupPayload) -> list[str]:
        if not self._rollup_period_is_in_progress(payload):
            return []
        if payload.level == "1d":
            return [
                "This day bucket is still in progress. Summarize it as the day so far.",
                "Use only completed 4-hour summaries that are present; do not invent activity later in the day.",
            ]
        if payload.level == "1w":
            return [
                "This week bucket is still in progress. Summarize it as the week so far.",
                "Use only completed day summaries that are present; do not invent activity later in the week.",
            ]
        return []

    def _rollup_period_is_in_progress(self, payload: LLMRollupPayload) -> bool:
        try:
            ended_at = datetime.fromisoformat(payload.ended_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return ended_at.astimezone(timezone.utc) > datetime.now(timezone.utc)

    def _rollup_strategy_lines(self, level: str) -> list[str]:
        if level == "5m":
            return [
                "This is a short evidence-synthesis pass.",
                "Combine the 1-minute evidence into a clearer local picture, but avoid broad claims about the user's whole day.",
                "Identify the likely immediate task, ambiguous cues, and any tiny side actions that should be down-weighted.",
            ]
        if level == "15m":
            return [
                "This is the first intent-inference pass.",
                "Infer what the user was probably trying to accomplish across the 15-minute period.",
                "Separate the main intent from brief support actions, checks, or distractions.",
            ]
        if level == "1h":
            return [
                "Infer the dominant work intent for the hour.",
                "Summarize by dominant time and intent, not by every tiny event.",
                "Explain whether the hour looked like deep work, planning, review, communication, admin, break, or mixed context switching.",
            ]
        if level == "4h":
            return [
                "Infer the larger work arc across this multi-hour block.",
                "Identify the main project or workstream, secondary threads, and meaningful transitions.",
                "Down-weight minor habits or interruptions unless they repeatedly changed the user's direction.",
            ]
        if level == "1d":
            return [
                "Infer the user's day-level story: main projects, dominant goals, focus blocks, context switches, and recovery patterns.",
                "Summarize what the user was trying to do overall, not just what apps they touched.",
                "Mention recurring habits only when they shaped the day or interrupted/reinforced focus.",
            ]
        if level == "1w":
            return [
                "Infer the user's week-level story: active projects, recurring goals, repeated habits, focus patterns, and major shifts.",
                "Summarize what the user appeared to be working toward across days.",
                "If the source summaries cover only part of the week, describe it as the week so far and do not invent future days.",
                "Prefer durable patterns over one-off events.",
            ]
        return [
            "Infer the dominant intent for this period.",
            "Summarize by dominant time and intent, not by every tiny event.",
        ]

    def _build_gantt_prompt(self, payload: LLMGanttPayload) -> str:
        candidate_lines = []
        for item in payload.candidates:
            candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
            parent = item.get("parent") if isinstance(item.get("parent"), dict) else {}
            candidate_lines.append(
                "Candidate "
                f"{item.get('candidate_id')}: mode={payload.mode}; "
                f"duration_fraction={item.get('duration_fraction')}; "
                f"consecutive_child_count={item.get('consecutive_child_count')}; "
                f"exceptional={item.get('exceptional')}; "
                f"parent={parent.get('time_range')} | {parent.get('activity_type')} / {parent.get('focus_state')} | "
                f"{parent.get('project')} | {parent.get('headline')} | {parent.get('summary')}; "
                f"child={candidate.get('time_range')} | {candidate.get('activity_type')} / {candidate.get('focus_state')} | "
                f"{candidate.get('project')} | {candidate.get('headline')} | {candidate.get('summary')}"
            )
        return "\n".join(
            [
                "System Instruction: Rank candidate interruptions for a compact personal-work Gantt chart.",
                f"View: {payload.mode}, period {payload.started_at} to {payload.ended_at}.",
                "The chart already has larger parent blocks. Smaller child blocks should replace parent time only when they are significant or disruptive enough to be visible at this zoom level.",
                "Meetings, calls, standups, reviews with other people, and strong context switches are usually high disruption.",
                "Deep work that continues the same project and goal as the parent is usually the same task and should not interrupt the parent.",
                "Longer consecutive child runs become more significant, but do not over-promote tiny routine app switches.",
                "For every candidate, return a score basis, not the final promotion decision.",
                "Use lane exactly one of: deep, meetings, comms, breaks.",
                "Respond strictly in JSON with this shape: {\"decisions\":[{\"candidate_id\":\"c1\",\"significance\":0.0,\"disruption\":0.0,\"same_task\":false,\"lane\":\"meetings\",\"display_label\":\"Short label\",\"reason\":\"Short reason\"}]}",
                "Candidates:",
                *candidate_lines,
            ]
        )

    def _build_gantt_composer_prompt(self, payload: LLMGanttComposerPayload) -> str:
        source_lines = []
        for item in payload.sources:
            source_lines.append(
                "Source "
                f"{item.get('id')}: "
                f"level={item.get('level')}; "
                f"range={item.get('time_range')}; "
                f"from={item.get('from')}; to={item.get('to')}; "
                f"lane_hint={item.get('lane')}; "
                f"activity={item.get('activity_type')} / {item.get('focus_state')}; "
                f"project={item.get('project')}; "
                f"headline={item.get('headline')}; "
                f"summary={item.get('summary')}; "
                f"evidence={item.get('evidence')}"
            )
        context_lines = []
        for item in payload.contexts:
            context_lines.append(
                "Context "
                f"{item.get('id')}: "
                f"level={item.get('level')}; "
                f"range={item.get('time_range')}; "
                f"activity={item.get('activity_type')} / {item.get('focus_state')}; "
                f"project={item.get('project')}; "
                f"headline={item.get('headline')}; "
                f"summary={item.get('summary')}; "
                f"evidence={item.get('evidence')}"
            )
        return "\n".join(
            [
                "System Instruction: Compose the final display blocks for a personal-work Gantt chart.",
                f"View: {payload.mode}, period {payload.started_at} to {payload.ended_at}.",
                "You have full authority over the final display blocks and lanes, but every visible non-gap block must stay grounded in the supplied source evidence.",
                "Use the coarser Context summaries to decide which adjacent Source blocks belong to the same workstream and should be merged. Context is guidance for grouping and labeling; source_ids should still cite the finer Source blocks that justify the visible interval.",
                "Merge adjacent similar project/task blocks when they read like one continuous workstream. Prefer fewer readable blocks over many tiny repeated labels.",
                "Assign visual_group and visual_tone for subtle color continuity. Blocks that belong to the same project, product, feature, or workstream should share the same visual_group and visual_tone even if their labels differ.",
                "Prefer project identity over micro-goal for visual_group. If multiple blocks mention Workday Lens or clearly share Workday as the product context, use visual_group=\"Workday Lens\" for all of them.",
                "visual_group should be a short stable workstream name like \"Workday Lens\" or \"DGX setup research\".",
                "visual_tone must be one of: base, warm, peach, amber, soft. These are subtle nearby variants of the original lane color, not different rainbow hues. Reuse tones for related work.",
                "Use pretty labels of 2-5 words. Summaries should be concrete and calm.",
                "Fill uncovered past time with low-emphasis gap blocks named \"Away from keyboard\" in the breaks lane. Do not create gap blocks for future time after the current moment. Gaps mean uncaptured or unanalyzed activity, not confirmed breaks.",
                "Return final chart blocks only. They must be sorted by time and must not overlap each other.",
                "Lane rules:",
                "- deep: focused work, research, planning, implementation, review, writing, or project-heavy activity.",
                "- comms: messages, email, chat, brief replies, or lightweight coordination.",
                "- meetings: only real meeting-like activity supported by evidence, such as Zoom, Teams meeting/call, Google Meet, Slack huddle, Discord voice, calendar/attendee context, standup meeting, 1:1, video call, or voice call.",
                "- Do not label vague review, sync, admin, demo prep, project review work, dashboard metric text, or labels like Meetings Time / meeting blocks as meetings unless the evidence supports an actual meeting/call with other people.",
                "- breaks: Away from keyboard gaps, idle/offline periods, or clear non-work breaks.",
                "If a small meeting-like source truly interrupts a larger work block, let it dominate that interval. Otherwise fold tiny side actions into the surrounding workstream.",
                "Use source_ids to cite the source blocks that justify each non-gap display block. For merged blocks, include every relevant source id.",
                "For evidence, provide a short source-evidence summary, not a chain-of-thought.",
                "Respond strictly in JSON with this shape:",
                "{\"blocks\":[{\"from\":\"ISO timestamp\",\"to\":\"ISO timestamp\",\"lane\":\"deep|meetings|comms|breaks\",\"label\":\"Short label\",\"summary\":\"User-facing summary\",\"project\":\"Project or General work\",\"source_ids\":[\"source-id\"],\"is_gap\":false,\"reason\":\"Composer reason grounded in source evidence\",\"evidence\":\"Brief evidence summary\",\"visual_group\":\"Stable workstream name\",\"visual_tone\":\"base\"}]}",
                "Coarser context summaries for grouping:",
                *context_lines,
                "Sources:",
                *source_lines,
            ]
        )

    def _build_day_story_prompt(self, payload: DayStoryPayload) -> str:
        segment_lines = []
        for index, segment in enumerate(payload.segments, start=1):
            source_level = segment.get("source_level") or "segment"
            source_role = segment.get("source_role") or "support"
            segment_lines.append(
                f"{index}. {source_level} {source_role} | {segment['time_range']} | {segment['activity_label']} | {segment['project']} | "
                f"{segment['headline']} | {segment['summary']}"
            )
        return "\n".join(
            [
                f"System Instruction: Summarize a single workday into one headline and one short dashboard insight for {payload.day}.",
                "You are summarizing already-analyzed rollup cards into a calmer dashboard story.",
                "If a 1d anchor source is present, always use it as the overall frame; it may be detailed, so make the final dashboard wording shorter and clearer.",
                "Use the selected 4h and 1h support sources as evidence for chronology, strongest focus/deep-work, and comms/admin patterns.",
                f"These {len(payload.segments)} sources were selected for the dashboard-story pass.",
                "Keep the headline under 12 words.",
                "Keep the summary to 1-2 sentences and make it easy to scan in a dashboard.",
                "Mention the strongest focus period or the main coordination pattern when possible.",
                "Respond strictly in JSON with keys: headline, summary.",
                "Segments:",
                *segment_lines,
            ]
        )


llm_service = LLMService()
