# Workday Lens Capture Helper

Native macOS menu-bar helper for the Workday Lens beta.

## Run

```bash
swift run WorkdayLensCapture
```

The helper posts buffered batches to:

```text
http://127.0.0.1:8000/api/v1/capture/events/batch
```

## Responsibilities

- Shows a menu-bar item with pause/resume, backend health, capture state, and permission status.
- Requests Accessibility, Input Monitoring, and optional Screen Recording permissions.
- Captures app, window, focused element, selected text, roles, values, bounds, AX notifications, pointer hover context, mouse actions, scrolls, semantic gestures such as desktop switches and zooms, system state such as lock/unlock and sleep/wake, command-key metadata, and heartbeats.
- Buffers events locally as JSONL under `~/Library/Application Support/WorkdayLens/CaptureBuffer/`.
- Saves optional screenshots under `~/Library/Application Support/WorkdayLens/ScreenCaptures/YYYY/MM/DD/HH/`.

The event tap emits command-key metadata and redacted keyboard-activity classes. Gesture capture stores semantic actions such as scroll, desktop switch, zoom, smart zoom, swipe, and rotate without finger-count data. System-state capture stores lock/unlock, display sleep/wake, system sleep/wake, and screensaver start/stop; screen dimming is intentionally not captured. Ordinary text content is captured from Accessibility value/name/selected-text changes with sensitive fields redacted.
