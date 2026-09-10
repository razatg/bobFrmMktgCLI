# Changelog

## 2026-09-10

### Campaign decisions and dates

- Normalized supported date aliases before period resolution.
- Changed bid/budget W0 to use Monday through yesterday, allowing decisions from a partial current week while retaining the prior two complete weeks as the reference.
- Tightened weekly input selection to require exact account and date-window coverage.

### Hosted Bob reliability

- Added per-job Codex input, cached-input, and output token estimates from native cumulative counters.
- Compacted persisted Codex events into bounded, secret-safe diagnostic records.
- Added a configurable input-token threshold that retires an oversized native thread and seeds the next thread with a bounded continuity handoff.
- Replaced command-word guessing for Google authorization with the deterministic `GOOGLE_AUTH_REQUIRED` error contract.
- Kept saved-data and wiki analysis available without Google OAuth while reserving live fetch and write operations for connected users.

### Users and account access

- Removed legacy management-role behavior from the hosted API and frontend.
- Kept users read-only by default with explicit per-account grants.
- Made client membership status independent from global user status and moved password resets to the dedicated global-user endpoint.
- Simplified the customer question bank and restored authoritative account-permission and Google-connection context for Bob.

### Customer artifacts

- Limited the customer artifact surface to Markdown and CSV; YAML, JSON, and TXT remain internal working files.
- Normalized safe account-scoped wiki references before path redaction so saved analyses and indexes render as clickable artifact links.
- Removed layered frontend path-rewriting wrappers in favor of the server-produced artifact marker.
- Made full-plan CSV presentation conditional on an explicit customer request; applying an internal plan creates no extra presentation artifact.

### Creative application

- Preserved ad-level creative placement identity and persisted the exact target ad ID in new copy plans.
- Built App Ad text fields with supported `AdTextAsset` protobuf objects.
- Merged all replacements for the same ad into one update and sent all ad updates in one atomic batch.
- Added complete local and Google validation before mutation, with partial failure disabled.
- Marked plans applied only after confirmed success and preserved the original plan on validation or mutation failure.
