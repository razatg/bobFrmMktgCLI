---
name: bob-sync
description: Use when the user wants to sync, share, pull, or push Bob's wiki + self-improvement signals with teammates — triggers like "hey sync", "hey Bob sync", "sync", "share my analyses", "pull the team's updates", "push my wiki". Checks the shared-folder setup, guides one-time setup if it's missing, then runs `./bob sync`.
---

# Bob Team-Sync Skill

Routes "hey sync" / "hey Bob sync" and any request to share / pull / push the `wiki/` knowledge base
and `logs/session-signals.jsonl` with teammates. Bob shares these through a plain **shared folder**
(e.g. a synced Dropbox folder) — **no git, never the public GitHub repo.** Background is in the
"Sharing across machines" section of `AGENTS.md`.

## Personality

Read `SOUL.md`. Wrap the command output in a line or two of Bob's voice — don't narrate the plumbing.

## Decision flow

When the user triggers a sync ("hey sync", "hey Bob sync", "share this", "pull the team's stuff"):

1. **Check whether the shared folder is configured.** Read `.bob/sync.json`.
   - **Not set up** — the file is missing, or it has no non-empty `shared_dir`:
     1. Tell the user (in Bob's voice) that sync isn't wired up yet, and what they need:
        install the **Dropbox desktop app**, sign in, and have a folder both they and their
        teammates can see — a folder **Shared** with the team and kept **available offline** so the
        files are real local files, not online-only placeholders. (Any synced / shared / network
        folder works; Dropbox is just the easy default. No git, no accounts, nothing else.)
     2. **Ask for the path** to that folder (e.g. `~/Dropbox/bob-shared`). Wait for their answer.
     3. Run `./bob sync --set-dir "<the path they gave>"` — this records it and does the first sync.
        Report the summary line back.
   - **Already set up** — skip straight to step 2. Do **not** ask for the path again.
2. **Sync.** Run `./bob sync` and report the one-line summary (signals merged, wiki files moved each
   way, any `.bak` saved). Honour an explicit direction if the user gave one:
   - "just pull" / "get the team's updates" → `./bob sync --pull`
   - "just push" / "share mine" → `./bob sync --push`
   - "what would change" / "preview" → `./bob sync --dry-run`
3. **If `./bob sync` errors** (e.g. *"shared folder not found — is it available / your cloud drive
   mounted?"*), surface that message — it usually means Dropbox isn't running or the folder hasn't
   finished downloading. Don't patch around it; tell the user what to check.

## What sync does (so you can answer follow-ups)

- `logs/session-signals.jsonl`, each `wiki/**/Index.md`, and `logs/backlog.md` are **unioned** —
  append-only log lines, bullet lists, and `### ` entry blocks respectively, so concurrent additions
  never conflict and nothing is lost. Stray Dropbox "conflicted copy" log files are folded in and
  removed automatically.
- Other wiki files are copied **newer-wins**, with the older version kept beside it as
  `<name>.bak-<timestamp>` (never silently overwritten). Re-running is idempotent — unchanged files
  aren't rewritten.
- **Out of scope:** only `pull-log.jsonl` (machine-local). `backlog.md` is now synced too (it used to
  ride the public repo; it's been untracked so user quotes stay private).

## Constraints

- **Never** push wiki/logs to the public GitHub `origin` — they stay gitignored; `./bob sync` only
  ever touches the configured shared folder.
- Runs in **analysis mode**: this skill only invokes the `./bob sync` CLI (which writes to the shared
  folder + local `wiki/` + `logs/session-signals.jsonl`). It does not edit source or skills, and needs
  no developer key.
- Don't reconfigure the shared folder unless the user asks — `--set-dir` is for first-time setup or an
  explicit change of folder, not for every sync.
