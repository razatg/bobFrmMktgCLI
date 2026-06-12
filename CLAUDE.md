# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
See also: `AGENTS.md`.

## Project Overview

Bob Frm Mktg is a CLI-first performance marketing automation tool for Google Ads app campaign analysis. It answers natural language questions about campaign performance using deterministic data pulls (via GARF) and reproducible metric calculations.

**Core design principle**: Don't replicate Google Ads data locally. Pull pre-aggregated period comparisons directly from the API; drill down to finer grains only when a significant delta is detected or the user asks. The CLI fetches and aggregates; the agent explains — never invents numbers.

**No data overfitting**: Never write logic that assumes the naming conventions, structural patterns, or data values of the current account or platform. All parsing, classification, and grouping must be derived from the data as it arrives — not from hardcoded keywords, thresholds, or patterns observed in this specific instance. This applies across any ad platform (Google Ads, Meta Ads, or others added in future).

**No advertiser overfitting**: Never anchor instructions, templates, or creative strategy to one advertiser's brand, products, colors, landmarks, or naming patterns. Creative guidance must generalize across advertisers and industries; account-specific examples are examples only, not reusable assumptions.

**No environment-specific paths**: Never hardcode paths tied to a specific AI runtime or developer tool (e.g. `~/.cache/codex-runtimes/`, Gemini CLI paths, Cursor paths). Binary resolution must use `shutil.which()` or `Path(sys.executable).parent` so the code runs identically regardless of which assistant or machine invoked it.

## Working in this repo

**Do not read or modify source files.** This covers `lib/datapull.py`, `garf/queries/*.sql`, `bin/`, `tests/`, `PLAN.md`, `ARCHITECTURE.md`, and `.meta.json` sidecars. All commands, columns, and behavior are documented in this file and the skill reference files. Run CLI commands directly; use `ls` to find data files. If a CLI command errors, surface the error to the user — do not patch code. Agent scope is CLI tools + `wiki/` writes only.

To find available data files, use `ls`:
```bash
ls garf/outputs/raw/                              # see which queries have been fetched
ls garf/outputs/raw/<query>/                      # list raw files for a specific query
ls data/processed/                                # list registered accounts (each is a subdir)
ls data/processed/<customer_id_no_hyphens>/       # see which grains have been processed for that account
ls data/processed/<customer_id_no_hyphens>/<subdir>/  # list processed files for a grain
```

## Commands

**Run the main data tool:**
```bash
./bob <subcommand> [options]
```

After onboarding, run commands as `./bob <subcommand>` — the launcher uses the project virtualenv. Use `python3 lib/datapull.py onboard` only to start onboarding before `./bob` exists. Do not call `bin/bob-*` directly except as fallback shortcuts (they proxy through `./bob`). When a question doesn't match any reference file, run `./bob` for the command map and `./bob <subcommand> --help` for flags — never invent a subcommand name.

