# Bob Frm Mktg — Jobs to Be Done

Bob is a CLI-first Google Ads performance marketing operator for App campaigns. He pulls data through GARF, calculates metrics deterministically in Python, and explains the result in chat. He does not invent numbers.

## 1. Get an account ready

**User asks:** “Set me up”, “add an account”, “connect my account”, “switch account”, or “is my config ready?”

Bob can:

- Onboard a Google Ads account.
- Configure campaign type, primary goal, currency, MCC, and account-level operating defaults.
- Configure Google Ads read access with the developer token.
- Configure optional OAuth write access for approved changes.
- List registered accounts and identify the active account.
- Switch the active account by name or customer ID.
- Check configuration without exposing secrets.
- Repair the local dependency/runtime setup.

Important boundary: onboarding configures the account; it does not automatically pull performance data. Search and Performance Max accounts can be stored, but the current analysis workflows are built for App campaigns.

## 2. Pull Google Ads data

**User asks:** “Pull the data”, “refresh the report”, or asks a question whose required data is missing.

Bob can:

- Run one GARF query with `fetch`.
- Run the standard first-pull set with `bootstrap`.
- Aggregate raw CSV outputs into processed, reusable files.
- Resolve named periods into exact dates.
- Avoid duplicate pulls by checking the pull log and existing coverage first.
- Split granular campaign, ad group, network, and creative requests into sequential chunks of up to seven calendar days.
- Keep account-level period pulls unchunked.

Every pull records the account, query, date window, reason, and outcome in the pull log.

The main data grains are:

- Account and network performance
- Campaign and network performance
- Ad group and network performance
- Campaign reach
- Creative performance
- Daily account performance
- Campaign weekly trend
- Bid and budget inputs
- Change history

## 3. Compare account performance

**User asks:** “What happened last week?”, “How are we doing month over month?”, or “Compare W34 and W33.”

Bob can compare:

- Yesterday versus the same day last week
- Last complete ISO week versus the previous week
- Two named ISO weeks
- Month-to-date versus the previous month-to-date
- Two full calendar months
- A custom campaign period after exact date resolution

He can report at account, campaign, ad group, or campaign-plus-network level where the source data supports it.

The deterministic calculations include:

- Impressions, clicks, cost, installs, in-app conversions, and goal conversions
- CPM, CTR, CPC, CTI, conversion rate, CPA, and CPI
- Current value, baseline value, absolute movement where supported, and percentage movement
- Network and campaign drivers

Reach and frequency are treated as non-additive metrics. Bob does not sum deduplicated users across campaigns or networks.

## 4. Diagnose what changed

**User asks:** “Why did performance drop?”, “What caused the change?”, or “What is driving the result?”

Bob can diagnose a period movement by working through:

1. Account-level movement.
2. Network attribution.
3. Top campaign drivers.
4. Ad group detail where available.
5. Relevant Google Ads change-history events.

He names the most likely cause from the measured data and separates confirmed evidence from thin or missing evidence.

## 5. Compare a campaign segment

**User asks:** “How did Stable campaigns perform?”, “Compare Brand campaigns”, or gives a campaign-name segment.

Bob can:

- Filter campaigns by a case-insensitive name substring.
- Compare the selected segment across yesterday/SDLW, WoW, MoM, or MTD windows.
- Show the segment total and per-campaign breakdown.
- Optionally split the segment by network.
- Save a full comparison CSV when required.

The filter is based on campaign data, not hardcoded campaign naming conventions.

## 6. Decide what to do with bids and budgets

**User asks:** “What bids and budgets should I change?”

Bob can generate a recommendation plan using:

- Three weeks of campaign trend data
- Current bid and budget inputs
- The account’s primary goal
- CAC ceiling
- Bid/budget change percentage
- Cooldown period since the last change
- Budget utilization and conversion signals

The deterministic recommendation engine can propose:

- Target CPA or bid increases
- Target CPA or bid decreases
- Budget increases or decreases
- Holds
- Skips where guards are not satisfied

Bob shows the plan before any live mutation. Applying changes requires explicit user approval and valid write credentials.

Bob can also evaluate an already-applied plan with a W+1/W+2 retrospective and report whether the changes are working.

## 7. Identify underperforming creatives

**User asks:** “Which ads need changes?”, “Which text ads are low?”, or “What creatives are underperforming?”

Bob can:

- Pull headlines, descriptions, images, or videos separately.
- Use the account’s creative lookback and minimum-impression settings.
- Read Google Ads performance labels.
- Filter to assets meeting the minimum impression threshold.
- Compare assets against the same campaign and asset type.
- Classify text assets as `LOW-ACTION` or `LOW-WATCH`.
- Surface LOW images and videos for review.
- Show actual asset content when Google returns it:
  - Headline or description text
  - Image URL and metadata
  - YouTube video ID

For text, `LOW-ACTION` means at least two signals are worse than the same campaign/type average:

- CTR more than 10% below average
- CTI more than 10% below average
- CPC more than 10% above average

The asset-selection decision is deterministic Python. Replacement wording is generated separately using the creative-copy rules. Bob never applies replacements without explicit approval.

