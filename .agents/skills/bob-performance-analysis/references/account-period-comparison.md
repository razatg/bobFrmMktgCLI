# Account Period Comparison

Use for questions about WoW, MoM, MTD, or account-level trend summaries.

## Intent

`account_period_comparison`

## Required Inputs

- `.bob/profile.json`
- Two `account_network_period` processed slices for the requested period

## Period Definitions

| Period | Current window | Baseline window |
|---|---|---|
| WoW | last 7 days (D-7 to D-1) | prior 7 days (D-14 to D-8) |
| MoM | last 30 days (D-30 to D-1) | prior 30 days (D-60 to D-31) |
| MTD | 1st of this month → D-1 | 1st of prior month → same day of prior month |

Always state the exact date windows used. Flag if a period is incomplete (e.g. MTD with only 3 days elapsed).

## CLI Commands

Bootstrap pre-fetches WoW, MoM, and MTD. Check what's available, then aggregate:

```bash
# See which raw files exist
ls garf/outputs/raw/account_network_period/

# Aggregate all available account_network_period raw files
python3 lib/datapull.py aggregate --grain account_network_period
# Output lands in data/processed/account-network/

# See processed outputs — date pairs in filenames identify each window
ls data/processed/account-network/
```

To re-fetch a specific period on demand:

```bash
python3 lib/datapull.py fetch --query account_network_period --from <start> --to <end>
python3 lib/datapull.py aggregate --grain account_network_period
```

## Output

- One compact table per requested period (or combined if multiple periods asked together).
- Prioritize: primary goal conversions, cost per goal, spend, volume.
- Include: impressions, clicks, cost, installs, in_app_conversions, CTR %, CPC, CTI %, conversion_rate %.
- Include per-network breakdown when available.
- Flag incomplete periods (e.g. "MTD is only 3 days; treat as directional").

## Significance Threshold and Auto-Escalation

Apply the shared significance thresholds and auto-escalation rule in `references/_common.md`, using the requested period's date windows.

## Wiki / Artefact

After the user confirms, offer to save:

```
Save this to wiki? → wiki/analyses/account-<period>-<YYYY-MM-DD>.md
```

File structure:

```markdown
---
date: <YYYY-MM-DD>
intent: account_period_comparison
period: <wow|mom|mtd>
---

# Account: <Period> Summary (<current_start>–<current_end> vs <baseline_start>–<baseline_end>)

## Headline
<1-2 sentences>

## Metric Table
| Metric | Current | Baseline | Δ abs | Δ % |
|---|---|---|---|---|

## Network Breakdown
| Network | Current | Baseline | Δ abs | Δ % |
|---|---|---|---|---|

## Drivers
- <bullet>

## Follow-up Actions
- <if any>
```
