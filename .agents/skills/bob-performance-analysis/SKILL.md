---
name: bob-performance-analysis
description: Use when answering Bob Frm Mktg Google Ads performance questions — yesterday-vs-SDLW, WoW/MoM/MTD account comparisons, ISO-week and calendar-month comparisons, named campaign-segment comparisons, delta diagnosis, creative-underperformance diagnosis, change-history summaries, and suggesting what to ask. Account setup/switching, bid/budget, creative-copy edits, static replacement generation, and sync each have their own skill.
---

# Bob Google Ads Skill

Use this skill when the user asks Bob Frm Mktg a Google Ads performance marketing question.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Investigation contract

Before presenting analysis, check the selected account, exact dates, evidence coverage and conversion maturity. Use calculated outputs to verify totals and ratios; compare the main explanation with plausible alternatives. If a tool fails, resolve the specific issue and rerun the relevant check. Explain missing evidence or unresolved uncertainty; a successful tool call alone does not establish the interpretation.

Start with `./bob brief --focus performance` (or `all` when explanations cross domains). The gateway's selected account is authoritative. Rules and evidence maturity come from the brief; unavailable evidence is not an empty finding. Use `./bob search` for relevant knowledge and history.

Recipes and fixed policies are baselines, not exclusive routes. Registered analysis operations may be used during ordinary investigations. Agree, hold or depart with evidence. Hard limits and explicit approval apply to everyone; no decision modes. Use current CLI help over legacy command examples.

Record consequential recommendations, immutable evidence and a prediction with `./bob decision record` before execution; put its `decision_id` on the plan. Bid changes require `bid-budget-validate` before approval and `--approval-hash` at apply, which rechecks live state. Review the recorded prediction with `./bob decision review` after the observation window and conversion maturity. Do not infer outcomes from action names.

## Operating Rules

- Follow the universal contract in `AGENTS.md`. Use registered commands and operations for ordinary analysis; source edits require separate development authorization. Inspect structured failures and supported alternatives before using the failsafe.
- Answer only from processed slices or freshly generated slices.
- Do not invent numbers, dates, campaign names, network names, or recommendations.
- **Check before fetching or aggregating.** Use `./bob data-manifest` for the selected account, query and exact window to verify coverage. Check the filename — it encodes `{account}_{start}_{end}`. If a file for the exact (account, start, end) already exists, the CLI dedup will skip it automatically, but do not issue the fetch at all when you can confirm coverage upfront. Staleness rules by query type:
  - `change_history`, `bid_budget_inputs`: valid for **3 days** from the file's end_date. If the most recent file's end_date is within 3 days of what you need AND covers at least 14 days back, use it — do not fetch.
  - `creative_period`: valid for **7 days** from the file's end_date. If a recent file covers an overlapping 30-day window, use it.
  - `account_network_period`, `campaign_network_period`: use if exact date match exists; otherwise fetch.
- Use the active account profile (via `load_profile()` — reads from `.bob/accounts/{id}/profile.json` via `.bob/accounts.json`) for primary goal and account context. To get `customer_id_no_hyphens` for wiki paths, read the active account from `.bob/accounts.json`.
- Treat CTR, CTI, and conversion rate as numeric percentages. A value of `3.2` means `3.2%`.
- Use CTI as `installs / clicks * 100`.
- Use the selected primary goal for `goal_conversions`.
- For bid and budget changes, create proposed mutation plans first. Do not push to Google Ads without explicit user approval.
- Ask before saving any analysis or action item to `wiki/`.
- **Always pass `--reason` and `--question` when calling `fetch` or `bootstrap`.** Both are logged to `logs/pull-log.jsonl`. `--reason` is your short description of why the pull was needed; `--question` is the user's exact words. Examples:
  - `--reason "user asked what happened yesterday vs SDLW" --question "what happened yesterday"`
  - `--reason "delta diagnosis: W20 vs W19 campaign files missing" --question "why did CPA go up last week"`
  - `--reason "daily bootstrap for account review" --question "bootstrap"`
