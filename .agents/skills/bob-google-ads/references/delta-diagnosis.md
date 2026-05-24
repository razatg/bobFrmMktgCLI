# Delta Diagnosis

Use for questions asking what caused performance to improve or deteriorate.

## Intent

`performance_delta_diagnosis`

## Required Inputs

- `.bob/profile.json`
- `account_network_period` slices for both comparison periods (Tier 1)
- `campaign_network_period` slices for both comparison periods (Tier 2a)
- `change_history` raw output for the same date window (Tier 2b — no extra fetch needed)
- `adgroup_network_period` slices on demand for top deviating campaigns (Tier 3)

## CLI Commands

**Tier 1 — Account × Network (aggregated from bootstrap raw files):**
```bash
ls garf/outputs/raw/account_network_period/
python3 lib/datapull.py aggregate --grain account_network_period
ls data/processed/account-network/
```

**Tier 2a — Campaign × Network:**
```bash
ls garf/outputs/raw/campaign_network_period/
python3 lib/datapull.py aggregate --grain campaign_network_period
ls data/processed/campaign-network/
```

**Tier 2b — Change history correlation (no new fetch — reuse bootstrap output):**
```bash
# Find the change history file
ls garf/outputs/raw/change_history/

# Filter for a campaign and date window (read CSV and filter by campaign_id and changed_at date)
# changed_at format: YYYY-MM-DD HH:MM:SS — compare first 10 chars to date range
# campaign_id column matches the campaign IDs from Tier 2a output
```

**Tier 3 — Ad Group × Network (on demand, not in bootstrap — fetch fresh):**
```bash
python3 lib/datapull.py fetch --query adgroup_network_period --from <start> --to <end>
ls garf/outputs/raw/adgroup_network_period/
python3 lib/datapull.py aggregate --grain adgroup_network_period
ls data/processed/adgroup-network/
```

## Diagnosis Order

Work top-down. Show each tier's result before drilling deeper.

**Step 1 — Confirm account movement.**
Read Tier 1 slices. State what moved: primary goal, cost, CTR %, CTI %, conversion_rate %. Confirm direction and magnitude.

**Step 2 — Attribute by network.**
From Tier 1 network breakdown: which network(s) drove the majority of the absolute delta? Rank by absolute delta contribution, not percent change alone.

**Step 3 — Top campaign contributors.**
From Tier 2a: rank campaigns by absolute delta in primary goal and cost. Separate:
- High-volume campaigns with meaningful delta (most important).
- Low-volume campaigns with high percent change (note but do not overstate).
- Volume drivers: impressions / clicks changed, efficiency stable.
- Efficiency drivers: CTI % / conversion_rate % changed, impressions stable.

**Step 4 — Ad group drill-down (Tier 3).**
Trigger when: a single campaign accounts for > 30% of total delta OR user explicitly asks "which ad group". Fetch `adgroup_network_period` for the same date window and those campaign(s). Show which ad groups within the campaign drove the movement.

**Step 5 — Change history overlay.**
For every campaign identified in Steps 3–4, call `correlate_change_history()` for the comparison period. Surface any bid, budget, conversion action, status, or asset changes that overlap in time and entity. State the change and its proximity to the performance shift. Do not assert causality from timing alone — say "change coincides with shift" not "change caused shift".

## Driver Rules

- Contribution to delta > percent change alone.
- Do not overstate low-volume movements.
- Volume movement: impressions / clicks changed, efficiency stable → budget, targeting, or auction competitiveness.
- Efficiency movement: conversions per click changed, impressions stable → bid strategy, creative quality, or conversion action change.

## Output

1. Account movement confirmation (one sentence).
2. Network attribution table: network | current | baseline | Δ abs | Δ %.
3. Top campaign drivers table: campaign | network | metric | Δ abs | Δ % | driver type.
4. Ad group table if Tier 3 triggered.
5. Change history events for implicated campaigns: changed_at | campaign | change_type | old_value | new_value.
6. Most likely cause (one sentence).
7. What needs follow-up before recommending bid or budget changes.

## Wiki / Artefact

After user confirms the diagnosis, offer to save:

```
Save diagnosis to wiki? → wiki/analyses/delta-<period>-<YYYY-MM-DD>.md
```

File structure:

```markdown
---
date: <YYYY-MM-DD>
intent: performance_delta_diagnosis
period: <period>
---

# Delta Diagnosis: <period> (<start>–<end> vs <baseline_start>–<baseline_end>)

## Account Movement
<sentence>

## Network Attribution
| Network | Current | Baseline | Δ abs | Δ % |
|---|---|---|---|---|

## Top Campaign Drivers
| Campaign | Network | Metric | Δ abs | Δ % | Driver type |
|---|---|---|---|---|---|

## Ad Group Breakdown
| Campaign | Ad Group | Network | Metric | Δ abs | Δ % |
|---|---|---|---|---|---|

## Change History Events
| Date | Campaign | Change type | Old value | New value |
|---|---|---|---|---|

## Most Likely Cause
<sentence>

## Open Questions / Follow-up
- <list>
```
