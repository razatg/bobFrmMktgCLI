# Mutation Plan — Review and Apply

## Workflow

1. Recover a matching saved proposal first. Run `bid-budget-recommend` only for a new or explicitly rebuilt proposal.
2. Show the plan to the user for review.
3. Record/link the decision, get the saved draft's hash with `bid-budget-validate` (offline), and obtain approval for that exact proposal.
4. Only after explicit approval ("make it live", "apply it", "go ahead") — run `bid-budget-apply`. It reads current campaign settings before executing. If that read times out, no mutation is sent; report the execution blocker without withdrawing the earlier recommendation.

## Step 1 — Generate Plan

```bash
./bob bid-budget-recommend --dry-run   # preview without writing files
./bob bid-budget-recommend              # write CSV + YAML
```

Output files:
- `data/processed/bid-budget-recs/{customer}_{YYYY-MM-DD}.csv`
- `wiki/{customer_id}/action-items/bid-budget-{YYYY-MM-DD}.yaml`

For an existing proposal, search with `./bob search "<proposal or campaign identifier>" --kind action`, read the matching YAML and inspect scope, decision and execution receipts. Missing hash output does not require rebuilding: `./bob bid-budget-validate --plan <saved-plan>` recalculates it offline. Confirm that explicit approval covers that exact saved proposal; a matching hash alone is not consent. If the plan is missing or ambiguous, resolve that before execution. Do not ask for a special phrase to continue.

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
./bob bid-budget-apply --approval-hash APPROVED_HASH --plan wiki/{customer_id}/action-items/bid-budget-YYYY-MM-DD.yaml
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
- If the YAML cannot be recovered through selected-account search or an existing artifact link, explain the missing evidence and ask for the plan or offer a rebuild for review. Never assume a missing hash means a missing plan.

## Dependencies

```bash
pip install google-ads pyyaml
```

Google Ads read credentials path is set in `.bob/accounts/{customer_id}/profile.json` → `google_ads_read_config_path`; write credentials use `google_ads_write_config_path`.
