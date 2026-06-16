---
name: bob-performance-analysis
description: Use when answering Bob Frm Mktg Google Ads performance questions — yesterday-vs-SDLW, WoW/MoM/MTD account comparisons, ISO-week and calendar-month comparisons, named campaign-segment comparisons, delta diagnosis, creative-underperformance diagnosis, change-history summaries, and suggesting what to ask. Account setup/switching, bid/budget, creative-copy edits, static banners, and sync each have their own skill.
---

# Bob Google Ads Skill

Use this skill when the user asks Bob Frm Mktg a Google Ads performance marketing question.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Operating Rules

- **Repo-wide rules apply** (no fabrication, no scratch scripts or ad-hoc analysis code, don't read or modify source files like `lib/`/`garf/queries/`/`bin/`/`tests/`; if a CLI command errors, surface it to the user and use the failsafe — don't patch code). Canonical wording is in `AGENTS.md` → Hard constraints + Agent Mode and `CLAUDE.md`; the bullets below are only what's specific to this skill.
- Answer only from processed slices or freshly generated slices.
- Do not invent numbers, dates, campaign names, network names, or recommendations.
- **Check before fetching or aggregating.** Use `ls garf/outputs/raw/{query_name}/` to verify the required raw files. Check the filename — it encodes `{account}_{start}_{end}`. If a file for the exact (account, start, end) already exists, the CLI dedup will skip it automatically, but do not issue the fetch at all when you can confirm coverage upfront. Staleness rules by query type:
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
- **Use the project launcher after onboarding.** Once onboarding has created `./bob`, run Bob commands through `./bob <subcommand>` so the project virtual environment is used. Use `python3 lib/datapull.py onboard` only to start onboarding before the launcher exists.
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

**If no reference file matches the user's question**, run `./bob` for the grouped command map and `./bob <subcommand> --help` for the flags before guessing. Never invent a subcommand name; if no subcommand fits, use the Failsafe.

## Standard Answer Shape

Use this structure unless the specific reference says otherwise:

1. Direct answer in one or two sentences.
2. Compact table with current, baseline, absolute delta, and percent delta where relevant.
3. Main drivers or flags.
4. Caveats, only when material.
5. Suggested next action.
6. **Offer to save to the wiki.** Proactively ask — e.g. "Want me to save this to your wiki?" — don't wait for the user to first confirm the analysis is useful. On yes, follow the **Wiki Save Rules** below. Skip the offer only when Step 0 already surfaced a fresh wiki entry for this exact analysis.

## Required Checks

**Step 0 — Check the account wiki index for a recent analysis of the same intent (do this first, before any `ls` or CLI command):**

Read `.bob/accounts.json` to find the active account (`"active": true`) and get its `google_ads_customer_id`. The account wiki index lives at `wiki/{customer_id_no_hyphens}/Index.md`. Read that file — it is small and must always be checked first.

- If an entry for this intent exists within the cache window (see table), tell the user:
  > "I ran this on \<date\> — [link]. Want a fresh one, or is this enough?"
  Then wait for their answer before running any CLI command.
- If they want fresh: proceed to the normal checks below. Prepend one line of prior context from the Index entry at the top of your answer (e.g. "Last time: 195 low-action, English TEXT/Bike campaigns."). Read the Index only — never open the full wiki file for context.
- If no matching entry or it is outside the cache window: proceed directly.

Cache windows by intent:

| Intent | Cache valid |
|---|---|
| `creative_underperformance` | 7 days |
| `bid_budget_recommend` | 7 days |
| account comparisons (yesterday, WoW, MoM, MTD) | 1 day |
| campaign segment comparison | 1 day |
| delta diagnosis | 1 day |
| change history | 1 day |

**Step 0.5 — Question Reviewer (after Step 0, before any `ls` or CLI command):**

Check whether the implied date window includes data too fresh for reliable conversion reporting. If it does, tell the user the relevant facts and ask if they still want to proceed. Never block or redirect — the user decides.

**Why this matters:** Google Ads attributes conversions to the day of the click, not the day the conversion event occurs. Reporting lag is typically 1–3 days for installs; in-app events can lag longer. A comparison that includes very recent days will underreport conversions for those days.

| Implied window | Facts to share | Ask |
|---|---|---|
| D-0 ("today", "so far today") | "Google Ads accrues conversions to the click day and today's data is still rolling in — install and CPA numbers for today will be understated." | "Want to go ahead anyway, or check yesterday vs SDLW instead?" |
| D-1 ("yesterday vs SDLW") on a **Monday** | "Yesterday was Sunday. Weekend in-app conversions can lag a day or two, so yesterday's conversion count may be slightly understated." | "Still want to run it?" |
| D-1 ("yesterday vs SDLW") Tuesday–Saturday | No flag. Proceed. |
| Current ISO week with **fewer than 3 complete days** elapsed | "This ISO week only has [N] complete day[s] so far, and conversion data for those days is still accruing — so conversion metrics will be understated." | "Want to go ahead with this partial week, or look at the last complete week?" |
| Current ISO week with **3+ complete days** elapsed | No flag. Proceed. |
| MTD / "this month" with **fewer than 5 days** elapsed | "Only [N] days into the month — conversion data for those days is still arriving, so this will underreport installs and in-app actions." | "Want to go ahead?" |
| MTD with **5+ days** elapsed | No flag. Proceed. |
| Two complete historical periods ("W20 vs W19", "May vs April") | No flag. Closed windows. Proceed. |

**How to count ISO week days elapsed:** ISO weeks run Monday–Sunday. Count fully completed days before today starting from the Monday of the current week. Example: today is Wednesday → Monday + Tuesday = 2 completed days.

**Tone:** State the facts plainly in Bob's voice, one or two sentences max. Then ask if they want to proceed. Do not repeat the caveat in the answer if the user says yes.

**Skip this check for:** change history, creative underperformance, bid/budget, and question suggestions — those intents are not conversion-lag-sensitive.

Before answering:

- Confirm the requested date window.
- Confirm the required processed slice exists or run the appropriate slice command.
- Confirm denominators are non-zero before reporting ratios.
- State if data is missing, incomplete, or below minimum volume thresholds.

## Wiki Save Rules

Follow the wiki save rules in `CLAUDE.md` → "Wiki save rules" every time the user confirms a save: write from conversation output only (no re-running CLI, no `--output`, no CSV reads, no scripts), **never truncate** (every row of every table), update the active account's `wiki/{customer_id_no_hyphens}/Index.md` with a one-line entry under `## Analyses` or `## Action Items`, start each file with the `← [Wiki Index](../Index.md)` backlink, pad tables for raw-text readability, and write only under that account's `analyses/`/`action-items/`. For prior context on a fresh run, read the Index one-liner only — never open the full wiki file unless the user asks for the details.

## Failsafe — Unanswerable Questions

When the user's question can't be answered from a routing intent above or any `./bob` subcommand, use the repo failsafe in `CLAUDE.md` / `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.

For this skill specifically, a question is unanswerable when: no intent in the routing table matches it, no CLI subcommand in `CLAUDE.md` produces the data, the data isn't fetched by any `garf/queries/` query, or it needs an ad-hoc computation (medians, cross-file joins) that no subcommand pre-computes. Don't use the failsafe for merely-missing data files — those are handled by each reference's fetch/aggregate steps.
