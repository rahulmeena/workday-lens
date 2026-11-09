# macOS Packaging

This branch packages Workday Lens as a macOS beta product:

- The Python launcher starts only the local FastAPI backend and dashboard.
- The native Swift menu-bar helper owns capture, pause/resume, permissions, local buffering, and backend health.
- Capture data is sent directly to `POST /api/v1/capture/events/batch` as `workday_lens_capture_event.v1` records.

The old Windows installer and screen-reader relay assets are intentionally absent from this branch. macOS packaging should wrap the Swift helper from `macos/WorkdayLensCapture` together with the backend/dashboard runtime.
