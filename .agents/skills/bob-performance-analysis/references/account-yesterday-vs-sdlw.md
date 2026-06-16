# Account Yesterday Vs SDLW

Use for questions like:

- "What was performance yesterday?"
- "What happened yesterday vs same day last week?"
- "How did the account do yesterday compared to SDLW?"

## Intent

`account_performance_comparison`

## Date Logic

- Current period: yesterday (D-1).
- Baseline: same day last week (D-8).
- State the exact dates in the answer.

## Required Inputs

- `.bob/profile.json`
- Two `account_network_period` processed slices — one for yesterday, one for SDLW

## CLI Commands

Bootstrap pre-fetches these. Check what's available, then aggregate:

```bash
# See which raw files exist
ls garf/outputs/raw/account_network_period/

# Aggregate all available account_network_period raw files
python3 lib/datapull.py aggregate --grain account_network_period
# Output lands in data/processed/account-network/

# See processed outputs — pick the yesterday and SDLW files by date in filename
ls data/processed/account-network/
```

To re-fetch if missing:

```bash
python3 lib/datapull.py fetch --query account_network_period --from <yesterday> --to <yesterday>
python3 lib/datapull.py fetch --query account_network_period --from <sdlw> --to <sdlw>
python3 lib/datapull.py aggregate --grain account_network_period
```

## Output

- Lead with primary goal movement (absolute delta and percent delta).
- Full metric table: impressions, clicks, cost, installs, in_app_conversions, CTR %, CPC, CTI %, conversion_rate %.
- Per-network breakdown from the two slices (Search, Display, YouTube, Play).
- Mention zero-denominator ratios explicitly.

## Significance Threshold and Auto-Escalation

Apply the shared significance thresholds and auto-escalation rule in `references/_common.md`, using the yesterday vs SDLW windows.

## Wiki / Artefact

Once the analysis is on screen, proactively offer to save — don't wait to be asked:

```
Save this to wiki? → wiki/analyses/account-yesterday-<YYYY-MM-DD>.md
```

File structure:

```markdown
---
date: <YYYY-MM-DD>
intent: account_performance_comparison
period: yesterday_vs_sdlw
---

# Account: Yesterday vs SDLW (<yesterday> vs <sdlw>)

## Headline
<1-2 sentence summary of what moved>

## Metric Table
| Metric | Yesterday | SDLW | Δ abs | Δ % |
|---|---|---|---|---|

## Network Breakdown
| Network | Yesterday | SDLW | Δ abs | Δ % |
|---|---|---|---|---|

## Drivers
- <bullet>

## Change History
<!-- Include only when change events were shown during the session. Copy directly from chat — never re-run. Omit this section entirely if no change events were found. -->
| Campaign | When | Change |
|---|---|---|
| <name> | <dates> | <description> |

## Follow-up Actions
- <if any>
```
