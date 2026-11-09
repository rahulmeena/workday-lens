"""Build the original judge instructions around caller-supplied evidence.

No inference or network calls. These rubrics preserve the historical research
protocol; the automation rubric includes exploratory, unvalidated constructs.
Use synthetic or consented evidence. Never commit rendered private prompts.
"""
from __future__ import annotations
import json
from pathlib import Path

RUBRICS = Path(__file__).parent / "rubrics"
KINDS = {"reference", "source-grounded", "automation"}


def build_prompt(kind: str, payload: dict) -> str:
    if kind not in KINDS:
        raise ValueError(f"Unknown rubric: {kind}")
    return (RUBRICS / f"{kind}.txt").read_text() + "\nEvaluation payload:\n" + json.dumps(payload, ensure_ascii=True, indent=2)


def output_schema(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError(f"Unknown rubric: {kind}")
    return json.loads((RUBRICS / f"{kind}.schema.json").read_text())
