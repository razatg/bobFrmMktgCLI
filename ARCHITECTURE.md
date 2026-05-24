# Bob Frm Mktg Architecture

Bob Frm Mktg is a CLI-first performance marketing automation tool. Bob is the proverbial marketing person: the user asks natural language questions, and Bob turns those questions into deterministic Google Ads data pulls, repeatable metric comparisons, diagnosis, recommendations, and durable wiki artifacts.

The MVP targets Google Ads app campaigns and restricts optimization goals to:

- Installs
- In-app conversions

The MVP metric vocabulary is intentionally small:

- Dimensions: account, date, network, campaign, creative asset, change history actor/change type
- Base metrics: unique users, impressions, clicks, cost, installs, in-app conversions
- Derived ratios: CTR %, CPC, CTI %, conversion rate %, frequency

This gives Bob enough structure to answer useful performance questions while avoiding a generic BI product too early.

## Goals

Bob must be able to:

1. Onboard a new user by learning their preferred goal metric and campaign context.
2. Fetch Google Ads reporting data through GARF.
3. Produce deterministic processed data slices with bash tools.
4. Let a CLI agent answer natural language questions using those processed slices.
5. Diagnose account-level changes by decomposing deltas across network, campaign, and creative levels.
6. Recommend bid and budget actions from clear, auditable rules.
7. Push accepted bid and budget changes to Google Ads through guarded write-back tools.
8. Store accepted analyses and action items in a file-backed wiki with backlinks.

## Non-Goals For The MVP

- Cross-channel marketing analysis.
- Unapproved or fully autonomous write-back into Google Ads.
- Arbitrary metric definitions at runtime.
- Deep MMM, incrementality, or causal inference.
- A web dashboard.
- Support for every Google Ads campaign type.

The first version should behave like a reliable analyst assistant, not an autonomous account manager.

## High-Level Architecture

```text
User
  |
  v
CLI Agent
  |
  +-- Onboarding/Profile Store
  |
  +-- Intent Router
  |     |
  |     +-- Performance Comparison
  |     +-- Delta Diagnosis
  |     +-- Bid/Budget Recommendation
  |     +-- Creative Fatigue/Underperformance
  |     +-- Change History Summary
  |
  +-- Data Slice Tools
  |     |
  |     +-- Bash wrappers
  |     +-- Processed CSV/JSON outputs
  |
  +-- GARF Queries
  |     |
  |     +-- Google Ads API
  |
  +-- Google Ads Write-Back Tools
  |     |
  |     +-- Approved bid/budget mutations
  |
  +-- Artifact Wiki
        |
        +-- index.md
        +-- analyses/
        +-- action-items/
        +-- decisions/
```

## Core Design Choice

Bob separates deterministic data preparation from language-model reasoning.

The agent should not directly improvise Google Ads queries or calculate deltas from raw API output during every answer. Instead, GARF query files and bash tools create repeatable data slices. The agent reads those slices, explains them, and asks for additional slices only when required.

This choice matters because marketing analysis needs reproducibility. If the same user asks "what happened yesterday vs same day last week" twice, Bob should compute the same numbers both times and leave a trail showing which query, date range, filters, and metric formulas were used.

## Main Components

### 1. CLI Agent

The CLI agent is the user-facing layer. It handles onboarding, natural language routing, response synthesis, and artifact creation.

Responsibilities:

- Ask onboarding questions in a fresh instance.
- Persist the user's primary KPI and campaign type.
- Parse questions into supported analysis intents.
- Select and run the right deterministic data slice tools.
- Validate whether required data exists before answering.
- Present answers with concise tables, drivers, caveats, and next actions.
- Ask the user whether an analysis or action item should be saved to the wiki.

The agent can be implemented with Codex, Gemini CLI, or another command-line assistant, but the project should keep business logic outside model prompts wherever possible. Prompts should orchestrate; scripts should compute.

### 2. Onboarding And Profile Store