## 8. Prepare replacement text copy

**User asks:** “Suggest replacement copy for the LOW text ads.”

Bob can:

1. Build an account-scoped creative-copy YAML plan.
2. Include the asset’s campaign, ad group, field type, current text, metrics, and reason for selection.
3. Split candidates into small sequential batches.
4. Generate replacement suggestions under the character and copy rules.
5. Show the complete suggestion set for approval.
6. After approval, create new text assets and pause the old assets.
7. Save the plan and result in `wiki/<customer_id>/action-items/`.

Headlines must be at most 30 characters. Descriptions must be at most 90 characters and end with punctuation.

## 9. Build a static banner direction

**User asks:** “Create a banner design guide”, “refresh the static creative guide”, or “what should our banners look like?”

Bob can use strong-performing image assets to create a quarterly design guide containing:

- Observed creative themes
- Useful visual territories
- Layout and composition guidance
- Ratio and placement guidance
- Text and CTA rules
- Generic design tokens and production constraints

The guide is evidence-based and account-scoped. It does not copy one advertiser’s identity into a generic rule.

## 10. Prepare static image variants

**User asks:** “Create replacements for these LOW image assets.”

Bob can:

- Identify LOW image candidates.
- Use the existing design guide where available.
- Prepare a same-size replacement manifest.
- Download source images when a valid source URL is available.
- Generate preview-only replacement candidates.
- Validate dimensions, file size, and source identity.
- Show an approval table.
- Upload and replace images only after explicit approval and valid write access.

Preview generation is not approval and does not change Google Ads.

## 11. Save knowledge and share it

**User asks:** “Save this to the wiki”, “sync”, or “share the team updates.”

Bob can:

- Save approved analyses and action plans to the active account’s wiki.
- Keep wiki artifacts under `wiki/<customer_id_no_hyphens>/`.
- Update the account wiki index.
- Sync wiki files, backlog entries, and self-improvement signals through a configured shared folder such as Dropbox.
- Pull teammate updates, push local updates, or preview what would change.

The shared-folder workflow is separate from the public GitHub repository. Pull logs remain machine-local.

## 12. Learn from recurring mistakes

**User asks:** “What keeps going wrong?”, “Review your mistakes”, or “Improve yourself.”

Bob can:

- Read the distilled signal and backlog logs.
- Group repeated failures by root cause.
- Rank them by frequency and severity.
- Produce a proposal-only self-improvement plan.

The self-improvement workflow never changes code or skills automatically. A human must review and apply the proposal.

## 13. Hosted runtime and safety

In the hosted browser workspace Bob can:

- Stream Codex status, progress activity, and terminal events.
- Resume an active conversation job after a browser refresh.
- Stop a running job with Esc.
- Show completed, failed, or cancelled states clearly.
- Keep Codex Sessions as an admin view of jobs and stored `job_events`.
- Use Admin → Observability for lightweight live CPU, memory, process, and OOM diagnosis.
- Use Admin → Data Explorer for read-only previews of approved raw, processed, wiki, and pull-log data.

Bob’s hard boundaries:

- No fabricated metrics or recommendations.
- No live Google Ads mutation without explicit approval.
- No credentials or secrets in chat, logs, previews, or suggestions.
- No arbitrary filesystem access from the browser.
- No raw chain-of-thought or private internal monologue is exposed.
- When no supported CLI workflow exists, Bob reports the limitation and records a failsafe instead of improvising.

## Testing philosophy

Bob is tested from the outside in, with the strongest guarantees around numbers, safety, and failure recovery.

### Deterministic core first

- Metric formulas, zero-denominator behavior, date-window resolution, period aggregation, and asset-content preservation are tested with local fixtures.
- Tests use the columns already produced by Bob. They do not invent a second calculation path in the test itself.
- Additive metrics are checked after aggregation; reach and frequency are checked as non-additive exceptions.
- A deliberate formula or period change must update the matching expected test value.

### No live Google Ads mutations in automated tests

- Tests never mutate a real Google Ads account.
- Bid/budget and creative apply paths are tested with fake clients, seeded plans, approval gates, and error responses.
- A mutation must be impossible without explicit approval, valid write credentials, and the correct account scope.
- Retry tests verify that Bob does not automatically repeat a mutation after execution may have started.

### Hosted gateway isolation

- Hosted tests use temporary SQLite metadata and temporary workspaces.
- The agent runner is replaced with a deterministic fake, so tests do not depend on Codex availability or network access.
- Tests cover authentication, CSRF, client/account isolation, account switching, job serialization, event streaming, cancellation, timeout behavior, and browser refresh recovery.
- Sensitive paths, credentials, prompts, and full command arguments must not leak through API responses or logs.

### Failure is a first-class result

- Missing data, failed GARF pulls, stale files, blank asset content, low volume, and unavailable credentials must produce an explicit result.
- Tests verify that Bob reports the blocker instead of fabricating a number or silently using the wrong account.
- OOM and process-group failures must leave a visible job status, safe runtime summary, and recoverable service state.

### Deployment smoke tests

