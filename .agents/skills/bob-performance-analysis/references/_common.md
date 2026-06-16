# Shared reference blocks

Snippets shared across the bob-performance-analysis intent references. Linked from each reference rather than copied, so the thresholds stay defined in one place.

## Significance Thresholds & Auto-Escalation

Compute automatically after showing the comparison table. If **any** threshold is crossed, **proceed to delta diagnosis without waiting for the user to ask**:

| Metric | Threshold |
|---|---|
| Primary goal conversions | > 10% change |
| Cost | > 15% change |
| CTR % | > 1 percentage point |
| CTI % or conversion_rate % | > 1 percentage point |

(This mirrors the **Auto-escalation rule** in `CLAUDE.md`.)

**Escalation procedure** — follow `references/delta-diagnosis.md` using the *same date windows* as the comparison that triggered it:

1. Show the network breakdown from `account_network_period` — which network drove the delta.
2. Show top campaign contributors from `campaign_network_period` for the same windows (`data/processed/campaign-network/`).
3. Overlay change history: filter `garf/outputs/raw/change_history/` for the contributing campaigns on those dates via `correlate_change_history()`.

For a **campaign-segment** comparison, filter the escalation to the matched campaign IDs. For a **calendar-period** comparison, use the two calendar windows being compared.
