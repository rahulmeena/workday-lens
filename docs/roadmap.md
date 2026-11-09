# Roadmap

These are contribution directions, not release-date commitments.

## Release foundations

- Converge Windows/macOS adapters around a shared ingest contract while preserving the working Windows distribution.
- Package and verify a signed/notarized macOS app on a fresh machine.
- Establish reproducible Windows builds with corresponding source and dependency notices.
- Record per-platform smoke tests and installer provenance for future releases.

## Privacy and reliability

- App exclusions, retention controls, and deletion workflows.
- macOS Keychain integration for API keys.
- Stronger local API trust boundaries and redaction coverage.
- Tests for interrupted uploads, duplicate events, queue recovery, and time-zone boundaries.

## Context quality

- A synthetic evaluation set for activity/goal extraction and summary fidelity.
- Reproducible latency, memory, token-use, and evidence-loss measurements across local/cloud models.
- Better project continuity across apps and summary levels.
- Pagination and incremental updates for long histories.

No quality or performance scores are published yet. Measurements should be reproducible before becoming product claims.
