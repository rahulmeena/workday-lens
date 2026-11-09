from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..models import Message
from ..schemas import CaptureBounds, CaptureEventIn


DEFAULT_MACOS_SESSION_ID = "macos-default"
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_capture_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def message_from_capture_event(event: CaptureEventIn, *, session_id: str = DEFAULT_MACOS_SESSION_ID) -> Message:
    captured_at = normalize_capture_datetime(event.captured_at)
    return Message(
        session_id=session_id,
        source=capture_event_source(event),
        text=capture_event_transcript_line(event),
        captured_at=captured_at,
    )


def capture_event_source(event: CaptureEventIn) -> str:
    app = _clean_token(event.bundle_id or event.app_name or "unknown")
    return f"macos:{event.tag}:{app}"[:512]


def capture_event_transcript_line(event: CaptureEventIn) -> str:
    if event.tag == "mouse_hover":
        return _format_mouse_hover(event)
    if event.tag == "mouse_action":
        return _format_mouse_action(event)
    if event.tag == "command_key":
        return _format_command_key(event)
    if event.tag == "keyboard_activity":
        return _format_keyboard_activity(event)
    if event.tag == "gesture":
        return _format_gesture(event)
    if event.tag == "system_state":
        return _format_system_state(event)
    return _format_accessibility_event(event)


def _format_accessibility_event(event: CaptureEventIn) -> str:
    fields = [
        ("app", event.app_name),
        ("bundle", event.bundle_id),
        ("pid", event.process_id),
        ("window", event.window_title),
        ("window_id", event.window_id),
        ("role", event.role),
        ("subrole", event.subrole),
        ("name", event.name),
        ("value", event.value),
        ("description", event.description),
        ("selected_text", event.selected_text),
        ("states", ",".join(event.states) if event.states else None),
        ("keyboard_shortcut", event.keyboard_shortcut),
        ("window_bounds", _bounds_value(event.window_bounds)),
        ("element_bounds", _bounds_value(event.element_bounds)),
        ("ancestors", _ancestor_path(event)),
    ]
    body = _compact_join(_kv(key, value) for key, value in fields if value not in (None, ""))
    speech_like = _speech_like(event)
    if speech_like:
        body = _compact_join([body, _kv("speech_like", speech_like)])
    if event.extra:
        body = _compact_join([body, _kv("extra", _safe_json(event.extra))])
    return f"[accessibility {event.tag}{(' ' + body) if body else ''}]"


def _format_command_key(event: CaptureEventIn) -> str:
    fields = [
        ("app", event.app_name),
        ("bundle", event.bundle_id),
        ("window", event.window_title),
        ("command_key", event.command_key_name),
        ("shortcut", event.keyboard_shortcut),
    ]
    body = _compact_join(_kv(key, value) for key, value in fields if value not in (None, ""))
    return f"[command key{(' ' + body) if body else ''}]"


def _format_keyboard_activity(event: CaptureEventIn) -> str:
    extra = event.extra if isinstance(event.extra, dict) else {}
    fields = [
        ("app", event.app_name),
        ("bundle", event.bundle_id),
        ("window", event.window_title),
        ("key_class", extra.get("key_class")),
        ("modifiers", extra.get("modifiers")),
        ("key", "redacted"),
    ]
    body = _compact_join(_kv(key, value) for key, value in fields if value not in (None, ""))
    return f"[keyboard activity{(' ' + body) if body else ''}]"


def _format_gesture(event: CaptureEventIn) -> str:
    extra = event.extra if isinstance(event.extra, dict) else {}
    payload: dict[str, Any] = {
        "platform": "macos",
        "gestureType": extra.get("gesture_type"),
        "action": extra.get("action"),
        "axis": extra.get("axis"),
        "direction": extra.get("direction"),
        "phase": extra.get("phase"),
        "magnitude": extra.get("magnitude"),
        "source": extra.get("source"),
        "x": event.x,
        "y": event.y,
        "app": event.app_name,
        "bundleId": event.bundle_id,
        "windowTitle": event.window_title,
        "location": _bounds_value(event.element_bounds or event.window_bounds),
    }
    if event.role:
        payload["role"] = event.role
    if event.subrole:
        payload["subrole"] = event.subrole
    if event.name:
        payload["name"] = event.name
    if event.description:
        payload["description"] = event.description
    if event.value:
        payload["value"] = _hover_text_value(event.value)
    if event.selected_text:
        payload["selectedText"] = _hover_text_value(event.selected_text)
    if event.states:
        payload["states"] = event.states
    speech_like = _speech_like(event)
    if speech_like:
        payload["speechLike"] = speech_like
    compact_payload = {key: value for key, value in payload.items() if value not in (None, "", [])}
    return "[gesture] " + json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))


def _format_system_state(event: CaptureEventIn) -> str:
    extra = event.extra if isinstance(event.extra, dict) else {}
    payload: dict[str, Any] = {
        "platform": "macos",
        "action": extra.get("action"),
        "state": extra.get("state"),
        "source": extra.get("source"),
        "app": event.app_name,
        "bundleId": event.bundle_id,
        "windowTitle": event.window_title,
    }
    if event.role:
        payload["role"] = event.role
    if event.name:
        payload["name"] = event.name
    compact_payload = {key: value for key, value in payload.items() if value not in (None, "", [])}
    return "[system] " + json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))


