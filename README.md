# Workday Lens - Windows ARM64 beta source

**Desktop activity capture and AI-generated personal timelines for Windows.**

[Project overview](https://github.com/rahulmeena/workday-lens) | [Windows download](https://navya.ai/download) | [Privacy](docs/privacy.md) | [Packaging](packaging/README.md)

This branch preserves the earlier Windows implementation. The maintainer installed and tested the Windows beta on a Windows machine. Separate ARM64 hardware validation is not claimed. The newer hierarchy, macOS helper, and local Qwen work are on `main`; they are not all in this beta.

## Pipeline

```text
NVDA + modified Speech Logger
  -> Python relay and local retry store
  -> FastAPI / SQLite
  -> LLM activity analysis
  -> Next.js personal timeline
```

The launcher coordinates the local services, tray controls, capture pause/resume, and portable NVDA. The packaging flow uses PyInstaller and Inno Setup.

## Build preparation

Use native Windows Python/Node and follow [packaging instructions](packaging/README.md). The public source excludes bundled installer binaries and includes editable add-on source. Prepare assets before running the existing packaging script:

```powershell
python packaging/nvda/prepare_assets.py
```

This downloads the pinned NVDA runtime from NV Access, verifies its SHA-256, and rebuilds the add-on. For source-only validation, use `--skip-installer`. The historical frontend dependencies are retained for this release line and may have security advisories; update and revalidate them before distributing a new build. Keep all services on loopback.

[Implementation notes](docs/windows-implementation.md) describe the original branch. [Versions/provenance](docs/versions.md) explain the public snapshot and its relationship to the website download. This preparation does not claim a byte-for-byte match to that installer.

## Data handling

Activity is stored locally. When the OpenAI provider is enabled, captured text and contextual summaries are sent to OpenAI using your key. Optional screenshot files remain local in the text-analysis path. Read [privacy](docs/privacy.md).

## License

Original code: GNU GPL v3.0, copyright Rahul Meena. NVDA and Speech Logger retain their upstream notices. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