On first run, Bob asks:

- Which primary metric do you care about most: installs or in-app conversions?
- What type of app campaign are you running?
- Which supporting metrics do you want surfaced by default?
- What is the Google Ads customer/account context?

The MVP can persist this as a local file:

```text
.bob/
  profile.json
```

Example:

```json
{
  "primary_goal": "in_app_conversions",
  "campaign_goal_type": "app_in_app_conversions",
  "default_metrics": [
    "unique_users",
    "impressions",
    "clicks",
    "cost",
    "installs",
    "in_app_conversions",
    "ctr",
    "cpc",
    "cti",
    "conversion_rate",
    "frequency"
  ],
  "google_ads_customer_id": "0000000000",
  "currency": "INR"
}
```

Keeping profile state in a file is enough for the CLI MVP and makes the system transparent. A database can be added later if multi-user or hosted workflows become necessary.

### 3. GARF Data Fetch Layer

GARF is the fetch layer for Google Ads API reports. Bob should store GARF queries as versioned files rather than generating them ad hoc.

Suggested layout:

```text
garf/
  queries/
    account_daily.sql
    network_daily.sql
    campaign_daily.sql
    creative_asset_daily.sql
    change_history.sql
  outputs/
    raw/
```

Initial query families:

- `account_daily`: account-level metrics by date.
- `network_daily`: metrics by date and ad network.
- `campaign_daily`: metrics by date, network, and campaign.
- `creative_asset_daily`: metrics by date, campaign, asset, and asset type.
- `change_history`: changes by date, campaign, user, client type, and change resource.

Why GARF:

- It is already built for Google Ads API reporting.
- Query files are auditable and reusable.
- It supports repeatable exports that downstream bash tools can consume.
- It avoids building a custom Google Ads extraction layer before the product direction is proven.

### 4. Processed Data Slice Tools

Bash tools create stable, reusable slices from raw GARF output. These scripts should be deterministic: same inputs, same outputs.

Suggested layout:

```text
bin/
  bob-fetch
  bob-slice-account
  bob-slice-network
  bob-slice-campaign-deltas
  bob-slice-creatives
  bob-slice-change-history
  bob-metrics

data/
  raw/
  processed/
    account/
    network/
    campaign/
    creative/
    change-history/
```

Example commands:

```bash
bin/bob-fetch --query account_daily --from 2026-05-01 --to 2026-05-18
bin/bob-slice-account --period yesterday_vs_sdlw
bin/bob-slice-account --period wow
bin/bob-slice-campaign-deltas --period wow --goal in_app_conversions
bin/bob-slice-creatives --min-impressions 50000
bin/bob-slice-change-history --period this_week
```

Why bash tools:

- They are easy to call from any CLI agent.
- They are transparent to inspect and debug.
- They create a contract between raw API data and model-generated analysis.
- They keep metric calculations out of fragile natural language prompts.

For non-trivial data transformation, bash scripts can delegate to `awk`, `jq`, `duckdb`, or small Python/R scripts. The interface should remain CLI-first.

### 5. Google Ads Write-Back Layer

Bob will use read-only GARF for reporting and the Google Ads API for approved mutations. In the MVP, write-back should be limited to processed bid and budget changes generated by the recommendation workflow.

Suggested layout:

```text
google-ads/
  mutations/
  logs/

bin/
  bob-plan-budget-changes
  bob-plan-bid-changes
  bob-apply-google-ads-changes
```

Write-back flow:

1. Recommendation tools create a proposed change file.
2. Bob shows the proposed campaign, current value, new value, reason, and expected impact.
3. The user explicitly approves the change.
4. `bob-apply-google-ads-changes` sends the mutation through the Google Ads API.
5. Bob stores the mutation request, API response, and resulting action item in the wiki.

Write-back guardrails:

- Never mutate Google Ads directly from a free-form natural language answer.
- Require an explicit approved change file.
- Require campaign IDs, current values, proposed values, and reason codes.
- Support dry-run mode by default.
- Log every mutation request and response.
- Keep budget and bid changes separate from read-only performance analysis.

