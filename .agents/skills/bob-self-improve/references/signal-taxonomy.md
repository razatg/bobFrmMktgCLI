# Signal Taxonomy

Reference for the `bob-self-improve` skill. Defines each signal `event_type`, how to weight it,
and how to cluster consistently from one pass to the next. Signals are produced by `./bob
log-signal` (see the "Signal logging" section in `AGENTS.md`) and stored one-per-line in
`logs/session-signals.jsonl`.

## Record shape

```json
{
  "timestamp": "2026-06-03T18:40:11",
  "event_type": "user_correction",
  "note": "routed 'this week vs last' to compare-weeks but user meant closed ISO weeks",
  "user_text": "I meant iso week 21 vs 20",
  "intent": "compare-weeks",
  "artifact": ".agents/skills/bob-google-ads/references/calendar-period-comparison.md",
  "severity": "wrong",
  "account": "3546923408"
}
```

Only `timestamp`, `event_type`, and `note` are always present. Other fields are best-effort and may
be absent — never treat a missing field as meaningful.

## Event types

`source` shows where a signal comes from: **CLI** = self-instrumented by `datapull.py` (fires
automatically, no agent cooperation — reliable); **agent/human** = flagged from the conversation,
which the CLI can't see (less complete — absence is not proof it didn't happen).

| event_type | source | meaning | typical root cause to look for |
|---|---|---|---|
| `tool_error` | CLI | a `./bob` subcommand failed (auto-logged with command + exit detail) | brittle command, stale file lookup, bad date window, credential/env issue |
| `redundant_fetch` | CLI | a `fetch` hit a window already on disk | the "check before fetching" rule wasn't followed — a SKILL/AGENTS reinforcement gap |
| `failsafe` | agent | a question was genuinely unanswerable | missing CLI capability — usually a FEATURE, cross-check `logs/backlog.md` |
| `retry` | agent | the same command was re-run after a worked-around failure | unclear error message, or a flow that needs two steps the skill didn't sequence |
| `user_correction` | agent/human | user corrected a wrong route/answer mid-conversation | routing rule too loose, or a reference doc that mis-describes a command |
| `plan_rejection` | agent/human | user rejected a proposed plan/action | wrong default, wrong scope, or misread intent |
| `friction` | agent/human | user had to repeat themselves / long way round | catch-all; read the note to find the real cause |

Because soft (agent/human) signals are undercounted by nature, weight a *confirmed* soft signal
heavily — if the user bothered to flag a correction, it's real. Don't dismiss a pitfall just
because it has few soft signals.

`event_type` is free-form — agents may log types outside this list. Treat unknown types as
`friction` and lean on the `note`.

## Severity weighting (for ranking)

Rank clusters by **frequency × severity**. Severity order:

1. `blocked` — Bob could not produce the answer at all.
2. `wrong` — Bob produced an answer/route that was incorrect.
3. `friction` — Bob got there but made the user work for it.
4. `cosmetic` — formatting/wording nit.

A `blocked` pitfall seen twice outranks a `cosmetic` one seen ten times. When `severity` is absent,
infer from `event_type` (failsafe→blocked, user_correction→wrong, retry/redundant_fetch→friction).

## Clustering guidance

- Group by **root cause**, not by wording. Many notes describing the same underlying gap are one
  pitfall.
- Prefer the `artifact` field to anchor a cluster when present; otherwise group by `intent`, then
  by the shape of the `note`.
- Cross-reference `logs/backlog.md`: a pitfall already captured there as a BUG/FEATURE should cite
  that entry rather than duplicating it.
- De-duplicate across passes by date — when re-running, focus on signals newer than the last plan
  in `wiki/_self-improve/`, but still fold in older unresolved pitfalls.