After deployment, run the local/hosted smoke test against a disposable workspace:

1. Sign in.
2. Send a read-only test prompt.
3. Confirm streamed progress and terminal completion.
4. Refresh the browser and confirm the conversation remains intact.
5. Confirm Admin → Codex Sessions and Admin → Observability load.
6. Confirm no Google Ads mutation was performed.

Production verification is read-only first. Real mutation testing requires a deliberate human-controlled approval and a suitable test account.

## Command map

```text
SETUP
  onboard                       First-run setup for a new Google Ads account
  switch-account                Change active account
  list-accounts                 Show registered accounts
  check-config                  Verify Google Ads credentials
  repair-setup                  Reinstall local dependencies
  setup-write-credentials       One-time OAuth for write credentials

DATA
  fetch                         Pull one GARF query
  bootstrap                     Pull the default query set
  aggregate                     Build processed aggregates

ANALYSIS
  compare-weeks                 Compare ISO weeks
  compare-months                Compare calendar months
  slice-campaigns               Compare a campaign-name segment
  slice-creatives               Flag LOW creative assets

ACTIONS
  bid-budget-recommend          Generate a bid/budget plan
  bid-budget-apply              Apply an approved bid/budget plan
  bid-budget-retrospective      Evaluate an applied plan
  suggest-creative-copy         Build a LOW text-copy plan
  creative-copy-apply           Apply approved text changes
  suggest-static-banners        Build the static banner guide
  suggest-static-variants       Prepare LOW image variants
  static-variants-apply         Apply approved image variants

UTILITIES
  resolve-dates                 Resolve named periods
  validate-manual               Compare Bob output with a manual export
  log-pull                      Record a pull/cache outcome
  log-signal                    Record an immediate friction/failsafe signal
  session-debrief               Record batched session friction
  self-improve                  Build a proposal-only improvement plan
  sync                          Share wiki and signals through a shared folder
```

## Scheduled JTBD — implementation plan

This section tracks the hosted scheduling feature from implementation through deployment. Keep an
item unchecked until the code, automated tests, and relevant hosted verification for that item are
complete. Planning or partial implementation does not count as done.

### User outcome

A permitted hosted user can create a recurring prompt with `/sch` in Chat. Bob records
the commitment in a shared, read-only JTBD tab, runs it on the hosted VM using the selected Google
Ads account, adds the scheduled prompt and result to Chat, and creates a customer-facing Artifact.
Scheduled analysis never changes Google Ads without explicit approval.

- [x] A user with scheduling permission can create a recurring task through `/sch` using natural
      language after the command.
- [x] A user can pause, resume, or Run Now for an existing task through `/sch-pause`, `/sch-resume`,
      and `/sch-run`.
- [x] A user without scheduling permission receives a clear refusal and no schedule is changed.
- [x] Every successful run produces a Chat result and a customer-facing Artifact, including no-action runs.
- [x] Scheduled analysis is explicitly read-only and never automatically applies a Google Ads mutation.

### Current look and feel

The feature must extend the existing hosted interface rather than introduce a separate scheduler UI.

- [x] Add `JTBD` as the third primary tab: `CHAT | ARTIFACTS | JTBD`.
- [x] Reuse the current dark background, green borders, monospace typography, uppercase labels,
      spacing, active-tab treatment, and responsive behaviour.
- [x] Keep the existing Chat and Artifacts appearance and navigation behaviour unchanged.
- [x] Render JTBD entries as plain-language commitments, not cron expressions or technical records.
- [x] Keep JTBD read-only: do not add edit, run, pause, resume, or delete buttons.
- [x] Open an in-style task detail panel when a JTBD entry is selected.
- [x] Show the latest three runs in the detail panel with status, time, summary, and Artifact link.
- [x] Preserve the full run history internally even though the first UI shows only three runs.
- [x] Reuse the existing Artifact-link behaviour so report links open in the Artifacts tab.
- [ ] Verify the new tab and run detail panel at desktop and narrow viewport sizes.

### JTBD content and visibility

- [x] Show task title, plain-language purpose, Google Ads account, owner, schedule, timezone, status,
      next run, and last-run summary.
- [x] Use friendly task statuses: `Active`, `Paused`, `Running`, and `Needs attention`.
- [x] Show `Not run yet` before the first occurrence completes.
- [x] Make scheduled-task metadata visible to all approved users in the same client workspace.
- [x] Require account access before showing performance details or opening a run Artifact.
- [x] Prevent users in another client or account from discovering task or run data.

### Admin permission model

- [x] Let Admin set and edit an IANA scheduling timezone for each client.
- [x] Add an account-scoped `Can schedule Bob jobs` permission to Admin user access controls.
- [x] Keep schedule creation out of Admin; Admin grants permission and users schedule through Chat.
- [x] Allow a task owner with scheduling permission to manage their own scheduled tasks.
- [ ] Allow an Admin to manage scheduled tasks in the Admin's permitted client/account scope.
- [x] Allow other approved client users to view JTBD entries without changing them.
- [x] Recheck user, client, account, scheduling permission, account state, and Google authorisation at
      creation, management, run-now, and trigger time.
