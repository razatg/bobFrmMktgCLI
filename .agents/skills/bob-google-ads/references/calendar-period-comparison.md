# Calendar Period Comparison

Use for questions comparing two specific ISO weeks or two calendar months (MTD or full).

Examples: "W20 vs W19", "week 20 vs week 19", "compare May MTD with April", "how did May compare to last month".

## Intent

`calendar_period_comparison`

## Required Inputs

- `.bob/profile.json`
- Processed `account_network_period` and/or `campaign_network_period` files for both comparison windows

## CLI Commands

### ISO Week Comparison

```bash
# Compare last complete week vs the week before (default)
python3 lib/datapull.py compare-weeks

# Compare specific weeks
python3 lib/datapull.py compare-weeks --week 20 --vs 19

# Account level only
python3 lib/datapull.py compare-weeks --week 20 --vs 19 --grain account

# Campaign level only, with name filter
python3 lib/datapull.py compare-weeks --week 20 --vs 19 --grain campaign --name-contains "Stable"

# Save full campaign CSV
python3 lib/datapull.py compare-weeks --week 20 --vs 19 --output FILE
```

### Month Comparison (MTD by default)

```bash
# Compare current month MTD vs prior month MTD (default)
python3 lib/datapull.py compare-months

# Compare specific months MTD: May 1–19 vs Apr 1–19
python3 lib/datapull.py compare-months --month 5 --vs 4

# Full calendar months (May 1–31 vs Apr 1–30)
python3 lib/datapull.py compare-months --month 5 --vs 4 --full

# Campaign level with name filter
python3 lib/datapull.py compare-months --month 5 --vs 4 --grain campaign --name-contains "Brand"

# Save account + campaign CSVs
python3 lib/datapull.py compare-months --month 5 --vs 4 \
  --output-account FILE_ACCOUNT --output FILE_CAMPAIGN
```

### When processed files are missing

The command prints the exact fetch + aggregate commands needed. Run them, then re-run the comparison:

```bash
# Example: W20 campaign files missing
python3 lib/datapull.py fetch --query campaign_network_period --from 2026-05-11 --to 2026-05-17
python3 lib/datapull.py fetch --query campaign_network_period --from 2026-05-04 --to 2026-05-10
python3 lib/datapull.py aggregate --grain campaign_network_period
python3 lib/datapull.py compare-weeks --week 20 --vs 19
```

## Date Resolution

### ISO weeks
- `--week` defaults to last fully completed ISO week (Monday–Sunday ending before today)
- `--vs` defaults to `week - 1`
- ISO weeks run Monday–Sunday; `--week 20 --year 2026` = 2026-05-11–2026-05-17
- Week 1 of a year can start in late December of the prior year; week-0 wraps to last week of prior year automatically

### Months
- `--month` defaults to current calendar month
- `--vs` defaults to `month - 1` (wraps to December of prior year at January boundary)
- MTD (default): current month from 1st to yesterday; prior month from 1st to same day-of-month
- `--full`: both months from 1st to their last day (current month capped at yesterday if incomplete)
- When comparing months of different lengths (e.g. Jan vs Feb), MTD caps at the shorter month's length

## Output Structure

Both commands print to stdout:

**Account × Network table** (when `--grain account` or `--grain both`):

| Network | Cur Goal | Base Goal | Δ% | Cur Cost | Base Cost | Δ% |
|---|---|---|---|---|---|---|
| CONTENT | ... | ... | ... | ... | ... | ... |
| SEARCH | ... | ... | ... | ... | ... | ... |
| TOTAL | ... | ... | ... | ... | ... | ... |

**Campaign table** (when `--grain campaign` or `--grain both`), sorted by absolute goal Δ descending:

| Campaign | Cur Goal | Base Goal | Δ% | Cur Cost | Base Cost | Δ% |
|---|---|---|---|---|---|---|
| Campaign A | ... | ... | ... | ... | ... | ... |
| — TOTAL — | ... | ... | ... | ... | ... | ... |

The `--output` CSV includes all metrics: impressions, clicks, cost, installs, in_app_conversions, ctr_percent, cpc, cti_percent, conversion_rate_percent — current + baseline + delta_pct for volume metrics.

## Interpretation Rules

- Lead with the TOTAL row across both account and campaign tables.
- For weeks: a completed week is a full 7-day signal; state the exact dates.
- For months MTD: flag if the day count differs significantly (e.g. April had a public holiday reducing trading days). Do not over-interpret MTD with fewer than 7 days elapsed.
- Apply significance thresholds:

| Metric | Threshold for flagging |
|---|---|
| Primary goal conversions | > 10% change |
| Cost | > 15% change |
| CTR % | > 1 percentage point |
| CTI % or conversion_rate % | > 1 percentage point |

If totals cross any threshold, automatically proceed to delta diagnosis: use `references/delta-diagnosis.md` with the same date windows.

## Wiki / Artefact

After user confirms the analysis is useful, offer to save:

```
Save to wiki? → wiki/analyses/week-comparison-W<N>-vs-W<M>-<YYYY-MM-DD>.md
             → wiki/analyses/month-comparison-<Mon>-vs-<Mon>-<YYYY-MM-DD>.md
```

File structure:

```markdown
---
date: <YYYY-MM-DD>
intent: calendar_period_comparison
period_type: <iso_week|month_mtd|month_full>
current: <W20 2026-05-11–2026-05-17 | May 2026 MTD>
baseline: <W19 2026-05-04–2026-05-10 | Apr 2026 MTD>
---

# <Period Type> Comparison: <current> vs <baseline>

## Summary
<1–2 sentences: total goal Δ and cost Δ, overall direction>

## Account × Network
| Network | Current | Baseline | Δ abs | Δ % |
|---|---|---|---|---|

## Top Campaign Movers
| Campaign | Status | Cur Goal | Base Goal | Δ% | Cur Cost | Base Cost | Δ% |
|---|---|---|---|---|---|---|---|

## Flags
- <significant movers, campaigns appearing/disappearing>

## Follow-up Actions
- <if any — e.g. trigger delta diagnosis on Campaign X>
```