**Common subcommands:**
```bash
# Bootstrap: fetch all default period windows (~16 small API calls)
./bob bootstrap [--account ID] [--dry-run]

# Fetch a single query for a specific date range
# --reason is required by convention — logged to logs/pull-log.jsonl with every live fetch
./bob fetch --query account_network_period --from 2026-05-13 --to 2026-05-19 --reason "TEXT"
./bob fetch --query adgroup_network_period --from DATE --to DATE --reason "TEXT"  # Tier 3

# Create processed aggregates from raw outputs
./bob aggregate --grain account_network_period
./bob aggregate --grain campaign_network_period
./bob aggregate --grain creative_period
./bob aggregate --grain campaign_weekly_trend  # reads 3 most recent campaign_network_period files
./bob aggregate --grain account_daily --source campaign_daily  # legacy daily grain

# Compare two ISO calendar weeks (defaults: last complete week vs prior week)
./bob compare-weeks [--week N] [--vs M] [--year YYYY] [--grain account|campaign|both]
./bob compare-weeks --week 20 --vs 19 --name-contains "Stable"  # with campaign filter
./bob compare-weeks --all-metrics  # show full metric table (users, CPM, freq, CTR, CPC, CTI, conv%, CPA)

# Compare two calendar months MTD (default) or full months
./bob compare-months [--month N] [--vs M] [--year YYYY] [--full]
./bob compare-months --month 5 --vs 4  # May MTD vs Apr MTD
./bob compare-months --month 5 --vs 4 --all-metrics  # with full metric table

# Flag LOW-label creatives vs campaign averages (low-action vs low-watch + pattern analysis)
./bob slice-creatives [--min-impressions N] [--output FILE]

# Copy suggestion + apply for LOW-action TEXT assets
./bob suggest-creative-copy [--min-impressions N]      # copy plan + compact agent-agnostic prompt
./bob creative-copy-apply --plan FILE [--suggestions JSON]  # approval table + push to Google Ads

# Compare a named campaign segment across two periods (network-aggregated, with totals row)
./bob slice-campaigns --name-contains "Stable" [--period yesterday_vs_sdlw|wow|mom|mtd]
./bob slice-campaigns --name-contains "Stable" --output FILE  # save full CSV
./bob slice-campaigns --name-contains "Stable" --all-metrics  # with full metric table

# Bid/budget recommendations — generate, review, apply, evaluate
./bob bid-budget-recommend [--dry-run]                     # generate plan from weekly trend
./bob bid-budget-recommend --cac-ceiling 150 --change-pct 15  # override profile defaults
./bob bid-budget-apply --plan wiki/action-items/bid-budget-YYYY-MM-DD.yaml  # apply plan to Google Ads
./bob bid-budget-retrospective --plan wiki/action-items/bid-budget-YYYY-MM-DD.yaml  # evaluate changes

# Validate against manual exports
./bob validate-manual --bob FILE --manual FILE [--mapping FILE]

# Check Google Ads YAML config (safe — does not print secrets)
./bob check-config [--config PATH]

# Account management
python3 lib/datapull.py onboard                # interactive setup before ./bob exists
./bob switch-account                           # switch active account context
./bob list-accounts                            # list all registered accounts

# Team sync — share wiki/ + logs/session-signals.jsonl across machines (no git)
./bob sync --set-dir ~/Dropbox/bob-shared      # one-time: record the shared folder
./bob sync                                     # reconcile both ways with the shared folder
./bob sync --pull                              # only pull teammates' changes
./bob sync --push                              # only push your changes
./bob sync --dry-run                           # show what would sync; change nothing
```

