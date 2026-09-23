---
name: bob-bid-budget
description: Use when answering bid and budget questions for Google Ads app campaigns — generating recommendations, reviewing mutation plans, applying changes, and evaluating whether past changes worked.
---

# Bob Bid/Budget Skill

Use this skill when the user asks what to do with bids or budgets, or wants to review, apply, or evaluate bid/budget changes.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Compact execution contract

Resolve the selected account with `./bob data-manifest --query campaign_network_period` before
reading period files. Use `fetch --quiet`, and keep recommendation CSV/YAML output in `--output`
files rather than printing full rows into the agent context. Load the algorithm and mutation
references only when the requested recommendation or apply decision requires them.

If the user says the selected account's KT contains exclusions for this run, read that KT before
the recommendation. Omit the explicitly identified campaigns from every customer-facing
recommendation, hold, skip, and table. Do not infer a city-to-campaign mapping; ask for exact
campaign identity if KT is ambiguous. A KT exclusion is run-specific unless the KT says otherwise.

Show the recommendation and outcome, not the internal command sequence or file paths. Keep operational details private unless the user explicitly asks for deployment, SSH, VM, or debugging instructions. YAML and JSON plans are internal working files: do not link or expose them. If the customer explicitly asks to see or download every planned change, convert the complete existing plan to CSV under the active account's `wiki/.../action-items/`, add that CSV to the Wiki Index, and link the CSV. Do not create a presentation CSV merely because the customer asks to apply an existing plan.

## Operating Rules

- **Repo-wide rules apply** (no fabrication, no scratch scripts or ad-hoc analysis code, don't read or modify source files like `lib/`/`garf/queries/`/`bin/`/`tests/`; if a CLI command errors, surface it and use the failsafe — don't patch code). Canonical wording: `AGENTS.md` → Hard constraints + Agent Mode and `CLAUDE.md`.
- Recommendations come only from `bid-budget-recommend` output. Do not invent numbers or signal assessments.
- Treat selected-account KT exclusions as authoritative scope for the current request. They are not
  a setup blocker and must never trigger a generic failsafe or be replaced by old backlog context.
- **Check before fetching.** Use `./bob data-manifest` for the selected account and each exact date window. Do not inspect raw directories to infer coverage. If the raw windows are complete but the processed trend is wrong or stale, rebuild it without refetching.
- Give the customer a concise mutation summary before applying. Never call `bid-budget-apply` without explicit user approval ("make it live", "apply it", "go ahead").
- Do not re-apply a plan that has `applied: true` — the tool will error, but surface this clearly to the user first.
- Use `.bob/profile.json` for `cac_ceiling`, `bid_budget_change_pct`, `primary_goal`, and `currency`.
- For retrospective questions, require an applied YAML plan path. If not provided, ask the user which plan to evaluate.
- **Always pass `--reason` when calling `fetch` or `bootstrap`.** This is logged to `logs/pull-log.jsonl`.
- **Write all outputs to the active account's wiki only** — first read the active account customer ID from `.bob/accounts.json`, remove dashes, and use `wiki/{customer_id_no_hyphens}/analyses/` and `wiki/{customer_id_no_hyphens}/action-items/`. Never write to the flat `wiki/analyses/` or `wiki/action-items/` directories, agent brain directories, temp paths, or any other location.
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

Run these steps in order before calling `bid-budget-recommend`. Use `data-manifest` to check coverage — do not inspect raw directories or read source files.

**Pre-flight — run `check-config` before anything else:**
```bash
./bob check-config
```
If the output contains `STATUS: FILE NOT FOUND` under the write config block:
1. **Do NOT copy `~/google-ads.yaml` to the write config path.** It does not contain valid OAuth2 credentials for the `google-ads` Python package.
2. Run the credential setup in the background:
   ```bash
   PYTHONUNBUFFERED=1 ./bob setup-write-credentials
   ```
   Use `run_in_background=True` on this Bash call.
3. Use the **Monitor** tool to stream its output. When a line beginning with `OAUTH_URL: ` appears, extract the URL (everything after `OAUTH_URL: `) and show it to the user as a clickable markdown link:
   > **Click to authorize Google Ads write access:** [Open authorization URL](`<extracted_url>`)
