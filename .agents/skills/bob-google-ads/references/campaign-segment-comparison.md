# Campaign Segment Comparison

Use for questions comparing performance of a named campaign group — e.g. "all campaigns with 'Stable' in their name", "how did the Brand campaigns do yesterday", "compare all UAC-iOS campaigns WoW".

## Intent

`campaign_segment_comparison`

## Required Inputs

- `.bob/profile.json`
- Two `campaign_network_period` processed files for the requested period (bootstrap pre-fetches yesterday_vs_sdlw, WoW, and 3-week rolling)

## CLI Commands

```bash
# Prerequisite: confirm processed campaign-network files exist
ls data/processed/campaign-network/

# Compare campaigns containing "Stable" yesterday vs SDLW (default period)
python3 lib/datapull.py slice-campaigns --name-contains "Stable"

# Other periods
python3 lib/datapull.py slice-campaigns --name-contains "Stable" --period wow
python3 lib/datapull.py slice-campaigns --name-contains "Stable" --period mom

# Save full comparison CSV
python3 lib/datapull.py slice-campaigns --name-contains "Stable" \
  --output data/processed/campaign-slices/stable-yesterday-vs-sdlw.csv

# Explicit files (if auto-detection fails)
python3 lib/datapull.py slice-campaigns \
  --name-contains "Stable" \
  --current data/processed/campaign-network/<account>_<yesterday>_<yesterday>.csv \
  --baseline data/processed/campaign-network/<account>_<sdlw>_<sdlw>.csv
```

If processed campaign-network files are missing, regenerate them first:
```bash
python3 lib/datapull.py aggregate --grain campaign_network_period
```

## Output Structure

The command prints a summary table to stdout:

| Campaign | Cur Goal | Base Goal | Δ% | Cur Cost | Base Cost | Δ% |
|---|---|---|---|---|---|---|
| Campaign A — Stable | ... | ... | ... | ... | ... | ... |
| — N matching campaigns — | (totals) | | | | | |

The last row is a TOTAL across all matching campaigns combined (metrics summed, ratios recalculated from sums).

The `--output` CSV includes all metrics: impressions, clicks, cost, installs, in_app_conversions, ctr_percent, cpc, cti_percent, conversion_rate_percent — both current and baseline values plus delta_pct for volume metrics.

## Interpretation Rules

- Lead with the TOTAL row — it gives the aggregate picture the user asked for.
- Then highlight individual campaigns with meaningful divergence from the group trend.
- A campaign present in current but not baseline (or vice versa) signals a status change — flag it.
- Apply the same significance thresholds as other period comparisons:

| Metric | Threshold for flagging |
|---|---|
| Primary goal conversions | > 10% change |
| Cost | > 15% change |
| CTR % | > 1 percentage point |
| CTI % or conversion_rate % | > 1 percentage point |

If the segment total crosses any threshold, automatically proceed to delta diagnosis on the matched campaigns: use `references/delta-diagnosis.md` for the same period windows, filtering to the implicated campaign IDs.

## When Processed Files Are Missing for the Period

Bootstrap pre-fetches `yesterday_vs_sdlw` and `3week_rolling` for `campaign_network_period`. For WoW and MoM, either:
- Re-run bootstrap, or
- Fetch manually:
```bash
python3 lib/datapull.py fetch --query campaign_network_period --from <start> --to <end>
python3 lib/datapull.py aggregate --grain campaign_network_period
```

## Wiki / Artefact

After user confirms the analysis is useful, offer to save:

```
Save segment comparison to wiki? → wiki/analyses/campaign-segment-<name>-<period>-<YYYY-MM-DD>.md
```

File structure:

```markdown
---
date: <YYYY-MM-DD>
intent: campaign_segment_comparison
segment: <name_contains filter>
period: <yesterday_vs_sdlw|wow|mom|mtd>
---

# Campaign Segment: "<segment>" — <period> (<current_start>–<current_end> vs <baseline_start>–<baseline_end>)

## Summary
<total matched campaigns, aggregate goal delta, aggregate cost delta — 1-2 sentences>

## Aggregate (Totals Row)
| Metric | Current | Baseline | Δ abs | Δ % |
|---|---|---|---|---|

## Per-Campaign Breakdown
| Campaign | Status | Cur Goal | Base Goal | Δ% | Cur Cost | Base Cost | Δ% |
|---|---|---|---|---|---|---|---|

## Flags
- <campaigns deviating meaningfully from group trend>
- <any campaigns appearing/disappearing between periods>

## Follow-up Actions
- <if any — e.g. trigger delta diagnosis on campaign X>
```
