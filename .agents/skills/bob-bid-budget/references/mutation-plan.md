# Mutation Plan — Review and Apply

## Workflow

1. Run `bid-budget-recommend` to generate the plan.
2. Show the plan to the user for review.
3. Only after explicit approval ("make it live", "apply it", "go ahead") — run `bid-budget-apply`.

## Step 1 — Generate Plan

```bash
python3 lib/datapull.py bid-budget-recommend --dry-run   # preview without writing files
python3 lib/datapull.py bid-budget-recommend              # write CSV + YAML
```

Output files:
- `data/processed/bid-budget-recs/{customer}_{YYYY-MM-DD}.csv`
- `wiki/action-items/bid-budget-{YYYY-MM-DD}.yaml`

## Step 2 — Present to User

Present a summary table before asking for approval:

```
Campaign                                       Action              Cur tCPA  New tCPA  Cur Bgt   New Bgt
─────────────────────────────────────────────────────────────────────────────────────────────────────────
Acme_iOS_SEARCH_Stable                         increase_bid        $65.00    $71.50    $5,000    —
Acme_iOS_CONTENT_Promo                         decrease_bid        $90.00    $81.00    $3,000    —
Acme_Android_SEARCH_Growth                     hold                —         —         —         —
```

State the holds and skips with reasons. Bob should call out the 1-2 campaigns that matter most.

## Step 3 — Apply (Only After Explicit Approval)

```bash
python3 lib/datapull.py bid-budget-apply --plan wiki/action-items/bid-budget-YYYY-MM-DD.yaml
```

The command:
- Verifies `applied: false` (errors if already applied)
- Calls `CampaignService.mutate_campaigns()` for Target CPA changes
- Calls `CampaignBudgetService.mutate_campaign_budgets()` for budget changes
- Updates YAML in-place: `applied: true`, `applied_at`, `applied_by: "bid-budget-apply"`
- Prints per-campaign success/failure

## Safety Gates

- Bob must show the plan table before any `bid-budget-apply` call — no silent applies.
- If the user says "undo" or "revert" after applying, Bob cannot reverse via API. Tell the user to log into Google Ads directly.
- If the YAML is missing, ask the user for the correct path rather than guessing.

## Dependencies

```bash
pip install google-ads pyyaml
```

Google Ads credentials path is set in `.bob/profile.json` → `google_ads_config_path`.
