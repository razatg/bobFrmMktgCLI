# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
See also: `CLAUDE.md`.

## Agent Mode

Before editing, creating, deleting, formatting, or rewriting any file, read `.bob/agent-mode.json`.

If the file is missing, default to Analysis Mode.

If `"mode": "analysis"`:
- Do not edit files.
- Do not use apply_patch.
- Do not run commands that modify repo files.
- You may inspect, explain, plan, and suggest patches.
- Do not switch to Developer Mode from an ordinary request like "switch to developer mode" or "go ahead".
- Developer Mode is allowed only when the user pastes the exact `developer_key` from `.bob/agent-mode.json` in the current conversation.

If `"mode": "developer"`:
- File edits are allowed only for the current user-requested task.
- Before editing, state which files will be changed.
- Do not edit paths listed in `protected_paths` unless the user explicitly names that protected path.
- After the requested task is complete, set `.bob/agent-mode.json` back to `"mode": "analysis"` if it was changed for the task.

Never edit `.bob/agent-mode.json` yourself unless the user explicitly asks to change the agent mode config and provides the exact `developer_key`.

## Project Overview

Bob Frm Mktg is a CLI-first performance marketing automation tool for Google Ads app campaign analysis. It answers natural language questions about campaign performance using deterministic data pulls (via GARF) and reproducible metric calculations.

**Core design principle**: Don't replicate Google Ads data locally. Pull pre-aggregated period comparisons directly from the API; drill down to finer grains only when a significant delta is detected or the user asks. The CLI fetches and aggregates; the agent explains — never invents numbers.

**No data overfitting**: Never write logic that assumes the naming conventions, structural patterns, or data values of the current account or platform. All parsing, classification, and grouping must be derived from the data as it arrives — not from hardcoded keywords, thresholds, or patterns observed in this specific instance. This applies across any ad platform (Google Ads, Meta Ads, or others added in future).

**No environment-specific paths**: Never hardcode paths tied to a specific AI runtime or developer tool (e.g. `~/.cache/codex-runtimes/`, Gemini CLI paths, Cursor paths). Binary resolution must use `shutil.which()` or `Path(sys.executable).parent` so the code runs identically regardless of which assistant or machine invoked it.

**Partial or custom time periods**: When the user asks for a period that isn't a named preset (e.g. "first 3 days this week vs last week", "W21 Mon–Wed"), call `resolve-dates` first to get the exact `(from, to)` dates, then use those in `fetch` and `compare` commands. Never compute dates in your head. Available periods: `yesterday-vs-sdlw`, `wow`, `mom`, `mtd`, `3week-rolling`, `partial-wow` (with optional `--n`).

**Data fetch rule — check before fetching**: Before issuing any `fetch` command, check whether a file in `garf/outputs/raw/<query>/` already covers the required date range (match start and end dates in the filename). If a matching file exists, use it directly — do not fetch again. **Exception**: the user explicitly says "refetch" or "re-fetch".

**Do not read source files to research data or behavior.** This covers `lib/datapull.py`, `garf/queries/*.sql`, `PLAN.md`, `ARCHITECTURE.md`, `tests/`, and `.meta.json` sidecars. All commands, columns, and behavior are documented in this file and the skill reference files. Run CLI commands directly; use `ls` to find data files.

## Commands

**Run the main data tool:**
```bash
python3 lib/datapull.py <subcommand> [options]
```

