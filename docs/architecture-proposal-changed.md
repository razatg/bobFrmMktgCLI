# Bob: architecture proposal

Author: Rajat · Date: 2026-11-18
Delivery plan: `rebuild-plan-changed.md`

Status: final agreed refactor proposal, updated 2026-11-19. This describes the target, not completed implementation. The delivery plan tracks implementation and verification.

**19 November Goals revision:** Marketing thresholds are guidance. Goals consolidates the acquisition cost reference, typical change size and preferred waiting period, carrying over existing values. Bob may depart with evidence, trade-offs, risk, expected outcome and a review window for explicit approval. This supersedes marketing “hard guard” wording in this proposal. Technical validity, account scope, explicit exclusions, permissions and exact-proposal execution approval remain enforced. See the delivery plan and release notes for implemented behavior.

---

## 1. Goal

Make Bob **intelligent** and **durable**, without rebuilding its structure.

- **Intelligent:** Bob investigates across the account, weighs competing explanations, and
  recommends a defensible action, including "wait". It doesn't just explain an answer a fixed
  policy already chose.
- **Durable:** decisions, evidence and predictions survive conversation handoffs, restarts and
  model changes, so they can be recalled and evaluated later.

## 2. Principles

1. **Deterministic where correctness matters:** evidence, metric calculations, date windows,
   allowed actions, limits, approvals and execution.
2. **Discretionary where judgement matters:** which evidence to look at, which explanation fits,
   and whether to act, hold or depart from the baseline policy.
3. **Fixed policies are baselines, not answers.** Bob may agree, hold, or propose another supported
   action. It records the baseline, its final recommendation, and why they differ.
4. **Every recommendation is recorded:** applied, held, rejected or overridden, with a prediction
   that can be reviewed.
5. **Answers are checked, not trusted.** Every answer's numbers and proposed changes are checked
   automatically against the data and the hard limits before the user sees them.
6. **Keep the existing layout.** Extend `lib/bob/`; add only what's missing.
7. **The whole product is in scope.** Video, images, copy, CLI, gateway and instructions follow the same investigation, decision, approval and review contracts. Integrate existing work rather than discarding it. Refactor affected code; do not rewrite working internals solely to touch every file.

## 3. How Bob works

```
 question / scheduled task
          │
          ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ CONTEXT   AGENTS.md (invariants + how to find skills) · SOUL.md · │
 │           skill index (names + "use when")   — nothing else loaded │
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ INVESTIGATE   ./bob brief (one call: goals, data status, perf,    │
 │               bids/budgets, creative, changes, KT rules, prior     │
 │               decisions) → drill down with ./bob search and        │
 │               ./bob commands + registered analysis operations     │
 │               (performance, creative, bid/budget inputs,          │
 │                change history)                                    │
 │               checks: grain, joins, coverage, conversion maturity │
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ JUDGE     baseline policy output (e.g. bid matrix, LOW 2-of-3)    │
 │           + evidence + goals → agree / hold / depart (with reason)│
 │           one behaviour for every account                         │
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ VALIDATE  validate_plan(final plan): hard limits, live values,    │
 │           same validation function for baseline                   │
 │           and Bob-changed plans                                   │
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ RECORD    decision record: goals used, immutable evidence,        │
 │           alternatives, baseline vs final, prediction, human      │
 │           response                                                │
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ ACT       approval bound to plan hash → validate_plan again on    │
 │           live values → apply (partial-safe, no duplicates) →     │
 │           execution linked to the decision                        │
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ REVIEW    on request, after the observation window: supported /   │
 │           contradicted / inconclusive against the recorded        │
 │           prediction                                              │
 └──────────────────────────────────────────────────────────────────┘
```

## 4. Components