4. Continue monitoring. The process will complete automatically once the user clicks the link and authorizes in their browser (Google redirects to `http://127.0.0.1:8080`, the local server catches it, and the file is saved).
5. Re-run `check-config` to confirm all write config fields are SET, then proceed with `bid-budget-apply`.

**Do NOT ask the user to run anything manually.** The agent handles the full flow.

**Step 0 — Check `wiki/{customer_id_no_hyphens}/Index.md` for a recent bid/budget plan before any CLI command:**

Read `wiki/{customer_id_no_hyphens}/Index.md`. It is small and must always be checked first.

- If an entry under `## Action Items` for `bid_budget_recommend` exists within 7 days, tell the user:
  > "I generated a plan on \<date\> — [link]. Want a fresh one this week, or is that still current?"
  Then wait for their answer before running any CLI command.
- If they want fresh: proceed to Step 1 below. Prepend one line of prior context from the Index entry at the top of your answer (e.g. "Last week: 8 increases, 4 holds — W21 plan."). Read the Index only — never open the full YAML for context.
- If no matching entry or it is older than 7 days: proceed directly to Step 1.

**Step 1 — Resolve and check the exact campaign weekly windows:**
```bash
./bob resolve-dates --period bid-budget-weeks
```
W0 is the seven days ending yesterday. W-1 and W-2 are the preceding two contiguous seven-day
windows. For each printed window, check the selected account before fetching:
```bash
./bob data-manifest --account CUSTOMER_ID --query campaign_network_period --from DATE --to DATE
```
If a required exact window is missing, fetch only that window:
```bash
./bob fetch --query campaign_network_period --from DATE --to DATE --reason "bid/budget prereq: campaign_network_period W{N}"
```

**Step 2 — Build the campaign_weekly_trend processed file:**
```bash
./bob aggregate --grain campaign_weekly_trend
```
Keep the exact output path printed by this command. Rebuilding a processed trend does not require
refetching when the manifest already confirms all three raw windows.

**Step 3 — Check bid_budget_inputs for the selected account (must be ≤7 days old):**
```bash
./bob data-manifest --account CUSTOMER_ID --query bid_budget_inputs --from DATE --to DATE
```
If missing or stale:
```bash
./bob fetch --query bid_budget_inputs --from DATE --to DATE --reason "bid/budget prereq: current bids and budgets"
```

**Step 4 — Run the recommendation:**
```bash
./bob bid-budget-recommend --trend <path printed by Step 2>
```

If `bid-budget-recommend` reports that the exact campaign trend is missing, Step 1 or Step 2 is incomplete. Recheck the manifests and rerun only the missing aggregation or fetch.

## Post-Apply Wiki Update

After `bid-budget-apply` completes (whether fully applied or partially applied), immediately update `wiki/{customer_id_no_hyphens}/Index.md` **without asking**:

- Find the existing line for this plan under `## Action Items`. Link its customer-facing CSV when one exists; otherwise keep the entry as plain text rather than linking the internal YAML.
- Append the apply result inline, e.g.:
  ```
  - Bid/Budget Plan — 2026-05-20 — W21 recommendations — applied 2026-05-21: 69 CPA + 55 budget changes, 0 errors
  ```
- If there were errors, note the count: `applied 2026-05-21: partial (3 errors)`

This prevents duplicate apply runs and gives future sessions the outcome at a glance from the Index alone.

## Wiki Save Rules

Follow the wiki save rules in `CLAUDE.md` → "Wiki save rules" whenever the user confirms a save: write from conversation output only (no re-running CLI, no CSV reads, no scripts), **never truncate** (every row of every table), update `wiki/{customer_id_no_hyphens}/Index.md` with a one-line entry under `## Analyses`/`## Action Items`, start each file with the `← [Wiki Index](../Index.md)` backlink (for a `.yaml` plan, add a `# See: Index.md` comment instead), pad tables for raw-text readability, and write only under that account's `analyses/`/`action-items/`. For prior context on a fresh run, read the Index one-liner only — never open the full YAML.

## Failsafe — Unanswerable Questions

When the question can't be answered from the references below or any `./bob` subcommand, use the repo failsafe in `CLAUDE.md` / `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.
