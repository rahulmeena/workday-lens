from __future__ import annotations

import os
import tempfile

import pytest
from pydantic import ValidationError


_TEST_DIR = tempfile.mkdtemp(prefix="workday-lens-backend-tests-")
os.environ["WFHS_DATABASE_URL"] = f"sqlite:///{_TEST_DIR}/test.db"
os.environ["WFHS_FAKE_LLM"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.db import SessionLocal  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import Message, Window  # noqa: E402
from backend.app.schemas import CaptureEventIn  # noqa: E402
from backend.app.services.capture import DEFAULT_MACOS_SESSION_ID, capture_event_transcript_line, message_from_capture_event  # noqa: E402
from backend.app.services.llm import llm_service  # noqa: E402


def _base_event(**overrides):
    payload = {
        "schema": "workday_lens_capture_event.v1",
        "event_id": "event-1",
        "captured_at": "2026-05-21T09:00:00Z",
        "source_platform": "macos",
        "tag": "focus",
        "app_name": "Finder",
        "bundle_id": "com.apple.finder",
        "process_id": 123,
        "window_title": "Documents",
        "role": "AXButton",
        "name": "Share",
        "states": ["focused"],
        "element_bounds": {"x": 10, "y": 20, "width": 80, "height": 24},
    }
    payload.update(overrides)
    return payload


def test_capture_event_schema_is_macos_only_and_rejects_image_bytes():
    valid = CaptureEventIn.model_validate(_base_event())
    assert valid.source_platform == "macos"

    with pytest.raises(ValidationError):
        CaptureEventIn.model_validate(_base_event(source_platform="windows"))

    with pytest.raises(ValidationError):
        CaptureEventIn.model_validate(
            _base_event(
                screenshot={
                    "local_path": "/Users/demo/Library/Application Support/WorkdayLens/ScreenCaptures/shot.png",
                    "reason": "clickDown",
                    "captured_at": "2026-05-21T09:00:00Z",
                    "image_bytes": "not-allowed",
                }
            )
        )


def test_capture_event_formatter_produces_accessibility_transcript_lines():
    event = CaptureEventIn.model_validate(
        _base_event(
            tag="mouse_hover",
            app_name="Google Chrome",
            x=50,
            y=60,
            element_bounds={"x": 40, "y": 50, "width": 120, "height": 32},
        )
    )

    line = capture_event_transcript_line(event)

    assert line.startswith("[mouse hover platform=macos")
    assert "appName=Google Chrome" in line
    assert "location=40,50,120x32" in line
    assert "role=AXButton" in line


def test_mouse_hover_formatter_includes_accessibility_text():
    event = CaptureEventIn.model_validate(
        _base_event(
            tag="mouse_hover",
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            window_title="Untitled",
            role="AXTextArea",
            value="Hover-visible document text",
            selected_text="document",
            ancestors=[{"role": "AXScrollArea"}, {"role": "AXWindow", "name": "Untitled"}],
            x=12,
            y=34,
        )
    )

    line = capture_event_transcript_line(event)

    assert line.startswith("[mouse hover")
    assert "window=Untitled" in line
    assert "value=\"Hover-visible document text\"" in line
    assert "selected_text=document" in line
    assert "ancestors=\"AXScrollArea > AXWindow:Untitled\"" in line
    assert "speech_like=" in line


def test_keyboard_activity_formatter_redacts_ordinary_keys():
    event = CaptureEventIn.model_validate(
        _base_event(
            tag="keyboard_activity",
            app_name="Google Chrome",
            bundle_id="com.google.Chrome",
            extra={"key_class": "character", "key_redacted": True, "modifiers": "shift"},
        )
    )

    line = capture_event_transcript_line(event)

    assert line.startswith("[keyboard activity")
    assert "key_class=character" in line
    assert "modifiers=shift" in line
    assert "key=redacted" in line
    assert "keycode" not in line


def test_gesture_formatter_keeps_semantics_without_finger_data():
    event = CaptureEventIn.model_validate(
        _base_event(
            tag="gesture",
            app_name="Safari",
            bundle_id="com.apple.Safari",
            window_title="Workday Lens",
            role="AXWebArea",
            name="Timeline",
            x=120,
            y=240,
            extra={
                "gesture_type": "desktop_switch",
                "action": "desktopSwitch",
                "axis": "horizontal",
                "direction": "left",
                "source": "active_space_notification",
            },
        )
    )

    line = capture_event_transcript_line(event)

    assert line.startswith("[gesture]")
    assert '"gestureType":"desktop_switch"' in line
    assert '"action":"desktopSwitch"' in line
    assert '"direction":"left"' in line
    assert '"app":"Safari"' in line
    assert "finger" not in line.lower()


def test_system_state_formatter_records_session_events():
    event = CaptureEventIn.model_validate(
        _base_event(
            tag="system_state",
            app_name="Finder",
            bundle_id="com.apple.finder",
            window_title="Desktop",
            extra={
                "action": "screenLocked",
                "state": "locked",
                "source": "distributed_notification",
            },
        )
    )

    line = capture_event_transcript_line(event)

    assert line.startswith("[system]")
    assert '"action":"screenLocked"' in line
    assert '"state":"locked"' in line
    assert '"source":"distributed_notification"' in line
    assert '"app":"Finder"' in line


def test_accessibility_text_formatter_includes_ui_text_value():
    event = CaptureEventIn.model_validate(
        _base_event(
            tag="ui_text",
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            role="AXTextArea",
            name="Document text",
            value="Drafting a Workday Lens note",
            extra={"text_source": "value", "text_length": 29},
        )
    )

    line = capture_event_transcript_line(event)

    assert line.startswith("[accessibility ui_text")
    assert "role=AXTextArea" in line
    assert "value=\"Drafting a Workday Lens note\"" in line
    assert "text_source" in line
    assert "speech_like=" in line


def test_accessibility_text_formatter_keeps_redaction_metadata():
    event = CaptureEventIn.model_validate(
        _base_event(
            tag="value_change",
            app_name="Safari",
            bundle_id="com.apple.Safari",
            role="AXSecureTextField",
            name="Password",
            value="[redacted]",
            selected_text="[redacted]",
            extra={
                "text_source": "value",
                "redacted": True,
                "redaction_reason": "secure_text_field",
            },
        )
    )

    line = capture_event_transcript_line(event)

    assert line.startswith("[accessibility value_change")
    assert "value=\"[redacted]\"" in line
    assert "selected_text=\"[redacted]\"" in line
    assert "redaction_reason" in line
    assert "secure_text_field" in line


def test_batch_ingest_stores_messages_and_queues_window():
    events = [
        _base_event(event_id="batch-1", captured_at="2026-05-21T09:00:00Z", tag="foreground"),
        _base_event(event_id="batch-2", captured_at="2026-05-21T09:01:01Z", tag="focus_entered"),
    ]

    with TestClient(app) as client:
        response = client.post("/api/v1/capture/events/batch", json={"events": events})

    assert response.status_code == 202
    assert response.json() == {
        "accepted_events": 2,
        "stored_messages": 2,
        "queued_windows": 1,
    }

    with SessionLocal() as session:
        messages = session.query(Message).order_by(Message.id.asc()).all()
        windows = session.query(Window).all()

    assert len(messages) == 2
    assert len(windows) >= 1
    assert messages[0].source.startswith("macos:foreground:")
    assert "[accessibility foreground" in messages[0].text


def test_capture_message_debug_feed_returns_stored_prompt_inputs():
    event = CaptureEventIn.model_validate(
        _base_event(
            event_id="debug-feed-1",
            captured_at="2026-05-21T09:02:00Z",
            tag="mouse_action",
            app_name="Google Chrome",
            bundle_id="com.google.Chrome",
            window_title="Dashboard",
            role="AXButton",
            name="Submit report",
            description="Submit report",
            value="Submit",
            states=["enabled"],
            element_bounds={"x": 90, "y": 190, "width": 120, "height": 32},
            ancestors=[{"role": "AXToolbar", "name": "Actions"}],
            x=100,
            y=200,
            button="left",
            state="down",
            extra={"action": "leftDown"},
        )
    )

    with SessionLocal() as session:
        latest = session.query(Message.id).order_by(Message.id.desc()).first()
        after_id = latest[0] if latest else 0
        session.add(message_from_capture_event(event, session_id=DEFAULT_MACOS_SESSION_ID))
        session.commit()

    client = TestClient(app)
    feed_response = client.get(f"/api/v1/capture/messages?after_id={after_id}&limit=10")

    assert feed_response.status_code == 200
    payload = feed_response.json()
    assert payload["latest_id"] >= after_id
    assert payload["data"]
    debug_message = next(item for item in payload["data"] if item["source"].startswith("macos:mouse_action:com.google.Chrome"))
    assert '"action":"leftDown"' in debug_message["text"]
    assert '"location":"90,190,120x32"' in debug_message["text"]
    assert '"role":"AXButton"' in debug_message["text"]
    assert '"name":"Submit report"' in debug_message["text"]
    assert '"description":"Submit report"' in debug_message["text"]
    assert '"value":"Submit"' in debug_message["text"]
    assert '"speechLike":"Button | Submit report | Submit | enabled"' in debug_message["text"]
    assert debug_message["captured_at"].endswith("Z")
    assert debug_message["window_id"] is None or isinstance(debug_message["window_id"], str)


def test_prompt_compaction_handles_macos_hover_and_scroll_bursts():
    transcript = "\n".join(
        [
            "[09:00:00] [mouse hover platform=macos appName=Chrome x=1 y=2 location=10,10,80x24 role=AXButton]",
            "[09:00:01] [mouse hover platform=macos appName=Chrome x=2 y=3 location=10,10,80x24 role=AXButton]",
            '[09:00:02] [mouse action] {"platform":"macos","action":"scrollDown","x":20,"y":30,"scrollDirection":"down"}',
            '[09:00:03] [mouse action] {"platform":"macos","action":"scrollDown","x":20,"y":60,"scrollDirection":"down"}',
            '[09:00:04] [mouse action] {"platform":"macos","action":"scrollStop","x":20,"y":60}',
        ]
    )

    compacted = llm_service.compact_transcript_for_prompt(transcript)

    assert "mouse hover summary: 2 consecutive events" in compacted
    assert "mouse scroll summary: 3 consecutive events" in compacted
