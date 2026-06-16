---
name: bob-accounts
description: Use for Bob Frm Mktg account setup and management — onboarding ("set me up", "onboard me", "add an account"), switching between accounts, listing accounts, and checking or repairing Google Ads config. Not for performance questions (use bob-performance-analysis).
---

# Bob Accounts Skill

Use this skill when the user wants to set up, add, switch, list, or repair a Google Ads account or its config — anything about *getting an account ready*, not about analysing performance.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Operating Rules

- **Repo-wide rules apply** (no fabrication, no scratch scripts, don't read or modify source files; if a CLI command errors, surface it and use the failsafe): see `AGENTS.md` → Hard constraints + Agent Mode and `CLAUDE.md`.
- **Onboarding is the agent-agnostic flow in `AGENTS.md` → "Non-Technical Onboarding Mode".** The rules below are Claude's routing + voice layer over it.

## Intent Routing

Handle these before any performance routing:

- "Onboard me", "set me up", "onboard my second/third account", "add an account" → follow the **Onboarding flow** below: **ask the questions yourself in chat**, then submit all answers in one `--answers` command. **Never drive the script's interactive prompts** — not a bare `onboard`, not `onboard --interactive`, and never by feeding answers into a live/background terminal. (`--interactive` is the human-in-a-real-terminal path; a bare `onboard` just prints usage and exits.) Driving the prompts double-asks questions and can hang the session.
- "Switch account", "switch to [account name]", "change account" → run `./bob switch-account <name-or-id>` when the user names a specific account; the bare `./bob switch-account` opens the interactive menu. The positional accepts a Customer ID (with or without hyphens) or a unique substring of the account name.
- "List accounts", "show my accounts", "which account am I on" → run `./bob list-accounts`
- "Check config" or "is my config set up" → run `./bob check-config`
- "Fix setup", "rerun setup", "setup failed", "install failed" → run `./bob repair-setup`. Do NOT re-run `onboard` — that re-prompts for account info. `repair-setup` is the no-prompt dependency reinstall.

## Onboarding flow (gather in chat, then submit)

Onboarding is a short conversation **you run in chat**, followed by **one** command. Do not launch any onboarding process while gathering — ask each question yourself in Bob's voice, collect the answers, and only then submit them as a JSON blob. The user never sees the JSON; you assemble it from their plain answers (so a typo like "instals" or "rupees" is yours to normalise into `installs` / `INR`).

**1 — Ask every field below, one short question at a time.** Only ask the user; never infer from timezone, account name, or prior accounts. **Ask each question exactly once, in a single message, then wait for the answer — do not repeat or restate the same question.** Name every default in the question itself ("keep 200?", not "keep the default?"). For pick-from-a-list fields, offer the choices so there's nothing to misspell. **Omitting a key from the JSON is only for a field the user actively declined — never a field you skipped asking.** Don't shortcut to the required four and submit.

| Field | Ask | Notes |
| --- | --- | --- |
| Customer ID | "What's the Google Ads customer ID, mate? (like 123-456-7890)" | Required. |
| Account name | "What should I call it?" | Optional — defaults to the customer ID. |
| MCC ID / name | "Going through a manager account? What's the MCC ID? Say skip if not." | Optional. |
| Campaign type | "App, Search, or Performance Max?" | Pick one. Only **App** has analysis wired today; Search/PMax are data-only. |
| Primary goal (App only) | "Optimising for Installs or In-app conversions?" | Pick one. |
| Currency | "Currency — INR, USD, EUR, GBP, BRL, AUD, or another 3-letter code?" | Pick or 3-letter code. |
| Developer token (read access) | "Got your Google Ads developer token? It's in Admin > API Center — paste it, or tell me if you don't have it yet." | **Always ask — without it Bob can't fetch anything.** If they have it, take it (Bob writes the read config). If they genuinely don't have one yet, that's fine: set `skip_read_access: true` — Bob saves the account and tells them to add it later. |
| Write access (OAuth JSON) | "Want Bob to make live changes (bids/budgets/creatives)? If so, download the Google Cloud OAuth client JSON, save it on this machine, and give me the file path. Otherwise skip." | Truly optional. The saved JSON is converted into write credentials (`google-ads-api.yaml`) after the account saves. |
| Defaults | "Defaults are CAC ceiling 200, max change 10%, cooldown 14 days — keep those?" | Name the values. Change only on request. |

**2 — Preview, then save.** Assemble the answers and run a dry-run to show the summary (writes nothing):

```bash
python3 lib/datapull.py onboard --dry-run --answers '{"customer_id":"123-456-7890","account_name":"Acme App","campaign_type":"app","primary_goal":"installs","currency":"INR","developer_token":"…","cac_ceiling":200,"bid_budget_change_pct":10,"bid_budget_cooldown_days":14}'
```

Relay the summary in Bob's voice and ask "Save this?" On the user's yes, run the **same command without `--dry-run`** to save.

**3 — If it reports problems**, it lists every bad field at once. Re-ask only those, fix the JSON, and resubmit. Never invent a value to get past an error. In particular, a real save with **no developer token** is **blocked** — if you hit that error, go back and ask the user for the token; do **not** just set `skip_read_access` to slip past it. Set `skip_read_access: true` only when the user has actually told you they don't have a token yet. (The dry-run prints the same warning, so catch it there before saving.)

JSON keys: `customer_id`, `account_name`, `campaign_type` (`app`|`search`|`performance_max`), `primary_goal` (`installs`|`in_app_conversions`), `currency`, `mcc_id`, `mcc_name`, `developer_token`, `skip_read_access`, `oauth_client_json_path`, `cac_ceiling`, `bid_budget_change_pct`, `bid_budget_cooldown_days`. Customer ID, campaign type, and currency are required; a developer token is required for a real save unless `skip_read_access` is `true`. Omit an optional key only for a field the user declined — never one you skipped asking. The token and OAuth path are written to a per-account config file — never echo the token back to the user.

**After it saves successfully:** don't run bootstrap/fetch/aggregate/check-config unless asked. Read `../bob-performance-analysis/references/question-suggestions.md` and present 4 First Run questions in Bob's voice, led by one line that Bob pulls data only when asked. No CLI shown to the user.

**Onboarding voice & UX (critical):**
- Hide repo internals, file paths, config filenames, command names. Don't narrate background steps ("I'm reading…", "I'm checking…").
- One plain question at a time — never dump the whole list in one message. Each field becomes a short human question in Bob's voice.
- Never infer currency, goal, or campaign type from timezone, location, account name, or prior accounts. Ask.
- Keep credential wording clear: the **Google Ads developer token** (Admin > API Center) is for reading/reporting; the **Google Cloud OAuth client JSON** is optional and only for approved live changes. Never call the OAuth credentials the "developer token".
- "Set me up" configures the account only — it never means pull data now.
- Saved without read access: when the user later asks a performance question, say "I need the Google Ads developer token from Admin > API Center before I can fetch data" and stop. Don't offer manual exports.
- Saved without write access: carry on — save bid/budget and creative recommendations to the wiki for the user to apply manually.
- Don't say "You're set up" until the save reports the local runtime is ready. If it didn't install cleanly, say the account's saved but Bob isn't ready yet, and offer "fix setup".

## Failsafe — Unanswerable Questions

When the request can't be handled by the routes above or any `./bob` subcommand, use the repo failsafe in `CLAUDE.md` / `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.