| Component | Where | What it does |
|---|---|---|
| Harness | Codex CLI (hosted container) | Agent loop, model calls, sandbox, native sessions |
| Instructions | `AGENTS.md`, `SOUL.md`, `.agents/skills/` | `AGENTS.md` = invariants + how to find skills (short). Skills are **recipes with baselines**: how to investigate and judge, which baseline to start from. No routing protocol, no exclusivity, no "only from command X" rules. One instruction set for everyone |
| Skill finding | Skill index + `./bob skills search` | The harness lists skill names and descriptions (Codex discovers `.agents/skills` natively). A generated `.agents/skills/INDEX.md` serves harnesses without discovery. `./bob skills search "<situation>"` covers skills and reference recipes once there are too many to list |
| Knowledge search | `./bob search` | Search over wiki analyses, action items, KT and decision records instead of loading wiki files into context. Returns snippets with path, kind and date |
| Situation brief | `./bob brief` | One call that returns everything a typical investigation needs (see §4.2) |
| Evidence and math | `lib/bob/platform`, `lib/bob/performance` | Metrics, dates, fetch, aggregation, manifests: exact and tested |
| Flexible analysis | `lib/bob/performance/adhoc.py`, `adhoc_data.py` | Registered datasets + bounded operations (group, join, derive, filter, rank, select), usable in normal investigations. Today: account / campaign / ad group performance, campaign reach, primary conversions, creative period. **Add:** `bid_budget_inputs` (it already carries status, primary status reasons, bidding strategy, budget, target CPA) and `change_history`, plus a derived budget-utilisation metric |
| Analysis checks | `lib/bob/performance` | Metric compatibility, join cardinality, rollups (reach never summed), coverage, conversion maturity and freshness carried with each result. **New in code:** today maturity is a prompt table in the performance skill, and it's skipped for creative and bid/budget |
| Baseline policies | `lib/bob/bid_budget`, `lib/bob/performance/creatives.py` | **Bids/budgets:** CPI × CPM scenarios plus guards (min 10 installs, CAC ceiling, cooldown, budget-constrained at ≥ 90% utilisation, CPM tolerance, post-install conv% decline, change % capped at 20). **Creatives:** LOW + min impressions + 2-of-3. The *scenario choice* is what Bob may depart from. The *business guards* (CAC ceiling, cooldown, max step) are always hard limits |
| Goals | Account profile (`lib/bob/platform`) | Today: primary goal, CAC ceiling, change %, cooldown, creative min impressions. **Add:** targets, **priority order** for conflicts, budget envelope, explicit risk constraints and review date. No decision modes |
| Decisions | `lib/bob/decisions/` (new) | Decision records, immutable evidence store, recall, prediction reviews |
| Execution | `lib/bob/bid_budget`, `creative_copy`, `creates_it`, `static_banners` | Plans, approval, apply, partial-failure handling (unchanged formats, additive fields) |
| Write protections | Existing apply paths + `validate_plan` | **Exist:** READ vs READ & WRITE permission, explicit approval, plan-level and per-change applied flags, failed-only retry, Google validate-only pass for creative changes. **New:** one deterministic `validate_plan` per domain, run on the *final* plan before approval and again at apply on live values (see §8.1); approval bound to the plan hash |
| MCP server | `lib/bob/mcp/server.py` | Exposes analysis operations; persists results a decision cites |
| Gateway | `server/` | Users, permissions, conversations, jobs, scheduling, Admin (adds goals) |
| Answer check | `lib/bob/answer_check.py` (new), called by the gateway | Runs on every answer before the user sees it: claims, proposed plans, scope (see §4.3) |
| Claims | Reply + `claims` block | Each answer emits a structured claims block (entity, metric, period, value, source) that the answer check verifies |

### 4.1 How Bob finds skills and knowledge

**Skills:**

- `AGENTS.md` stays short: invariants, then "pick the skill whose *use when* fits; if none clearly does, run `./bob skills search`; recipes give a baseline, not the only answer".
- Each skill's frontmatter carries `description` with *use when / don't use when*. That is what the harness shows.

**Knowledge:**

- **No wiki file is loaded into context.** Bob calls `./bob search "<query>" --account <id> [--kind kt|analysis|action|decision] [--since DATE]` and reads only what it needs.
- **Safety-critical account rules** (KT exclusions, house rules) are not left to search. `./bob brief` always includes them, deterministically.
- **Implementation:** text search first (SQLite FTS5 index under the client state root, refreshed on wiki/KT/decision writes). Embeddings only if real usage shows retrieval misses.

