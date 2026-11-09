"""Run the dashboard backend with fictional data, isolated from real capture."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / ".demo-data"
MARKER = "workday-lens-synthetic-demo-v1"

# Duration, headline, type, project, fictional evidence. No captured user data.
ACTIVITIES = [
    (45, "Designing an activity memory pipeline", "planning", "Context Engine", "Outlined event schemas and a bounded context pipeline in the design document."),
    (90, "Building reliable event ingestion", "deep_work", "Context Engine", "Implemented validation and retry handling; added synthetic batch-ingest tests."),
    (30, "Discussing the capture API", "communication", "Context Engine", "Met the team in Google Meet to review the event contract and open questions."),
    (15, "Taking a screen break", "break", "Personal", "A fictional break between work sessions."),
    (75, "Comparing local inference outputs", "research", "Local Models", "Compared structured summaries on fictional transcripts and inspected unsupported claims."),
    (45, "Reviewing a timeline change", "review", "Timeline UI", "Checked date boundaries, source links, and loading states in a pull request."),
    (30, "Lunch and time away", "break", "Personal", "A fictional lunch break with no desktop activity."),
    (90, "Connecting the hierarchy to the dashboard", "deep_work", "Timeline UI", "Wired rollup queries and rendered drill-down cards for the sample day."),
    (30, "Writing up decisions and next steps", "communication", "Context Engine", "Replied to project questions in Slack and posted decisions, test results, and next steps."),
]


def configure_demo() -> None:
    """Fail closed if this folder is not ours, and override inherited real settings."""
    marker = DEMO_DIR / ".demo-marker"
    if DEMO_DIR.is_symlink():
        raise SystemExit("Refusing a symlinked demo directory.")
    if DEMO_DIR.exists() and any(DEMO_DIR.iterdir()):
        if not marker.is_file() or marker.read_text() != MARKER:
            raise SystemExit("Refusing to reuse an unrelated .demo-data directory.")
    DEMO_DIR.mkdir(exist_ok=True)
    marker.write_text(MARKER)
    for name in list(os.environ):
        if name.startswith("WFHS_"):
            del os.environ[name]
    os.environ.update({
        "WFHS_DATA_DIR": str(DEMO_DIR),
        "WFHS_DATABASE_URL": f"sqlite:///{(DEMO_DIR / 'demo.db').as_posix()}",
        "WFHS_RUNTIME_SETTINGS_PATH": str(DEMO_DIR / "runtime-settings.json"),
        "WFHS_RUNTIME_SECRETS_PATH": str(DEMO_DIR / "runtime-secrets.json"),
        "WFHS_FAKE_LLM": "true",
        "WFHS_DISPLAY_NAME": "Demo",
        "WFHS_OPENAI_API_KEY": "",
    })
    # Keep fake mode enforced even if a previous demo user changed Settings.
    (DEMO_DIR / "runtime-settings.json").write_text(json.dumps({
        "display_name": "Demo", "fake_llm_mode": True, "llm_provider": "openai",
    }))
    (DEMO_DIR / "runtime-secrets.json").write_text("{}")


def seed() -> None:
    from sqlalchemy import select
    from backend.app.db import SessionLocal, init_db
    from backend.app.models import ActivityRollup, LLMRun, Message, Window, WindowStatus
    from backend.app.services.analysis import normalize_activity_analysis, serialize_activity_analysis
    from backend.app.services.rollup import bucket_bounds_for, ROLLUP_LEVELS, ROLLUP_CHILD_LEVEL

    init_db()
    with SessionLocal() as db:
        if db.scalar(select(Window.id).limit(1)):
            print("Using the existing synthetic day. Remove .demo-data while stopped to refresh it.")
            return
        start = (datetime.now().astimezone() - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        minute_rows = []
        offset = 0
        for duration, headline, kind, project, evidence in ACTIVITIES:
            analysis = normalize_activity_analysis({
                "headline": headline, "summary": evidence, "goal": headline,
                "project": project, "activity_type": kind,
                "focus_state": "idle" if kind == "break" else "focused",
                "next_step": "Continue with the next planned task.",
                "confidence": 0.85, "evidence": [evidence],
                "uncertainty_notes": ["Fictional demo data; not a model evaluation."],
            })
            summary = serialize_activity_analysis(analysis)
            for minute in range(duration):
                began = (start + timedelta(minutes=offset + minute)).astimezone(timezone.utc)
                ended = began + timedelta(minutes=1)
                item = Window(session_id="synthetic-demo", started_at=began, ended_at=ended,
                              token_count=0, status=WindowStatus.PROCESSED)
                db.add(item)
                db.flush()
                db.add(Message(session_id="synthetic-demo", source="demo:fictional",
                               text=f"[SYNTHETIC] {evidence}", captured_at=began, window_id=item.id))
                db.add(LLMRun(window_id=item.id, prompt_tokens=0, completion_tokens=0,
                              total_tokens=0, latency_ms=0, verdict=WindowStatus.PROCESSED,
                              confidence=0.85, summary_text=summary, model_name="synthetic-demo"))
                minute_rows.append((began, summary))
            offset += duration
        for level in ROLLUP_LEVELS:
            buckets = {}
            for began, summary in minute_rows:
                bounds = bucket_bounds_for(began, level)
                buckets.setdefault(bounds, []).append((began, summary))
            for (began, ended), children in buckets.items():
                summaries = [summary for _, summary in children]
                summary = Counter(summaries).most_common(1)[0][0]
                child_level = ROLLUP_CHILD_LEVEL.get(level)
                source_count = (len({bucket_bounds_for(at, child_level) for at, _ in children})
                                if child_level else len(children))
                if level in {"1d", "1w"}:
                    summary = serialize_activity_analysis(normalize_activity_analysis({
                        "headline": "From capture design to a working timeline",
                        "summary": "Designed the Context Engine and implemented reliable ingestion. Compared local model outputs on fictional evidence. Connected hierarchical summaries to the dashboard and reviewed the timeline UI.",
                        "goal": "Build an inspectable desktop activity pipeline.",
                        "project": "Context Engine", "activity_type": "deep_work",
                        "focus_state": "focused", "confidence": 0.85,
                        "secondary_goals": ["Evaluate local inference", "Polish the timeline"],
                    }))
                db.add(ActivityRollup(level=level, started_at=began, ended_at=ended,
                                     status=WindowStatus.PROCESSED, source_count=source_count,
                                     summary_text=summary, confidence=0.85, model_name="synthetic-demo"))
            db.flush()
        db.commit()
        print(f"Seeded {len(minute_rows)} fictional minutes for {start.date()} in {DEMO_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    configure_demo()
    seed()
    if not args.seed_only:
        import uvicorn
        print(f"Synthetic demo API: http://127.0.0.1:{args.port}/docs")
        print("No native capture or external model service is started.")
        uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
