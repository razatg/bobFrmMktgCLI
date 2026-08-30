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
