# Bob: delivery plan

Author: Rajat · Date: 2026-11-18
Architecture: `architecture-proposal-changed.md`

**19 November saved-proposal recovery follow-up:**

- [x] Index selected-account YAML/YML proposals and filenames in `bob search`, alongside existing Markdown and decisions. Exclude foreign-account plans, malformed YAML and file links outside the account wiki.
- [x] Preserve workspace-relative artifact paths when hosted wiki storage is linked outside conversation state.
- [x] Recover and inspect the existing proposal and receipts before rebuilding. Recalculate a missing hash offline; do not require a new baseline, new trend table or special user phrase to recover it. Explicit approval must still cover the exact proposal.
- [x] Accept literal `YYYY-MM-DD` dates through CLI and registered date resolution; retain named periods and exact-window checks for genuinely new bid/budget analyses.
- [x] Focused recovery tests pass, including missing-hash recovery without credentials or proposal edits, shared wiki links, account isolation and invalid calendar dates. The actual launcher resolves `2026-11-18` successfully.
- [x] Full regression suite: **294 tests passed**. Compilation and diff checks passed. No live Ads changes performed.

**19 November query compatibility follow-up:**

- [x] Register existing primary-conversion and context aggregations in the CLI; calculate and advertise only metrics with available inputs. Keep primary CPA distinct from install/in-app CPA.
- [x] Retire new fetches of the incompatible ad-group app-conversion query, preserving the old aggregation route for historical files. Update recipes to the supported query and explain the conversion-definition difference.
- [x] Reuse complete exact-period raw files before looking for weekly chunks. Fetch campaign reach for the whole period, reject chunk summation, and rebuild long-period legacy reach caches without whole-period provenance. Apply the same provenance check to dataset preparation.
- [x] Keep punctuation preferences in writing guidance; remove punctuation-only save/apply vetoes that rejected previously accepted copy.
- [x] Compare with pre-refactor commit `a7de598`: all 77 original core tests pass against current code, retaining their expected outputs. Creative test transport/profile fixtures were adapted for added reads. The isolated original suite ran 247 tests with one existing client-fixture hygiene failure; it was not a fully green baseline.
- [x] Final local verification: **290 tests passed**, including CLI handoff, compatible derived metrics, complete-range cache reuse, whole-period reach and rejection of unsafe reach caches. Compilation and diff checks passed.
- [ ] Read-only staging verification of the supported queries against Google Ads. Local/mock verification does not establish provider compatibility.

**19 November compatibility audit (supersedes live-validation and brief-first wording below):**

- [x] Search saved selected-account artifacts before new analysis; inspect resolved dates, evidence coverage and current account rules. Reuse and link sufficient work. Brief fills gaps or starts new investigations. Updated the hosted prompt, AGENTS and relevant recipes.
- [x] Make `bid-budget-validate` an offline saved-draft check/hash. Recommendations require no execution-oriented live validation. Apply reads current campaign settings in one query; performance and change-history fetches are no longer prerequisites to execution validation. Exact approval and execution protections remain.
- [x] Treat acquisition-cost, volume and preferred-wait references as recommendation guidance rather than automatic skips.
- [x] Preserve generated copy/bid proposal formats and supporting evidence. Verify the existing compact copy suggestions can select and apply exactly 26 of 32 candidates through a mocked Ads client. Reject rewriting plans with execution receipts.
- [x] Fix blank-category grouping versus missing join identities, explicit-input context aggregation, long account KT, and partial account updates preserving names.
- [x] Regression verification: **282 tests passed**, compilation and diff checks passed. Tests include offline validation without credentials and a live-settings timeout stopping apply before mutation. No live Ads mutations or paid creative generation were performed; staging acceptance remains open.

**19 November verification revision (supersedes automatic-answer-check steps below):** Remove the universal answer checker and gateway repair loop. Bob verifies work through task-specific skill guidance and tool feedback, corrects recoverable failures and rechecks, and explains uncertainty. Existing domain/execution checks remain enforced. The copy-save command returns row errors before saving an invalid proposal. Historical answer-check checklist items and numerical-check test counts below describe the earlier implementation, not the current acceptance criteria. Current regression verification: **275 tests passed**, including copy-save failure/correction, direct prose and legacy-envelope handling, and existing approval/execution protections. Python compilation and diff checks passed. Agent judgement still requires live staging acceptance.

Status: final agreed refactor delivery proposal, updated 2026-11-19. Checkboxes indicate verified implementation only; the proposal itself does not mean the refactor has shipped.

