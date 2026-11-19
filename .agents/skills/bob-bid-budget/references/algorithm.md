# Bid/Budget Decision Algorithm

## Signal Inputs

Two signals, each compared against the average of the prior two rolling seven-day windows (W-1
and W-2):

- **W0** = the seven calendar days ending yesterday.
- **W-1 and W-2** = the two preceding contiguous seven-day windows.

- **CPI** = W0 cost / W0 installs
- **CPM** = W0 cost / W0 impressions × 1000
- **Reference CPI** = (W-1 CPI + W-2 CPI) / 2
- **Reference CPM** = (W-1 CPM + W-2 CPM) / 2

CPM tolerance band: W0 CPM ≤ ref_CPM × 1.05 counts as "lower or same."

## Decision Matrix

| CPI vs ref | CPM vs ref | Interpretation | Action |
|---|---|---|---|
| Lower | Lower or same | Converting better, buying efficient | Increase bid; also increase budget if constrained |
| Lower | Higher | Converting better but buying less efficient | Hold — temporary, won't last |
| Higher | Higher or same | Converting worse, buying less efficient | Decrease bid; also decrease budget if constrained |
| Higher | Lower | Converting worse but buying getting cheaper | Hold — wait and watch |

**Budget-constrained**: 7-day actual spend ≥ 90% of (daily_budget × 7).

**"Increase bid"** = RAISE Target CPA value (e.g. ₹65 → ₹71.50 at 10%). A higher Target CPA allows Google to bid more aggressively, capturing more volume.

**"Decrease bid"** = LOWER Target CPA value (e.g. ₹65 → ₹58.50 at 10%). A lower Target CPA restricts bids to protect efficiency.

## Guidance for reviewing the baseline

| Reference | How Bob should use it |
|---|---|
| Acquisition cost reference | Compare W0 CPA with the saved reference; discuss whether efficiency or volume matters more. Above-reference cost is a warning, not an automatic skip. |
| Minimum volume | Below 10 installs is a weak-evidence warning; investigate maturity and uncertainty. |
| Conv% declining | Hold (do not increase) if post-install conv% (in_app / installs) drops >5% from W-1 to W0 — more volume won't help until quality improves |
| Preferred wait | A recent change calls for checking learning and conversion lag; it does not automatically exclude the campaign. |
| Usual adjustment | Use the saved percentage as a starting point. Explain evidence-backed departures and their risks. |

## Magnitude

```
pct = profile.bid_budget_change_pct   # reference size; default 10

# Increase bid (raise Target CPA)
new_target_cpa = current_target_cpa × (1 + pct / 100)

# Decrease bid (lower Target CPA)
new_target_cpa = current_target_cpa × (1 − pct / 100)

# Budget change (same pct)
new_daily_budget = current_daily_budget × (1 ± pct / 100)
```

## CLI Command

```bash
# Generate recommendations from the exact current W0 campaign trend and
# the selected account's newest bid_budget_inputs file.
./bob bid-budget-recommend

# Override inputs explicitly
./bob bid-budget-recommend \
  --trend data/processed/campaign-trend/<file>.csv \
  --bid-budget garf/outputs/raw/bid_budget_inputs/<file>.csv

# Override profile defaults at runtime
./bob bid-budget-recommend --cac-ceiling 150 --change-pct 15
```

## Output

Two files (suppressed with `--dry-run`):

- `data/processed/bid-budget-recs/{customer}_{date}.csv` — human-readable per-campaign table
- `wiki/action-items/bid-budget-{date}.yaml` — machine-readable mutation plan for `bid-budget-apply`

The YAML plan has `applied: false`. It will not be re-applied once `applied: true` is set.
