# Bob Frm Mktg Build Plan

This plan turns the architecture into an executable MVP roadmap for Google Ads app campaign analysis. The goal is to build Bob as a CLI-first analyst that fetches data with GARF, creates deterministic processed slices, answers supported marketing questions, and stores accepted analyses/actions in a file wiki.

## MVP Scope

Bob will support Google Ads app campaigns with two goal types:

- Installs
- In-app conversions

The first supported metrics are:

- Unique users
- Impressions
- Clicks
- Cost
- Installs
- In-app conversions
- CTR %
- CPC
- CTI %
- Conversion rate %
- Frequency

The first supported user questions are:

1. Yesterday vs same day last week at account level.
2. WoW, MoM, and MTD at account level.
3. What caused performance to improve or deteriorate, first by network, then campaign.
4. What should be done with bids and budgets.
5. Which creatives are underperforming after enough delivery or at least 50k impressions.
6. What the team changed yesterday, this week, or this month.

## Build Principles

- GARF fetches raw Google Ads reporting data.
- Bash/CLI tools create deterministic processed slices.
- The agent explains slices; it does not invent numbers or calculate from raw API data ad hoc.
- Bid and budget write-back uses explicit Google Ads mutation plans.
- Live Google Ads mutation requires user approval.
- Wiki memory is written only after user acceptance.

## Phase 0: Project Skeleton

Create the repository structure:

```text
bin/
garf/
  queries/
  outputs/raw/
data/
  processed/
    campaign/
    account/
    network/
    creative/
    change-history/
google-ads/
  mutations/
  logs/
lib/
  metrics/
  periods/
  recommendations/
.agents/
  skills/
wiki/
  index.md
  analyses/
  action-items/
  decisions/
tests/
  fixtures/
  slice-contracts/
.bob/
```

Acceptance criteria:

- Folder structure exists.
- `ARCHITECTURE.md`, `PLAN.md`, and local agent skill files are present.
- `.bob/` is gitignored later if credentials or local profile data are stored there.

## Phase 1: Onboarding And Profile

Build `bin/bob-onboard`.

It should ask:

- Primary goal: installs or in-app conversions.
- Google Ads customer ID.
- Currency.
- Campaign context.
- Optional target CPI/CPA.
- Default metrics to show.

Persist:

```text
.bob/profile.json
```

Acceptance criteria:

- Running onboarding creates valid JSON.
- Re-running Bob detects the existing profile.
- The profile can be read by all slice and recommendation commands.

## Phase 2: GARF Query Files

Split [sugestedSql.sql](/Users/E2005/projects/bobFrmMktgCLI/sugestedSql.sql) into runnable GARF query files.

Recommended files:

```text
garf/queries/
  campaign_daily.sql
  campaign_reach_daily.sql
  conversion_action_daily.sql
  network_daily.sql
  campaign_delta_daily.sql
  bid_budget_inputs.sql
  creative_asset_daily.sql
  creative_conversion_action_daily.sql
  change_history.sql
```

First fetch strategy:

```text
campaign_daily: last 90 days
campaign_reach_daily: last 90 days
network_daily: last 30 days
creative_asset_daily: last 30 days
change_history: last 30 days
```

Why:

- Campaign daily last 90 days is the reusable spine for yesterday vs SDLW, WoW, MoM, MTD, campaign deltas, and recommendations.
- Reach/frequency must stay separate because unique users are non-additive and constrained.
- Network and creative data are diagnostic and larger, so start with 30 days and expand on demand.
- Change history is only available for a recent window, so fetch it every run or scheduled refresh.

Acceptance criteria:

- Each query is runnable independently with GARF.
- Query outputs include stable column names.
- Date macros are documented.
- Creative threshold is not applied inside the query; it is applied after aggregation.

## Phase 3: Fetch Commands

Build `bin/bob-fetch`.

Responsibilities:

- Read `.bob/profile.json`.
- Resolve date windows.
- Run the right GARF query file.
- Store raw outputs under `garf/outputs/raw/`.
- Include query name, customer ID, and date range in filenames.

Example:

```bash
bin/bob-fetch --query campaign_daily --days 90
bin/bob-fetch --query network_daily --days 30
bin/bob-fetch --query change_history --days 30
```

Acceptance criteria:

- Fetch command fails clearly when profile/config is missing.
- Raw output filenames are deterministic.
- Fetch metadata records query, customer, date range, and run timestamp.

## Phase 4: Metrics And Period Helpers

Build shared helpers under:

```text
lib/metrics/
lib/periods/
```

Metric formulas:

```text
cost = cost_micros / 1000000
ctr_percent = clicks / impressions * 100
cpc = cost / clicks
cti_percent = installs / clicks * 100
conversion_rate_percent = goal_conversions / clicks * 100
frequency = impressions / unique_users where supported
cost_per_goal = cost / goal_conversions
```

Period helpers:

- Yesterday
- Same day last week
- WoW
- MoM
- MTD
- Custom date range

Acceptance criteria:

- Zero denominators return `NA` or `null`, not zero.
- Percent metrics are stored as numeric percentages.
- Period helpers output exact start and end dates.
- Unit tests cover date edge cases.

## Phase 5: Processed Slice Commands

Build deterministic slice commands:

```text
bin/bob-slice-account
bin/bob-slice-network
bin/bob-slice-campaign-deltas
bin/bob-slice-creatives
bin/bob-slice-change-history
```

Required output contracts:

```text
data/processed/account/
data/processed/network/
data/processed/campaign/
data/processed/creative/
data/processed/change-history/
```

Acceptance criteria:

- Each command reads raw GARF output and writes stable CSV/JSON.
- Each output includes date windows and source filenames.
- Re-running a slice with the same inputs produces the same output.
- Contract tests validate headers and required fields.