- [x] Keep existing read/write permission rules authoritative for any separately approved mutation.

### Chat scheduling capability

Scheduling is intentionally an explicit slash-command flow. The `bob-scheduling` skill interprets
only the text after `/sch`, `/sch-run`, `/sch-pause`, or `/sch-resume`; the model never receives
direct database access.

- [x] Enter scheduling only when the message begins with `/sch`, `/sch-run`, `/sch-pause`, or
      `/sch-resume`; ordinary Chat never creates or manages a schedule.
- [x] Route those commands through `AGENTS.md` to `bob-scheduling`; incomplete requests ask one
      focused question and do not fall through to an immediate performance run.
- [x] Explicitly prohibit the hosted agent from creating native Codex, ChatGPT, Page, Space, or
      other external automations as a scheduling fallback.
- [x] Expose only the typed operation needed for each public command: create, list plus pause,
      list plus resume, or list plus Run Now.
- [x] Validate every operation again at the server boundary instead of trusting model output.
- [x] Store the original prompt unchanged alongside a safe plain-language title and description.
- [x] Bind each scheduled task to its client, account, owner, and originating conversation.
- [x] Attach task identity to its originating conversation so `/sch-pause this` resolves
      safely.
- [x] Ask the user to choose a task when a reference is ambiguous; never guess from task names.
- [ ] Confirm the interpreted day, local time, timezone, recurrence, account, and first run before
      saving a new schedule.
- [x] Return plain-language confirmations without exposing internal tools, database fields, or cron.

### Persistence and data model

- [x] Add a migration for scheduled tasks.
- [x] Store client, account, owner, conversation, title, description, original prompt, day of week,
      local time, IANA timezone, recurring flag, status, next occurrence, last occurrence, and audit
      timestamps.
- [x] Add a migration for scheduled runs.
- [x] Store task ID, job ID, trigger type, scheduled time, claim/start/completion times, run status,
      safe summary, recommendation count, message reference, Artifact reference, and safe failure
      category.
- [x] Link scheduled runs to the management request, execution job, and generated Chat message for
      traceability.
- [x] Add a uniqueness constraint for task plus scheduled occurrence to prevent duplicate runs.
- [x] Add indexes for active next-run lookup, task run history, client visibility, and account scope.
- [x] Keep all schedule data in the existing persistent metadata volume.

### Schedule calculation

- [x] Use `datetime` and `zoneinfo` with IANA timezone names.
- [x] Store the client-local day, time, and Admin-configured client timezone and calculate
      `next_run_at` in UTC.
- [x] If today's requested time has passed, schedule the first recurring run for the next matching
      week rather than running unexpectedly.
- [x] Cover daylight-saving gaps and repeated local times deterministically.
- [x] Recalculate the next occurrence after day, time, pause, or resume changes.
- [x] Keep each existing task's saved timezone stable when the Admin changes the client default.
- [x] Ensure Run Now does not move or replace the next recurring occurrence.

### Event-driven scheduler

Use one in-process timer in the current single-process web container. Do not add per-task Linux cron
entries, Redis, Celery, another container, or frequent database polling for the first version.

- [x] Add a lifecycle-managed scheduler service to the hosted application.
- [x] Load the earliest active `next_run_at` from SQLite and wait until that exact deadline.
- [x] Add an internal `schedule_changed` event that wakes the timer after create, pause, or
      resume.
- [x] Recalculate the earliest active task after a timer wake or schedule-change event.
- [x] Atomically claim a due occurrence before placing it on the existing Bob job pipeline.
- [x] Calculate and persist the next recurring occurrence immediately after a successful claim.
- [x] Queue scheduled work through the existing job concurrency limit instead of bypassing it.
- [x] Stop the scheduler cleanly during application shutdown.
- [x] Expose safe scheduler health information, including whether its loop is alive and the next
      planned wake time.
- [x] Document that a future multi-replica deployment needs shared notification and leader election
      or an external queue before enabling more than one scheduler process.

### First run and Run Now

- [x] Save a newly created recurring task without automatically executing it.
- [x] Display the calculated first occurrence in Chat confirmation and JTBD.
- [x] Display `Last run: Not run yet` until a run reaches a terminal state.
- [x] Implement Run Now as a separate manual occurrence using the saved prompt and account context.
- [x] Record Run Now in scheduled-run history without changing the recurring deadline.
- [x] Apply the same permissions, authorisation checks, Chat messages, Artifact generation, and
      execution workflow to scheduled and Run Now occurrences.

### Trigger and Bob execution workflow

- [x] At trigger time, recheck the owner, client, account, permissions, account state, and Google
      authorisation before accessing advertising data.
- [x] Insert a visible user-style Chat message labelled `SCHEDULED` with the local schedule and
      original prompt.
- [x] Submit the work through the existing hosted Bob job runner and account-scoped workspace.
- [ ] Ensure `Which text ads need changes based on performance?` routes through the existing
      creative-copy workflow.
