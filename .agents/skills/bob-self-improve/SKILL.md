---
name: bob-self-improve
description: Use when the user asks Bob to learn from past sessions, review recurring mistakes, run a self-improvement or retro pass, or improve its own skills. Clusters logged friction signals into a proposal-only action plan; never applies changes itself.
---

# Bob Self-Improvement Skill

Use this skill when the user asks Bob to learn from its own mistakes — "review your recent
stumbles", "what keeps tripping you up", "run a self-improvement pass", "how can you get better".

This is the **synthesis** half of the self-improvement loop. The **capture** half is agent-agnostic:
the CLI auto-logs hard signals, the agent batches soft friction into one `./bob session-debrief` at
a success beat (and uses `./bob log-signal` for immediate criticals like `failsafe`) — see the
"Signal logging" section in `AGENTS.md`. Each signal carries a `source` field (`cli` | `inline` |
`debrief`). This skill reads those signals and proposes fixes.

## Personality

Read `SOUL.md` before answering. The verdict line at the top of the plan sounds like Bob wrote it;
the body is a structured, scannable proposal.

## Operating constraints — proposal only

- **This skill never applies changes.** It reads logs and writes a single proposal file. It must
  NOT edit `lib/`, `bin/`, `AGENTS.md`, `CLAUDE.md`, `.agents/skills/**`, query templates, or any
  source — **even in developer mode**. The output is a plan a human reads and applies.
- **Reads only the distilled signal.** Read `logs/session-signals.jsonl` and `logs/backlog.md`.
  Do NOT read session transcripts or any agent-runtime files — there is nothing agent-specific to
  parse, and the signal log is already the distilled record.
- **No scratch scripts, no fabrication.** Cluster and rank by reading the JSONL lines directly. Do
  not write Python/pandas to crunch them. Every pitfall must trace to real logged signals.
- Allowed writes: `wiki/_self-improve/` only. This works in analysis mode (no developer key needed)
  because the loop produces a proposal, not a change.

## Procedure

1. **Prep.** Run `./bob self-improve`. It prints signal counts by event type and severity and the
   exact files to read. Say one Bob-voice line to the user — don't narrate the mechanics.
2. **Read** `logs/session-signals.jsonl` and `logs/backlog.md` in full. If the signal log is empty
   or missing, the prep command says so — stop and tell the user plainly; write no plan.
3. **Cluster** signals by root cause. Collapse many signals describing the same underlying problem
   into one pitfall (e.g. several `tool_error`/`user_correction` signals about "compare-weeks
   couldn't find a freshly-fetched closed-week slice" are one pitfall, not five). Use
   `user_correction` and `friction` signals as soft evidence — apply judgment about whether each
   was a genuine Bob mistake or a benign follow-up.
4. **Rank** clusters by frequency × severity. Severity order: `blocked` > `wrong` > `friction` >
   `cosmetic`. A pitfall that blocked an answer twice outranks a cosmetic one logged ten times.
5. **Trace** each pitfall to the responsible artifact and name it precisely:
   - a routing/wording gap → a specific `references/*.md` or `SKILL.md` rule, or the `AGENTS.md` contract;
   - genuine CLI logic/behaviour → say "needs developer + maintainer" and point at `logs/backlog.md`
     as the channel (do not propose a code diff inline — you can't verify it).
6. **Write the action plan** to `wiki/_self-improve/action-plan-YYYY-MM-DD.md`. Proposal only.
   See the template below. Never truncate — list every ranked pitfall and all its evidence.
7. **Update** `wiki/_self-improve/Index.md` (create it if missing) with a one-line entry.
8. **Tell the user** the plan path and that **nothing was changed** — each item needs their approval
   before anyone applies it.

## Action plan template

```markdown
---
date: YYYY-MM-DD
intent: self-improve
signals_reviewed: <N>
---
← [Self-Improve Index](Index.md)

# Self-Improvement Plan — YYYY-MM-DD

<one Bob-voice verdict line: the single biggest thing tripping me up lately>

## Ranked pitfalls

### 1. <short title>  ·  severity: <blocked|wrong|friction|cosmetic>  ·  <N> signals
- **Evidence:** <signal counts + 1–2 sample notes, with dates>
- **Root cause:** <why it keeps happening>
- **Target artifact:** <exact file/rule, or "CLI logic — needs developer + maintainer">
- **Proposed change:** <concrete edit to propose — wording, routing rule, or backlog entry>
- [ ] Approved to apply

### 2. …
```

## Failsafe

If `./bob self-improve` reports no signals, say so in Bob's voice — honest, one line — and stop.
Don't manufacture pitfalls or write an empty plan.
