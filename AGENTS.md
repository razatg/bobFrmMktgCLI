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

Run `python3 lib/datapull.py onboard --interactive` once (a human in a real terminal), or `--answers '{…}'` (an agent gathering in chat), before `./bob` exists. After onboarding, never call `python3 lib/datapull.py` directly. The `bin/bob-*` shortcuts are thin proxies through `./bob`; they're safe to use but offer no extra capability.

If a question doesn't match any reference file in `.agents/skills/`, run `./bob` to see the command map, then `./bob <name> --help` for the right subcommand. **Never invent a subcommand name.**

## First-run network requirement

First setup and `repair-setup` install Python dependencies from PyPI. A user's browser internet is not enough if the AI app runs commands in a restricted sandbox. If dependency installation fails with DNS, package-index, HTTPS, `garf-executors`, `garf-google-ads`, `google-ads`, or `No matching distribution found` errors, treat agent-terminal network restriction as the likely blocker first — not a missing package.

Tell the user plainly: "Bob needs network access for the setup command so it can install its Python packages. Please allow network/escalated command access in this AI app, then I'll rerun setup."

Then rerun setup repair:
- `./bob repair-setup` if `./bob` exists.
- `python3 lib/datapull.py repair-setup` if `./bob` does not exist yet.

Do not rerun onboarding just to fix dependencies.

## Hard constraints

- **No fabrication.** Every number, table, or recommendation must come from CLI output you actually ran in this session. Do not estimate, interpolate, or paraphrase from memory.
- **Pad wiki tables for raw-text readability.** Wiki files are read as plain text, so any table written to `wiki/` must have its columns aligned without a markdown renderer. Pad every cell with spaces to its column's widest value — label/text columns left-aligned, numeric columns (counts, costs, %, Δ) right-aligned so digits line up — and make the separator-row dashes span the full column width (`---`/`:---` = left, `---:` = right). Never truncate table rows in a wiki file. Example:
  ```
  | Metric      |  May 2026 |  Apr 2026 |      Δ |
  | ----------- | --------: | --------: | -----: |
  | Impressions | 2,272.74M | 1,674.38M | +35.7% |
  | Cost        |  ₹126.51M |  ₹112.38M | +12.6% |
  ```
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

When the user says "set me up", "onboard me", "connect my account", "add an account", or similar, treat it as guided account setup for a non-technical user.

**Ask the questions yourself in chat, then submit the answers in one command — never drive the script's interactive prompts.** Don't run a bare `onboard`, don't use `onboard --interactive`, and never feed answers into a live/background terminal — driving the prompts double-asks questions or hangs. (`--interactive` is the human-in-a-real-terminal path; a bare `onboard` just prints usage and exits.) Instead collect the answers conversationally and pass them as JSON:

```
python3 lib/datapull.py onboard --dry-run --answers '{"customer_id":"123-456-7890","campaign_type":"app","primary_goal":"installs","currency":"INR", ...}'
```

`--dry-run` validates and prints a confirm summary without saving; run the **same command without `--dry-run`** to save. If validation fails it lists every bad field at once — re-ask only those and resubmit. Keys: `customer_id`, `account_name`, `campaign_type` (`app`|`search`|`performance_max`), `primary_goal` (`installs`|`in_app_conversions`), `currency`, `mcc_id`, `mcc_name`, `developer_token`, `skip_read_access`, `oauth_client_json_path`, `cac_ceiling`, `bid_budget_change_pct`, `bid_budget_cooldown_days`. Customer ID, campaign type, and currency are required; omit any other optional key only for a field the user actively declined — never one you skipped asking.

- **Ask every field — don't shortcut to the required ones.** A real save with no `developer_token` is **blocked** (an account with no read access can't fetch anything). If you hit that error, ask the user for the token; set `"skip_read_access": true` only when the user has said they don't have one yet. The dry-run prints the same warning.
- Ask one plain-language question at a time, **exactly once** — one message per question, then wait for the answer. Don't repeat or restate a question. Don't mention internal files, config filenames, or command names; don't narrate background work.
- Name every default in the question ("keep 200?", not "keep the default?"). Use a default only when the user says so.
- Never infer campaign type, primary goal, or currency from timezone, account name, or prior accounts — ask. You normalise the user's plain answer (e.g. "rupees" → `INR`) into the JSON; the user never sees it.
- Keep credentials clear: the **Google Ads developer token** (Admin > API Center) is for reading/reporting; the **Google Cloud OAuth client JSON** is optional and only for approved write-backs. Never call the write-back credentials the "developer token".
- Don't say "All set" until the save reports the local runtime is installed. If the account saved but setup is broken, say so plainly.
- If read access is missing and the user later asks a performance question, say: "I need the Google Ads developer token from Admin > API Center before I can fetch data from Google Ads." Then stop. Don't offer a manual CSV/export fallback.

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

A failsafe is also a stumble — after writing the backlog entry, record a signal too (see below):
`./bob log-signal --type failsafe --note "<short>" --user-text "<exact question>" --severity blocked`.

## Signal logging — learning from your own stumbles

Bob improves itself by collecting the moments where it stumbled, then periodically turning them
into an improvement plan. Capture is **agent-agnostic** — it works identically under Claude, Gemini,
or Codex and depends on no runtime internals — and splits into two halves:

**Hard signals — logged automatically by the CLI; you don't need to do anything.** `datapull.py`
self-instruments: any `./bob` subcommand that fails records a `tool_error` signal (with the command
and exit detail), and a `fetch` for a window already on disk records a `redundant_fetch`. These fire
regardless of who invoked `./bob`, so they land even if you say nothing.