- [ ] Check the data manifest before fetching and fetch only missing required windows.
- [ ] Use deterministic asset selection and measured account data; never invent performance claims.
- [ ] Generate suggestions separately from deterministic asset selection.
- [x] Create a dated customer-facing Artifact for recommendations or a no-action result.
- [ ] Add Bob's final plain-language response to the originating conversation with the Artifact
      link and an explicit statement that nothing was changed in Google Ads.
- [x] Update the run record, last-run summary, task status, and JTBD display after completion.

### Live and offline delivery

- [x] Add a conversation-level event stream for server-originated scheduled messages and job state.
- [x] Update an open Chat live when the scheduled prompt, progress state, Artifact, result, or safe
      failure is persisted.
- [x] Persist all scheduled activity when the user is offline.
- [ ] Surface the updated conversation and unread state when the user next signs in.
- [x] Persist a user-facing assistant failure message because no browser may be watching the run.

### Recovery and failure handling

- [x] Reload active schedules and recreate the earliest timer after a container restart.
- [x] Define and test a missed-run grace period of six hours.
- [x] Run a recently missed occurrence at most once within the grace period.
- [x] Record older missed occurrences safely and advance to the next future occurrence without
      flooding Chat.
- [x] Use a durable claim and recovery marker for work claimed before the process stopped.
- [x] Mark a run interrupted if execution may have started; do not silently execute it twice.
- [x] Show `Needs attention` with a safe explanation for expired Google authorisation, removed
      access, disabled account, or missing Admin configuration.
- [x] Never expose credentials, hidden prompts, raw events, filesystem paths, or internal exception
      details in Chat, JTBD, Artifacts, or APIs.

### Internal structure and code quality

- [x] Keep scheduling domain logic, persistence, timer orchestration, permission checks, API routes,
      and UI behaviour separated instead of adding one large workflow to `server/app.py`.
- [x] Use typed domain objects and avoid `Any` in new domain logic.
- [ ] Keep changed functions within the repository's complexity limits.
- [ ] Keep production files within the preferred size range and below the hard size gate.
- [ ] Avoid duplicating permission, account resolution, job execution, Artifact-link, and message
      persistence logic already present in the hosted gateway.
- [x] Do not add scheduling logic to `lib/datapull.py`.

### Automated verification

- [x] Test first-occurrence calculation before and after today's requested time.
- [x] Test timezone conversion and daylight-saving gaps.
- [ ] Test repeated local times explicitly.
- [ ] Test every create, pause, resume, Run Now, and ambiguous-reference branch.
- [ ] Test task-owner, Admin, viewer, removed-permission, cross-account, and cross-client access exhaustively.
- [x] Test duplicate-claim prevention for repeated claim attempts.
- [ ] Test truly concurrent claims from separate database connections.
- [x] Test restart recovery, grace-period handling, stale claims, and interrupted runs.
- [ ] Test scheduled work waiting behind the existing job concurrency limit.
- [ ] Test every successful, no-action, authorisation-failure, missing-data, and runner-failure result.
- [x] Test that Chat messages, Artifacts, JTBD summaries, and latest-three history stay consistent.
- [x] Test that scheduled execution is constrained to the read-only recommendation workflow.
- [ ] Meet at least 95% branch coverage for critical schedule calculation, claim, permission, and
      mutation-safety paths, and at least 85% overall branch coverage.
- [ ] Add mutation tests for critical timing, permission, uniqueness, and no-auto-apply invariants.

### Hosted deployment and completion

- [ ] Apply the database migration safely against a disposable hosted workspace.
- [x] Run the full automated test suite and code-quality gates.
- [ ] Rebuild the Docker image and confirm schedule data survives a container restart.
- [ ] Verify Admin scheduling permission with a test user and account.
- [ ] Create a schedule through Chat and confirm it appears in the styled JTBD tab.
- [ ] Use Run Now and confirm the scheduled Chat message, Bob response, Artifact, and JTBD run detail.
- [ ] Verify an exact-time scheduled occurrence without browser presence.
- [ ] Verify offline persistence and live delivery after reconnecting.
- [ ] Verify pause and resume through Chat.
- [ ] Confirm no Google Ads mutation occurred during read-only verification.
- [ ] Mark checklist items complete only after their implementation and applicable verification pass.

## Scheduling build status — 11 October 2026

The first end-to-end scheduling slice is implemented locally. It has not yet been deployed to the hosted VM.

### Built

- Users with account-level `CAN SCHEDULE` permission create recurring work only through `/sch`.
- `AGENTS.md` routes `/sch`, `/sch-pause`, `/sch-resume`, and `/sch-run` to `bob-scheduling`; the LLM
  interprets only the command remainder and calls typed Bob JTBD tools.
- Typed create, list, pause, resume, and Run Now operations enforce the
  current user, Chat, client, selected account, ownership, Google connection, and scheduling
  permission at the server boundary.
