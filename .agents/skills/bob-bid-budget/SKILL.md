---
name: bob-bid-budget
description: Use when answering bid and budget questions for Google Ads app campaigns — generating recommendations, reviewing mutation plans, applying changes, and evaluating whether past changes worked.
---

# Bob Bid/Budget Skill

Use this skill when the user asks what to do with bids or budgets, or wants to review, apply, or evaluate bid/budget changes.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Investigation contract

Before presenting a proposal, verify its saved values against current account evidence and goals. Explain the trade-offs, risk, prediction and review window. Run the existing bid-budget validation command, inspect its findings and correct/recheck recoverable failures. Read the saved final plan before displaying it; show warnings about departures. Do not execute a change as part of verification or interpret a tool result as approval.

Start with `./bob brief --focus bids` (or `all` when explanations cross domains). The gateway's selected account is authoritative. Rules and evidence maturity come from the brief; unavailable evidence is not an empty finding. Use `./bob search` for relevant knowledge and history.

Recipes and saved Goals are baselines, not exclusive routes or marketing vetoes. Goals are included automatically in the brief; the user need not mention them. Acquisition cost references, usual change size and preferred wait periods guide judgement. Depart with executed evidence, a trade-off/risk explanation, expected outcome and review window. Set rationale and forecast on each departing proposal and record the decision. Account scope, explicit exclusions, valid values, permissions and exact-proposal approval remain enforced. Use current CLI help over legacy examples.

Record consequential recommendations, immutable evidence and a prediction with `./bob decision record` before execution; put its `decision_id` on the plan. Bid changes require `bid-budget-validate` before approval and `--approval-hash` at apply, which rechecks live state. Review the recorded prediction with `./bob decision review` after the observation window and conversion maturity. Do not infer outcomes from action names.

## Saving a final departure

Use `./bob bid-budget-propose --plan <baseline> --changes-json '<final actions>' --output <account plan>` to save a different final choice without editing protected mutation files. This does not approve or apply it. Record the prediction, then `./bob decision link <id> --plan <final plan>`, then validate and request approval of the resulting exact hash.

## Operating Rules

- Follow the universal contract in `AGENTS.md`. Use registered commands and operations for ordinary analysis; source edits require separate development authorization. Inspect structured failures and supported alternatives before using the failsafe.
- The recommender supplies a numerical baseline; departures require executed evidence. Never invent numbers or signal assessments.
- The bid/budget weekly trend includes only campaigns marked `ENABLED` in the current W0 pull;
  that active-campaign set is applied to all three weeks. Current `bid_budget_inputs` are also
  restricted to enabled campaigns. Shared campaign-performance pulls remain status-unfiltered.
- Treat selected-account KT exclusions as authoritative scope for the current request. They are not
  a setup blocker and must never trigger a generic failsafe or be replaced by old backlog context.
- **Check before fetching.** Use `./bob data-manifest` for the selected account and each exact date window. Do not inspect raw directories to infer coverage. If the raw windows are complete but the processed trend is wrong or stale, rebuild it without refetching.
- Give the customer a concise mutation summary before applying. Never call `bid-budget-apply` without explicit user approval ("make it live", "apply it", "go ahead").
- Do not re-apply a plan that has `applied: true` — the tool will error, but surface this clearly to the user first.
- Read Goals and account settings from the selected-account brief. Legacy CAC/change/cooldown fields are derived compatibility aliases; Goals is authoritative. The conservative recommender remains a reference; use a final proposal when judgement supports a departure.
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

## Required evidence and approval

The brief prepares available evidence and reports gaps. If the full baseline is needed, use current `bid-budget-recommend --help` and its exact-window prerequisites; use `data-manifest` before fetching. Do not run write-credential setup as a prerequisite for read-only investigation. Hosted authorization is managed by the gateway.

Save the final choice with the registered proposal command, record and link its prediction, then validate before approval. The apply command re-reads live state and requires the exact approved hash. A baseline hold does not prevent further investigation.

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

Ask before saving an ordinary analysis. Reuse executed evidence and the existing artifact; keep complete, padded tables with numeric columns right-aligned. Write under the selected account's analyses/action-items, add the Wiki Index backlink and an index entry. Use search for prior context; do not load the whole wiki or re-read private mutation files unnecessarily.

## Failsafe — Unanswerable Questions

When the question can't be answered from the references below or any `./bob` subcommand, use the repo failsafe in `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.
