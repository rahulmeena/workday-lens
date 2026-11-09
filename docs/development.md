# Development setup

Use `main` for current macOS/backend/dashboard development. For Windows capture and installers, see [windows-beta](https://github.com/rahulmeena/workday-lens/tree/windows-beta) and its packaging guide.

## Requirements

Python 3.12, Node.js 22, npm. Native capture additionally requires macOS 13+ and Swift 5.9+ / Xcode Command Line Tools. The demo needs no model or API key.

## Synthetic demo

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python scripts/demo.py
```

In another terminal, from the root:

```bash
cd frontend
cp .env.demo.example .env.local  # only for a fresh configuration
npm ci
npm run dev -- --hostname 127.0.0.1
```

Open http://127.0.0.1:3000. API docs: http://127.0.0.1:8010/docs. If `.env.local` already exists, update only `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010/api/v1`. Set `NEXT_PUBLIC_DEMO_MODE=true` so the dashboard opens the sample day and labels it as fictional. Restart Next.js after environment changes.

The demo seeds fictional activity for yesterday in the machine's local time zone in `.demo-data/`. It refuses an unrelated database and never starts native capture. Stop it with Ctrl+C. To refresh the dataset, remove only `.demo-data/` while the demo is stopped. `python scripts/demo.py --seed-only` prepares fixtures without running a server.

## Real macOS capture

Read [privacy](privacy.md). Start an isolated development backend:

```bash
source .venv/bin/activate
export WFHS_DATA_DIR="$PWD/data"
export WFHS_FAKE_LLM=true
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Set the frontend API URL to `http://127.0.0.1:8000/api/v1` and start it as above. Then, from the root:

```bash
swift run --package-path macos/WorkdayLensCapture WorkdayLensCapture
```

Grant Accessibility/Input Monitoring permissions in System Settings. Screen Recording is optional for screenshots. Use the menu-bar pause/resume controls. The helper targets port 8000; the synthetic demo intentionally uses 8010.

To use real inference, stop the backend, set `WFHS_FAKE_LLM=false`, restart, and configure the provider in Settings. OpenAI needs your own key and may incur charges. Local Qwen needs its runtime/model setup, disk space, and sufficient memory; no universal minimum-memory claim is made.

`.env.example` documents variables but is not automatically loaded by Python. `WFHS_` remains the compatibility prefix from the original implementation.

## Checks

```bash
python -m pytest backend/tests -q
cd frontend
npm run lint
npm run typecheck
npm run build
```

On macOS, from the root:

```bash
swift build --package-path macos/WorkdayLensCapture
```

CI checks backend tests, frontend build/types/lint, and the Swift build. It does not run live permission-gated capture or certify Windows installers.

## Troubleshooting

- Empty dashboard: check the frontend API port and selected date.
- Port busy: stop the conflicting instance or change the port and frontend URL. Do not run two backends against the same database.
- No events: check macOS permissions, pause state, and backend health.
- Pending model queue: check provider setup and local debug views; report only synthetic excerpts.
- Environment changes ignored: settings persist per data directory; use an isolated directory when testing defaults.

The React 19 migration currently reports advisory lint warnings for existing effect synchronization and render-time clock reads. Core lint errors and type/build failures still fail CI.