**19 November revision:** Goals now owns marketing reference values. Existing CAC, change-size and cooldown values carry over into `usual_approach`; older profile fields are compatibility aliases. Marketing values guide the baseline rather than vetoing a final proposal. Departures require rationale, forecast and explicit approval, and surface review notes. This supersedes the CAC/cooldown/step-cap “hard limits” wording below. Account scope, explicit campaign exclusions, valid values, permissions, approval hashes and duplicate/ambiguous-execution protections remain enforced.

---

## 1. Outcome

Bob makes better-supported recommendations, including knowing when to wait, from fewer and
richer calls. Every recommendation is recorded with its evidence and prediction, so it can be
recalled and evaluated.

## 2. Rules for every step

- Every step ships with the standard questions passing the automatic answer check on staging, and the team reading the before/after answers.
- CLI commands, persisted plan formats and approval semantics stay compatible; new fields are additive.
- No new interfaces without a second implementation.
- Typed models only where there's identity or state (decision record, prediction).
- Skill packages don't import each other. `brief`, `search` and `decisions` compose them without holding domain logic.
- Video, images, copy, CLI, gateway and instructions are all in scope. Integrate existing uncommitted work and its useful behaviour; it is not exempt from refactoring. Change working internals only where the agreed contracts require it.

## 3. Rollout

There is **one instruction set**: recipes with baselines. Safety comes from four things, not from
running two versions:

1. **The automatic answer check on every answer** (Step 0): numbers verified, plans validated, scope enforced.
2. **Hard guards in code:** one `validate_plan` per domain checks the final plan before approval and again at apply on live values (CAC ceiling, cooldown, max step, permissions, entity state), with approval bound to the plan hash.
3. **One behaviour for every account.** The baseline is a reference; Bob may depart with evidence, within hard limits and with explicit approval. Test the complete investigation → decision → review loop in staging before releasing it. No strict/advisory account modes.
4. **Rollback:** redeploy the previous image.

## 4. Steps

### Step 0: Automatic answer check and staging
- **Add a structured `claims` list to Bob's answers:** entity, metric, period, value, source file for every number stated.
- **Add `lib/bob/answer_check.py`**, run by the gateway after each answer and before the user sees it:
  - **numbers:** direct values match the source; derived values are recomputed with the shared metric functions; any number missing from the claims list counts as unchecked;
  - **plans:** proposed plans go through `validate_plan` (from Step 1 onward; until then, the existing recommender guards);
  - **scope:** selected account; KT exclusions respected.
- **On failure:**
  - wrong or unchecked number → flagged in Admin, plus a short note to the user;
  - plan over a limit → the proposal-bearing reply is withheld with a reason; a revised proposal must be reviewed before approval (no new card framework for the MVP);
  - wrong account → answer held, job failed.
- **Stand up staging from what exists:** `./bob snapshot-pull` + `docker-compose.vm-snapshot.yml`, with Google Ads writes disabled.
- **Write down the standard questions,** one per main type:
  1. Performance deteriorated; what should we do?
  2. CPI up: bids/budget or creative mix?
  3. Which text ads need changes based on performance?
  4. Conflicting goals (volume vs CPI)
  5. Waiting is right (immature conversions, learning, a recent change)

  Run them once on today's Bob in staging and keep the answers for before/after reading.
- **Done when:** every production answer is checked; a planted wrong number, an out-of-limit plan and a wrong-account answer are each caught.

### Step 1: Simple router, recipes with baselines, hard guards
- **Rewrite `AGENTS.md` short:**
  - invariants;
  - "pick the skill whose *use when* fits; if none clearly does, run `./bob skills search`";
  - "recipes give a baseline, not the only answer".

  Remove the routing protocol, the exclusivity rules and "only from command X" rules.
- **Edit skills in place as recipes with baselines:**
  - bid matrix and LOW 2-of-3 as baselines;
  - registered analysis operations allowed in normal work;
  - fix the stale commands and paths in `creative-underperformance.md`.
- **Generate `.agents/skills/INDEX.md`** from frontmatter, and add `./bob skills search`.
- **Split the recommender:**
  - scenario choice is discretionary;
  - CAC ceiling, cooldown, max step and permissions are hard limits.
- **Add `validate_plan` per domain** (`bid_budget/guards.py`, `creative_copy/rules.py`), run on the **final** plan, whether baseline or changed by Bob:
  - before approval, with verdicts shown on the approval card;
  - again at apply, on freshly read live values.

  Approval is bound to the plan hash. Baseline departures are recorded and explained; they are not controlled by an account mode.