Why use Google Ads API directly for writes:

- GARF is the right tool for reporting, not account mutation.
- Bids and budgets require explicit mutation calls, validation, error handling, and audit logs.
- The write tools can use the `google-ads` client/library or official Google Ads API client for the implementation language chosen later.
- Separating read and write paths reduces the chance that analysis code accidentally changes an account.

### 6. Agent Skills

The CLI agent should have a project-local skill folder that tells it how to handle each supported question type. These skills are procedural instructions for the agent, while `bin/` scripts remain responsible for deterministic computation.

Suggested layout:

```text
.agents/
  skills/
    bob-google-ads/
      SKILL.md
      references/
        account-yesterday-vs-sdlw.md
        account-period-comparison.md
        delta-diagnosis.md
        bid-budget-recommendations.md
        creative-underperformance.md
        change-history-summary.md
      agents/
        openai.yaml
```

Skill structure follows the Codex skill convention:

```text
my-skill/
  SKILL.md
  scripts/
  references/
  assets/
  agents/
```

`SKILL.md` is required and contains metadata plus instructions. `scripts/`, `references/`, `assets/`, and `agents/` are optional skill resources.

Why this exists:

- The agent gets a compact routing guide.
- Each question type has a repeatable workflow.
- Prompt instructions stay versioned with the product.
- The implementation can evolve without relying on hidden assistant behavior.

The skill should tell the agent:

- Which intent matches the user question.
- Which profile fields are required.
- Which data slices to request or generate.
- Which output format to use.
- Which caveats to mention.
- Whether the result may create an action item, wiki page, or Google Ads mutation.

### 7. Metric Definitions

Metric definitions must be centralized so every analysis uses the same formulas.

Base metrics:

```text
unique_users        = Google Ads unique users where available, otherwise documented proxy
impressions         = impressions
clicks              = clicks
cost                = cost_micros / 1,000,000
installs            = install conversions
in_app_conversions  = selected in-app conversion actions
```

Derived metrics:

```text
ctr              = (clicks / impressions) * 100
cpc              = cost / clicks
cti              = (installs / clicks) * 100
conversion_rate  = (goal_conversions / clicks) * 100
frequency        = impressions / unique_users
```

For the user's selected goal:

```text
goal_conversions      = installs OR in_app_conversions
cost_per_goal         = cost / goal_conversions
goal_conversion_rate  = (goal_conversions / clicks) * 100
```

All ratio calculations should handle zero denominators explicitly. Outputs should use `null`, `NA`, or a documented sentinel rather than silently returning zero.

Percent metrics should be stored as numeric percentages, not fractions. For example, a CTR of `3.2` means `3.2%`, not `0.032`.

## Supported MVP Questions

### 1. Yesterday Vs Same Day Last Week

User question:

```text
What was performance yesterday vs sdlw at account level?
```

Intent:

```text
account_performance_comparison
```

Date logic:

- Yesterday: `current_date - 1 day`
- SDLW: same day last week, `current_date - 8 days`

Output:

- Account-level table for base and derived metrics.
- Absolute delta.
- Percent delta.
- Short interpretation focused on the user's primary KPI.

Why this is first:

- It is the most common daily performance question.
- It validates date handling, metric formulas, and account-level data availability.

### 2. WoW, MoM, And MTD

User question:

```text
What's the performance WoW, MoM, MTD at account level?
```

Intent:

```text
account_period_comparison
```

Period logic:

- WoW: completed or current week compared with equivalent previous week window.
- MoM: completed or current month window compared with equivalent previous month window.
- MTD: month-to-date compared with equivalent prior-month-to-date or target baseline.

The implementation should make period conventions explicit in the output because marketing teams often use different definitions.

Output:

- Summary table by period.
- KPI deltas.
- Spend, volume, efficiency, and reach/frequency movement.
- Caveat if the current period is incomplete.