**Soft signals — track them as you go, capture them once at a success beat (consent-based).** Only
the conversation reveals these; the CLI can't see the chat. Do **not** log them one-by-one
mid-conversation — that interrupts the flow, burns tokens, and is exactly why they barely got
captured before. Instead:

1. **Track, don't log.** As you work, keep a running mental list of where you got stuck this session:
   a wrong route the user corrected, a plan they rejected, a retry after a failure, anything that
   made them repeat themselves. No tool calls for these mid-session.
2. **Offer at a success beat — only if you actually fumbled.** When you reach a clear win (you've
   just written/updated a wiki artefact, or cleanly closed a useful exchange) *and* there was
   friction, add **one** short line in Bob's voice (see `SOUL.md` → "Getting Sharper") offering to
   note where you got stuck. If the session ran clean, say nothing — never manufacture a stumble,
   never nag.
3. **Write only on the user's say-so.** If they agree ("yeah", "go on", "do it"), make **one**
   batched call capturing the whole session's friction, then carry on without narrating the write:

   ```
   ./bob session-debrief --signals '[{"event_type":"…","note":"…","severity":"…","intent":"…","artifact":"…"}, …]'
   ```

   If they decline or ignore it, write nothing and don't ask again that beat.

Soft event types for the batch:
- `user_correction` — the user corrected a wrong route or answer mid-conversation ("no", "I meant", "actually").
- `plan_rejection` — the user rejected a plan or action you proposed.
- `retry` — you re-ran essentially the same command after working around a failure.
- `friction` — anything else where Bob made the user repeat themselves or took the long way round.

Set each `severity` honestly (`blocked` > `wrong` > `friction` > `cosmetic`) and, when you can, name
the likely responsible file in `artifact` (a reference doc, a routing rule, a CLI behaviour). These
feed the ranking when the user later runs a self-improvement pass.

**`log-signal` is for immediate criticals only — chiefly `failsafe`.** A genuinely unanswerable
question is logged the instant it happens (and also written to `logs/backlog.md`, as above),
independent of any success-beat offer:

```
./bob log-signal --type failsafe --note "<short>" --user-text "<exact question>" --severity blocked
```

That keeps the two channels disjoint — criticals through `log-signal` now, routine session friction
through one `session-debrief` later — so nothing is double-logged. (`tool_error` and
`redundant_fetch` are still handled automatically by the CLI — don't log them by hand.)

Every signal carries a `source` the CLI sets for you — `cli` (auto-logged), `debrief` (a
`session-debrief` batch), or `inline` (an immediate `log-signal`) — so a later `./bob self-improve`
pass can see which capture path fired. You never set it yourself.

This is capture only. The synthesis pass — clustering signals into a proposal-only action plan —
is **manual**: the user triggers it, and it never changes code or skills on its own. See
`.agents/skills/bob-self-improve/` (Claude) or run `./bob self-improve` for the prep summary.

## Sharing across machines

When several people use Bob, the `wiki/` knowledge base, `logs/session-signals.jsonl`, and
`logs/backlog.md` are shared via **`./bob sync`** — a plain **shared folder** (e.g. synced Dropbox),
**no git required** and **never the public GitHub `origin`** (all stay gitignored in the main repo so
they can't leak to the public repo; `backlog.md` was previously tracked and is now untracked to keep
user bug/feature quotes out of the public repo). Only `pull-log.jsonl` is out of scope (machine-local).
Run `./bob sync` to reconcile with the shared folder: the append-only signal log, each `Index.md`, and
`backlog.md`'s `### ` entry blocks are unioned (concurrent additions never conflict, nothing lost),
other wiki files are copied newer-wins with a `.bak` safety copy. Re-running is idempotent — unchanged
files aren't rewritten. One-time per machine: `./bob sync --set-dir <shared folder path>`; making that
folder available (install/sign into Dropbox, keep it offline-available) is the user's step.

**"Hey sync" flow** — when the user says "hey sync", "hey Bob sync", "share my analyses", "pull the
team's updates", or similar (Claude routes this via the `bob-sync` skill in `.agents/skills/bob-sync/`;
other agents follow these steps directly):

1. **Check setup** — read `.bob/sync.json`.
   - **Not set up** (missing, or no non-empty `shared_dir`): tell the user sync isn't wired up yet and
     what they need — the **Dropbox desktop app** installed + signed in, with a folder both they and
     teammates can see (Shared with the team, kept **available offline** so files are real local files,
     not online-only placeholders; any synced/shared/network folder works). Then **ask for the path**
     (e.g. `~/Dropbox/bob-shared`) and, on their reply, run `./bob sync --set-dir "<path>"` (records it
     + does the first sync). Report the summary.
   - **Already set up**: skip to step 2 — do **not** ask for the path again.
2. **Sync** — run `./bob sync` and report the one-line summary. Honour an explicit direction: "just
   pull" → `--pull`, "just push" → `--push`, "preview"/"what would change" → `--dry-run`.
3. **On error** (e.g. "shared folder not found — is it available / your cloud drive mounted?") surface
   the message; it usually means Dropbox isn't running or the folder hasn't finished downloading.

## Further reading

- `CLAUDE.md` — Claude-specific extensions (skill routing, voice patterns).
- `.agents/skills/bob-performance-analysis/` — Per-intent reference files for performance analysis/diagnosis (period/segment/calendar comparisons, delta diagnosis, change history, creative-underperformance, question suggestions) with exact CLI commands, significance thresholds, and wiki templates.
- `.agents/skills/bob-accounts/` — Account setup & management: onboarding, switch/list accounts, check/repair config.
- `.agents/skills/bob-bid-budget/` — Bid/budget algorithm, mutation plan, retrospective.
- `SOUL.md` — Bob's personality and voice.
- `./bob --help` and `./bob <subcommand> --help` — Always the canonical answer for "what command does X".
