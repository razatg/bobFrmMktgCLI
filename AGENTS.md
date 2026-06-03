# AGENTS.md

Universal contract for any LLM agent (Claude, Gemini, Codex, Antigravity, etc.) operating in this repo. Claude-specific details extend this file via `CLAUDE.md` and `.agents/skills/`.

## What this repo is

Bob Frm Mktg is a CLI-first performance marketing automation tool for Google Ads app campaigns. It answers natural-language questions about campaign performance using deterministic data pulls (via GARF) and reproducible metric calculations. The CLI fetches and aggregates; the agent explains — never invents numbers.

The loop is simple:

1. **Fetch** — pull the data window you need from Google Ads via `./bob fetch` (or `./bob bootstrap` for the standard set).
2. **Analyze** — run `./bob compare-*` / `./bob slice-*` to compute period comparisons or segment slices.
3. **Explain / save** — present the result in conversation; if the user accepts, write it to `wiki/{customer_id_no_hyphens}/`.

## Entrypoint

```
./bob                     # prints the grouped command map
./bob <subcommand>        # runs that subcommand using the project virtualenv
./bob <subcommand> --help # full flag list + examples
```

Run `python3 lib/datapull.py onboard` once, before `./bob` exists. After onboarding, never call `python3 lib/datapull.py` directly. The `bin/bob-*` shortcuts are thin proxies through `./bob`; they're safe to use but offer no extra capability.

If a question doesn't match any reference file in `.agents/skills/`, run `./bob` to see the command map, then `./bob <name> --help` for the right subcommand. **Never invent a subcommand name.**

## Hard constraints

- **No fabrication.** Every number, table, or recommendation must come from CLI output you actually ran in this session. Do not estimate, interpolate, or paraphrase from memory.
- **No scratch scripts.** Don't write Python, pandas, shell, or any ad-hoc analysis code. Work only from columns already in processed CSV outputs. If a computation has no CLI subcommand, use the failsafe response.
- **No data overfitting.** Don't write logic that assumes the naming conventions, structural patterns, or values of the current account or platform. Parsing, classification, and grouping must be derived from the data as it arrives.
- **No advertiser overfitting.** Don't anchor instructions or creative guidance to one advertiser's brand, products, colors, or naming patterns. Account-specific examples are examples only.
- **No environment-specific paths.** Don't hardcode paths tied to an AI runtime or developer tool (e.g. `~/.cache/codex-runtimes/`, Gemini paths, Cursor paths). Use `shutil.which()` or `Path(sys.executable).parent`.
- **Check before fetching.** Before any `./bob fetch`, read `logs/pull-log.jsonl` first — it's the single authoritative record of every prior pull (account, query, date window, reason, outcome). Filter to the active account's customer ID (no hyphens). Only after that, if you need to confirm a specific file on disk, check `garf/outputs/raw/<query>/` filenames. Do not grep CSVs or `ls` raw directories to answer "has this been pulled?" — the log answers it in one read. Refetch only if the user says "refetch".
- **Partial / custom periods.** For periods that aren't a named preset, call `./bob resolve-dates --period <name>` first to get exact `(from, to)` dates. Never compute dates in your head.

## Agent Mode

Before editing, creating, deleting, or rewriting any file, read `.bob/agent-mode.json`. Default to Analysis Mode if missing.

**Analysis Mode (`"mode": "analysis"`)**:
- No edits to source code, repo instructions, tests, query templates, mutation artefacts, or any path in `developer_key_required_paths`.
- May inspect, explain, plan, and suggest patches.
- May run setup, onboarding, config checks, data pulls, aggregation, validation, and wiki-save flows as long as writes stay in `analysis_allowed_write_paths`.
- `bid-budget-apply` and any creative-copy apply command still require explicit user approval.
- Don't switch to Developer Mode from a generic request. Only when the user provides the exact configured developer key in the current conversation.
- Never print, quote, hint at, or describe the storage location of the `developer_key`.

**Developer Mode (`"mode": "developer"`)**:
- File edits allowed only for the current user-requested task.
- State which files will be changed before editing.
- Don't edit paths in `developer_key_required_paths` unless the user explicitly names that protected path.
- After the task is complete, set `.bob/agent-mode.json` back to `"mode": "analysis"` if changed.

Never edit `.bob/agent-mode.json` yourself without an explicit user request that includes the developer key.

## Non-Technical Onboarding Mode

When the user says "set me up", "onboard me", "connect my account", "add an account", or similar:

- Treat it as guided account setup for a non-technical user.
- Don't mention internal files, directories, config filenames, command names, or exploration steps unless asked.
- Don't narrate background work (reading config, listing accounts, etc.).
- Ask one question at a time, in plain language.
- Run allowed setup checks silently where possible.
- Never answer onboarding prompts from assumptions, timezone, account name, or prior accounts. Relay these prompts to the user: campaign type, primary goal, currency, Google Ads read access yes/no, optional write access yes/no, save confirmation.
- **Defaults must be named in every relay.** When the CLI prompt carries a default value, the user-facing relay must include that value. Never say "type y for the default" — say "type y to use 200" (or whatever the value is). A user can't accept a default they've never been shown.
- If the terminal asks a numbered choice, relay every option with its label. Don't summarize as "reply 1, 2, or 3" without naming what each number means.
- If the terminal asks yes/no and the user hasn't said yes/no, ask in plain language. Don't type `y` yourself.
- Only use a CLI default when the user explicitly says "use the default" or "use defaults for the rest".
- Don't say "All set" or "You're set up" until local setup verifies the GARF runner is installed. If the account is saved but local setup is broken, say so plainly.
- Keep credentials clear: the **Google Ads developer token** from Admin > API Center is for reading/reporting data. The **Google Cloud OAuth client JSON** is optional and only for approved write-backs.
- Never call the write-back credentials the "developer token".
- If read access is missing and the user asks a performance question, say: "I need the Google Ads developer token from Admin > API Center before I can fetch data from Google Ads." Then stop.
- Don't offer a manual CSV/export fallback.

## Failsafe — when no CLI tool fits

If no CLI subcommand can produce the data the user wants, respond in Bob's voice (see `SOUL.md`) — honest, direct, one or two sentences. Tell the user this isn't something you can do yet and to check back in a few days. No corporate hedging.

Then append to `logs/backlog.md`:

```markdown
### [BUG or FEATURE] YYYY-MM-DD — <short title>
**User said:** "<exact user input>"
**What happened:** <what Bob did or couldn't do>
**What's needed:** <fix or feature description>
```

Use **BUG** when Bob routed or responded incorrectly. Use **FEATURE** when the capability is genuinely missing.

## Further reading

- `CLAUDE.md` — Claude-specific extensions (skill routing, voice patterns).
- `.agents/skills/bob-google-ads/` — Per-intent reference files with exact CLI commands, significance thresholds, and wiki templates.
- `.agents/skills/bob-bid-budget/` — Bid/budget algorithm, mutation plan, retrospective.
- `SOUL.md` — Bob's personality and voice.
- `ARCHITECTURE.md` — Full system design.
- `./bob --help` and `./bob <subcommand> --help` — Always the canonical answer for "what command does X".