### 4.2 One-call situation brief

```text
./bob brief --account <id> [--focus performance|bids|creative|all]
            [--period yesterday|wow|mom|<from>:<to>] [--campaigns ...] [--json]
```

It composes existing functions. It isn't a new framework: each section is a small function over
code that already exists, with a size cap. Missing data is prepared inside the call (manifest →
fetch → aggregate).

Bound fetching work as well as output size. Load sections relevant to the requested focus and return useful partial results if another section fails. Distinguish unavailable evidence from an empty result. Introduce expanded goals, decision history and due reviews as their delivery steps land; never imply a missing capability has found nothing.

| Section | Contents | Source today |
|---|---|---|
| Goals | Objective, targets, priority order, risk constraints, review date | Account profile |
| Data status | Coverage, freshness, conversion-maturity flags per window | `data-manifest`, date resolution |
| Performance | Account → network → top campaign drivers for the period | `compare` functions |
| Bids / budgets | Per campaign: strategy, target CPA, budget, utilisation, primary status reasons, **baseline recommendation + guard outcomes** | `bid_budget_inputs`, recommender |
| Creative | LOW / low-action / low-watch counts, top patterns, spend share on LOW vs prior window | `creative_*_period`, `creatives.py` |
| Recent changes | Change events for the entities in focus (≈ last 30 days) | `change_history` |
| Account rules | KT exclusions and house rules | `wiki/<id>/KT.md` |
| History | Prior decisions on these entities and reviews due | `decisions` |
| Evidence | Path, extraction time and hash for every section | `decisions/evidence.py` |
| Next looks | Registered datasets and commands useful for drill-down | analysis catalog |

A typical question becomes: **one `brief` call → judgement → (optional) one or two drill-downs →
recommendation**, instead of a recipe of 10+ commands.

### 4.3 Automatic answer check

Plain code (no model) that runs after Bob writes an answer and before the user sees it.

**What it checks:**

1. **Numbers.** Each answer carries a hidden `claims` list. Every number Bob states has an entry: entity, metric, period, value, source file.
   - Direct values must match the source.
   - Derived values (CPI, % change, ratios) are recomputed from the source with the shared metric functions, within rounding tolerance.
   - A number in the answer that isn't in the list counts as **unchecked**. An incomplete list can't pass.
2. **Proposed changes.** Any bid, budget or creative plan runs through `validate_plan` (hard limits, live values; §8.1).
3. **Scope.** The answer is about the selected account and respects KT exclusions.

**On failure:**

| Failure | Result |
|---|---|
| Wrong or unchecked number | Answer flagged in Admin; user sees a short "this figure couldn't be verified" note |
| Plan breaks a limit | Proposal-bearing reply withheld with a reason; revised proposal must be reviewed before approval |
| Wrong account | Answer held back; job marked failed |

**Cost:** milliseconds per answer, no model calls. It reuses the metric functions, processed
files and guards that already exist.

**Before a release:** run a short list of standard questions (one per main question type) on
staging. The answers must pass the check, and the team skims them.

MVP interpretation: numerical-literal coverage and structured claim context are checked; this is not semantic verification of arbitrary prose or judgement. Proposed financial values cite the validated plan, separately from observed metrics. Live plan checks involve API reads and have a time budget; they are not guaranteed to finish in milliseconds. See the delivery checklist for verified implementation and remaining staging acceptance.

## 5. What exists vs what's new (checked against the repo)

