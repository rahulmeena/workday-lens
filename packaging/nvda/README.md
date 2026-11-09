# Workday Lens NVDA Add-on

This folder contains editable sources and asset preparation scripts for the Windows installer. Run `python packaging/nvda/prepare_assets.py` from the repository root to fetch the pinned NVDA runtime and rebuild the add-on. Generated binaries are excluded from Git.
The add-on archive is based on `speechLogger`, with Workday Lens-specific changes for
screen-reader event capture, mouse action metadata, and optional screenshot benchmarking.

## Files

- `nvda_2025.3.3.exe`: official NVDA installer used to create the managed portable NVDA copy.
- `speechLoggerMod2-silentSpeechOff-25.1.0.nvda-addon`: bundled add-on installed into portable NVDA.
- `addon_overrides/`: source files that override files inside the `.nvda-addon` archive.
- `rebuild_addon.py`: rebuilds the `.nvda-addon` after editing files in `addon_overrides/`.

Do not edit the generated `.nvda-addon` directly. Edit `addon_overrides/`, then rebuild the archive.

## Current Behavior

The patched add-on sends timestamped JSON events to the local Workday Lens relay on
`127.0.0.1:12345`. The relay preserves add-on timestamps so NVDA speech, hover metadata,
and mouse actions stay in the correct order.

Event payloads use:

```json
{
  "schema": "workday_lens_nvda_event.v1",
  "tag": "speech",
  "captured_at": "2026-05-02T06:45:12.123Z",
  "text": "NVDA spoken text"
}
```

Supported event tags:

- `speech`: normal NVDA speech output.
- `mouse_hover`: compact pointer/object metadata from NVDA mouse tracking.
- `mouse_action`: low-level mouse click and scroll actions.

## Mouse Action Messages

Mouse actions are detected with a Windows low-level mouse hook. The hook only records
small metadata and queues any screenshot work to a background thread so mouse input
does not block.

Captured action messages include:

- left, right, and middle button down/up
- vertical scroll up/down
- horizontal scroll left/right
- event timestamp as the outer Workday Lens `captured_at`
- x/y screen coordinates
- injected-input flag only when Windows marks the event as injected

Screenshot paths, capture status, JPEG settings, and internal event IDs are kept in the
local screenshot metadata index when captures are enabled, but are not sent in the LLM
mouse action text.

Example:

```text
[mouse action] {"action":"leftDown","x":944,"y":512}
```

## Screenshot Policy

Screenshots are controlled by the NVDA settings checkbox:

```text
NVDA Settings -> Speech Logger -> Screen Logger: save click screenshots
```

When enabled:

- Only button-down events save screenshots.
- Button-up events are still sent as ordered mouse action messages, but do not save screenshots.
- Double-clicks save only the first click-down screenshot. The second click-down is marked
  `duplicateClickDown` and keeps the action signal without creating another image.
- Screenshots are saved as JPEG at quality `60` to keep file size small.
- The current mouse pointer is drawn into the screenshot before saving. Raw `BitBlt`
  desktop captures do not include the cursor, so the add-on uses `GetCursorInfo`,
  `GetIconInfo`, and `DrawIconEx` to draw it at the recorded click coordinate.

Scroll screenshots have a separate checkbox:

```text
NVDA Settings -> Speech Logger -> Screen Logger: save screenshots after scrolling stops
```

When both Screen Logger checkboxes are enabled:

- Wheel events are still sent immediately as ordered `scrollUp`, `scrollDown`,
  `scrollLeft`, or `scrollRight` mouse action messages.
- The add-on waits for scrolling to be quiet for `650ms`.
- When scrolling stops, the add-on emits one extra `scrollStop` mouse action message
  with a JPEG screenshot path and queues exactly one screenshot.
- More wheel events before the `650ms` quiet window reset the timer, so long scrolls do
  not create many images.

The current LLM receives the mouse action text and screenshot path metadata, but not the
image bytes. Screenshot files are for future offline benchmarking and VLM analysis.

## Screenshot Storage

By default screenshots are written under:

```text
%LOCALAPPDATA%\WorkdayLens\ScreenCaptures\YYYY\MM\DD\HH\
```

Each day also receives an index file:

```text
%LOCALAPPDATA%\WorkdayLens\ScreenCaptures\YYYY\MM\DD\mouse_actions.jsonl
```

The capture root can be overridden for testing:

```powershell
$env:WFHS_SCREEN_CAPTURE_DIR = "D:\WorkdayLensCaptures"
```

## Rebuilding The Add-on

After changing files in `addon_overrides/`, rebuild the add-on archive:

```powershell
python packaging\nvda\rebuild_addon.py
```

Then rebuild the Windows app payload or installer:

```powershell
.\packaging\build_windows.ps1 -TargetArch arm64 -AppVersion "0.1.0-beta"
```

The packaging script stages the rebuilt add-on into:

```text
packaging\out\app\WorkdayLens\runtime\nvda\
```

## Future Plan

Near-term improvements:

- Add retention controls for screenshot folders and JSONL indexes.
- Add a capture health/status line so the app can show whether Screen Logger is active.
- Store a reference from duplicate double-click actions to the first click-down screenshot.
- Add optional image hashing to detect and skip visually identical captures.
- Add a debug tool that opens a recent mouse action and its screenshot side by side.

Benchmarking/VLM plan:

- Keep sending ordered NVDA speech and mouse action text to the LLM.
- Keep screenshots local and out of LLM prompts until a VLM benchmark path is ready.
- Later, join `mouse_actions.jsonl` with stored transcript windows to build benchmark examples.
- For VLM evaluation, use the screenshot path plus action metadata to load the image out of band.

Possible performance upgrade:

- Maintain a rolling screenshot buffer in a background worker, refreshed every few hundred
  milliseconds, and save the latest frame on click-down. This can reduce click-time latency,
  but it uses steady CPU/RAM and is more complex than the current on-click worker capture.