def _format_mouse_hover(event: CaptureEventIn) -> str:
    app_name = event.app_name or event.bundle_id or "unknown"
    fields: list[str] = [
        "platform=macos",
        f"appName={_plain_value(app_name)}",
    ]
    if event.window_title:
        fields.append(_kv("window", event.window_title))
    if event.x is not None:
        fields.append(f"x={int(event.x)}")
    if event.y is not None:
        fields.append(f"y={int(event.y)}")
    location = _bounds_value(event.element_bounds or event.window_bounds)
    if location:
        fields.append(f"location={location}")
    for key, value in (
        ("role", event.role),
        ("subrole", event.subrole),
        ("name", event.name),
        ("value", _hover_text_value(event.value)),
        ("description", event.description),
        ("selected_text", _hover_text_value(event.selected_text)),
        ("states", ",".join(event.states) if event.states else None),
        ("ancestors", _ancestor_path(event)),
        ("speech_like", _speech_like(event)),
    ):
        if value not in (None, ""):
            fields.append(_kv(key, value))
    return "[mouse hover " + " ".join(fields) + "]"


def _hover_text_value(value: str | None) -> str:
    cleaned = _clean_text(value)
    if len(cleaned) > 700:
        return cleaned[:697] + "..."
    return cleaned


def _format_mouse_action(event: CaptureEventIn) -> str:
    action = event.extra.get("action") if isinstance(event.extra, dict) else None
    if not isinstance(action, str) or not action:
        action = _mouse_action_name(event)
    payload: dict[str, Any] = {
        "platform": "macos",
        "action": action,
        "x": event.x,
        "y": event.y,
        "button": event.button,
        "state": event.state,
        "scrollAxis": event.scroll_axis,
        "scrollDirection": event.scroll_direction,
        "app": event.app_name,
        "bundleId": event.bundle_id,
        "windowTitle": event.window_title,
        "location": _bounds_value(event.element_bounds or event.window_bounds),
    }
    if event.role:
        payload["role"] = event.role
    if event.subrole:
        payload["subrole"] = event.subrole
    if event.name:
        payload["name"] = event.name
    if event.description:
        payload["description"] = event.description
    if event.value:
        payload["value"] = _hover_text_value(event.value)
    if event.selected_text:
        payload["selectedText"] = _hover_text_value(event.selected_text)
    if event.states:
        payload["states"] = event.states
    ancestors = _ancestor_path(event)
    if ancestors:
        payload["ancestors"] = ancestors
    speech_like = _speech_like(event)
    if speech_like:
        payload["speechLike"] = speech_like
    if event.screenshot:
        payload["screenshotReason"] = event.screenshot.reason
        payload["screenshotStatus"] = "localOnly"
    compact_payload = {key: value for key, value in payload.items() if value not in (None, "", [])}
    return "[mouse action] " + json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))


def _mouse_action_name(event: CaptureEventIn) -> str:
    if event.scroll_direction:
        direction = event.scroll_direction[:1].upper() + event.scroll_direction[1:]
        if direction:
            return f"scroll{direction}"
    if event.button and event.state:
        state = event.state[:1].upper() + event.state[1:]
        return f"{event.button}{state}"
    if event.state:
        return event.state
    return "mouseAction"


def _speech_like(event: CaptureEventIn) -> str:
    parts: list[str] = []
    if event.role:
        parts.append(event.role.replace("AX", ""))
    for value in (event.name, event.value, event.description, event.selected_text):
        cleaned = _clean_text(value)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    if event.states:
        parts.extend(event.states[:4])
    return " | ".join(part for part in parts if part)[:600]


def _ancestor_path(event: CaptureEventIn) -> str:
    labels = []
    for ancestor in event.ancestors[:6]:
        role = _clean_text(ancestor.role)
        name = _clean_text(ancestor.name or ancestor.description)
        if role and name:
            labels.append(f"{role}:{name}")
        elif role:
            labels.append(role)
        elif name:
            labels.append(name)
    return " > ".join(labels)


def _bounds_value(bounds: CaptureBounds | None) -> str:
    if bounds is None:
        return ""
    return (
        f"{int(round(bounds.x))},{int(round(bounds.y))},"
        f"{max(0, int(round(bounds.width)))}x{max(0, int(round(bounds.height)))}"
    )


def _kv(key: str, value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{key}={value}"
    cleaned = _clean_text(str(value))
    if not cleaned:
        return ""
    if re.search(r'[\s"\[\]{}=]', cleaned):
        return f"{key}={json.dumps(cleaned, ensure_ascii=False)}"
    return f"{key}={cleaned}"


def _plain_value(value: str) -> str:
    cleaned = _clean_text(value)
    return cleaned or "unknown"


def _clean_token(value: str) -> str:
    cleaned = _clean_text(value)
    return cleaned.replace(" ", "_") or "unknown"


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RE.sub(" ", value.strip())


def _compact_join(values: Any) -> str:
    return " ".join(str(value) for value in values if value)


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return ""