- **Done when:**
  - the standard questions pass the answer check on staging and read better than before;
  - baseline outputs remain available as a reference;
  - departures cite evidence and never break a hard guard, for every account;
  - any plan breaking a limit (including hand-edited or Bob-changed plans) is rejected before approval and at apply;
  - meaningful tests cover scope, changed proposals, caps, cooldown, invalid values and mutation ambiguity. The coverage/mutation targets in `CODE_GATE.md` are soft guidance for this MVP, not a separate infrastructure project.

### Step 2: One-call brief and wider investigation
- **Add `./bob brief`** (sections in architecture §4.2): goals, data status, performance drivers, bids/budgets with baseline and guards, creative summary, recent changes, KT rules, prior decisions, evidence refs. Missing data is prepared inside the call.
- **Register `bid_budget_inputs` and `change_history`** for analysis, and add budget utilisation as a metric.
- **Add result checks in code:** compatibility, join cardinality, coverage, conversion maturity.
- **Copy validators:** punctuation, proper nouns, no GOOD/BEST duplicates.
- **Stage brief sections honestly:** Step 2 provides existing settings and evidence; Step 4 adds expanded goals, Step 5 adds decision history, and Step 6 adds due reviews. Mark unsupported or failed sections unavailable, not empty. Bound fetching work and allow useful partial results.
- **Include creative production:** integrate existing image/video generation, review and publication paths and their CLI/skill instructions with applicable final-plan validation and approval contracts. Provider/rendering internals may be reused; the workflows are not excluded.
- **Done when:**
  - the five standard questions start from one `brief` call;
  - tool calls per question drop against today's answers;
  - end-to-end latency and fetching work are measured alongside call count;
  - the standard questions pass the answer check and read at least as well as before.

### Step 2b (only if real questions show the need): creative age and fatigue
- **Add `asset_first_seen`:** a one-off month-segmented backfill, kept current from regular pulls.
- **Add a weekly asset trend grain.**
- **Register both, and add them to the brief's creative section.**
- **Done when:** a creative-fatigue question is answered from evidence.

### Step 3: Knowledge search instead of loading the wiki
- **Add `./bob search`** over wiki analyses, action items, KT and (once Step 5 lands) decisions. It uses SQLite FTS5, refreshed on writes.
- **Remove the wiki and KT reading instructions** from the prompt and skills. The brief always carries KT exclusions and house rules, so they're never search-dependent.
- **Done when:** the standard questions pass the answer check with less context loaded; no answer misses an account rule.

### Step 4: Goals and priorities
- **Extend the account profile:** targets, priority order, budget envelope, explicit risk constraints, review date. Persist them authoritatively so hosted profile regeneration preserves them. Show them in Admin and include them in the brief. No decision modes.
- **Done when:** the conflicting-goals question follows the stated priority and say so.

### Step 5: Decision records
- **Add `lib/bob/decisions/`** (records, evidence). Every recommendation gets a record, including holds and rejected or overridden ones.
- **Make evidence immutable but lean:**
  - copy cited processed files and analysis results into a content-addressed store (`evidence/<sha256>`);
  - pin cited raw pulls against pruning;
  - store the operation spec and code version with each item.

  Only what consequential decisions cite is kept.
- **Write intent before execution;** link execution results afterwards.
- **Add `decision_id` to plans.**
- **Persist cited analysis results.**
- **Add prior decisions and due reviews to the brief,** and make decisions searchable.
- **Done when:** after a handoff, restart or later re-aggregation, a new conversation recalls the decision with its original evidence contents and prediction; questions with history use it.

### Step 6: Prediction reviews
- **Add `./bob decision review <id>`**, run on request after the observation window and once conversions have matured.
- **It compares the recorded prediction against observed values:** correct grain (e.g. cost and installs summed across networks before CPI), windows counted from execution, using the recorded review criteria.
- **It returns supported / contradicted / inconclusive** and stores the verdict, observed values and windows on the decision record.
- **Migrate the old retrospective:** correct or delegate its direction checks, campaign/network aggregation and execution-relative windows. Until migrated, disable misleading verdicts rather than retaining a contradictory review path.
- **The brief lists reviews that are due.**
- **Done when:** reviews reproduce correct verdicts on fixture cases (including inconclusive ones), and never claim causation.

## 5. Release check

Before each release, on staging:

1. Run the standard questions on the new build.
2. All answers must pass the automatic answer check.
3. The team reads them next to the previous release's answers.

