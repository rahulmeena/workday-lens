# Versions and source provenance

This repository begins with a reviewed public source snapshot on November 10, 2026. Earlier development occurred privately. Private databases, capture buffers, real activity screenshots, credentials, model caches, migration bundles, and raw experiment outputs are excluded. Reviewed numeric aggregates from the historical benchmark are available in the [evaluation report](evaluation.md).

| Branch | Source lineage | Intended use |
| --- | --- | --- |
| `main` | Current macOS development snapshot, including resource monitoring and capture-helper improvements | Current development and synthetic demo |
| `windows-beta` | Windows beta release line, source commit `aaa06e0` | Earlier Windows capture/launcher/installer implementation |
| `windows-arm64-beta` | Windows ARM64 release line, source commit `71531ca` | ARM64 packaging variant with runtime port handling |

The maintainer installed and used the Windows beta on a Windows machine. It is available through [navya.ai](https://navya.ai/download). This source release does not establish a byte-for-byte mapping to the historical website installer or claim separate ARM64 hardware validation.

macOS has been used and verified by the maintainer for development. No external installer is available yet; this is not a signed/notarized macOS distribution.

The branches preserve the implementations without claiming feature parity. Windows beta predates the hierarchy and local Qwen work in `main`. Public-release preparation adds documentation, licensing, source hygiene, the synthetic demo, and validation; it does not make the historical Windows download a new release.
