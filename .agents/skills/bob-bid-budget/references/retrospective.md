# Retrospective — Did the Changes Work?

Use when the user asks whether applied bid/budget changes are working, what effect they had, or whether to hold/extend/revert.

## CLI Command

```bash
python3 lib/datapull.py bid-budget-retrospective --plan wiki/action-items/bid-budget-YYYY-MM-DD.yaml
```

Requires:
- An applied YAML plan (`applied: true`)
- Processed `campaign-network` files for W+1 and W+2 after the applied date

If W+1 or W+2 data is missing, fetch and aggregate first:
```bash
python3 lib/datapull.py fetch --query campaign_network_period --from DATE --to DATE --reason "retro: W+N check for bid changes applied YYYY-MM-DD"
python3 lib/datapull.py aggregate --grain campaign_network_period
```

## Verdict Logic

Each changed campaign gets one of three verdicts:

| Verdict | Condition |
|---|---|
| `working` | CPI moved in the expected direction in both W+1 and W+2 |
| `too_early` | Only W+1 available, or W+1 confirms but W+2 doesn't yet |
| `not_working` | CPI moved opposite to expected direction in both W+1 and W+2 |

**Expected direction:**
- For `increase_bid` / `increase_bid_and_budget` actions → CPI should be lower (more volume, holding or improving efficiency)
- For `decrease_bid` / `decrease_bid_and_budget` actions → CPI should be lower (efficiency improving at lower volume)

## How Bob Presents Results

Bob leads with the overall verdict, then the per-campaign table.

**Example — working:**
> W21 and W22 are confirming the call. The two campaigns we raised on are converting 12% cheaper than the W20 baseline. Holding direction for now — no new changes needed.

**Example — not_working:**
> The CONTENT campaigns we increased on W20 are going the wrong way. CPI is up 18% in W21 and W22 vs baseline. I'd lower those back down this week.

**Example — too_early:**
> Only one week of post-change data. W21 is looking positive but I need W22 to confirm before calling it. Check back next week.

## Per-Campaign Table

| Campaign | Action | Baseline CPI | W+1 CPI | W+2 CPI | Verdict |
|---|---|---|---|---|---|
| Acme_iOS_SEARCH_Stable | increase_bid | $65.00 | $58.40 | $57.20 | working |
| Acme_iOS_CONTENT_Promo | decrease_bid | $90.00 | $96.00 | — | too_early |

Baseline CPI = W0 CPI from the YAML plan (pre-change snapshot).

## Next Action Options

After presenting verdicts, Bob suggests one of:
- **Extend the change**: if `working`, consider whether a second round is warranted
- **Hold and watch**: if `too_early`, come back next week
- **Revert or go further**: if `not_working`, lower bids further or revert in Google Ads UI