| Capability | Status | Where / note |
|---|---|---|
| Period performance at account / campaign / ad group / network grain | **Exists** | GARF period queries, `aggregate`, `compare-*`, `slice-campaigns` |
| Asset performance label (BEST / GOOD / LOW), asset text | **Exists** | `creative_*_period` queries (server-filtered by min impressions) |
| LOW + 2-of-3 flagging, pattern summary | **Exists** | `performance/creatives.py` (`slice-creatives`) |
| Copy plan, batch generation, partial-safe apply | **Exists** | `creative_copy/suggest.py`, `apply.py`; char limits checked in code |
| Copy rules beyond length (punctuation, proper nouns, no GOOD/BEST duplicates) | **Prompt only** | `copy-rules.md`; move into validators |
| Static image and video generation, review, apply | **Exists** | `creates_it`, `static_banners`. The video workflow has uncommitted work in progress (`creates_it/video.py`, `video_media.py`, `cli.py`, the creates-it skill, `AGENTS.md`) to be integrated, not discarded |
| Bid/budget scenarios, guards, plan, apply, failed-only retry | **Exists** | `bid_budget/__init__.py` |
| Bid/budget retrospective | **Exists, verdicts unreliable** | Direction checks contradict the recorded forecast; CPI is taken from a single campaign/network row; the first window can include pre-action days. Delegates to `decisions/review.py` or its verdicts are disabled |
| Budget utilisation, post-install conv% trend | **Exists inside the recommender only** | Not reachable by investigation; expose via `bid_budget_inputs` + derived metric |
| Campaign status / primary status reasons / bidding strategy / budget / tCPA | **Exists in raw `bid_budget_inputs`** | Not registered for analysis |
| Change history (incl. asset adds and edits) | **Exists** | `change_history` query (Google keeps roughly the last 30 days); not registered for analysis |
| Flexible analysis engine | **Exists** | `adhoc.py`; results held in process memory |
| Conversion-lag caution | **Prompt only** | Performance skill table; skipped for creative and bid/budget |
| Account KT, thread handoff continuity | **Exists** | `wiki/<id>/KT.md`, `conversation_handoff` |
| Weekly scheduled tasks | **Exists** | `scheduled_tasks` (day of week + local time) |
| Daily asset metrics | **Query exists, no processed grain** | `creative_asset_daily.sql` (legacy, on demand) |
| **Creative age** (days since an asset first served) | **Does not exist** | No creation or first-served date in any query; change history only covers ~30 days |
| **Creative fatigue** (an asset's CTR/CTI decaying over time) | **Does not exist** | No asset-level trend grain; frequency only at campaign level |
| Goals beyond primary goal / CAC / change % | **New** | Account profile |
| Decision records, durable evidence, recall | **New** | `lib/bob/decisions/` |
| Business limits on the bid/budget path | **Exists only inside the recommender** | CAC ceiling, cooldown, min installs and change cap are checked while generating; `bid-budget-apply` doesn't re-check them on the plan it applies |
| `validate_plan` on the final plan, before approval and at apply | **New** | `bid_budget/guards.py`, `creative_copy/rules.py` |
| Approval bound to plan hash | **New** | Apply paths |
| Immutable evidence store (copy on cite) | **New** | `decisions/evidence.py`. Raw pulls are already per-run files (`…_{run_id}.csv`); processed files are overwritten on re-aggregation |
| Automatic answer check (claims, plans, scope) | **New** | `lib/bob/answer_check.py`, called by the gateway on every answer |
| Prediction review (supported / contradicted / inconclusive) | **New** | `decisions/review.py` |

## 6. Creative age and fatigue (new capability, built only if real questions need it)

Creative age and fatigue aren't in Bob today. If real questions show they matter, add them as
deterministic evidence, not as a prompt instruction:

1. **First-seen date per asset (age).**
   - A one-off backfill uses `ad_group_ad_asset_view` segmented by **month** over the past year: the first month with impressions approximates an asset's start. That's a few cheap queries, not hundreds of 7-day pulls.
   - After that, keep a small per-account `asset_first_seen` table up to date from regular creative pulls.
   - `change_history` gives exact add dates for assets created in roughly the last 30 days.
2. **Asset trend (fatigue).** A weekly asset grain, the same shape as `campaign_weekly_trend`, built from `creative_asset_daily` or weekly-segmented pulls. It gives CTR, CTI and CPC per asset over the last 3–4 weeks, plus a trend direction.
3. **Register both** in the analysis engine so investigations can join age and trend to performance.
4. **Note the limit:** there's no asset-level frequency on Google App campaigns. Fatigue is inferred from the metric trend and age, not from exposure.

## 7. Decision records

Every recommendation gets one, including holds and recommendations the user rejects or overrides.

| Field | Contents |
|---|---|
| Identity | `decision_id`, account, entities, created_at, model, release (Git SHA) and skill versions |
| Situation | Question or trigger; goals and priorities used |
| Evidence | Immutable copies of the cited inputs and outputs (content-addressed), the operation spec that produced them (aggregation grain or analysis steps) and the code version; reporting windows; conversion maturity |
| Reasoning | Hypotheses, alternatives considered, material uncertainty |
| Baseline vs final | Baseline policy output, final recommendation, why they differ |
| Prediction | Metric(s), expected direction or range, observation window, review date, review criteria |
| Review | Verdict (supported / contradicted / inconclusive), observed values, windows used, notes on confounders. Empty until reviewed |
| Human | Approval, rejection or override; who; when |
| Execution | Link to the existing plan's apply results and partial failures (the plan stays authoritative for execution state) |


**Evidence is immutable, but kept lean:**

- **Copy on cite.** When a decision cites a processed file or an analysis result, it's copied into a content-addressed store (`evidence/<sha256>`). Period aggregates are small, and analysis results are capped at 10K rows.
- **Raw pulls** are per-run files already. Any a decision cites are pinned against pruning.
- **The operation spec and code version** are stored with each item, so the evidence can be re-derived as well as re-read.
- **Only what consequential decisions cite is kept.** Fetched datasets aren't archived wholesale.

**Reviews** are requested manually (`./bob decision review <id>`), after the observation window
and once conversions have matured:

- The review compares the recorded prediction against observed values at the correct grain (e.g. cost and installs summed across networks before CPI), over windows counted from execution.
- It returns **supported**, **contradicted** or **inconclusive**. It describes whether observations support the prediction; it doesn't claim causation.
- `./bob brief` lists reviews that are due.

The existing bid/budget retrospective must delegate to the corrected review semantics or have its misleading verdicts disabled until migrated. There must not be two active review paths that contradict one another.

**When things are written:** intent is written before execution, and actual results are linked
afterwards. Existing YAML plans carry the `decision_id` as an additive field.

**Recall:** `./bob brief` includes prior decisions and reviews due for the entities in focus;
`./bob search --kind decision` finds anything older or broader. Both use account / entity / date
filters plus text search.

**Memory rules:**

- Observations stay account-scoped.
- Records keep provenance, dates and applicability.
- Counter-evidence and superseded versions are retrieved alongside.

## 8. One decision behaviour

Every account uses the same behaviour: Bob investigates, uses the baseline as a reference and
may depart with cited evidence. Departures are visible in the approval summary and decision record.
There is no strict/advisory switch or staged account behaviour.

Business guards (CAC ceiling, cooldown, max step, permissions, approval) are always hard limits.
Account goals and explicit constraints can differ; the reasoning and execution contract does not.

### 8.1 Validating the final plan

The limits apply to the **final plan**, whether the baseline produced it or Bob changed it, so they
can't live only inside the baseline generator.

- **Guards become pure functions** (`bid_budget/guards.py`, `creative_copy/rules.py`), used both by the baseline generator and by one `validate_plan(plan, profile, live_state)` per domain.
- **What `validate_plan` checks:**
  - every entity belongs to the account and is enabled;
  - every action type is supported;
  - each step is within the cap relative to the **current live value**;
  - cooldown, counting Bob's own recent applies;
  - CAC ceiling;
  - minimum data;
  - an account-level daily change cap.
  - For creative copy plans: copy validators, and the asset is still enabled and unchanged.
  - For image and video publishing plans: the existing spec checks (dimensions, file size, source identity), and the target asset and ad still exist and match the plan.
- **When it runs:**
  - on the proposed plan before approval, so the approval card shows the verdict per action;
  - again at apply, against freshly read live values.

  Approval is bound to the plan's hash, so what was validated is exactly what's applied. Hand-edited plans go through the same check.
- **Use `CODE_GATE.md` as soft engineering guidance for the MVP.** Meaningful tests must exercise safety invariants and failure paths; do not build a measurement framework just to hit coverage or mutation targets.


## 9. Example: "Which text ads need changes based on performance?"

1. **Context.** Invariants and the skill index. Bob picks the creative recipe by its description.
2. **One call.** `./bob brief --focus creative` returns:
   - goals;
   - data status;
   - headline/description performance for the creative lookback (prepared inside the call);
   - the LOW summary and baseline lists;
   - recent changes;
   - KT house rules;
   - prior creative decisions for these ad groups.
3. **Baseline** (included in the brief). LOW label + ≥ minimum impressions + 2 of 3 (CTR < 90%, CTI < 90%, CPC > 110% of the same-type campaign average) gives the low-action and low-watch lists.
4. **Investigate.** Using registered operations, Bob:
   - joins with change history to spot assets added or edited in roughly the last 30 days (the window Google keeps);
   - checks installs against the goal, not just CTR;
   - looks for patterns by ad group or theme.

   Asset age and trend are only available if the §6 capability is built.
5. **Judge.** Each asset is marked **replace / pause / watch / leave**, with the evidence cited and any departure from the baseline explained.
6. **Record.** A decision record captures the baseline vs final lists, reasons, holds, and a prediction (e.g. "replacement CTR at or above campaign average within 21 days").
7. **Replacement copy.** Drafts are written by today's batch generation under the copy rules. Code checks character limits today; punctuation, proper-noun and no-duplicate rules move from prompt into validators.
8. **Act.** `validate_plan` runs on the final plan and its verdicts appear in the approval table. On explicit approval (bound to the plan hash), `validate_plan` runs again on live values, confirming each old asset is still enabled and unchanged. Then apply runs partial-safe as today, and execution results are linked to the decision.
9. **Review.** After the observation window, a manual review checks the prediction and records supported / contradicted / inconclusive.

## 10. Example: "Performance deteriorated; what should we do?"

1. **Context.** Invariants and the skill index. Bob picks the performance/bids recipe.
2. **One call, then drill down.** `./bob brief --focus all --period wow` returns goals, data status, account → network → campaign drivers, the bids/budgets section (with the baseline), the creative section, recent changes, KT rules and prior decisions. Drill-downs then use registered operations to join performance with `bid_budget_inputs` and change history:
   - bidding strategy, target CPA, budget, utilisation;
   - primary status reasons (e.g. learning or limited);
   - what changed in roughly the last 30 days.

   Results carry conversion maturity.
3. **Baseline.** The recommender gives its scenario and guard outcome per campaign.
4. **Judge.** Bob weighs competing explanations:
   - bid;
   - budget cap;
   - a recent edit or learning;
   - a shift of spend toward LOW-labelled assets (from two creative-period windows);
   - immature conversions;
   - seasonality noted in KT.

   It agrees with the baseline, holds, or proposes another supported action, tied to the account's priority order and within the hard guards. "Wait" is a valid answer. Creative age and fatigue join this list only if §6 is built.
5. **Validate, record and act.** As in §9, using the bid/budget plan: `validate_plan` checks the final plan (including any campaign or step size Bob changed from the baseline) before approval and again at apply.

## 11. A second platform (Meta)

- **Native semantics stay explicit.** Attribution settings, where budgets live (campaign or ad set), creative reporting, learning behaviour.
- **Shared reasoning, platform-specific baselines.** Diagnosis principles carry over; baselines and playbooks are platform-tagged. Google's LOW-label baseline doesn't exist on Meta.
- **Cross-platform answers** show each platform with its attribution. Blended totals come only from a neutral source (an MMP).
- **The adapter seam is designed when Meta is actually implemented,** not before.

## 12. Practices adopted from other agent products

| Practice | From | In Bob |
|---|---|---|
| Skill index in context, full skill on demand | OpenClaw, Hermes | Skill index; no exclusive routing |
| Goals the agent keeps working toward | Meta Muse | Account goals with priorities and review date |
| Decisions and context survive handoff and compaction | OpenClaw, Hermes | Decision records + recall |
| Full-text search before embeddings | Hermes | Filters + text search for recall |
| Approval before sensitive actions, shown as a card or table | Grok Bot, Meta Muse | Approval on every write |
| Plan for stale memory, stale permissions, changed state, duplicate triggers | Grok Bot | Live-state check before apply (new); duplicate prevention (exists); dated, provenance-tagged memory |
| Patch knowledge instead of rewriting it; promote only after review | Hermes | Reviewed promotion of account observations (future) |

## 13. Future directions (only when a demonstrated need appears)

- MCP-only interface for multiple harnesses or thin clients.
- A separate reviewer model for proposed actions.
- Role profiles or multi-agent group work.
- Monitors that proactively raise situations.
- Embedding-based retrieval.
- Per-client workers and cross-channel continuity.
- Automatic review scheduling, lesson drafting from reviews, and reviewed promotion of lessons into shared guidance.
- Saved failure cases replayed before releases, and later a model grader comparing releases (when the team wants regression protection beyond the automatic check).

## 14. Risks

| Risk | Mitigation |
|---|---|
| Structural work replaces judgement work | Each step is shown on real questions in staging, with before/after answers read by the team |
| Plausible but invalid analysis | Compatibility, cardinality, coverage and maturity checks on results |
| Inconsistent recommendations | Baseline, rationale and versions recorded; evaluate defensibility and enforce hard limits for every account |
| Decisions can't be reconstructed | Immutable content-addressed evidence with operation spec and code version |
| Bob's changes bypass limits | `validate_plan` on the final plan, before approval and at apply; approval bound to plan hash |
| Wrong numbers or unsafe plans reach users | Automatic answer check on every answer |
| Memory stale, self-reinforcing or leaking | Provenance, dates, counter-evidence, supersession; account scope |
| Conflicting or stale goals | Priority order and review date; goals recorded per decision |

## 15. How the repo changes

Legend: **A** = added · **M** = modified · *reuse* = retain working internals, changing integration where required. No subsystem is exempt from the agreed contracts. Step numbers refer to `rebuild-plan-changed.md`.

### 15.1 Code and instructions

```text
bobFrmMktgCLI/
├── AGENTS.md                                   M  rewritten short: invariants + how to find skills; routing
│                                                  protocol, exclusivity and "only from X" rules removed      [1]
├── SOUL.md                                        reuse
├── .agents/skills/                             M  edited in place (one instruction set)                      [1]
│   ├── INDEX.md                                A  generated from frontmatter (for harnesses without discovery)
│   ├── bob-performance-analysis/                  recipe with baselines; brief-first; fix stale commands/paths
│   │                                              in references/creative-underperformance.md
│   ├── bob-bid-budget/                            baseline (scenarios) + discretion within hard guards
│   ├── bob-creative-copy/                         baseline (LOW 2-of-3) + discretion; validators named
│   ├── bob-wings-it/                              becomes "drill-down with registered operations", not a
│   │                                              last-resort fallback
│   └── bob-accounts/, bob-sync/, bob-scheduling/, bob-self-improve/, bob-creates-it/   frontmatter only
├── lib/bob/
│   ├── answer_check.py                         A  claims, plans (validate_plan), scope; runs on every answer [0]
│   ├── brief.py                                A  ./bob brief: composes existing functions, size-capped   [2]
│   ├── search.py                               A  ./bob search + ./bob skills search (SQLite FTS5)        [3]
│   ├── platform/core.py                        M  profile: goals, targets, priority order, budget envelope,
│   │                                              explicit risk constraints and review date               [4]
│   ├── performance/
│   │   ├── adhoc.py                            M  register bid_budget_inputs, change_history; budget_utilisation [2]
│   │   ├── adhoc_data.py                       M  preparation for the new datasets                        [2]
│   │   ├── aggregate.py                        M  processed grains for bid_budget_inputs and change_history [2]
│   │   ├── checks.py                           A  compatibility, join cardinality, coverage, maturity      [2]
│   │   ├── asset_trend.py                      A  (Step 2b only) asset first-seen + weekly asset trend
│   │   └── creatives.py, fetch.py, compare.py, manifest.py   reuse (brief calls them)
│   ├── bid_budget/
│   │   ├── guards.py                           A  pure guard functions + validate_plan (final plan, live
│   │   │                                          values, all accounts)                                   [1]
│   │   └── __init__.py                         M  recommender uses guards.py; retrospective delegates to
│   │                                              decisions/review.py (or verdicts disabled); plan carries baseline + final +
│   │                                              decision_id; apply re-runs validate_plan; approval hash  [1][5]
│   ├── creative_copy/
│   │   ├── rules.py                            A  validators: length (moved), punctuation, proper nouns,
│   │   │                                          no GOOD/BEST duplicates                                 [2]
│   │   ├── suggest.py                          M  decision_id on the plan                                 [5]
│   │   └── apply.py                            M  re-runs validate_plan on live values; uses rules.py   [1][2]
│   ├── decisions/                              A  records.py · evidence.py (content-addressed, copy on cite)
│   │                                              · review.py (supported / contradicted / inconclusive)   [5][6]
│   ├── mcp/server.py                           M  persist results a decision cites                        [5]
│   ├── cli.py                                  M  brief, search, skills search,
│   │                                              decision record | link | review                    [2][3][5][6]
│   ├── creates_it/, static_banners/             M  integrate image/video plans (incl. the in-progress video
│   │                                              workflow), CLI and recipes with shared
│   │                                              decision/evidence/approval contracts; retain provider work
│   ├── accounts/, sync/, self_improve/, snapshot.py   reuse; update integration where required
│   └── platform/dates.py, metrics.py, google_ads.py   reuse
├── garf/queries/
│   ├── creative_asset_monthly.sql              A  (Step 2b only)
│   └── (existing 20 queries)                      reuse
├── server/
│   ├── app.py                                  M  run the answer check before showing a reply; flag in Admin;
│   │                                              Admin endpoints and authoritative persistence for goals;
│   │                                              no wiki/KT reading instructions in the prompt
│   │                                              (brief + search replace them)                        [3][4]
│   ├── agent_runner.py                         M  MCP allowlist includes analysis tools                     [1]
│   ├── static/app.js                           M  Admin: goals                                              [4]
│   ├── models.py / schema.sql                  M  authoritative goal persistence and compatible migration;
│   │                                              runtime account materialisation preserves goal fields
│   └── scheduling.py, schedule_tools.py           reuse
├── tests/                                      A  test_answer_check.py, test_brief.py, test_search.py, test_decisions.py,
│                                                  test_bid_budget_guards.py, test_validate_plan.py,
│                                                  test_evidence_store.py, test_decision_review.py,
│                                                  test_adhoc_new_datasets.py, test_creative_rules.py
├── .bob/profile.example.json                   M  goal and explicit constraint fields                       [4]
├── docs/                                       M  this doc, the plan, CHANGELOG
└── Dockerfile, docker-compose.yml, bin/, lib/datapull.py   reuse
```

### 15.2 Client state (per client, under `BOB_STATE_ROOT`)

```text
data/processed/<customer_id>/
├── bid-budget-inputs/          A  registered for analysis
├── change-history/             A  registered for analysis
└── asset-trend/, asset-first-seen/   A  Step 2b only
search/<customer_id>.fts.sqlite A  text index over wiki, KT and decision records
decisions/<customer_id>/
├── decisions.sqlite            A  decision records
├── evidence/<sha256>           A  immutable copies of cited inputs and outputs
└── evidence/manifests/<decision_id>.json   A  items cited, operation spec, code version, pinned raw files
wiki/<customer_id>/
├── KT.md                          unchanged (rules surfaced by brief; rest via search)
└── action-items/*.yaml         M  plans gain decision_id + baseline/final fields (additive)
```
