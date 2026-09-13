# Changelog

## 2026-09-13

### Account-bound hosted conversations

- Fixed the hosted account selector so it loads the account attached to the active conversation,
  rather than showing a default account while Bob works in a different conversation.
- Switching accounts now resumes that account’s latest conversation or creates its first one; it
  never rewrites another account’s conversation, native Codex session, workspace, messages, or
  artifacts.
- Prevented an account switch while the loaded conversation has a queued or running job.
- Bumped the hosted JavaScript cache key and made the browser shell and application bundle
  revalidate on every load, preventing an older UI from ignoring the account conversation returned
  by a newer server deployment.
- Added hosted regression coverage for durable account switching, account-specific runtime
  isolation, browser cache revalidation, and the active-job guard; included those checks in the
  practical pre-commit gate.

## 2026-09-12

### CLI architecture refactor

- Reduced `lib/datapull.py` from the multi-domain implementation to an 80-line executable
  compatibility facade.
- Moved the unchanged parser, command map, and dispatcher into `lib/bob/cli.py` while preserving
  every existing `./bob` command, flag, default, help route, and launcher.
- Extracted shared runtime, configuration, dates, metrics, CSV presentation, data discovery, and
  Google Ads connection behavior into `lib/bob/platform/`.
- Extracted performance fetching, aggregation, validation, comparisons, creative slicing, and the
  authoritative data manifest into `lib/bob/performance/`.
- Isolated bid/budget, creative-copy, static-banner, account-management, self-improvement, sync,
  and snapshot workflows into their owning packages or modules.
- Preserved existing processed-data layouts, YAML plan formats, approval behavior, partial-failure
  handling, and failed-only retry behavior; no database or user-data migration was introduced.

### Refactor safety gates

- Added a frozen CLI contract test covering command registration, representative arguments,
  direct script execution, and launcher compatibility.
- Added direct platform tests for date, metric, and error primitives.
- Updated repository and hosted-path tests to inspect the extracted owning modules.
- Expanded the fast pre-commit gate to cover deterministic core, platform, and CLI contracts.
- Verified all extracted modules compile, the fast 83-test gate passes, and the complete 135-test
  regression suite passes.
- Recorded the incremental, anti-bloat object-model guidance in `docs/OOP.md`; an OOP conversion is
  not required before deployment.

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

### Live follow-up corrections

- Made bid/budget recommendation consume the exact account-scoped W0 trend file instead of selecting an overlapping stale file by start date.
- Scoped default bid/budget input selection to the active account and added fail-closed trend date/schema validation.
- Moved creative validation and atomic application to explicit `GoogleAdsService` mutate requests, which support `validate_only` and `partial_failure` on the request object.
- Tightened the bid and creative workflows to use manifest-based coverage checks and complete customer review CSV fields.
