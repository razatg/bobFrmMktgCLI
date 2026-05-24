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

Compute automatically after showing the account table. If any threshold is crossed, **proceed to delta diagnosis without waiting for the user to ask**:

| Metric | Threshold |
|---|---|
| Primary goal conversions | > 10% change |
| Cost | > 15% change |
| CTR % | > 1 percentage point |
| CTI % or conversion_rate % | > 1 percentage point |

When escalating to delta diagnosis, use the same yesterday vs SDLW windows and follow `references/delta-diagnosis.md`:
1. Show network breakdown from `account_network_period` — which network drove the delta.
2. Show top campaign contributors from `campaign_network_period` yesterday vs SDLW slices (`data/processed/campaign-network/`).
3. Overlay change history: filter `garf/outputs/raw/change_history/` for the contributing campaigns on those dates using `correlate_change_history()`.

## Wiki / Artefact

After the user confirms the analysis is useful, offer to save:

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
