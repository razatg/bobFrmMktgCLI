# Changelog

## 2026-09-09

- Added compact data manifests and quieter fetch output so Bob can verify existing pulls without exposing large pull logs.
- Added account-level KT files at `wiki/<customer_id>/KT.md`, editable from each account’s Wiki Index; simplified the KT instructions to plain-language bullets.
- Removed the client-level KT layer and its stored local KT file. Account KT is now the only terminology and clarification memory used by Bob.
- Added Management users: they can use saved data and wiki context without Google Ads OAuth; Read and Read & Write behavior remains unchanged.
- Fixed selected-account binding, Google Ads MCC fallback, orphan-user re-add, and Docker secret-volume permissions.
- Hid manifests and KT files from the general Artifacts list while keeping the useful account KT link inside the account Wiki Index.
- Fixed the duplicate `showArtifact` declaration that prevented the frontend and sign-in modal from loading.
- Added hosted gateway coverage for Management access, account KT, account isolation, permissions, and related fixes.
