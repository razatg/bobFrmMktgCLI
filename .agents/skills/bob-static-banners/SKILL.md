---
name: bob-static-banners
description: Use when creating or refreshing the quarterly static banner design guide from best-performing Google Ads image assets, or when preparing/reviewing LOW static image replacement variants.
---

# Bob Static Banners Skill

Use this skill when the user asks for a static ads studio, static banner guide, banner design playbook, fresh static creative direction, or same-size replacement variants for LOW static image/banner assets.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Operating Rules

- **Repo-wide rules apply** (no fabrication, no scratch scripts, don't read or modify source files; if a CLI command errors, surface it and use the failsafe): see `AGENTS.md` → Hard constraints + Agent Mode and `CLAUDE.md`.
- **Never call a Google Ads mutation command without explicit user approval.** Preview generation is never approval to upload.

## Scope — two workflows

| The user wants… | Load |
|---|---|
| To create or refresh the quarterly static banner **design guide** (best-performing assets → `banner-design-strategy.md` + `DESIGN.md` + `banner-design.md`) | `references/design-guide.md` |
| To prepare, generate, or apply a same-size **replacement variant** for a LOW static image asset | `references/low-variant.md` |

The two are independent: a design-guide refresh produces the reusable spec; the LOW-variant workflow consumes that spec (`DESIGN.md`) plus a source image to generate preview-only replacements, then applies only after explicit approval.

## Failsafe — Unanswerable Questions

When the request can't be handled by the workflows above or any `./bob` subcommand, use the repo failsafe in `CLAUDE.md` / `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.
