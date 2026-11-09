from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


ACTIVITY_TYPES = {
    "deep_work",
    "planning",
    "research",
    "review",
    "communication",
    "admin",
    "break",
    "other",
}

FOCUS_STATES = {
    "focused",
    "steady",
    "switching",
    "blocked",
    "idle",
}

PRODUCTIVITY_STATES = {
    "productive",
    "neutral",
    "unproductive",
    "unknown",
}


def normalize_activity_analysis(
    payload: Mapping[str, Any] | None,
    *,
    fallback_text: str = "",
    transcript: str = "",
) -> dict[str, Any]:
    data = dict(payload or {})
    summary = _clean_text(data.get("summary")) or _fallback_summary(fallback_text, transcript)
    activity_type = _normalize_choice(data.get("activity_type"), ACTIVITY_TYPES, "other")
    focus_state = _normalize_choice(data.get("focus_state") or data.get("focus_level"), FOCUS_STATES, "steady")
    headline = _clean_text(data.get("headline")) or _headline_for(activity_type, summary)
    goal = _clean_text(data.get("goal") or data.get("user_goal")) or _goal_for(activity_type, summary)
    project = _clean_text(data.get("project") or data.get("primary_project")) or "General work"
    next_step = _clean_text(data.get("next_step") or data.get("specific_task")) or _next_step_for(activity_type)
    confidence = _normalize_confidence(data.get("confidence"), default=0.58)
    dominant_goal = _clean_text(data.get("dominant_goal")) or goal
    secondary_goals = _clean_text_list(data.get("secondary_goals"))
    important_intervals = _clean_text_list(data.get("important_intervals"))
    ignored_noise = _clean_text(data.get("ignored_noise"))
    primary_app = _clean_text(data.get("primary_app"))
    productivity = _normalize_choice(data.get("productivity"), PRODUCTIVITY_STATES, "unknown")
    evidence = _clean_text_list(data.get("evidence"))[:3]
    uncertainty_notes = _clean_text_list(data.get("uncertainty_notes"))[:3]
    unknown_fields = _clean_text_list(data.get("unknown_fields"))[:3]
    return {
        "headline": headline,
        "summary": summary,
        "goal": goal,
        "user_goal": goal,
        "dominant_goal": dominant_goal,
        "project": project,
        "primary_project": project,
        "primary_app": primary_app,
        "productivity": productivity,
        "activity_type": activity_type,
        "focus_state": focus_state,
        "focus_level": focus_state,
        "next_step": next_step,
        "specific_task": next_step,
        "evidence": evidence,
        "uncertainty_notes": uncertainty_notes,
        "unsupported_claim_count": _normalize_int(data.get("unsupported_claim_count"), default=0),
        "contradicted_claim_count": _normalize_int(data.get("contradicted_claim_count"), default=0),
        "over_specific_claim_count": _normalize_int(data.get("over_specific_claim_count"), default=0),
        "uncertainty_count": _normalize_int(data.get("uncertainty_count"), default=len(uncertainty_notes)),
        "unknown_fields": unknown_fields,
        "evidence_coverage_score": _normalize_confidence(data.get("evidence_coverage_score"), default=0.0),
        "secondary_goals": secondary_goals,
        "important_intervals": important_intervals,
        "ignored_noise": ignored_noise,
        "confidence": confidence,
    }


def serialize_activity_analysis(analysis: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "headline": analysis.get("headline", ""),
            "summary": analysis.get("summary", ""),
            "goal": analysis.get("goal", ""),
            "user_goal": analysis.get("user_goal", analysis.get("goal", "")),
            "dominant_goal": analysis.get("dominant_goal", analysis.get("goal", "")),
            "project": analysis.get("project", "General work"),
            "primary_project": analysis.get("primary_project", analysis.get("project", "General work")),
            "primary_app": analysis.get("primary_app", ""),
            "productivity": analysis.get("productivity", "unknown"),
            "activity_type": analysis.get("activity_type", "other"),
            "focus_state": analysis.get("focus_state", "steady"),
            "focus_level": analysis.get("focus_level", analysis.get("focus_state", "steady")),
            "next_step": analysis.get("next_step", ""),
            "specific_task": analysis.get("specific_task", analysis.get("next_step", "")),
            "evidence": _clean_text_list(analysis.get("evidence"))[:3],
            "uncertainty_notes": _clean_text_list(analysis.get("uncertainty_notes"))[:3],
            "unsupported_claim_count": _normalize_int(analysis.get("unsupported_claim_count"), default=0),
            "contradicted_claim_count": _normalize_int(analysis.get("contradicted_claim_count"), default=0),
            "over_specific_claim_count": _normalize_int(analysis.get("over_specific_claim_count"), default=0),
            "uncertainty_count": _normalize_int(analysis.get("uncertainty_count"), default=0),
            "unknown_fields": _clean_text_list(analysis.get("unknown_fields"))[:3],
            "evidence_coverage_score": _normalize_confidence(analysis.get("evidence_coverage_score"), default=0.0),
            "secondary_goals": _clean_text_list(analysis.get("secondary_goals")),
            "important_intervals": _clean_text_list(analysis.get("important_intervals")),
            "ignored_noise": _clean_text(analysis.get("ignored_noise")),
            "confidence": _normalize_confidence(analysis.get("confidence"), default=0.58),
        },
        ensure_ascii=True,
    )


