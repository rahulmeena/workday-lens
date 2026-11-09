"""Historical prompt-comparison heuristic, extracted without private inputs.

Preserves the original scoring implementation. This is a lexical/structural
proxy, not an LLM judge or a semantic-accuracy measure.
"""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import statistics
from typing import Any

@dataclass
class ExperimentCard:
    source_id: str
    captured_from: Any
    transcript: str
    silver: dict[str, Any]


def _norm(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _similarity(left: Any, right: Any) -> float:
    left_norm = _norm(left)
    right_norm = _norm(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _token_set(value: Any) -> set[str]:
    return {token for token in _norm(value).split() if len(token) > 2}


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(right_tokens))


def _field_match(parsed: dict[str, Any], silver: dict[str, Any]) -> float:
    exact_keys = ("activity_type", "productivity", "focus_level")
    exact = [
        1.0 if _norm(parsed.get(key)) and _norm(parsed.get(key)) == _norm(silver.get(key)) else 0.0
        for key in exact_keys
    ]
    fuzzy = [
        _similarity(parsed.get("primary_app"), silver.get("primary_app")),
        _similarity(parsed.get("primary_project"), silver.get("primary_project")),
        _similarity(parsed.get("user_goal"), silver.get("user_goal")),
        _similarity(parsed.get("specific_task"), silver.get("specific_task")),
    ]
    return statistics.mean(exact + fuzzy)


def _collapse_flags(parsed: dict[str, Any], transcript: str) -> list[str]:
    headline = str(parsed.get("headline") or "").strip()
    summary = str(parsed.get("summary") or "").strip()
    flags: list[str] = []
    if not headline or not summary:
        flags.append("missing_core")
    if len(_norm(headline).split()) > 14:
        flags.append("headline_long")
    if _similarity(headline, summary) > 0.84:
        flags.append("headline_summary_duplicate")
    if "{" in headline or "}" in headline or "json" in headline.lower():
        flags.append("instruction_leak")
    transcript_lines = [re.sub(r"^\[[^\]]+\]\s*", "", line).strip() for line in transcript.splitlines()]
    long_lines = [line for line in transcript_lines if len(line) >= 45]
    if long_lines:
        headline_overlap = max((_token_overlap(headline, line) for line in long_lines), default=0.0)
        summary_overlap = max((_token_overlap(summary, line) for line in long_lines), default=0.0)
        if headline_overlap >= 0.88 and len(_norm(headline).split()) >= 7:
            flags.append("headline_copies_title")
        if summary_overlap >= 0.88 and len(_norm(summary).split()) >= 12:
            flags.append("summary_copies_title")
    return flags


def _score(parsed: dict[str, Any], card: ExperimentCard) -> dict[str, Any]:
    silver = card.silver
    headline_sim = _similarity(parsed.get("headline"), silver.get("headline"))
    summary_sim = _similarity(parsed.get("summary"), silver.get("summary"))
    field_score = _field_match(parsed, silver)
    evidence_text = " ".join(str(item) for item in (parsed.get("evidence") or []) if isinstance(item, str))
    evidence_overlap = _token_overlap(evidence_text, f"{silver.get('headline')} {silver.get('summary')}")
    flags = _collapse_flags(parsed, card.transcript)
    noncollapse = 1.0 if not flags else max(0.0, 1.0 - 0.18 * len(flags))
    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence_sanity = 1.0 if 0.15 <= confidence <= 0.95 else 0.5
    combined = (
        0.22 * headline_sim
        + 0.38 * summary_sim
        + 0.20 * field_score
        + 0.10 * evidence_overlap
        + 0.08 * noncollapse
        + 0.02 * confidence_sanity
    )
    return {
        "combined": combined,
        "headline_sim": headline_sim,
        "summary_sim": summary_sim,
        "field_score": field_score,
        "evidence_overlap": evidence_overlap,
        "noncollapse": noncollapse,
        "confidence_sanity": confidence_sanity,
        "flags": ",".join(flags),
    }
