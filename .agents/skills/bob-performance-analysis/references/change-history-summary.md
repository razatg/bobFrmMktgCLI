# Change History Summary

Use for questions asking what the team worked on yesterday, this week, or this month.

## Intent

`change_history_summary`

## Required Inputs

- Change history raw output (14-day window, fetched by bootstrap)
- Optional: `campaign_network_period` processed slices for performance context alongside changes

## CLI Commands

```bash
# Change history raw file (fetched by bootstrap):
# garf/outputs/raw/change_history/<account>_<start>_<end>_<run>.csv

# Re-fetch for a wider or custom window:
python3 lib/datapull.py fetch --query change_history --days <N>

# For performance context alongside changes:
python3 lib/datapull.py aggregate --grain campaign_network_period \
  --input garf/outputs/raw/campaign_network_period/<account>_<start>_<end>_<run>.csv
```

## Period Defaults

| User asks | Filter on changed_at |
|---|---|
| "yesterday" | `changed_at` date = yesterday |
| "this week" | `changed_at` date in last 7 days |
| "last 14 days" | full bootstrap window (default) |

Filter raw CSV rows by the first 10 characters of `changed_at` (YYYY-MM-DD).

## Summary Rules

Group changes by: date → campaign → actor (user_email) → change category.

Call out these change categories explicitly:

| Category | What to look for |
|---|---|
| Budget | `change_resource_type = CAMPAIGN_BUDGET`, old vs new `daily_budget` |
| Bid strategy | `change_resource_type = CAMPAIGN`, bid-strategy or target CPA/ROAS fields |
| Conversion action | conversion action addition or removal at campaign level |
| Asset | `change_resource_type = AD_GROUP_AD` or `ASSET` — new uploads or removals |
| Campaign status | `operation = UPDATE`, status field (ENABLED / PAUSED / REMOVED) |
| Ad group | `change_resource_type = AD_GROUP` — status, bid, name changes |
| Targeting | geo, audience, bid modifier changes |

Connect a change to a performance shift only when:
1. The `campaign_id` matches a campaign showing a delta in performance data.
2. The `changed_at` date falls within or just before the comparison window.

Do not assert causality from timing alone — say "change coincides with shift" not "change caused shift".

## Output

1. Total changes in the period and busiest campaign or actor.
2. Grouped change table: date | campaign | actor | change_type | old_value | new_value.
3. Notable changes flagged for performance review (budget, bid, or conversion action changes on campaigns with meaningful performance delta).
4. Links to related delta diagnosis analyses when available.

## Wiki / Artefact

After user confirms useful, offer one or both:

```
Save change summary?   → wiki/analyses/change-history-<period>-<YYYY-MM-DD>.md
Create follow-up item? → wiki/action-items/follow-up-<YYYY-MM-DD>.md
```

File structure for change summary:

```markdown
---
date: <YYYY-MM-DD>
intent: change_history_summary
period: <yesterday|this_week|custom>
---

# Change History: <period> (as of <YYYY-MM-DD>)

## Summary
<total changes, busiest campaign, busiest actor>

## Change Log

| Date | Campaign | Actor | Change Type | Old Value | New Value |
|---|---|---|---|---|---|

## Notable Changes (Need Performance Review)
- <list: change + which campaign + why it matters>

## Follow-up Actions
- <if any>
```

File structure for follow-up action item:

```markdown
---
date: <YYYY-MM-DD>
type: follow-up
source: change_history
---

# Follow-up: <topic> — <YYYY-MM-DD>

## Context
<what change triggered this follow-up>

## Action Required
<what to check or do>

## Due
<next bootstrap run / next week / specific date>
```