### 3. Cause Of Improvement Or Deterioration

User question:

```text
What caused performance to improve or deteriorate?
```

Intent:

```text
performance_delta_diagnosis
```

Diagnosis order:

1. Account-level movement.
2. Network-level contribution.
3. Campaigns responsible for majority of deviation.
4. Campaigns with unusually high deviation.

Driver logic:

- Calculate absolute contribution to goal conversions, cost, and cost per goal.
- Rank networks and campaigns by contribution to total delta.
- Flag high deviation when a campaign's percent change is large and volume is above a minimum threshold.
- Separate volume changes from efficiency changes.

Why start at network:

- Google Ads app campaign performance often shifts materially by network inventory.
- Network movement explains whether change came from Search, Display, YouTube, Google Play, or cross-network serving changes before drilling into campaign-level issues.

### 4. Bid And Budget Recommendations

User question:

```text
For improving performance, what should I do with bids and budgets?
```

Intent:

```text
bid_budget_recommendation
```

Recommendation inputs:

- Primary goal metric.
- Cost per goal.
- Conversion volume.
- Spend utilization.
- Recent trend versus baseline.
- Campaign-level contribution to positive or negative delta.
- Optional user-entered target CPI/CPA when available.

MVP rules:

- Increase budget for campaigns with strong goal volume, improving or stable cost per goal, and budget-limited behavior.
- Reduce budget or investigate campaigns with rising spend and deteriorating cost per goal.
- Raise bids only where conversion volume is strong and efficiency is acceptable.
- Lower bids where efficiency deteriorates and there is enough volume to trust the signal.
- Avoid recommendations where data volume is too low.

Why rule-based first:

- Bid and budget advice has business risk.
- Deterministic rules make recommendations explainable.
- The user can accept, reject, or edit action items before they become wiki memory.

Write-back behavior:

- Recommendations are read-only until the user approves them.
- Approved bid and budget recommendations are converted into structured Google Ads mutation files.
- The apply command defaults to dry-run and requires an explicit apply flag for live changes.
- Successful pushes create a wiki action item linking the recommendation, mutation file, and API response log.

### 5. Creative Underperformance

User question:

```text
Which creatives are underperforming after running for some time or 50k impressions?
```

Intent:

```text
creative_underperformance
```

Default threshold:

```text
minimum_impressions = 50000
```

Creative flags:

- At least 50,000 impressions.
- Below account, campaign, or asset-type benchmark for CTR %, CTI %, and conversion rate %.
- High spend with low goal conversions.
- Frequency is high and CTR % or conversion rate % is deteriorating.

Output:

- Creative asset ID/name/type.
- Campaign.
- Impressions, clicks, cost, goal conversions.
- CTR %, CTI %, conversion rate %, cost per goal.
- Benchmark comparison.
- Suggested action: pause, replace, iterate, or keep observing.

Why use impression threshold:

- Creative decisions need enough exposure.
- A threshold prevents overreacting to noisy early data.

### 6. Change History Summary

User question:

```text
What has the team worked on yesterday, this week, or this month?
```

Intent:

```text
change_history_summary
```

Change history output:

- Date range.
- Total changes.
- Changes grouped by campaign.
- Changes grouped by actor/client type where available.
- Change categories such as budget, bid strategy, conversion action, asset, campaign status, ad group, and targeting.
- Notable changes near performance inflection points.

Why change history matters:

- It connects observed performance movement to human actions.
- It helps distinguish market/platform movement from team-driven changes.

## Intent Routing

The CLI agent should map user questions into a small set of supported intents.

```text
account_performance_comparison
account_period_comparison
performance_delta_diagnosis
bid_budget_recommendation
creative_underperformance
change_history_summary
```

Each intent should define:

- Required date range.
- Required GARF query outputs.
- Required processed slices.
- Required profile fields.
- Output template.
- Artifact save behavior.