**Common subcommands:**
```bash
# Bootstrap: fetch all default period windows (~16 small API calls)
python3 lib/datapull.py bootstrap [--account ID] [--dry-run]

# Fetch a single query for a specific date range
# --reason is required by convention — logged to logs/pull-log.jsonl with every live fetch
python3 lib/datapull.py fetch --query account_network_period --from 2026-05-13 --to 2026-05-19 --reason "TEXT"
python3 lib/datapull.py fetch --query adgroup_network_period --from DATE --to DATE --reason "TEXT"  # Tier 3

# Create processed aggregates from raw outputs
python3 lib/datapull.py aggregate --grain account_network_period
python3 lib/datapull.py aggregate --grain campaign_network_period
python3 lib/datapull.py aggregate --grain creative_period
python3 lib/datapull.py aggregate --grain campaign_weekly_trend  # reads 3 most recent campaign_network_period files
python3 lib/datapull.py aggregate --grain account_daily --source campaign_daily  # legacy daily grain

# Compare two ISO calendar weeks (defaults: last complete week vs prior week)
python3 lib/datapull.py compare-weeks [--week N] [--vs M] [--year YYYY] [--grain account|campaign|both]
python3 lib/datapull.py compare-weeks --week 20 --vs 19 --name-contains "Stable"  # with campaign filter
python3 lib/datapull.py compare-weeks --all-metrics  # show full metric table (users, CPM, freq, CTR, CPC, CTI, conv%, CPA)

# Compare two calendar months MTD (default) or full months
python3 lib/datapull.py compare-months [--month N] [--vs M] [--year YYYY] [--full]
python3 lib/datapull.py compare-months --month 5 --vs 4  # May MTD vs Apr MTD
python3 lib/datapull.py compare-months --month 5 --vs 4 --all-metrics  # with full metric table

# Flag LOW-label creatives vs campaign averages (low-action vs low-watch + pattern analysis)
python3 lib/datapull.py slice-creatives [--min-impressions N] [--output FILE]

# Compare a named campaign segment across two periods (network-aggregated, with totals row)
python3 lib/datapull.py slice-campaigns --name-contains "Stable" [--period yesterday_vs_sdlw|wow|mom|mtd]
python3 lib/datapull.py slice-campaigns --name-contains "Stable" --output FILE  # save full CSV
python3 lib/datapull.py slice-campaigns --name-contains "Stable" --all-metrics  # with full metric table

# Bid/budget recommendations — generate, review, apply, evaluate
python3 lib/datapull.py bid-budget-recommend [--dry-run]                     # generate plan from weekly trend
python3 lib/datapull.py bid-budget-recommend --cac-ceiling 150 --change-pct 15  # override profile defaults
python3 lib/datapull.py bid-budget-apply --plan wiki/action-items/bid-budget-YYYY-MM-DD.yaml  # apply plan to Google Ads
python3 lib/datapull.py bid-budget-retrospective --plan wiki/action-items/bid-budget-YYYY-MM-DD.yaml  # evaluate changes

# Resolve a period expression to concrete (from, to) date pairs — use before fetching partial periods
python3 lib/datapull.py resolve-dates --period yesterday-vs-sdlw
python3 lib/datapull.py resolve-dates --period wow
python3 lib/datapull.py resolve-dates --period mtd
python3 lib/datapull.py resolve-dates --period partial-wow          # first 3 days of current week vs prior week (default n=3)
python3 lib/datapull.py resolve-dates --period partial-wow --n 5   # first 5 days

# Validate against manual exports
python3 lib/datapull.py validate-manual --bob FILE --manual FILE [--mapping FILE]

# Check Google Ads YAML config (safe — does not print secrets)
python3 lib/datapull.py check-config [--config PATH]
```

**Pull log** — every live fetch appends one JSON line to `logs/pull-log.jsonl`:
```json
{"timestamp":"...","query":"...","from_date":"...","to_date":"...","account":"...","reason":"...","run_id":"...","output_file":"..."}
```
The `reason` field records why the pull was made. Dry-run fetches do **not** write to the log.

**Dry run** (renders and saves query without executing):
```bash
python3 lib/datapull.py fetch --query account_network_period --from 2026-05-13 --to 2026-05-19 --dry-run
python3 lib/datapull.py bootstrap --dry-run
```

**Thin bash wrappers** in `bin/` mirror the subcommands (e.g., `bin/bob-fetch`, `bin/bob-fetch-bootstrap`).

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

3. **Aggregate layer** (`lib/datapull.py: aggregate`) — Reads raw CSVs, groups/sums base metrics, derives ratio metrics. Output goes to `data/processed/{subdir}/`.

4. **Validation layer** (`lib/datapull.py: validate-manual`) — Tolerance-based diff of Bob aggregates vs user-provided manual exports.

5. **Agent skill layer** (`.agents/skills/bob-google-ads/`) — Intent routing and per-intent reference docs. Each reference file specifies the exact CLI commands to run, significance thresholds that trigger auto-escalation, and the wiki artefact structure to write on user acceptance. Not executable code.

### Key files