Ship, or roll back the image.

Saved failure cases, replay scripts and a model grader are future options (architecture §13), not
part of this plan.

## 6. Repo changes

File-by-file changes and the client-state layout are in `architecture-proposal-changed.md` §15. In
short:

- **New:**
  - `lib/bob/brief.py`, `search.py`, `decisions/` (records, evidence store, review), `performance/checks.py`;
  - `bid_budget/guards.py`, `creative_copy/rules.py`;
  - `.agents/skills/INDEX.md`;
  - `lib/bob/answer_check.py` (+ claims list in answers);
  - search index, decisions and evidence in client state.
- **Modified:**
  - `AGENTS.md` and the skills, in place;
  - `adhoc.py`, `adhoc_data.py`, `aggregate.py`;
  - `bid_budget/__init__.py` (including the retrospective delegating to the decision review, or its verdicts disabled);
  - `creative_copy/suggest.py`, `creative_copy/apply.py`;
  - `mcp/server.py`, `cli.py`, profile;
  - `server/app.py`, `agent_runner.py`, `static/app.js`.
  - `creates_it/`, `static_banners/` and their CLI/recipe integration where needed for the shared contracts, including the uncommitted video work (`creates_it/video.py`, `video_media.py`, `cli.py`, creates-it skill, `AGENTS.md`, `tests/test_creates_it_video.py`);
  - `server/models.py` / `schema.sql` as needed for authoritative goal persistence, compatible migration and runtime profile materialisation.
- **Reuse existing internals where sufficient:** GARF queries (one added in Step 2b), fetch, compare, dates, metrics, accounts, sync, scheduling and deployment. This is not an exclusion from integration or verification.

## 7. Out of scope

- Automatic review scheduling, lesson drafting from reviews, and promotion of lessons into shared guidance.
- MCP-only interface, reviewer model, profiles, monitors, embedding retrieval, worker expansion, cross-channel continuity.
- Meta adapter (designed when Meta is implemented).

## 8. Backlog (not blocking)

- CI running the full test suite; SHA-tagged images; one-command rollback.
- Encrypted backups and a restore drill.
- Bind the app to `127.0.0.1:8000`; remove the default admin password fallback.
- `./bob doctor`; an instruction-size budget test.
- Action-level permissions; credentials out of the harness shell.

## 9. Implementation checklist

Updated 2026-11-19. Checked items mean implemented and exercised, not deployed or accepted on the standard staging questions.

