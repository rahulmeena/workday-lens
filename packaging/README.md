# Windows Packaging

This folder contains the MVP packaging flow for shipping Workday Lens as a Windows installable app.

## What The Build Produces
- A PyInstaller one-directory launcher app named `WorkdayLensLauncher.exe`
- A staged friendly app icon set under `runtime\assets`
- A staged `runtime\frontend` Next standalone bundle
- A staged `runtime\node\node.exe` copy so the installed app does not depend on a user-managed Node install
- A staged `runtime\nvda\nvda_2025.3.3.exe` copy of the official NVDA installer for offline portable setup
- A staged `runtime\nvda\speechLoggerMod2-silentSpeechOff-25.1.0.nvda-addon` bundle used to configure portable NVDA
- An optional Inno Setup installer that installs the staged app folder

## Prerequisites
- `node.exe` and `npm.cmd` on `PATH`
- `pyinstaller` on `PATH`
- `ISCC.exe` on `PATH` if you want the `.exe` installer output

## Build Commands
From the repo root:

```powershell
.\packaging\build_windows.ps1 -AppVersion "0.1.0-beta" -SkipInstaller
```

That creates a staged app payload under `packaging\out\app\WorkdayLens`.

To build the installer too:

```powershell
.\packaging\build_windows.ps1 -AppVersion "0.1.0-beta"
```

If Inno Setup is installed, the installer is written to `packaging\out\installer`.

## Layout Expected By The Launcher
- `WorkdayLensLauncher.exe`
- `runtime\assets\workday-lens-friendly.png`
- `runtime\frontend\server.js`
- `runtime\frontend\.next\static\...`
- `runtime\node\node.exe`
- `runtime\nvda\nvda_2025.3.3.exe`
- `runtime\nvda\speechLoggerMod2-silentSpeechOff-25.1.0.nvda-addon`

When this layout exists, the launcher prefers the packaged frontend runtime and does not fall back to `npm run start`.

## Bundled NVDA Behavior
- The installer runs four NVDA setup steps after copying files so Windows shows clearer progress during install.
- Portable NVDA is created under `%LOCALAPPDATA%\WorkdayLens\NVDA`.
- The official NVDA installer EXE is bundled into the app payload by default, and `WFHS_NVDA_INSTALLER_PATH` can still override it for local testing.
- The patched `speechLogger` add-on is injected directly into portable NVDA without using the NVDA add-on UI.
- The launcher writes managed `userConfig\nvda.ini` defaults before NVDA starts: command keys are spoken, browse/focus mode audio cues and NVDA sounds are muted, and mouse tracking is enabled for compact hover tags.
- The patched add-on also enforces those settings on startup and emits timestamped JSON events for normal NVDA speech and compact mouse tags such as `[mouse hover appName=chrome x=1535 y=-1342 location=1500,-1360,209x57]`.
- Each NVDA event includes `captured_at` from the add-on at generation time; Workday Lens preserves that timestamp for storage, windowing, and LLM transcript lines.
- In mouse hover tags, `appName` is the NVDA app/module name, `x` and `y` are mouse cursor coordinates, and `location` is the hovered object's bounding box as `left,top,widthxheight`.
- The NVDA add-on mouse action and optional screenshot behavior is documented in `packaging\nvda\README.md`.
- Workday Lens starts NVDA when observation starts, stops NVDA when observation stops, and removes portable NVDA during uninstall through `--uninstall-nvda`.

## Public source preparation

Run `python packaging/nvda/prepare_assets.py` from the repository root before packaging. The public source omits generated binaries and includes full editable add-on source. See the root README and THIRD_PARTY_NOTICES.md.