- `lib/datapull.py` — All Python logic: period date resolution, GARF command building, metric calculations, CSV handling, aggregate grains, subcommand dispatch.
- `garf/queries/` — 12 SQL query templates. Period-aggregate queries (new): `account_network_period`, `campaign_network_period`, `adgroup_network_period`, `creative_period`. Legacy daily queries (on-demand only): `campaign_daily`, `network_daily`, `creative_asset_daily`, `campaign_reach_daily`.
- `.bob/accounts.json` — Flat registry of all registered accounts. The `active` flag is the source of truth for which account is loaded. Per-account config lives in `.bob/accounts/{customer_id_no_hyphens}/profile.json`.
- `.bob/metrics-reference-{campaign_type}.json` — Metric catalog for a specific campaign type (e.g. `metrics-reference-app.json`). Contains primary goal rationale, full acquisition funnel, formula for every metric, and the `do_not_select` policy for pre-computed API averages. Load the file matching the active account's `campaign_type`.
- `SOUL.md` — Bob's personality: voice, tone, analysis style, and response patterns. Read at the start of every conversation. Kept separate so it can evolve independently of the data layer.
- `.agents/skills/bob-google-ads/SKILL.md` — Agent routing rules and operating constraints for performance analysis.
- `.agents/skills/bob-google-ads/references/` — 6 reference files, one per intent. Each contains: required inputs, working CLI commands, significance thresholds + auto-escalation rules, and a wiki artefact template.
- `.agents/skills/bob-bid-budget/SKILL.md` — Bid/budget skill: algorithm, mutation plan, apply, and retrospective routing.
- `.agents/skills/bob-bid-budget/references/` — 3 reference files: `algorithm.md` (4-scenario decision matrix), `mutation-plan.md` (review + apply workflow), `retrospective.md` (W+1/W+2 evaluation).
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
- **Processed outputs**: `data/processed/{subdir}/{customer_id}_{start}_{end}.csv`
  - `account-network/`, `campaign-network/`, `adgroup-network/`, `creative/`, `campaign-trend/`, `account/`
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
- Pre-computed API averages (`metrics.ctr`, `metrics.average_cpc`) are **not** selected in period-aggregate queries — they'd be averages of averages. Recalculate from raw sums instead.

**Default output** (compact): goal metric + cost + Δ% per row.  
**`--all-metrics` flag**: adds a transposed metric table (metrics as rows, periods as columns) before the per-row table. Available on `compare-weeks`, `compare-months`, `slice-campaigns`. Use when the user says "complete set of metrics" or "all metrics".

See `.bob/metrics-reference-{campaign_type}.json` for the full metric catalog with formulas, funnel ordering, and significance thresholds — read it for business context without needing to parse Python source.

### Bid/budget trend logic (`campaign_weekly_trend` grain)

The `campaign_weekly_trend` aggregate uses actual ISO week numbers as column prefixes (e.g. `w20_cost`, `w19_cost`, `w18_cost`) rather than generic `w0_`/`w1_`/`w2_`. The file also includes `current_iso_week`, `prior1_iso_week`, `prior2_iso_week` integer columns.

`signal_strength` / `trend_direction` describe the CPI trajectory across the 3 weeks:

| signal_strength | trend_direction | Meaning |
|---|---|---|
| `confirmed` | improving | W0 and W1 both show CPI improvement — act |
| `confirmed` | deteriorating | W0 and W1 both show CPI worsening — act |
| `early` | either | W0 signals a direction but W1 doesn't support it yet — observe |
| `blip` | deteriorating | W0 is worse but W1 was already improving — likely noise, do not act |
| `stable` | stable | No meaningful change — hold |

**`bid-budget-recommend`** applies the 4-scenario algorithm (CPI × CPM vs prior 2-week average). Guards: `cac_ceiling` (default 200, uses actual W0 CPA; falls back to `target_cpa` bid when no conversions), min 10 installs in W0, declining post-install conv% blocks increases, `bid_budget_cooldown_days` (default 14) skips recently-changed campaigns. Magnitude: `bid_budget_change_pct` (default 10%, capped at 20%). Each YAML entry includes `last_bid_budget_change_date`, `days_since_last_change`, `cooldown_ok`. See `.agents/skills/bob-bid-budget/references/algorithm.md`.

**`bid-budget-apply`** writes Target CPA and budget changes to Google Ads via the `google-ads` Python library. Requires `pip install google-ads pyyaml`. **Never call without explicit user approval.**

**`bid-budget-retrospective`** evaluates W+1/W+2 CPI vs the pre-change baseline. Verdicts: `working`, `too_early`, `not_working`.

### External dependency: GARF

```bash
pip install garf-executors garf-google-ads
```

Requires a `google-ads.yaml` config file. Path is set in `.bob/profile.json` as `google_ads_config_path`.

### Agent Intent → Reference File Map

| User question | Reference file |
|---|---|
| What happened yesterday / yesterday vs SDLW | `account-yesterday-vs-sdlw.md` |
| WoW / MoM / MTD performance | `account-period-comparison.md` |
| What caused the change (network → campaign → ad group) | `delta-diagnosis.md` |
| What to do with bids and budgets | `bob-bid-budget` skill — see `.agents/skills/bob-bid-budget/` |
| Which creatives are underperforming | `creative-underperformance.md` |
| Review / replace LOW text asset copy | `bob-creative-copy` skill |
| What did the team work on / change history | `change-history-summary.md` |
| Compare a named campaign group ("Stable campaigns", "Brand campaigns") | `campaign-segment-comparison.md` |
| Compare two ISO weeks or calendar months ("W20 vs W19", "May MTD vs April") | `calendar-period-comparison.md` |

