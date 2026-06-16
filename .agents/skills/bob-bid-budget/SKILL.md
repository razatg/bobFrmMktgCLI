---
name: bob-bid-budget
description: Use when answering bid and budget questions for Google Ads app campaigns — generating recommendations, reviewing mutation plans, applying changes, and evaluating whether past changes worked.
---

# Bob Bid/Budget Skill

Use this skill when the user asks what to do with bids or budgets, or wants to review, apply, or evaluate bid/budget changes.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Operating Rules

- **Repo-wide rules apply** (no fabrication, no scratch scripts or ad-hoc analysis code, don't read or modify source files like `lib/`/`garf/queries/`/`bin/`/`tests/`; if a CLI command errors, surface it and use the failsafe — don't patch code). Canonical wording: `AGENTS.md` → Hard constraints + Agent Mode and `CLAUDE.md`.
- Recommendations come only from `bid-budget-recommend` output. Do not invent numbers or signal assessments.
- **Check before fetching or aggregating.** Use `ls` to verify the required raw and processed files already cover the date window. If they do, use them — do not re-fetch or re-aggregate. Only fetch when the date window is not yet covered or the file is stale per the reference's stated staleness window.
- Always show the mutation plan (CSV or YAML summary) before applying. Never call `bid-budget-apply` without explicit user approval ("make it live", "apply it", "go ahead").
- Do not re-apply a plan that has `applied: true` — the tool will error, but surface this clearly to the user first.
- Use `.bob/profile.json` for `cac_ceiling`, `bid_budget_change_pct`, `primary_goal`, and `currency`.
- For retrospective questions, require an applied YAML plan path. If not provided, ask the user which plan to evaluate.
- **Always pass `--reason` when calling `fetch` or `bootstrap`.** This is logged to `logs/pull-log.jsonl`.
- **Write all outputs to `wiki/` only** — analyses to `wiki/analyses/`, mutation plans to `wiki/action-items/`. Never write to agent brain directories, temp paths, or any other location.
- **Do not use `--dry-run` in normal operation.** Run `bid-budget-recommend` directly — it writes the CSV and YAML plan that the user reviews. `--dry-run` is for development only and does not produce the files needed for review or apply.

## Intent Routing

- "What should I do with bids/budgets this week?" → `references/algorithm.md` + run `bid-budget-recommend`
- "Show me the recommendation plan" → `references/mutation-plan.md`
- "Apply the changes / make it live" → `references/mutation-plan.md` → `bid-budget-apply` → **update wiki Index**
- "Are the changes working?" / "How did the bid changes do?" → `references/retrospective.md`

## Standard Answer Shape

1. Direct verdict in one or two sentences (Bob's call).
2. Per-campaign table: action, current vs proposed values, rationale.
3. Holds and skips with reason.
4. Next action (approve to apply, or watch until next week).

## Required Checks — Ordered Prerequisite Chain

Run these steps in order before calling `bid-budget-recommend`. Use `ls` to check for files — do not read source files.

**Pre-flight — run `check-config` before anything else:**
```bash
python3 lib/datapull.py check-config
```
If the output contains `STATUS: FILE NOT FOUND` under the write config block:
1. **Do NOT copy `~/google-ads.yaml` to the write config path.** It does not contain valid OAuth2 credentials for the `google-ads` Python package.
2. Run the credential setup in the background:
   ```bash
   PYTHONUNBUFFERED=1 python3 lib/datapull.py setup-write-credentials
   ```
   Use `run_in_background=True` on this Bash call.
3. Use the **Monitor** tool to stream its output. When a line beginning with `OAUTH_URL: ` appears, extract the URL (everything after `OAUTH_URL: `) and show it to the user as a clickable markdown link:
   > **Click to authorize Google Ads write access:** [Open authorization URL](`<extracted_url>`)
4. Continue monitoring. The process will complete automatically once the user clicks the link and authorizes in their browser (Google redirects to `http://127.0.0.1:8080`, the local server catches it, and the file is saved).
5. Re-run `check-config` to confirm all write config fields are SET, then proceed with `bid-budget-apply`.

**Do NOT ask the user to run anything manually.** The agent handles the full flow.

**Step 0 — Check `wiki/Index.md` for a recent bid/budget plan (do this first, before any `ls` or CLI command):**

Read `wiki/Index.md`. It is small and must always be checked first.

- If an entry under `## Action Items` for `bid_budget_recommend` exists within 7 days, tell the user:
  > "I generated a plan on \<date\> — [link]. Want a fresh one this week, or is that still current?"
  Then wait for their answer before running any CLI command.
- If they want fresh: proceed to Step 1 below. Prepend one line of prior context from the Index entry at the top of your answer (e.g. "Last week: 8 increases, 4 holds — W21 plan."). Read the Index only — never open the full YAML for context.
- If no matching entry or it is older than 7 days: proceed directly to Step 1.

**Step 1 — Check for 3 weeks of campaign_network_period raw files:**
```bash
ls garf/outputs/raw/campaign_network_period/
```
Need at least 3 files with different week start dates. If missing, fetch the missing weeks:
```bash
python3 lib/datapull.py fetch --query campaign_network_period --from DATE --to DATE --reason "bid/budget prereq: campaign_network_period W{N}"
python3 lib/datapull.py aggregate --grain campaign_network_period
```

**Step 2 — Build the campaign_weekly_trend processed file:**
```bash
ls data/processed/campaign-trend/
python3 lib/datapull.py aggregate --grain campaign_weekly_trend
```

**Step 3 — Check for bid_budget_inputs raw file (must be ≤7 days old):**
```bash
ls garf/outputs/raw/bid_budget_inputs/
```
If missing or stale:
```bash
python3 lib/datapull.py fetch --query bid_budget_inputs --from DATE --to DATE --reason "bid/budget prereq: current bids and budgets"
```

**Step 4 — Run the recommendation:**
```bash
python3 lib/datapull.py bid-budget-recommend [--dry-run]
```

If `bid-budget-recommend` errors with "no processed file found", it means Step 1 or Step 2 is incomplete — re-run them. Do not read source files to diagnose; just check `ls` outputs and re-run the missing step.

## Post-Apply Wiki Update

After `bid-budget-apply` completes (whether fully applied or partially applied), immediately update `wiki/Index.md` **without asking**:

- Find the existing line for this plan under `## Action Items`
- Append the apply result inline, e.g.:
  ```
  - [Bid/Budget Plan — 2026-05-20](action-items/bid-budget-2026-05-20.yaml) — W21 recommendations — applied 2026-05-21: 69 CPA + 55 budget changes, 0 errors
  ```
- If there were errors, note the count: `applied 2026-05-21: partial (3 errors)`

This prevents duplicate apply runs and gives future sessions the outcome at a glance from the Index alone.

## Wiki Save Rules

Follow the wiki save rules in `CLAUDE.md` → "Wiki save rules" whenever the user confirms a save: write from conversation output only (no re-running CLI, no CSV reads, no scripts), **never truncate** (every row of every table), update `Index.md` with a one-line entry under `## Analyses`/`## Action Items`, start each file with the `← [Wiki Index](../Index.md)` backlink (for a `.yaml` plan, add a `# See: wiki/Index.md` comment instead), pad tables for raw-text readability, and write only under `analyses/`/`action-items/`. For prior context on a fresh run, read the Index one-liner only — never open the full YAML.

## Failsafe — Unanswerable Questions

When the question can't be answered from the references below or any `./bob` subcommand, use the repo failsafe in `CLAUDE.md` / `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.
