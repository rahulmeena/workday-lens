# Security policy

Workday Lens is a local single-user beta/development app, not a public service. Bind the API/dashboard to `127.0.0.1`; do not expose them through a public tunnel or proxy.

Use [GitHub private vulnerability reporting](https://github.com/rahulmeena/workday-lens/security/advisories/new) when available. Otherwise use the [contact form](https://navya.ai/contact) to request a private channel. Do not submit exploit details or captured content in a public issue or contact form.

Include branch/commit, platform, a minimal synthetic reproduction, and impact. No response-time SLA is promised.

## Current boundaries

- Unauthenticated local API; assumes a trusted local user.
- Best-effort redaction; accessibility content may be sensitive.
- Windows keys use DPAPI; macOS keys currently use a local file, not Keychain.
- Databases/screenshots are not encrypted by the app.
- Cloud inference transmits captured text to the configured provider; see [privacy](docs/privacy.md).

Fixes are prioritized for `main`; Windows changes need branch-specific validation. CI is not a security audit.
