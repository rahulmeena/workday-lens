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

- Build on the [published evaluation archive](evaluation.md): 46 configurations, reference/source-grounded judgments, runtime metrics and prompt-regression sweeps.
- Publish a synthetic/consented evaluation set with a held-out split for activity/goal extraction and summary fidelity.
- Calibrate and blind judge rubrics against human labels; extend source-grounded coverage to newer local models.
- Standardize model revisions, prompts, hardware and input cohorts for reproducible latency, memory, token-use and evidence-loss comparisons.
- Better project continuity across apps and summary levels.
- Pagination and incremental updates for long histories.

Historical aggregate scores and their limitations are published. A shareable dataset and controlled comparisons are the next step before making general quality or performance claims.
