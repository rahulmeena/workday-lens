# Privacy and data handling

Workday Lens observes desktop activity when its capture component is enabled. Use it on your own machine with appropriate permission for the content visible there.

## What is captured

Depending on platform/settings: application and window names, accessibility text, selected text, element roles/values, pointer context, mouse actions, shortcuts, and system-state events. macOS does not record ordinary typed characters from the event tap, but accessibility text can still expose what you type.

Optional screenshots are local files. macOS screenshots are disabled by default. The text-analysis path does not attach image bytes to model requests.

| Mode | Processing |
| --- | --- |
| Synthetic demo / fake LLM | Local data and deterministic sample output; no live capture or model API calls |
| Local Qwen on macOS | Local inference after runtime/model downloads |
| OpenAI provider | Captured text, selected prior summaries, and prompts sent to OpenAI using your API key |

The application has no hosted Workday Lens activity-upload service. Cloud inference still transmits content to the provider. Website signup/download handling is separate from the desktop app.

## Local files

- Backend: `WFHS_DATA_DIR` if set; otherwise `%LOCALAPPDATA%\\WorkdayLens` on Windows or `./data` for source runs without that variable.
- macOS helper: `~/Library/Application Support/WorkdayLens/CaptureBuffer/` and optional `ScreenCaptures/`.
- Local Qwen: caches and inference files under `~/WorkdayLensData/` by default.
- Synthetic demo: repository-local `.demo-data/`, isolated from the normal database.

Raw messages, summaries, and model metadata are stored in SQLite. Debug views can reveal source content. Activity databases and screenshots are not encrypted by the app. Windows API-key storage uses DPAPI; macOS currently uses a local file rather than Keychain.

## Controls and limits

Pause capture using platform controls. Pausing stops new observation; it does not erase stored data or cancel every queued inference request. To remove a dataset, stop capture and the backend, then delete the corresponding data directory, capture buffers, and screenshots. Preserve any desired backup separately.

Redaction is best effort. Comprehensive automatic retention/deletion controls are not yet implemented. Do not capture confidential work unless permitted and you understand the chosen inference mode.

The API is unauthenticated. Keep it on loopback. For vulnerabilities, follow [SECURITY.md](../SECURITY.md) rather than posting private activity in an issue.