- **Granular pull limit:** campaign, ad-group, network-daily, and creative-level queries are limited to seven inclusive calendar days per Google Ads pull. If a larger range is requested, `fetch` runs sequential seven-day chunks automatically (a 30–31 day range is normally five pulls). Every chunk is deduplicated and logged; aggregation must use the complete `--from`/`--to` range so all chunks are combined before metrics are calculated. Account-level period queries are not chunked.
- **Use the project launcher after onboarding.** Once onboarding has created `./bob`, run Bob commands through `./bob <subcommand>` so the project virtual environment is used. Use `./bob onboard` only to start onboarding before the launcher exists.
- **Log wiki cache hits.** When the wiki cache check finds a valid recent analysis and you return it without fetching, record this: `./bob log-pull --query {relevant_query} --reason "wiki cache hit — {intent} analysis from {date} still valid" --question "{user's exact question}" --outcome skipped_wiki`. This keeps the pull log as a complete question-to-outcome trail.

## Intent Routing

**Account setup / onboarding / switching / config → use the `bob-accounts` skill.** Anything about getting an account ready ("set me up", "add an account", "switch account", "list accounts", "check config", "fix setup") belongs there, not here. Route it and stop.

**Multiple accounts:** Whenever context is ambiguous (e.g. user asks "what happened yesterday" with 2+ accounts registered), always clarify by account name first: "Which account — {name1} or {name2}?" Never assume silently.

Load the matching reference file for performance questions:

- Yesterday vs same day last week at account level: `references/account-yesterday-vs-sdlw.md`
- WoW, MoM, or MTD account performance: `references/account-period-comparison.md`
- What caused performance to improve or deteriorate: `references/delta-diagnosis.md`
- What to do with bids and budgets: use the `bob-bid-budget` skill instead
- Underperforming creatives (diagnosis only): `references/creative-underperformance.md`
- Reviewing or replacing LOW text asset copy: use the `bob-creative-copy` skill
- Team work/change history: `references/change-history-summary.md`
- Compare a named group of campaigns (e.g. "all Stable campaigns", "Brand campaigns yesterday"): `references/campaign-segment-comparison.md`
- Compare two ISO weeks or two calendar months (e.g. "W20 vs W19", "May MTD vs April"): `references/calendar-period-comparison.md`
- Suggest questions, what can I ask, what should I ask, what can you do, show me examples: `references/question-suggestions.md`

If a question matches more than one intent, answer in this order: account summary, driver diagnosis, recommendation, action item.

**If no reference file matches the user's question**, run `./bob` for the grouped command map and
`./bob <subcommand> --help` for the flags before guessing. Never invent a subcommand name. If no
subcommand fits and the request is a novel read-only analysis, route to the `bob-wings-it` skill;
otherwise use the Failsafe.

## Standard Answer Shape

Use this structure unless the specific reference says otherwise:

1. Direct answer in one or two sentences.
2. Compact table with current, baseline, absolute delta, and percent delta where relevant.
3. Main drivers or flags.
4. Caveats, only when material.
5. Suggested next action.
6. **Offer to save to the wiki.** Proactively ask — e.g. "Want me to save this to your wiki?" — don't wait for the user to first confirm the analysis is useful. On yes, follow the **Wiki Save Rules** below. Skip the offer only when Step 0 already surfaced a fresh wiki entry for this exact analysis.

## Required checks

Use the brief for current settings, KT rules, data status and evidence. Drill down using registered commands or operations as needed. Respect conversion maturity and avoid unnecessary confirmation for routine technical choices. Ask only when a material business assumption is missing. Do not load the whole wiki or treat a cached answer as a blocker to investigation.

## Wiki Save Rules

Ask before saving an ordinary analysis. Reuse executed evidence and the existing artifact; keep complete, padded tables with numeric columns right-aligned. Write under the selected account's analyses/action-items, add the Wiki Index backlink and an index entry. Use search for prior context; do not load the whole wiki or re-read private mutation files unnecessarily.

## Failsafe — Unanswerable Questions

When the user's question can't be answered from a routing intent above or any `./bob` subcommand, use the repo failsafe in `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.

For this skill specifically, a question is unanswerable when: no intent in the routing table
matches it, no CLI subcommand produces the data, and `bob-wings-it` lacks the required registered
dataset, dimension, or typed operation. Don't use the failsafe for merely-missing registered data
files — the normal reference flow or `bob-wings-it` prepares those through the existing fetch and
aggregate path.