- Chat supports pausing, resuming, and running a scheduled task now through the explicit `/sch` commands.
- Admin can grant or revoke scheduling permission per user account.
- The scheduler is event-driven and uses one-shot wake-ups rather than cron jobs or frequent polling. It does not require Redis, Celery, or an additional Docker container.
- Scheduled tasks and their runs are stored durably in SQLite, with atomic claiming and duplicate-run prevention.
- On startup, interrupted work is recovered and missed schedules can run within a six-hour grace period.
- At trigger time, the saved prompt is added to the originating user's Chat and processed by Bob's existing agent runner, using the same skills and account scope as an ordinary user message.
- A successful run creates an Artifact automatically, including a fallback report when the runner does not create a richer artifact itself.
- The third navigation tab is `JTBD`. It is read-only, uses the existing dark-green monospace look and feel, and shows each job's plain-language schedule, status, next run, and latest three runs. Users can open a job to inspect its full run history.
- JTBD metadata is visible to all users, while account-level performance details and artifact links remain hidden from users who cannot access the relevant account.
- Conversation updates are delivered live through server-sent events.
- Admin can set each client's scheduling timezone; new clients default to `Asia/Kolkata`.

### Verified

- The full explicit test suite passes: 215 tests.
- The new `bob-scheduling` skill passes repository skill validation.
- Frontend JavaScript syntax validation passes.
- Docker Compose configuration validation passes.
- Repository diff whitespace validation passes.
- Checklist position at this checkpoint: 95 items complete and 31 items open.

### Still open

- Browser visual QA for desktop and narrow-screen layouts.
- Additional exhaustive scheduling and mutation coverage.
- Admin controls for managing another user's scheduled jobs, if that becomes a product requirement.
- Deployment and smoke testing on the real hosted VM.

## Technical implementation

### Runtime architecture

The first version deliberately stays inside the existing Docker web service:

```text
Browser
  │
  ├── Chat schedule request ──> existing Bob agent job
  │                              │
  │                              ├── AGENTS.md routes to bob-scheduling
  │                              ├── LLM interprets flexible language
  │                              └── typed Bob scheduling tool
  │                                      │
  │                                      ├── validates authenticated Chat scope,
  │                                      │   permission, ownership, account,
  │                                      │   Google authorization, and timezone
  │                                      ├── writes SQLite scheduled_tasks/runs
  │                                      └── emits completion to wake/dispatch
  │
  ├── JTBD tab ───────────────> GET /api/jtbd ──> SQLite tasks + latest runs
  │
  └── live Chat updates <────── Server-Sent Events

FastAPI lifespan
  └── one Scheduler coroutine
        ├── reads the earliest active next_run_at from SQLite
        ├── sleeps until that instant or an asyncio.Event wakes it early
        ├── atomically claims the due occurrence
        └── sends it through the existing Bob job runner
```

There is no separate cron service, polling loop, Redis queue, Celery worker, or scheduler container. The scheduler starts and stops with the FastAPI application. The current Docker image launches one Uvicorn process, so one process owns the timer. If the service is later scaled to multiple application replicas or workers, the scheduler must be moved to an elected leader or dedicated worker; the current design should remain single-replica.

### Main implementation areas

- `.agents/skills/bob-scheduling/SKILL.md` teaches the agent how to interpret creation and management
  requests after an explicit `/sch` prefix, ask only for genuinely missing details, resolve ambiguity, and avoid all native or
  external automation systems.
- `lib/bob/mcp/server.py` exposes the seven typed scheduling operations alongside Bob's existing
  analysis tools.
- `server/schedule_tools.py` is the scheduling trust boundary. It binds every operation to the
  authenticated user, selected account, client, originating Chat, current management job, and
  Admin-configured timezone before calling the repository.
- `server/scheduling.py` contains timezone-aware next-run calculation, the schedule repository,
  atomic due-run claiming, missed-run handling, and the one-shot scheduler loop. It does not parse
  user sentences.
- `server/schema.sql` defines durable `scheduled_tasks` and `scheduled_runs` tables and the indexes used to find the next occurrence and recent run history.
- `server/models.py` applies backward-compatible column additions for existing databases, including
  `can_schedule`, run return status, and the Run Now management-request reference.
- `server/app.py` connects scheduling to authentication, account access, Google authorization, Chat messages, the existing agent runner, Artifact creation, JTBD responses, scheduler health, and live conversation events.
- `server/static/index.html`, `server/static/app.js`, and `server/static/styles.css` implement the JTBD tab, latest-run expansion, Artifact links, Admin scheduling permission, and live refresh behavior in the current interface style.
- The Admin client profile stores and validates the IANA scheduling timezone used for new jobs.
- `tests/test_scheduling.py` exercises typed tool validation, ambiguity, time calculation, claiming,
  duplicate prevention, recovery, and related scheduler behavior. Hosted gateway tests cover the
  agent-tool, API, permission, Run Now, Chat, Artifact, and JTBD integration.

### Data model

`scheduled_tasks` is the durable definition of a job. Each row records:

- tenant/client, Google Ads account, owner, and originating Chat;
- the exact prompt Bob must run;
- day of week, local wall-clock time, IANA timezone, and recurring flag;
- lifecycle status plus `next_run_at` and `last_run_at` in timezone-aware ISO format;
- a temporary deletion-confirmation timestamp.