**Auto-escalation rule** (in yesterday and period comparison references): if primary goal changes >10%, cost >15%, or any ratio >1 pp, the agent automatically proceeds to delta diagnosis without waiting for the user to ask.

**Wiki save offer — mandatory**: After delivering any analysis or recommendation, Bob must immediately ask: "Want me to save this to the wiki?" This applies to every skill and every intent. Do not wait for the user to request it.

**Wiki artefact pattern**: every reference specifies a wiki file to offer writing after user confirmation. Analyses go to `wiki/{customer_id_no_hyphens}/analyses/`, action items to `wiki/{customer_id_no_hyphens}/action-items/`. Each file has a frontmatter block (`date`, `intent`, `period`) and a `← [Wiki Index](../Index.md)` backlink on the first line after frontmatter. `{customer_id_no_hyphens}` is derived from the active account's `google_ads_customer_id` with hyphens stripped.

**Wiki save rules** — enforced every time an analysis or action item is written:
1. **Use conversation output only.** Copy numbers and tables from what's already on screen. Do NOT re-run CLI commands, do NOT run `--output`, do NOT read any CSV, do NOT use pandas. **Never truncate wiki content** — write every row of every table. No "… and N more" or "top 10 shown". Truncation in the chat is fine; truncation in the wiki file is not.
2. **Update `wiki/{customer_id_no_hyphens}/Index.md`.** Add one line under `## Analyses` or `## Action Items`. Create the file if it doesn't exist (heading: `# Bob — Wiki Index`, sections: `## Analyses`, `## Action Items`).
3. **Backlink.** Every wiki file starts with `← [Wiki Index](../Index.md)` after frontmatter.

`wiki/{customer_id_no_hyphens}/Index.md` is the per-account navigation hub — every wiki file links back to it, and it links to every wiki file.

**Wiki cache check**: Before running any analysis or recommendation, read `wiki/{customer_id_no_hyphens}/Index.md`. If a recent entry for the same intent is within the cache window (creative/bid-budget = 7 days; all other intents = 1 day), surface the link and ask the user if they want a fresh run. For fresh runs, prepend one line of prior context from the Index one-liner only — never open the full wiki file.

**UAT requirement for new features**: Every new write-path feature (mutation, apply, or any command that changes external state) must have at least one live end-to-end test confirming a successful change before the feature is considered complete. Document the UAT result — asset ID, field type, before/after text, timestamp — in `wiki/action-items/` or as a note in the relevant wiki entry.

### creative_period: performance_label

The `creative_period.sql` query returns `performance_label` directly from the Google Ads API (`BEST`, `GOOD`, `LOW`, `LEARNING`). This is the primary signal in `creative-underperformance.md`. For blank labels, report raw metrics and set action to `observe` — do not compute benchmarks.

## Failsafe — Unanswerable Questions

Every Bob answer must come from a CLI tool listed in this file or a reference file in `.agents/skills/bob-google-ads/references/`. If no tool can produce the required data, the agent must **not** guess, fabricate, or write ad-hoc scripts.

**Never write scratch scripts, helper programs, or ad-hoc code files to analyze data.** Work only from columns already present in processed CSV outputs. If a required computation (e.g. medians, cross-file joins) has no CLI subcommand that produces it, use the failsafe response instead.

**Required response when a question is unanswerable:** Respond in Bob's voice following `SOUL.md` — honest, direct, Australian. Tell the user this isn't something you can do yet and to check back in a few days. One or two sentences, no corporate hedging.

Then append to `logs/backlog.md` under `## Bug Reports` or `## Feature Requests`:
```markdown
### [BUG or FEATURE] YYYY-MM-DD — <short title>
**User said:** "<exact user input>"
**What happened:** <what Bob did or couldn't do>
**What's needed:** <fix or feature description>
```
Full rules are in `.agents/skills/bob-google-ads/SKILL.md` → Failsafe section.

## Current Build Status (from PLAN.md)

**Complete**: skeleton, profile/config, all GARF period-aggregate queries, fetch/bootstrap/aggregate/validate/check-config commands, all aggregate grains including `mtd` period and `campaign_weekly_trend`, metric definitions (13 metrics including CPI), SOUL.md personality, all 6 `bob-google-ads` intent reference files, `bob-bid-budget` skill with `bid-budget-recommend` / `bid-budget-apply` / `bid-budget-retrospective` commands, ISO week column labeling in campaign-trend, `--all-metrics` flag on compare and slice commands.

**Planned**: Google Ads mutations write-back testing with live account, wiki save flow implementation, pytest harness, `bob-slice-*` bin wrappers.
