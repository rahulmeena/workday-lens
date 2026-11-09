# Workday Lens

Workday Lens is a standalone mini product built on top of the original WFH Security ingestion pipeline.
Instead of admin review, policy editing, and violation tracking, this branch focuses on one person and answers a different question:

What was I doing today, what was I trying to complete, and how did my time actually get spent?

This branch lives on `feature-personal-activity-timeline` and is intended to move fast as a side project while staying close enough to the original codebase that the capability can later fold back into WFH Security.

## What It Does
- Captures screen-reader text from a local Windows machine through the existing Python agent.
- Persists raw snippets locally and forwards them to a local FastAPI service.
- Groups snippets into rolling windows of activity.
- Uses an LLM to infer:
  - what the user is doing
  - the likely goal or deliverable
  - the probable project or workstream
  - the focus state
  - the likely next step
- Can optionally make a second LLM pass over the day view to produce a calmer story headline and summary for the Gantt-style dashboard.
- Renders a personal dashboard that shows:
  - current intent
  - daily time breakdown by activity type
  - daily time breakdown by project
  - a summarized Gantt-style day story
  - a detailed chronological activity feed

## Product Shape
This branch currently behaves like a personal activity replay tool:

- `/` shows the main Workday Lens dashboard.
- `/employee` points to the same dashboard for compatibility.
- `/admin` is intentionally reduced to a note that the admin console is not part of this MVP.

The visual language is already nudging toward the future timeline/Gantt direction, but the current implementation is optimized for shipping a usable first version quickly.

## Core Flow
1. A Windows-side relay receives text from the screen-reader feed.
2. The agent saves that text locally and retries delivery to the API when needed.
3. The backend groups messages into time windows.
4. The background worker sends each window to the LLM.
5. The LLM returns structured activity analysis instead of compliance verdicts.
6. The dashboard can optionally send those analyzed segments through a second day-level summarization pass.
7. The frontend reads those windows back as activity segments and day summaries.

## Architecture
```
┌────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│ Screen Reader  │ -> │ Ingest Agent (Py)   │ -> │ Local SQLite Store  │
└────────────────┘    └─────────────────────┘    └────────┬────────────┘
                                                           │
                                 ┌──────────────────────────▼─────────────────────────┐
                                 │ FastAPI Service                                    │
                                 │  - message ingest                                  │
                                 │  - window assembly                                 │
                                 │  - background activity analysis worker             │
                                 │  - dashboard + metrics APIs                        │
                                 └──────────────────────────┬──────────────────────────┘
                                                            │
                                         ┌──────────────────▼──────────────────┐
                                         │ Next.js Dashboard                   │
                                         │  - current intent                   │
                                         │  - day summary                      │
                                         │  - Gantt-style day story            │
                                         │  - detailed activity feed           │
                                         └─────────────────────────────────────┘
```

All services run locally in this MVP.

## API Surface Used By This Branch

### Ingest
- `POST /api/v1/messages`
  - Internal endpoint used by the Windows agent to persist raw captured snippets.

### Dashboard
- `GET /api/v1/activity/dashboard`
  - Returns the branch-specific day view used by Workday Lens.
  - Includes:
    - top-level summary metrics
    - current intent
    - optional `story_headline`, `story_summary`, and `story_model_name` fields when day-level summarization is enabled
    - activity breakdown
    - project breakdown
    - ordered activity segments

### Compatibility Timeline
- `GET /api/v1/employee/activity`
  - Still available for compatibility and simpler timeline reads.

### Health
- `GET /api/v1/health`
- `GET /api/v1/metrics`

## Data Notes
This branch deliberately reuses the original SQLite schema where possible so the product can evolve without a large refactor.

Important branch-specific behavior:
- `messages` still store raw captured snippets.
- `windows` still represent grouped activity buffers.
- `llm_runs` still store one analysis result per processed window.
- In this branch, `llm_runs.summary_text` stores structured activity-analysis JSON rather than policy/violation-style text.

The original policy and admin tables/routes still exist in the repo because this branch was created as a fast spinout, but they are not the primary product surface anymore.

## Local Development

### 1. Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```

### 3. Agent
```bash
cd agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m agent.main
```

### 4. Windows Launcher
```bash
cd launcher
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd ..
python -m launcher.main
```