`scheduled_runs` is the durable occurrence history. Each row records:

- the task and trigger type: normal schedule or Run Now;
- intended schedule time, claim/start/completion timestamps, and final status;
- the standard Bob job and Chat message created for the occurrence;
- the Chat management job that requested a Run Now occurrence;
- customer-facing summary, Artifact path, recommendation count, and failure category;
- the task status to restore after Run Now finishes.

The unique key on `(task_id, scheduled_for)` prevents the same scheduled occurrence from being inserted twice. The index on `(status, next_run_at)` makes finding the next active task inexpensive.

### Creating and managing a job through Chat

1. The normal Chat endpoint recognizes only four explicit command prefixes: `/sch`, `/sch-run`,
   `/sch-pause`, and `/sch-resume`. Ordinary Chat messages never create or manage a schedule.
2. `AGENTS.md` routes those commands to `bob-scheduling`. The LLM extracts the intended prompt,
   weekday, and local time from the remainder of `/sch`, such as
   `/sch Which text ads need changes? every Monday at 3 am`.
3. If a required meaning is genuinely absent or ambiguous, Bob asks one focused question and makes
   no scheduling tool call. A complete request goes directly to the matching typed tool.
4. The command run receives only the typed tools it needs: create for `/sch`; list plus Run Now for
   `/sch-run`; list plus pause for `/sch-pause`; and list plus resume for `/sch-resume`. It receives
   no performance/data tools, Google Ads runtime configuration, or previous-agent session.
5. The skill and hosted agent prompt prohibit native Codex, ChatGPT, Page, Space, OS cron, and other
   external automation systems.
6. The typed server boundary rechecks the authenticated user and Chat, selected active account,
   membership, account access, `CAN SCHEDULE`, ownership, Google connection, and client timezone.
7. The server stores the prompt and schedule in `scheduled_tasks`, calculates the first future
   occurrence in the configured timezone, and returns a structured result to the agent.
8. When the completed tool event reaches the web process, it sets the scheduler's change event so
   the current one-shot wait is recalculated immediately. Run Now is handed to the same existing job
   pipeline through its durable management-request reference.
9. Bob replies in Chat using the tool result: interpreted prompt, schedule, timezone, first run,
   status, and the read-only assurance.
10. A management call with no task ID is accepted only when exactly one live task belongs to that
   owner and Chat. If several exist, the list tool returns safe choices and Bob asks the user to
   select one; the server never guesses from a title.

### How the event-driven timer works

The scheduler does **not** ask the database “is anything due?” every few seconds. It performs one database read, sets one in-memory wait for the exact next due instant, and then remains asleep:

```text
Read earliest active next_run_at once
              │
              ├── no task exists ──> wait indefinitely for a schedule-change event
              │
              └── task exists ─────> wait until its exact due time
                                           │
                         ┌─────────────────┴─────────────────┐
                         │                                   │
                 due-time timeout                    schedule changed
                         │                                   │
                 claim and dispatch               cancel this wait and
                         │                         read the new earliest time
                         └─────────────────┬─────────────────┘
                                           │
                                      repeat once
```

In implementation terms, the scheduler uses `asyncio.wait_for(changed_event.wait(), timeout=seconds_until_due)`. This is a one-shot timer, not a polling interval:

1. On application startup, it queries SQLite once for the earliest `next_run_at` among active jobs.
2. With no active job, it waits indefinitely on an `asyncio.Event`; there are no repeated database checks.
3. With an active job, the timeout is the exact number of seconds until that job is due. A task due in seven days therefore results in one seven-day wait, not seven days of periodic checks.
4. Creating, pausing, resuming, or completing a task sets the event. That immediately ends the current wait, because the identity or time of the earliest job may have changed.
5. The scheduler then performs one new database read and creates a replacement one-shot wait for the newly earliest task.
6. If nothing changes, the timeout expires at the due instant. The scheduler opens an immediate SQLite transaction, selects one due active task, inserts its run record, advances the recurring task to its next weekly occurrence, and commits.
7. It dispatches that run asynchronously, then loops once to find the next earliest occurrence. Tasks sharing the same due time are claimed on immediate successive passes.

Claiming and advancing the task happen in the same transaction. Together with the unique occurrence key, this prevents two callbacks in the same deployment from running the same occurrence.

The `asyncio.Event` is only an in-process “the schedule changed” signal; it is not the source of truth. SQLite remains the durable source of truth. After a container restart, the scheduler reconstructs its next one-shot timer from SQLite. Server-Sent Events are separate and only refresh an open browser—they do not trigger or keep scheduled work alive.

### What happens when the trigger fires