If the question falls outside supported intents, Bob should respond with the closest supported actions instead of pretending to answer.

## Data Contracts

Processed slice outputs should use stable schemas so the agent can rely on them.

### Account Slice

```csv
period_start,period_end,comparison_start,comparison_end,metric,current,baseline,absolute_delta,percent_delta
```

### Network Slice

```csv
network,metric,current,baseline,absolute_delta,percent_delta,delta_contribution_percent
```

### Campaign Delta Slice

```csv
campaign_id,campaign_name,network,metric,current,baseline,absolute_delta,percent_delta,delta_contribution_percent,volume_flag
```

### Creative Slice

```csv
asset_id,asset_name,asset_type,campaign_id,campaign_name,impressions,clicks,cost,installs,goal_conversions,ctr,cti,conversion_rate,cost_per_goal,benchmark_ctr,benchmark_cti,benchmark_conversion_rate,status_flag
```

### Google Ads Mutation Plan

```json
{
  "customer_id": "0000000000",
  "dry_run": true,
  "changes": [
    {
      "type": "campaign_budget",
      "campaign_id": "123",
      "campaign_name": "App Campaign - Android",
      "current_value": 10000,
      "proposed_value": 12500,
      "currency": "INR",
      "reason_code": "efficient_volume_budget_limited",
      "source_analysis": "wiki/analyses/2026-05-19-budget-recommendation.md"
    }
  ]
}
```

### Change History Slice

```csv
change_date,campaign_id,campaign_name,actor,client_type,change_resource,change_type,old_value,new_value
```

Stable schemas are more important than perfect first-pass completeness. They let the agent, wiki, and tests depend on known fields.

## Artifact And Wiki Memory Layer

Bob stores accepted analyses and action items as markdown files. This is the memory layer.

Suggested layout:

```text
wiki/
  index.md
  analyses/
    2026-05-19-account-yesterday-vs-sdlw.md
    2026-05-19-wow-mom-mtd.md
  action-items/
    2026-05-19-budget-reallocation.md
  decisions/
    2026-05-19-primary-kpi.md
```

`wiki/index.md` should contain:

- Recent analyses.
- Open action items.
- Accepted decisions.
- Links by campaign, metric, and date.

Each analysis page should contain:

- Question asked.
- Date generated.
- User profile context.
- Data sources used.
- Date windows.
- Key table.
- Interpretation.
- Recommendations.
- Links to related analyses or action items.

Why markdown:

- Easy to review in git.
- Easy for humans and agents to read.
- No database dependency for the MVP.
- Backlinks can be simple markdown links.

Bob should only persist analysis as memory after user acceptance. This prevents temporary explorations and mistaken conclusions from becoming durable context.

## Recommended Repository Structure

```text
.
  ARCHITECTURE.md
  README.md
  bin/
    bob
    bob-fetch
    bob-onboard
    bob-slice-account
    bob-slice-network
    bob-slice-campaign-deltas
    bob-slice-creatives
    bob-slice-change-history
    bob-plan-budget-changes
    bob-plan-bid-changes
    bob-apply-google-ads-changes
  .agents/
    skills/
      bob-google-ads/
        SKILL.md
        references/
        agents/
  garf/
    queries/
    outputs/
  google-ads/
    mutations/
    logs/
  data/
    raw/
    processed/
  lib/
    metrics/
    periods/
    recommendations/
  prompts/
    system.md
    intents/
  tests/
    fixtures/
    slice-contracts/
  wiki/
    index.md
    analyses/
    action-items/
    decisions/
  .bob/
    profile.json
```

The split keeps concerns clear:

- `garf/` fetches source data.
- `google-ads/` stores approved mutation payloads and API response logs.
- `bin/` exposes user- and agent-callable commands.
- `.agents/skills/` tells the CLI agent how to handle each supported question type.
- `lib/` contains reusable calculation logic.
- `data/` stores generated data.
- `prompts/` contains agent orchestration text.
- `wiki/` stores accepted memory.
- `.bob/` stores local runtime configuration.