def parse_activity_analysis(summary_text: str | None, *, fallback_excerpt: str = "") -> dict[str, Any]:
    if not summary_text:
        return normalize_activity_analysis(None, transcript=fallback_excerpt)
    try:
        raw = json.loads(summary_text)
    except json.JSONDecodeError:
        raw = {"summary": summary_text}
    if not isinstance(raw, dict):
        raw = {"summary": summary_text}
    return normalize_activity_analysis(raw, fallback_text=summary_text, transcript=fallback_excerpt)


def build_context_summary(summary_text: str | None) -> str:
    analysis = parse_activity_analysis(summary_text)
    return f"{analysis['headline']}: {analysis['summary']}"


def activity_type_label(value: str) -> str:
    labels = {
        "deep_work": "Deep Work",
        "planning": "Planning",
        "research": "Research",
        "review": "Review",
        "communication": "Communication",
        "admin": "Admin",
        "break": "Break",
        "other": "Other",
    }
    return labels.get(value, "Other")


def focus_state_label(value: str) -> str:
    labels = {
        "focused": "Focused",
        "steady": "Steady",
        "switching": "Switching",
        "blocked": "Blocked",
        "idle": "Idle",
    }
    return labels.get(value, "Steady")


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _clean_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower().replace(" ", "_")
    return normalized if normalized in allowed else default


def _normalize_confidence(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def _normalize_int(value: Any, *, default: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, numeric)


def _fallback_summary(fallback_text: str, transcript: str) -> str:
    source = _clean_text(fallback_text) or _clean_text(transcript)
    if not source:
        return "Captured activity without enough detail to classify."
    words = source.split()
    if len(words) <= 24:
        return source
    return " ".join(words[:24]) + "..."


def _headline_for(activity_type: str, summary: str) -> str:
    templates = {
        "deep_work": "Building and drafting",
        "planning": "Organizing the next move",
        "research": "Reading and investigating",
        "review": "Reviewing existing work",
        "communication": "Coordinating with others",
        "admin": "Handling routine work",
        "break": "Stepping away",
        "other": "General activity",
    }
    base = templates.get(activity_type, "General activity")
    if not summary:
        return base
    trimmed = summary.split(".")[0].strip()
    if len(trimmed) <= 80:
        return trimmed
    return base


def _goal_for(activity_type: str, summary: str) -> str:
    defaults = {
        "deep_work": "Make meaningful progress on the current deliverable.",
        "planning": "Turn open work into a clearer plan of attack.",
        "research": "Gather the information needed to move forward.",
        "review": "Evaluate existing work and identify the next changes.",
        "communication": "Align with others and unblock shared work.",
        "admin": "Keep routine tasks moving.",
        "break": "Pause briefly before the next block of work.",
        "other": "Advance the current workstream.",
    }
    if summary:
        return defaults.get(activity_type, defaults["other"])
    return defaults["other"]


def _next_step_for(activity_type: str) -> str:
    defaults = {
        "deep_work": "Keep the current task moving until the next clear milestone.",
        "planning": "Convert this plan into a concrete next action.",
        "research": "Turn the findings into a decision or implementation step.",
        "review": "Capture the key change request or follow-up action.",
        "communication": "Record decisions and return to execution.",
        "admin": "Close the loop and move back to primary work.",
        "break": "Resume with the clearest pending task.",
        "other": "Clarify the next meaningful step.",
    }
    return defaults.get(activity_type, defaults["other"])