**Team sync** (`./bob sync`) shares the `wiki/` knowledge base, `logs/session-signals.jsonl`, and `logs/backlog.md` with teammates through a **plain shared folder** (e.g. a synced Dropbox folder) — **no git required**. It never touches the public GitHub `origin`; all three stay gitignored in the main repo (`backlog.md` was previously tracked and is now untracked so user bug/feature quotes stay out of the public repo). Out of scope: only `pull-log.jsonl` (machine-local). The append-only signal log, each `Index.md`'s bullet lists, and `backlog.md`'s `### ` entry blocks are **unioned** (so concurrent additions never conflict and nothing is lost — even stray Dropbox "conflicted copy" log files are folded in); other wiki files are copied **newer-wins**, with the older version kept as a `.bak` safety copy. Re-running is idempotent — unchanged files are not rewritten. Setup is one-time per machine (`--set-dir` points at that machine's synced shared-folder path); the user just makes the folder available (install/sign into Dropbox and keep it offline-available, or any shared/network folder).

**Pull log** — every live fetch appends one JSON line to `logs/pull-log.jsonl`:
```json
{"timestamp":"...","query":"...","from_date":"...","to_date":"...","account":"...","reason":"...","run_id":"...","output_file":"..."}
```
The `reason` field records why the pull was made. Dry-run fetches do **not** write to the log.

**Read the log first.** Before any `./bob fetch`, before any `ls garf/outputs/raw/`, before any grep over CSVs — read `logs/pull-log.jsonl` and filter to the active account's customer ID (no hyphens). That single file is the canonical answer to "what's been pulled, when, and why for this account." Only fall back to `ls`/`grep` if you need to confirm a specific file on disk after consulting the log.

**Dry run** (renders and saves query without executing):
```bash
./bob fetch --query account_network_period --from 2026-05-13 --to 2026-05-19 --dry-run
./bob bootstrap --dry-run
```

**Thin bash wrappers** in `bin/` mirror the subcommands (e.g., `bin/bob-fetch`, `bin/bob-fetch-bootstrap`, `bin/bob-onboard`, `bin/bob-switch-account`, `bin/bob-list-accounts`).

**No test harness exists yet** (planned for Phase 13). Validation is done via `validate-manual`. Fixtures live in `tests/fixtures/`.

## Architecture

### Tier Model

| Tier | Query | Grain | When pulled |
|---|---|---|---|
| 1 | `account_network_period` | Account × Network, period SUM | Every comparison (WoW, MoM, yesterday vs SDLW) |
| 2a | `campaign_network_period` | Campaign × Network, period SUM | Delta > threshold or user asks "which campaign" |
| 2b | `change_history` | Event, filtered by campaign_id | Overlaid on Tier 2a for context — no extra fetch |
| 3 | `adgroup_network_period` | Campaign × AdGroup × Network, period SUM | Deeper diagnosis or user asks "which ad group" — on demand only |
| B/B | `campaign_network_period` × 3 weeks | Campaign × Network, 3-week rolling | Bid/budget trend validation |
| Creative | `creative_period` | Asset, period SUM, ≥50k imp | Creative underperformance question |

Bootstrap fetches ~16 small queries (each returning <100 rows) instead of 90 days of daily rows. Periods covered: `yesterday_vs_sdlw`, `wow`, `mom`, `mtd` (all four for account-level), `yesterday_vs_sdlw` + `3week_rolling` for campaign-level, plus creative/change_history/bid_budget windows.

### Layers

1. **GARF query layer** (`garf/queries/*.sql`) — SQL templates with `{start_date}`, `{end_date}` macros. Period-aggregate queries omit `segments.date` from SELECT so GAQL aggregates server-side. All filter to `APP_CAMPAIGN` / `APP_CAMPAIGN_FOR_ENGAGEMENT`.

2. **Fetch layer** (`lib/datapull.py: fetch`) — Renders macros, builds GARF CLI command, executes, saves raw CSV + `.meta.json` sidecar.

3. **Aggregate layer** (`lib/datapull.py: aggregate`) — Reads raw CSVs, groups/sums base metrics, derives ratio metrics. Output goes to `data/processed/{customer_id_no_hyphens}/{subdir}/`.

4. **Validation layer** (`lib/datapull.py: validate-manual`) — Tolerance-based diff of Bob aggregates vs user-provided manual exports.

5. **Agent skill layer** (`.agents/skills/bob-google-ads/`) — Intent routing and per-intent reference docs. Each reference file specifies the exact CLI commands to run, significance thresholds that trigger auto-escalation, and the wiki artefact structure to write on user acceptance. Not executable code.

### Key files

- `lib/datapull.py` — All Python logic: period date resolution, GARF command building, metric calculations, CSV handling, aggregate grains, subcommand dispatch.
- `garf/queries/` — 12 SQL query templates. Period-aggregate queries (new): `account_network_period`, `campaign_network_period`, `adgroup_network_period`, `creative_period`. Legacy daily queries (on-demand only): `campaign_daily`, `network_daily`, `creative_asset_daily`, `campaign_reach_daily`.
- `.bob/accounts.json` — Flat registry of all registered accounts: `[{"google_ads_customer_id": "...", "account_name": "...", "campaign_type": "...", "active": true|false}]`. The `active` flag is the source of truth for which account is loaded.
- `.bob/accounts/{customer_id_no_hyphens}/profile.json` — Per-account canonical profile. `load_profile()` reads the active account's profile from here (via accounts.json), not from a flat profile.json. Fields: `google_ads_customer_id`, `account_name`, `google_ads_mcc_id`, `google_ads_mcc_name`, `campaign_type` (`"app"` | `"search"` | `"performance_max"`), `primary_goal`, `currency`, `campaign_goal_type`, `google_ads_read_config_path` (GARF read config, default per-account file in `.bob/accounts/{customer_id_no_hyphens}/`; blank `""` if skipped), `google_ads_write_config_path` (mutation config, default per-account file in the same directory; blank `""` if skipped), `creative_min_impressions` (default 50000), `cac_ceiling` (default 200), `bid_budget_change_pct` (default 10), `bid_budget_cooldown_days` (default 14).
- `.bob/profile.example.json` — Blank-value copy of the full profile schema for reference.
- `.bob/metrics-reference-{campaign_type}.json` — Metric catalog for a specific campaign type (e.g. `metrics-reference-app.json` for App Campaigns). Contains: primary goal rationale, full acquisition funnel, formula for every metric, and the `do_not_select` policy for pre-computed API averages. Load the file matching the active account's `campaign_type`. When a new campaign type is added (Search, Performance Max), add a new reference file — do not merge into the existing one. Edit `primary_goal_context` to reflect why your primary goal matters for that type.
- `SOUL.md` — Bob's personality: voice, tone, analysis style, and response patterns. Read at the start of every conversation. Kept separate so it can evolve independently of the data layer.
- `.agents/skills/bob-google-ads/SKILL.md` — Agent routing rules and operating constraints for performance analysis.
- `.agents/skills/bob-google-ads/references/` — 6 reference files, one per intent. Each contains: required inputs, working CLI commands, significance thresholds + auto-escalation rules, and a wiki artefact template.
- `.agents/skills/bob-bid-budget/SKILL.md` — Bid/budget skill: algorithm, mutation plan, apply, and retrospective routing.
- `.agents/skills/bob-bid-budget/references/` — 3 reference files: `algorithm.md` (4-scenario decision matrix), `mutation-plan.md` (review + apply workflow), `retrospective.md` (W+1/W+2 evaluation).
- `.agents/skills/bob-sync/SKILL.md` — Team-sync skill: routes "hey sync" / "hey Bob sync"; checks the shared-folder setup (`.bob/sync.json`), guides one-time `--set-dir` setup if missing, otherwise runs `./bob sync`.
- `ARCHITECTURE.md` — Full system design doc.
- `PLAN.md` — MVP build roadmap with phase completion status.

### Key functions in `lib/datapull.py`

- `resolve_period_dates(period)` — Returns list of `(start, end)` date tuples for `yesterday_vs_sdlw`, `wow`, `mom`, `mtd`, `3week_rolling`. MTD computes 1st-of-month → yesterday vs same range prior month, with edge-case handling for months of different lengths.
- `find_period_files(query_name, n)` — Returns n most recent raw CSV files sorted by start_date in filename. Used by `campaign_weekly_trend` to locate the 3 weekly windows.
- `find_processed_files_for_period(subdir, windows)` — Returns processed CSV files matching given `(start, end)` date windows by filename encoding. Used by `slice_campaigns` to locate the right pair of files.
- `_aggregate_period_rows(rows, key_cols, primary_goal)` — Core grouping function: sums base metrics, recalculates derived metrics, returns output rows.
- `correlate_change_history(campaign_id, start_date, end_date, path)` — Filters change_history raw output by campaign and date window. Called by slice tools for diagnostic overlay.
- `_agg_campaign_weekly_trend(...)` — Reads 3 `campaign_network_period` files (W0/W1/W2), sums across networks per campaign, assigns `trend_direction` and `signal_strength`.
- `slice_campaigns(args)` — Filters processed `campaign-network/` files by `--name-contains` pattern, aggregates across networks per campaign, prints summary table, optionally writes full CSV.
- `iso_week_to_dates(week, year)` — Returns `(monday, sunday)` for an ISO week number. Raises error on invalid week.
- `last_complete_iso_week(reference)` — Returns `(week, year)` for the most recently completed ISO week before `reference`.
- `_month_date_range(month, year, full, reference)` — Returns `(start, end)` for a calendar month; MTD caps at `min(yesterday.day, last_day_of_month)`.
- `_build_comparison_rows(current_rows, baseline_rows, key_cols, primary_goal)` — Shared helper: aggregates both sets, joins by key, computes `current_*`, `baseline_*`, `delta_*_pct` columns.
- `compare_weeks(args)` / `compare_months(args)` — ISO week and calendar month comparison commands; auto-detect processed files by date window; print account × network and campaign tables; emit fetch commands if files are missing.

### Output conventions

- **Raw outputs**: `garf/outputs/raw/{query_name}/{customer_id}_{start}_{end}_{run_id}.csv` with a `.meta.json` sidecar.
- **Processed outputs**: `data/processed/{customer_id_no_hyphens}/{subdir}/{customer_id}_{start}_{end}.csv`
  - Subdirs: `account-network/`, `campaign-network/`, `adgroup-network/`, `creative/`, `campaign-trend/`, `account/`, `bid-budget-recs/`, `change-history/`
  - Legacy flat paths (`data/processed/{subdir}/`) are supported via backward-compat fallback in `_resolve_processed_dir()`.
- **Wiki outputs**: `wiki/{customer_id_no_hyphens}/analyses/` and `wiki/{customer_id_no_hyphens}/action-items/`
- Filenames encode date ranges to enable `find_period_files()` sorting.

### Metric formulas (all centralized in `lib/datapull.py: _derive_metrics`)

Full set (13 metrics): `reach`, `impressions`, `cpm`, `frequency`, `clicks`, `ctr_percent`, `cpc`, `installs`, `cti_percent`, `goal_conversions`, `conversion_rate_percent`, `cpa`, `cpi`.

- `cpm = (cost / impressions) * 1000`
- `frequency = impressions / reach`
- `ctr_percent = (clicks / impressions) * 100`
- `cpc = cost / clicks`
- `cti_percent = (installs / clicks) * 100`
- `conversion_rate_percent = (goal_conversions / clicks) * 100`
- `cpa = cost / goal_conversions`
- `cpi = cost / installs`  (always installs regardless of primary_goal)
- Zero denominators return `"NA"`, never `NaN` or `0`.
- `goal_conversions` = `installs` when `primary_goal == "installs"`, else `in_app_conversions`.
- `reach` / `Users` is surfaced only where the slice exposes it at the account or campaign total level. For network and ad group breakdowns, keep `reach` and `frequency` as `NA` rather than forcing `0`.
- Pre-computed API averages (`metrics.ctr`, `metrics.average_cpc`) are **not** selected in period-aggregate queries — they'd be averages of averages. Recalculate from raw sums instead.

**Default output** (compact): goal metric + cost + Δ% per row.  
**`--all-metrics` flag**: adds a transposed metric table (metric as rows, periods as columns) before the per-row table. Available on `compare-weeks`, `compare-months`, and `slice-campaigns`. Show it when the user says "complete set of metrics" or "all metrics".

`METRIC_DISPLAY_SPEC` in `lib/datapull.py` defines the ordered display set and format kinds (`count`, `cost`, `percent`, `ratio`). `_print_metric_table` renders the transposed table using `_fmt_display` (M/K suffixes, currency symbol from profile) and `_fmt_delta_display`.

### Bid/budget trend logic (`campaign_weekly_trend` grain)

The `campaign_weekly_trend` aggregate uses actual ISO week numbers as column prefixes (e.g. `w20_cost`, `w19_cost`, `w18_cost`) rather than generic `w0_`/`w1_`/`w2_`. The file also includes `current_iso_week`, `prior1_iso_week`, `prior2_iso_week` integer columns so consumers know which week each prefix refers to.

`signal_strength` / `trend_direction` describe the CPI trajectory across the 3 weeks:

| signal_strength | trend_direction | Meaning |
|---|---|---|
| `confirmed` | improving | W0 and W1 both show CPI improvement — act |
| `confirmed` | deteriorating | W0 and W1 both show CPI worsening — act |
| `early` | either | W0 signals a direction but W1 doesn't support it yet — observe |
| `blip` | deteriorating | W0 is worse but W1 was already improving — likely noise, do not act |
| `stable` | stable | No meaningful change — hold |

**`bid-budget-recommend`** applies the 4-scenario algorithm (CPI × CPM vs prior 2-week average). Guards: `cac_ceiling` (default 200, uses actual W0 CPA; falls back to `target_cpa` bid when no conversions), min 10 installs in W0, declining post-install conv% blocks increases, `bid_budget_cooldown_days` (default 14) skips recently-changed campaigns. Magnitude: `bid_budget_change_pct` (default 10%, capped at 20%). Each YAML entry includes `last_bid_budget_change_date`, `days_since_last_change`, `cooldown_ok`. See `.agents/skills/bob-bid-budget/references/algorithm.md` for the full decision matrix.

**`bid-budget-apply`** writes Target CPA and budget changes to Google Ads via the `google-ads` Python library. Requires `pip install google-ads pyyaml`. **Never call without explicit user approval.**

**`bid-budget-retrospective`** evaluates W+1/W+2 CPI vs the pre-change baseline recorded in the YAML plan. Verdicts: `working`, `too_early`, `not_working`.

### External dependency: GARF

```bash
pip install garf-executors garf-google-ads
```

Requires a `google-ads-garf.yaml` config file (read-only, 2 required keys: `developer_token`, `login_customer_id`). Onboarding creates a separate read config per account beside the profile under `.bob/accounts/{customer_id_no_hyphens}/` and stores the path as `google_ads_read_config_path`. For write operations (bid/budget and approved creative mutations), onboarding asks for the separate Google Cloud OAuth client JSON and converts it into `google-ads-api.yaml` in the same account folder (5 required keys: adds `client_id`, `client_secret`, and `refresh_token`), set as `google_ads_write_config_path`. Both paths are optional — stored as `""` if skipped during onboarding.

### Agent Intent → Reference File Map

| User question | Reference file |
|---|---|
| What happened yesterday / yesterday vs SDLW | `account-yesterday-vs-sdlw.md` |
| WoW / MoM / MTD performance | `account-period-comparison.md` |
| What caused the change (network → campaign → ad group) | `delta-diagnosis.md` |
| What to do with bids and budgets | `bob-bid-budget` skill — see `.agents/skills/bob-bid-budget/` |
| Which creatives are underperforming | `creative-underperformance.md` |
| What did the team work on / change history | `change-history-summary.md` |
| Compare a named campaign group ("Stable campaigns", "Brand campaigns") | `campaign-segment-comparison.md` |
| Compare two ISO weeks or calendar months ("W20 vs W19", "May MTD vs April") | `calendar-period-comparison.md` |
| Sync / share wiki + signals with teammates ("hey sync", "hey Bob sync", "share my analyses") | `bob-sync` skill — see `.agents/skills/bob-sync/` |

**Auto-escalation rule** (in yesterday and period comparison references): if primary goal changes >10%, cost >15%, or any ratio >1 pp, the agent automatically proceeds to delta diagnosis without waiting for the user to ask.

**Wiki artefact pattern**: every reference specifies a wiki file to offer writing after user confirmation. Analyses go to `wiki/{customer_id_no_hyphens}/analyses/`, action items to `wiki/{customer_id_no_hyphens}/action-items/`. Each file has a frontmatter block (`date`, `intent`, `period`) and a `← [Wiki Index](../Index.md)` backlink on the first line after frontmatter.

`{customer_id_no_hyphens}` is derived from the active account's `google_ads_customer_id` (loaded via `load_profile()`) with hyphens stripped (e.g. `123-456-7890` → `1234567890`).

**Wiki save rules** — enforced every time an analysis or action item is written:
1. **Use conversation output only.** Copy numbers and tables from what's already on screen. Do NOT re-run CLI commands, do NOT run `--output`, do NOT read any CSV, do NOT use pandas. **Never truncate wiki content** — write every row of every table. No "… and N more" or "top 10 shown". Truncation in the chat is fine; truncation in the wiki file is not.
2. **Update `wiki/{customer_id_no_hyphens}/Index.md`.** Add one line under `## Analyses` or `## Action Items`. Create the file if it doesn't exist (heading: `# Bob — Wiki Index`, sections: `## Analyses`, `## Action Items`, `## Backlog`).
3. **Backlink.** Every wiki file starts with `← [Wiki Index](../Index.md)` after frontmatter.
4. **Pad every table for raw-text readability.** Wiki tables are read as plain text, so columns must align without a markdown renderer. Pad every cell with spaces to its column's widest value: **label/text columns left-aligned, numeric columns (counts, costs, %, Δ) right-aligned** so digits and decimals line up. The separator row encodes the alignment (`---` or `:---` = left, `---:` = right) and its dashes span the full column width. Example:
   ```
   | Metric      |  May 2026 |  Apr 2026 |      Δ |
   | ----------- | --------: | --------: | -----: |
   | Impressions | 2,272.74M | 1,674.38M | +35.7% |
   | Cost        |  ₹126.51M |  ₹112.38M | +12.6% |
   ```

`wiki/{customer_id_no_hyphens}/Index.md` is the per-account navigation hub — every wiki file links back to it, and it links to every wiki file.

**Wiki cache check**: Before running any analysis or recommendation, read `wiki/{customer_id_no_hyphens}/Index.md`. If a recent entry for the same intent is within the cache window (creative/bid-budget = 7 days; all other intents = 1 day), surface the link and ask the user if they want a fresh run. For fresh runs, prepend one line of prior context from the Index one-liner only — never open the full wiki file.

### creative_period: performance_label

The `creative_period.sql` query returns `performance_label` directly from the Google Ads API (`BEST`, `GOOD`, `LOW`, `LEARNING`). This is the primary signal in `creative-underperformance.md`. For blank labels, report raw metrics and set action to `observe` — do not compute benchmarks.

## Failsafe — Unanswerable Questions

Every Bob answer must come from a CLI tool listed in this file or a reference file in `.agents/skills/bob-google-ads/references/`. If no tool can produce the required data, the agent must **not** guess, fabricate, or write ad-hoc scripts.

**Never write scratch scripts, helper programs, or ad-hoc code files to analyze data.** Work only from columns already present in processed CSV outputs. If a required computation (e.g. medians, cross-file joins) has no CLI subcommand that produces it, use the failsafe response instead.

**Required response when a question is unanswerable:** Respond in Bob's voice following `SOUL.md` — honest, direct, Australian. Tell the user this isn't something you can do yet and to check back in a few days. One or two sentences, no corporate hedging.

The question must then be appended to `logs/backlog.md` under `## Bug Reports` or `## Feature Requests`:
```markdown
### [BUG or FEATURE] YYYY-MM-DD — <short title>
**User said:** "<exact user input>"
**What happened:** <what Bob did or couldn't do>
**What's needed:** <fix or feature description>
```
Use **BUG** when Bob routed or responded incorrectly. Use **FEATURE** when the capability is genuinely missing. Full rules are in `.agents/skills/bob-google-ads/SKILL.md` → Failsafe section.

## Self-Improvement

Bob learns from its own stumbles through a three-layer, fully **agent-agnostic** loop — nothing
depends on Claude Code internals (no hooks, no transcript scraping), so it runs identically under
any agent:

1. **Capture (two halves, both agent-agnostic).** *Hard signals* are logged automatically by the
   CLI — `datapull.py` self-instruments, so any failed `./bob` subcommand records a `tool_error`
   and a fetch for an on-disk window records a `redundant_fetch`, with no agent cooperation.
   *Soft signals* live only in the conversation (the CLI can't see it), so the agent flags them via
   `./bob log-signal --type <failsafe|user_correction|plan_rejection|retry|friction> --note "…"
   [--severity …]`. The contract lives in `AGENTS.md` → "Signal logging". Log once per stumble;
   don't narrate it. A failsafe both writes `logs/backlog.md` and logs a `failsafe` signal.
2. **Storage.** `log-signal` appends one JSON line to `logs/session-signals.jsonl` (gitignored,
   machine-local), mirroring the pull-log. Allowed in analysis mode.
3. **Synthesis (manual, proposal-only).** When the user asks Bob to review its mistakes, run
   `./bob self-improve` (prep summary + file pointers — no LLM), then the `bob-self-improve` skill
   clusters the signal log + `logs/backlog.md` by root cause, ranks by frequency × severity, traces
   each pitfall to a responsible artifact, and writes a **proposal-only** action plan to
   `wiki/_self-improve/action-plan-YYYY-MM-DD.md`. It never edits source or skills — a human
   approves and applies each item. See `.agents/skills/bob-self-improve/`.

## Current Build Status (from PLAN.md)

**Complete**: skeleton, profile/config, all GARF period-aggregate queries, fetch/bootstrap/aggregate/validate/check-config commands, all aggregate grains including `mtd` period and `campaign_weekly_trend`, metric definitions, all 6 MVP intent reference files with CLI commands + auto-escalation + wiki artefact templates.

**Planned**: `bob-slice-*` bin wrappers, Google Ads mutations write-back, wiki save flow implementation, pytest harness.