- [x] Step 0: hidden answer envelope and numerical claims; source/period/entity validation, shared ratio calculations, comparison deltas and unchecked-number warnings.
- [x] Step 0: gateway checks before displaying model replies; Admin diagnostic event, user warning and foreign-account hold. Tests plant unchecked numbers and foreign-account replies through the gateway.
- [x] Step 0: declared bid/copy plans are checked; denied proposals are withheld. Snapshot overlay disables Ads writes and live fetching in code.
- [ ] Step 0 release acceptance: run all five standard questions on staging and retain before/after answers for team review. Offline snapshot CLI checks are not a substitute.
- [x] Step 1: shorter AGENTS.md, nonexclusive investigation recipes, generated INDEX.md and skills search; one decision behaviour, no strict/advisory settings.
- [x] Step 1: independent bid-plan validator, pre-approval validation command, approval hash and apply-time live checks. Scope, caps, volume, CAC, cooldown, duplicate proposals and invalid numeric limits have tests.
- [x] Step 1: registered `bid-budget-propose` and `creative-copy-propose` save discretionary final choices while preserving the baseline. New plans require a linked decision before apply; proposal creation never approves or applies them.
- [x] Step 1: bid mutation intent is checkpointed before requests; successful receipts survive later failures, and unknown outcomes require reconciliation rather than blind retries.
- [x] Step 1: baseline and final bid plans share eligibility primitives. Copy checks live ads before approval and rechecks status, identity and text after approval; live peer labels override plan assertions. Static publishing verifies enabled target ads before approval and again during apply; approved image bytes are retained in memory and hashed.
- [ ] Step 1 release acceptance: prove the complete approval flow on staging. No live Ads mutations were performed during implementation verification.
- [x] Step 2: bounded brief, partial results, explicit unavailable sections, account totals, performance drivers, baseline summaries, KT, history and fetch budget. Offline snapshot smoke check returns available performance with missing events marked unavailable and zero fetches.
- [x] Step 2: bid inputs and change history registered; native context aggregation, non-additive settings, budget utilisation, empty event windows and conversion-maturity metadata.
- [x] Step 2: copy length/punctuation/name/duplicate validators; copy apply rechecks account and proposal content. Names and known GOOD/BEST text require explicit vocabulary/input; they are not guessed from capitalization.
- [x] Step 2: existing image/video work retained; linked decision identity is checked and preserved across creative revisions. Copy/static apply can link receipts to decisions.
- [x] Step 2: GOOD/BEST peers are refreshed from the live asset view; required names are populated from explicit account vocabulary, including an Admin field. Copy final-plan checks reject changed/disabled targets and campaign identity mismatches.
- [ ] Step 2 release acceptance: measure standard-question call count and latency and review image/video publication behaviour on staging. Existing generation/checkpoint/review code is integrated and covered by regression tests; no paid provider runs are claimed.
- [ ] Step 2b (conditional, not started): asset first-seen and weekly trend only if real questions demonstrate the need.
- [x] Step 3: account-scoped FTS search for wiki/KT/decisions; gateway points to brief/search. Index refreshes on search, including external/manual edits, rather than requiring hooks on every writer.
- [ ] Step 3 acceptance: verify reduced context and rule adherence on the standard questions. Free-form KT is carried as guidance; machine-enforced exclusions use explicit account goal identifiers.
- [x] Step 4: validated goals endpoint and Admin form; SQLite migration; goals survive hosted profile regeneration and are included in the brief. Regression test exercises repeated regeneration.
- [x] Step 5: account-scoped decision journal, immutable atomic content-addressed evidence, provenance, recall and linking existing plans through the registered CLI. Evidence survives re-aggregation and reopen in tests.
- [x] Step 5: MCP decision capture persists cited transformed results and prepared inputs before in-memory handles disappear; receipt linking on bid/copy/static apply.
- [x] Step 5: model/code/instruction provenance, entity-filtered recall before limiting results, execution-relative due dates, and retained human/review history. `decision respond` records rejection/override/approval without authorising an Ads mutation.
- [ ] Step 5 release acceptance: verify recommendation/hold/rejection capture in real conversations. Direct raw-file citations are not accepted by the MVP capture path; prepared MCP inputs and processed/account-wiki evidence are copied instead, so raw pruning cannot remove those snapshots.
- [x] Step 6: manual prediction review, execution-relative full-day windows, maturity, confounders, summed campaign metrics and inconclusive outcomes. The old retrospective no longer emits misleading verdicts.
- [ ] Final release acceptance: complete remaining integration items and all five standard staging questions, review before/after answers, then deploy. No release or production mutations are claimed by this checklist.

## 10. Verification notes

- [x] Consolidated Goals form: CPI/CPA selection, currency labels, carried-over usual approach and plain-newline examples. Campaign search/selection removed from Goals; campaign preferences belong in KT or the current prompt.
- [x] Marketing departures receive warnings and require rationale/forecast; technical execution checks remain enforced.
- [x] P1 fixes: account rename preserves omitted settings; saved goals survive tab navigation, reload and repeated saves (browser checked in an isolated snapshot).
- [x] Release notes updated with blank-goal fallback and one illustrative decision record.
- Goals consolidation verification: **281 tests passed**, plus browser save/navigation/reload checks, JavaScript syntax, Python compilation and diff checks. These do not replace staging acceptance or deploy the update.

- Final local verification: `python -m unittest discover -s tests -q` passed **279 tests**. Python compilation, `node --check server/static/app.js`, and `git diff --check` passed. These are code/regression checks, not a claim that the standard staging questions were run or that judgement improved.
- Focused flow tests exercise immutable evidence, MCP result/input persistence, account scope, final-plan limits, unsafe proposal withholding, partial briefs, mutation ambiguity and prediction reviews.
- The existing local VM snapshot has historical campaign data but lacks some requested event/creative windows. Offline checks correctly expose these gaps rather than fetching or inventing evidence. Docker engine availability was checked; no caproduction container was changed.
- Implementation intentionally adds no evaluator service, model grader, replay framework, new runtime decision modes or blanket platform abstraction.
- Numerical coverage is conservative, not a semantic proof of prose. Structured entity/metric/period claims are checked against sources, and unmatched numerical literals are flagged; dates/list numbering are excluded. Human review must still catch narrative errors, misleading selection and context mismatches. Proposed bid/budget figures can cite the validated plan as proposal claims rather than pretending to be observed performance.
- A brief's fetch budget counts dataset preparations, which can involve bounded seven-day query chunks; it is not a claim that one CLI call equals one Google API request.
