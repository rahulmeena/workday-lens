# Contributing

Start with the [development guide](https://github.com/rahulmeena/workday-lens/blob/main/docs/development.md) and synthetic demo. No personal activity capture is needed for dashboard development.

## Branches

- `main`: macOS capture and current backend/dashboard development.
- `windows-beta`: earlier Windows beta implementation.
- `windows-arm64-beta`: Windows ARM64 packaging variant.

Include branch/commit, OS, architecture, and reproduction steps in a bug report. Use fictional input. Never attach activity databases, secrets, personal transcripts, or confidential screenshots.

## Changes

1. Discuss substantial changes in an issue first.
2. Keep pull requests focused and reviewable.
3. Run the documented checks. Add regression tests for capture, storage, queue, or model-output behavior.
4. Describe resulting behavior, validation, and platform limitations.

Capture changes should explain added data collection and pause/redaction behavior. Model changes should include synthetic examples and discuss evidence fidelity, latency, and token use.

Original contributions are licensed under the project's GPL-3.0 license. Preserve third-party notices. Be considerate, specific, and respectful.