## Phase 6: Account-Level Answers

Implement CLI flows for:

- Yesterday vs SDLW.
- WoW.
- MoM.
- MTD.

The agent should load:

```text
.agents/skills/bob-google-ads/
```

Acceptance criteria:

- Bob answers using processed account slices.
- Bob shows exact date windows.
- Bob leads with the user's primary goal.
- Bob includes cost, volume, CTR %, CPC, CTI %, conversion rate %, and frequency where available.

## Phase 7: Delta Diagnosis

Implement diagnosis for performance improvement/deterioration.

Flow:

1. Account-level movement.
2. Network contribution.
3. Campaigns responsible for most absolute delta.
4. Campaigns with high percent deviation and enough volume.
5. Separate volume movement from efficiency movement.

Acceptance criteria:

- Network-level diagnosis uses `network_daily`.
- Campaign-level diagnosis uses campaign delta slices.
- Low-volume movement is flagged as low confidence.
- Bob distinguishes spend, traffic, CTI, conversion rate, CPC, and frequency movement.

## Phase 8: Bid And Budget Recommendations

Build:

```text
lib/recommendations/
bin/bob-plan-budget-changes
bin/bob-plan-bid-changes
```

Recommendation categories:

- Increase
- Decrease
- Hold
- Investigate

Rules:

- Increase budget for efficient, high-volume, constrained campaigns.
- Reduce or hold budget for deteriorating campaigns.
- Raise bids only when volume is strong and efficiency is acceptable.
- Lower bids when efficiency worsens with enough volume.
- Avoid strong recommendations on weak data.

Acceptance criteria:

- Recommendations include reason codes.
- Recommendations include current value, proposed value, and expected impact.
- No recommendation directly mutates Google Ads.
- Recommendation output can be saved as a wiki action item.

## Phase 9: Google Ads Mutation Planning

Build:

```text
bin/bob-apply-google-ads-changes
google-ads/mutations/
google-ads/logs/
```

Mutation flow:

1. Recommendation creates a dry-run mutation plan.
2. Bob displays the plan.
3. User explicitly approves.
4. Apply command validates current values.
5. Apply command pushes through the Google Ads API.
6. API request and response are logged.

Acceptance criteria:

- Dry-run is default.
- Live apply requires an explicit flag and approval.
- Mutation plans include campaign IDs and current values.
- Logs link back to the recommendation/action item.

## Phase 10: Creative Underperformance

Implement creative analysis from asset-level slices.

Default threshold:

```text
minimum_impressions = 50000
```

Flags:

- Low CTR % vs benchmark.
- Low CTI % vs benchmark.
- Low conversion rate % vs benchmark.
- High spend with low goal conversions.
- High frequency with deteriorating engagement or conversion.

Acceptance criteria:

- 50k impression threshold is applied after date-range aggregation.
- Output includes asset ID/name/type, campaign, impressions, cost, installs, goal conversions, CTR %, CTI %, conversion rate %, and cost per goal.
- Bob suggests pause, replace, iterate, or observe.

## Phase 11: Change History

Implement change history summary from `change_event`.

Output should group by:

- Date
- Campaign
- Actor
- Client type
- Change resource type
- Operation

Acceptance criteria:

- Supports yesterday, this week, and this month.
- Mentions the 30-day change event limitation.
- Connects changes to performance only when entity and timing match.
- Avoids implying causality from change history alone.

## Phase 12: Wiki Memory

Build wiki save flow:

```text
wiki/index.md
wiki/analyses/
wiki/action-items/
wiki/decisions/
```

Each saved analysis should include:

- Question asked.
- Date generated.
- Profile context.
- Exact date windows.
- Source processed slices.
- Key table.
- Interpretation.
- Recommendations.
- Backlinks.

Acceptance criteria:

- Bob asks before saving.
- `wiki/index.md` is updated with links.
- Action items can link to mutation plans and API logs.

## Phase 13: Tests

Create fixture-based tests.

Test areas:

- Period logic.
- Metric formulas.
- Zero denominator behavior.
- Slice contract headers.
- Delta contribution ranking.
- Creative thresholding.
- Recommendation rules.
- Mutation plan generation.
- Wiki page generation.

Acceptance criteria:

- Tests run locally with sample fixture data.
- Tests do not require live Google Ads credentials.
- Live fetch/apply tests are separated from offline unit tests.

## Phase 14: CLI Integration

Build `bin/bob` as the main entrypoint.

Responsibilities:

- Detect onboarding state.
- Route natural language question to the right skill/reference.
- Run missing fetch/slice commands.
- Present answers.
- Ask about saving to wiki.
- Ask about mutation planning/apply when relevant.

Acceptance criteria:

- A fresh user can onboard and ask the six MVP questions.
- Bob reuses existing processed slices when valid.
- Bob clearly states when it needs more data.

## Suggested Build Order

1. Project skeleton.
2. Onboarding/profile.
3. GARF query files.
4. Fetch command.
5. Metrics and period helpers.
6. Account slices.
7. Account answers for yesterday vs SDLW, WoW, MoM, MTD.
8. Network and campaign delta diagnosis.
9. Bid/budget recommendation planning.
10. Creative analysis.
11. Change history.
12. Wiki save flow.
13. Google Ads mutation apply.
14. Test hardening and CLI polish.

## Definition Of MVP Done

The MVP is done when a user can:

1. Run onboarding.
2. Fetch the first data set.
3. Ask all six supported question types.
4. Get answers based only on processed slices.
5. Save accepted analyses to the wiki.
6. Generate bid/budget mutation plans.
7. Apply approved bid/budget changes through Google Ads with logs.