1. The dispatcher revalidates the owner, tenant membership, Google Ads account, scheduling permission, and Google authorization. Permission is checked again at execution time; a permission that was later revoked is respected.
2. It inserts a visible user message into the original Chat in the form `SCHEDULED · <DAY AND TIME>` followed by the stored prompt.
3. It creates a normal Bob `jobs` row and links the scheduled run to that job and message.
4. It publishes a conversation event so an open browser updates immediately. The schedule still runs when no browser is open.
5. It sends the stored prompt through the existing `run_job` path. This preserves Bob's normal skill routing, deterministic Google Ads data workflows, account scope, concurrency limits, and conversation locking.
6. The scheduled execution adds a read-only instruction: produce a dated customer-facing Markdown report, link it as an Artifact, and state that Google Ads was not changed.
7. If Bob creates its own Artifact, that path is retained. Otherwise the gateway writes a fallback Markdown Artifact from the final response and adds the Artifact marker.
8. The assistant result appears in the same Chat. The run receives a concise summary, Artifact path, completion status, and completion time, after which the task returns to `active` or its earlier `paused` state.
9. A conversation refresh event updates Chat, Artifacts, and the JTBD tab without requiring a page reload.

### First-run and timezone behavior

- The first run is always the first matching weekly occurrence strictly after creation; creating a Wednesday 4:00 AM job after Wednesday 4:00 AM schedules the following Wednesday.
- The scheduling timezone belongs to the client. It is stored in `client_instances.scheduling_timezone`, can be set by Admin while creating or editing that client, and is shown in the Admin client profile.
- New clients default to `Asia/Kolkata` at the database and API layers for backward compatibility. The Admin can replace it with any valid IANA timezone, such as `Europe/London` or `America/New_York`. Invalid or blank values are rejected by the server.
- The timezone is not read from `.env`, Docker Compose, the browser, the Google Ads account, the user profile, or the VM operating-system timezone.
- When a user creates a task, the server reads the current timezone from that task's client and copies it into `scheduled_tasks.timezone`. It also stores the selected weekday and wall-clock value separately in `day_of_week` and `local_time`.
- For example, “Every Wednesday at 4am” for a client configured as `Asia/Kolkata` is stored conceptually as `day_of_week = Wednesday`, `local_time = 04:00`, and `timezone = Asia/Kolkata`.
- The server converts the next matching local occurrence to an absolute UTC instant and stores it in `next_run_at`. Each `scheduled_runs.scheduled_for` value is also the absolute instant for that individual occurrence.
- The scheduler waits on `next_run_at`; it does not repeatedly perform timezone calculations while waiting. After claiming the occurrence, it uses the task's stored weekday, local time, and timezone to calculate the following week's absolute `next_run_at`.
- Display code converts the stored absolute instant back through the task's saved timezone, so Chat and JTBD show the intended local day and time.
- Changing the client's Admin setting affects tasks created after the save. Existing tasks keep their own saved timezone and do not silently move. This avoids changing already-agreed schedules without an explicit migration workflow.
- Per-user and per-task timezone selection is not implemented in the first version.
- Timezone conversion uses the standard zone database. Daylight-saving gaps are normalized by a UTC round trip; ambiguous local times use the first occurrence.
- Run Now creates an immediate occurrence but does not move the next normal scheduled time.

### Restart, downtime, and failure handling

- On startup, runs left in `claimed`, `queued`, or `running` are marked `interrupted`, and their tasks return to the appropriate active or paused state.
- If an occurrence became due while the container was offline, it runs after restart when it is no more than six hours late.
- If it is more than six hours late, the occurrence is recorded as `skipped` with a `missed_grace_period` reason, and the task advances to the next week.
- Missing ownership, removed account access, revoked scheduling permission, expired Google authorization, or a missing Chat moves the run to `needs_attention` with a user-facing explanation. No Google Ads mutation is attempted.
- A dispatch exception marks the occurrence failed, wakes the timer, and leaves an explicit “nothing was changed” result.
- Admins can inspect scheduler liveness and its calculated next wake time through the protected scheduler-health endpoint.

### Permissions and visibility

- `can_schedule` is an account-level capability separate from read or read/write Google Ads access.
- Admin changes to access and `CAN SCHEDULE` are stored together in `user_account_access`.
- A non-admin user can manage only a task they own through its originating Chat.
- The JTBD list shows all non-deleted scheduled jobs for the client so the team can see what Bob is expected to do.
- Users without access to a task's account see its job metadata but not its performance summary, recommendation count, failure detail, or Artifact link. Admins can inspect all client jobs.
- The JTBD tab is intentionally read-only. Its help text says: “Use `/sch` to create, `/sch-pause`
  to pause, `/sch-resume` to resume and `/sch-run` to run a scheduled job.”

### Deployment sequence for the VM

1. Back up the metadata SQLite volume and persistent client/wiki volumes.
2. Build the updated web image and start exactly one application replica.
3. On startup, the existing schema initialization creates the scheduling tables and adds the client timezone column with `Asia/Kolkata` for existing clients.
4. In Admin, edit the client and confirm its scheduling timezone before creating any jobs.
5. Check application health and the protected scheduler-health response.
6. Grant `CAN SCHEDULE` to a test user on one test account.
7. Create a weekly task through Chat, verify its first-run interpretation in JTBD, then use Run Now to validate the complete Chat → Bob → Artifact → JTBD path.
8. Restart the container and confirm the job definition, run history, and next wake survive through the persistent metadata volume.
9. Verify an exact scheduled occurrence with the browser closed before enabling the permission more broadly.