Launcher notes:
- The launcher reads the preferred local dashboard port from the runtime setup flow.
- If the preferred port is busy, it falls back to another free `127.0.0.1` port for that run.
- The backend currently binds to `127.0.0.1:8000`, so another local process cannot already be using that port.
- `Pause Observation` and `Resume Observation` control the capture path together: the dashboard and backend stay up, while the agent and portable NVDA stop or resume together.
- Portable NVDA now lives under `%LOCALAPPDATA%\WorkdayLens\NVDA`, is installed by the Windows installer, and follows observation start/stop automatically.
- Portable NVDA is preconfigured through `userConfig\nvda.ini` and add-on startup enforcement, so users do not need to open NVDA Preferences for Workday Lens defaults.
- The patched NVDA add-on captures normal speech plus compact mouse hover tags without emitting the full NVDA object metadata stream, for example `[mouse hover appName=chrome x=1535 y=-1342 location=1500,-1360,209x57]`.
- In mouse hover tags, `appName` is the NVDA app/module name, `x` and `y` are mouse cursor coordinates, and `location` is the hovered object's bounding box as `left,top,widthxheight`.
- Runtime settings, launcher logs, and the default local SQLite data now live under `%LOCALAPPDATA%\WorkdayLens`.
- When a packaged `runtime\frontend\server.js` and `runtime\node\node.exe` are present, the launcher uses those instead of `npm run start`.
- The packaged app also carries a bundled offline `runtime\nvda\nvda_2025.3.3.exe`, the patched `runtime\nvda\speechLoggerMod2-silentSpeechOff-25.1.0.nvda-addon`, and launcher commands such as `--prepare-nvda-install`, `--create-portable-nvda`, `--install-nvda-addon`, `--install-nvda`, `--start-nvda`, `--stop-nvda`, and `--uninstall-nvda`.
- `python -m launcher.main --headless` runs the same orchestration without the tray icon.
- `python -m launcher.main --once --no-browser` is useful for a quick readiness check.

### 5. Packaging For Windows
```powershell
.\packaging\build_windows.ps1 -AppVersion "0.1.0-beta" -SkipInstaller
```

When PyInstaller is installed, that produces a staged Windows app payload under `packaging\out\app\WorkdayLens`.

To build the installer too, install Inno Setup and run:

```powershell
.\packaging\build_windows.ps1 -AppVersion "0.1.0-beta"
```

## Environment Variables

### Backend
- `WFHS_OPENAI_API_KEY`
- `WFHS_FAKE_LLM`
- `WFHS_LLM_MODEL`
- `WFHS_DASHBOARD_STORY_LLM_ENABLED`
- `WFHS_DASHBOARD_STORY_MODEL`
- `WFHS_DASHBOARD_STORY_SEGMENT_LIMIT`
- `WFHS_LLM_TIMEOUT_SECONDS`
- `WFHS_CONTEXT_SUMMARY_LIMIT`
- `WFHS_WINDOW_MIN_SECONDS`
- `WFHS_WINDOW_MAX_SECONDS`
- `WFHS_WINDOW_TOKEN_LIMIT`

### Agent
- `WFHS_API_BASE_URL`
- `WFHS_SCREEN_READER_PORT`
- `WFHS_SESSION_ID`

### Frontend
- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_POLL_INTERVAL_MS`

The backend defaults to fake LLM mode for offline development. Set `WFHS_FAKE_LLM=false` and provide `WFHS_OPENAI_API_KEY` to use a real model.
When the optional day-story pass is enabled, the backend sends a representative slice of the day rather than blindly sending the first N segments, so `WFHS_DASHBOARD_STORY_SEGMENT_LIMIT` acts as a quality/cost control instead of only a hard truncation.

### Suggested Model Setup
As of April 18, 2026, the OpenAI model docs recommend starting with `gpt-5.4` for the strongest reasoning/coding quality, and using `gpt-5.4-mini` or `gpt-5.4-nano` when latency or cost matters more.

Practical guidance for this project:
- Keep `WFHS_LLM_MODEL=gpt-5-nano-2025-08-07` or move to `gpt-5.4-nano` for cheap per-window analysis during high-volume capture.
- Use `WFHS_DASHBOARD_STORY_MODEL=gpt-5.4-mini` for the second day-level summarization pass when you want cleaner story text in the Gantt chart.
- Move both paths to `gpt-5.4` later if quality matters more than cost and latency.

Reference docs:
- https://developers.openai.com/api/docs/models
- https://openai.com/index/introducing-gpt-5-4-mini-and-nano/

## Current MVP Output
For each captured window, the system tries to infer:
- headline
- summary
- goal
- project
- activity type
- focus state
- next step
- confidence

When enabled, the dashboard can also produce:
- a day-level story headline
- a short story summary for the Gantt/timeline view

The activity types currently supported are:
- `deep_work`
- `planning`
- `research`
- `review`
- `communication`
- `admin`
- `break`
- `other`

## Near-Term Roadmap
- Improve project detection using richer window title and application metadata.
- Add a more expressive zoomable day timeline and Gantt-like interaction model.
- Group low-level windows into larger task sessions.
- Add daily and weekly rollups.
- Improve activity classification prompts and confidence handling.
- Reintroduce selected pieces back into WFH Security once the personal timeline model is strong enough.

## Project Layout
- `agent/` - Windows-side relay and local retry store
- `backend/` - FastAPI service, queue processing, activity analysis
- `frontend/` - Next.js dashboard UI
- `launcher/` - Windows beta launcher, tray icon, and process supervision

## Branch Context
This repository name is still `wfhsecurity`, but on this branch the product is Workday Lens.
That mismatch is intentional for now so development stays fast and code can be merged back into the parent project later.