## Execution Flow

### Fresh Instance

1. User starts Bob.
2. Bob checks for `.bob/profile.json`.
3. If missing, Bob runs onboarding.
4. Bob saves the profile.
5. Bob asks for the first supported question or suggests common analyses.

### Returning Instance

1. User asks a natural language question.
2. Intent router maps the question to a supported intent.
3. Bob checks whether required processed slices already exist.
4. If missing, Bob runs GARF fetch and slice tools.
5. Bob reads processed data.
6. Bob produces the answer with tables, drivers, caveats, and recommended next actions.
7. If recommendations include bids or budgets, Bob creates proposed change files but does not apply them.
8. Bob asks whether to save the analysis, create action items, or approve a Google Ads mutation.
9. If accepted, Bob writes markdown and updates `wiki/index.md`.
10. If explicitly approved for live apply, Bob pushes the mutation through the Google Ads API and stores the response log.

## Testing Strategy

The MVP should test the deterministic layers first.

Test areas:

- Period calculations for yesterday, SDLW, WoW, MoM, and MTD.
- Metric formulas and zero denominator behavior.
- Processed slice schema validation.
- Delta contribution ranking.
- Creative underperformance thresholding.
- Recommendation rules.
- Google Ads mutation payload generation in dry-run mode.
- Wiki page generation and backlink updates.

Fixture-based tests are enough initially:

```text
tests/
  fixtures/
    account_daily.csv
    network_daily.csv
    campaign_daily.csv
    creative_asset_daily.csv
    change_history.csv
```

The agent response itself can be evaluated with golden answer checks later, but correctness should start with scripts and data contracts.

## Key Risks And Mitigations

### Risk: The Agent Hallucinates Numbers

Mitigation:

- The agent only answers from processed slices.
- Outputs include data source filenames and date windows.
- Metric calculations happen in scripts, not prose.

### Risk: Google Ads Metric Definitions Drift

Mitigation:

- Keep GARF query files versioned.
- Centralize metric formulas.
- Document conversion action filters in profile/config.

### Risk: Recommendations Are Too Aggressive

Mitigation:

- Start with conservative rule-based recommendations.
- Require minimum volume thresholds.
- Store recommendations as action items for user acceptance, not automatic changes.

### Risk: Google Ads Write-Back Changes The Wrong Entity

Mitigation:

- Require campaign IDs and current values in every mutation payload.
- Re-read or validate current values before applying changes.
- Default to dry-run.
- Store API responses and link them to the original recommendation.

### Risk: Wiki Memory Becomes Noisy

Mitigation:

- Save only accepted analyses.
- Keep `index.md` curated around recent analyses, open action items, and decisions.
- Include links back to exact source slices.

### Risk: Bash Scripts Become Hard To Maintain

Mitigation:

- Keep bash as the command interface.
- Move complex calculations into `lib/` scripts when needed.
- Preserve stable CLI inputs and outputs.

## MVP Build Sequence

1. Create onboarding and `.bob/profile.json`.
2. Add GARF query files for account, network, campaign, creative, and change history reports.
3. Implement metric definitions and period helpers.
4. Implement account-level yesterday vs SDLW slice and answer flow.
5. Add WoW, MoM, and MTD account comparisons.
6. Add network and campaign delta diagnosis.
7. Add bid/budget recommendation rules.
8. Add Google Ads mutation planning for approved bid and budget changes.
9. Add creative underperformance slice.
10. Add change history summary.
11. Add project-local agent skill references for each supported question.
12. Add wiki save flow with `index.md` backlinks.
13. Add fixture-based tests for every slice contract.

This order validates the product from daily account reporting outward into diagnosis and recommendations.

## Guiding Principle

Bob should be opinionated about the workflow but humble about decisions. It should compute consistently, explain clearly, and ask for acceptance before turning analysis into memory or action.
