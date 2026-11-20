"""Bid and budget recommendation, application, and retrospective commands."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *  # noqa: F403
from lib.bob.platform.data import *  # noqa: F403
from lib.bob.platform.google_ads import *  # noqa: F403
from lib.bob.platform.presentation import *  # noqa: F403

def _write_plan_review(plan: dict, path: Path) -> dict:
    """Publish the exact saved choices and receipts as a customer-readable CSV."""
    receipts = plan.get('apply_results', [])
    fields = ['campaign_id', 'campaign_name', 'action', 'current_target_cpa', 'proposed_target_cpa',
              'current_daily_budget', 'proposed_daily_budget', 'rationale', 'forecast', 'status', 'reason']
    rows = []
    for change in plan.get('changes', []):
        results = [r for r in receipts if str(r.get('campaign_id')) == str(change.get('campaign_id'))]
        row = {key: change.get(key, '') for key in fields}
        row['status'] = '; '.join(f"{r['field']}: {r['status']}" for r in results) or 'proposed; not live checked'
        row['reason'] = '; '.join(dict.fromkeys(r['error'] for r in results if r.get('error')))
        rows.append(row)
    review = path.with_suffix('.review.csv')
    write_csv(review, rows, fields)
    result = {'review': str(review)}
    account = str(plan.get('customer_id', '')).replace('-', '')
    wiki = account_wiki_dir(account).resolve()
    if review.resolve().is_relative_to(wiki):
        relative = review.resolve().relative_to(wiki).as_posix()
        result['artifact'] = f'[[artifact:wiki/{account}/{relative}|Review proposal and results]]'
    return result


def bid_budget_recommend(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    cac_ceiling = float(args.cac_ceiling or profile.get("cac_ceiling", 200))
    change_pct = float(args.change_pct or profile.get("bid_budget_change_pct", 10))
    min_installs = 10
    budget_constrained_threshold = 0.90
    cpm_tolerance = 1.05
    cooldown_days = int(profile.get("bid_budget_cooldown_days", 14))

    customer_id = str(profile.get("google_ads_customer_id") or "").replace("-", "")
    trend_path, expected_windows = bid_budget_trend_path(customer_id, args.trend)
    trend_rows = read_csv(trend_path)
    validate_bid_budget_trend_rows(trend_rows, customer_id, expected_windows)

    # Load bid_budget_inputs for the same account as the validated trend.
    if args.bid_budget:
        bb_path = Path(args.bid_budget).expanduser()
    else:
        bb_path = newest_raw_for_customer("bid_budget_inputs", customer_id)
    bb_rows = read_csv(bb_path)
    foreign_bb_accounts = sorted({
        str(row.get("customer_id", "")).replace("-", "")
        for row in bb_rows
        if str(row.get("customer_id", "")).replace("-", "") != customer_id
    })
    if foreign_bb_accounts:
        die(
            "bid_budget_inputs contains missing or foreign customer IDs: "
            + ", ".join(account or "<missing>" for account in foreign_bb_accounts[:10])
        )

    # Index bid_budget_inputs by campaign_id (sum cost over 7 days per campaign)
    bb_index: dict[str, dict] = {}
    for row in bb_rows:
        cid = str(row.get("campaign_id", "")).replace("-", "")
        if cid not in bb_index:
            bb_index[cid] = dict(row)
            bb_index[cid]["_total_cost"] = 0.0
        bb_index[cid]["_total_cost"] += number(row.get("cost", 0))

    # Build cooldown index from change_history: last CAMPAIGN/CAMPAIGN_BUDGET update per campaign
    ch_index: dict[str, str] = {}  # campaign_id → most recent change date (ISO)
    try:
        ch_path = find_newest_raw_for_customer("change_history", customer_id)
        if ch_path and ch_path.exists():
            for row in read_csv(ch_path):
                cid = str(row.get("campaign_id", "")).replace("-", "")
                rtype = row.get("change_resource_type", "").upper()
                op = row.get("operation", "").upper()
                changed_at = (row.get("changed_at", "") or "")[:10]
                if cid and op == "UPDATE" and rtype in ("CAMPAIGN", "CAMPAIGN_BUDGET") and changed_at:
                    if cid not in ch_index or changed_at > ch_index[cid]:
                        ch_index[cid] = changed_at
    except (OSError, SystemExit):
        pass  # change_history is informational; don't block recommend if unavailable

    today_str = today().isoformat()

    changes: list[dict] = []
    holds: list[dict] = []
    skipped: list[dict] = []

    for row in trend_rows:
        cid = str(row.get("campaign_id", "")).replace("-", "")
        cname = row.get("campaign_name", "")
        cstatus = row.get("campaign_status", "")

        # Detect which ISO weeks are present
        try:
            w0_iso = int(row.get("current_iso_week", 0))
            w1_iso = int(row.get("prior1_iso_week", 0))
            w2_iso = int(row.get("prior2_iso_week", 0))
        except (ValueError, TypeError):
            skipped.append({"campaign_id": cid, "campaign_name": cname, "reason": "could not read ISO week columns"})
            continue

        def _w(iso: int, col: str) -> str:
            return row.get(f"w{iso}_{col}", "0") or "0"

        w0_cost = number(_w(w0_iso, "cost"))
        w0_inst = number(_w(w0_iso, "installs"))
        w0_imp = number(_w(w0_iso, "impressions"))
        w0_conv = number(_w(w0_iso, "in_app_conversions"))
        w1_cost = number(_w(w1_iso, "cost"))
        w1_inst = number(_w(w1_iso, "installs"))
        w1_imp = number(_w(w1_iso, "impressions"))
        w1_conv = number(_w(w1_iso, "in_app_conversions"))
        w2_cost = number(_w(w2_iso, "cost"))
        w2_inst = number(_w(w2_iso, "installs"))
        w2_imp = number(_w(w2_iso, "impressions"))

        # CPI = cost / installs
        w0_cpi = w0_cost / w0_inst if w0_inst > 0 else 0.0
        w1_cpi = w1_cost / w1_inst if w1_inst > 0 else 0.0
        w2_cpi = w2_cost / w2_inst if w2_inst > 0 else 0.0
        ref_cpi = (w1_cpi + w2_cpi) / 2 if (w1_cpi > 0 and w2_cpi > 0) else 0.0

        # CPM = cost / impressions * 1000
        w0_cpm = w0_cost / w0_imp * 1000 if w0_imp > 0 else 0.0
        w1_cpm = w1_cost / w1_imp * 1000 if w1_imp > 0 else 0.0
        w2_cpm = w2_cost / w2_imp * 1000 if w2_imp > 0 else 0.0
        ref_cpm = (w1_cpm + w2_cpm) / 2 if (w1_cpm > 0 and w2_cpm > 0) else 0.0

        # Post-install conversion rate (in_app / installs) for declining conv% guard
        w0_conv_rate = w0_conv / w0_inst * 100 if w0_inst > 0 and w0_conv > 0 else 0.0
        w1_conv_rate = w1_conv / w1_inst * 100 if w1_inst > 0 and w1_conv > 0 else 0.0
        conv_rate_declining = (
            w0_conv_rate > 0 and w1_conv_rate > 0
            and w0_conv_rate < w1_conv_rate * 0.95  # >5% drop in conv%
        )

        # Read bid_budget_inputs for this campaign early — needed by CAC guard
        bb = bb_index.get(cid, {})
        target_cpa_bid = number(bb.get("target_cpa", 0))

        # CPA for CAC guard: use actual W0 CPA if available; fall back to target_cpa bid
        w0_cpa = w0_cost / w0_conv if w0_conv > 0 else 0.0
        from .guards import eligibility
        last_change = ch_index.get(cid, "")
        vol_ok, cac_ok, cooldown_ok = eligibility(
            w0_inst, w0_cpa if w0_cpa > 0 else target_cpa_bid,
            dt.date.fromisoformat(last_change) if last_change else None,
            on_date=today(), ceiling=cac_ceiling, cooldown_days=cooldown_days)
        days_since_change = (
            (dt.date.fromisoformat(today_str) - dt.date.fromisoformat(last_change)).days
            if last_change else None
        )

        cpi_pct = (w0_cpi - ref_cpi) / ref_cpi * 100 if ref_cpi > 0 else 0.0
        cpm_pct = (w0_cpm - ref_cpm) / ref_cpm * 100 if ref_cpm > 0 else 0.0

        base_info = {
            "customer_id": row.get("customer_id", ""),
            "campaign_id": cid,
            "campaign_name": cname,
            "campaign_status": cstatus,
            "current_iso_week": w0_iso,
            "w0_cpi": format_float(w0_cpi),
            "ref_cpi": format_float(ref_cpi),
            "cpi_pct_vs_ref": format_float(cpi_pct),
            "w0_cpm": format_float(w0_cpm),
            "ref_cpm": format_float(ref_cpm),
            "cpm_pct_vs_ref": format_float(cpm_pct),
            "w0_cpa": format_float(w0_cpa),
            "cac_ceiling": format_float(cac_ceiling),
            "cac_guard_passed": str(cac_ok),
            "w0_installs": format_float(w0_inst),
            "min_installs_met": str(vol_ok),
            "last_bid_budget_change_date": last_change or "unknown",
            "days_since_last_change": str(days_since_change) if days_since_change is not None else "unknown",
            "cooldown_days": str(cooldown_days),
            "cooldown_ok": str(cooldown_ok),
        }

        guidance_notes = []
        if not vol_ok:
            guidance_notes.append(f'recent install volume is below the usual {min_installs} reference')
        if not cac_ok:
            guidance_notes.append(f'acquisition cost is above the {cac_ceiling:g} reference or conversion evidence is missing')
        if not cooldown_ok:
            guidance_notes.append(f'a recent change is within the preferred {cooldown_days}-day waiting period')
        if ref_cpi == 0:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": "insufficient prior-week data for CPI reference"})
            continue

        # Budget utilization (bb already read above for CAC guard)
        daily_budget = number(bb.get("daily_budget", 0))
        target_cpa = target_cpa_bid
        budget_id = bb.get("campaign_budget_id", "")
        actual_7d_cost = bb.get("_total_cost", w0_cost)
        utilization = actual_7d_cost / (daily_budget * 7) if daily_budget > 0 else 0.0
        budget_const = utilization >= budget_constrained_threshold

        base_info["budget_utilization_pct"] = format_float(utilization * 100)
        base_info["budget_constrained"] = str(budget_const)
        base_info["w0_conv_rate_pct"] = format_float(round(w0_conv_rate, 2))
        base_info["w1_conv_rate_pct"] = format_float(round(w1_conv_rate, 2))
        base_info["conv_rate_declining"] = str(conv_rate_declining)
        base_info["current_target_cpa"] = format_float(target_cpa)
        base_info["current_daily_budget"] = format_float(daily_budget)
        base_info["campaign_budget_id"] = budget_id

        cpi_lower = w0_cpi < ref_cpi
        cpm_lower_or_same = w0_cpm <= ref_cpm * cpm_tolerance

        if cpi_lower and cpm_lower_or_same:
            # Conv% declining overrides any increase — more volume won't convert
            if conv_rate_declining:
                holds.append({**base_info,
                              "reason": (f"CPI efficient but post-install conv% declining "
                                         f"({w1_conv_rate:.1f}%% → {w0_conv_rate:.1f}%%) — "
                                         f"more installs won't convert until quality improves; hold")})
                continue
            if budget_const:
                action = "increase_bid_and_budget"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% below ref, "
                             f"CPM flat/lower, budget constrained — scale bid+budget")
            else:
                action = "increase_bid"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% below ref, "
                             f"CPM flat/lower, budget headroom available — scale bid")
            forecast = f"Higher spend and volume; CPI may edge up slightly toward target"
        elif cpi_lower and not cpm_lower_or_same:
            holds.append({**base_info,
                          "reason": f"CPM rising {cpm_pct:.1f}%% — CPI improvement is likely temporary; hold"})
            continue
        elif not cpi_lower and cpm_lower_or_same:
            holds.append({**base_info,
                          "reason": f"CPI worsening but CPM improving {abs(cpm_pct):.1f}%% — buying getting cheaper; wait"})
            continue
        else:
            if budget_const:
                action = "decrease_bid_and_budget"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% above ref, "
                             f"CPM also up, budget constrained — protect efficiency")
            else:
                action = "decrease_bid"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% above ref, "
                             f"CPM also up — tighten bid to protect CPI")
            forecast = f"Lower spend and volume; CPI should improve toward target"

        new_tgt = new_bgt = None
        if "bid" in action and target_cpa > 0:
            new_tgt = target_cpa * (1 + change_pct / 100) if "increase" in action else target_cpa * (1 - change_pct / 100)
        if "budget" in action and daily_budget > 0:
            new_bgt = daily_budget * (1 + change_pct / 100) if "increase" in action else daily_budget * (1 - change_pct / 100)

        if guidance_notes:
            rationale += '. Review guidance: ' + '; '.join(guidance_notes)
        changes.append({
            **base_info,
            "action": action,
            "rationale": rationale,
            "forecast": forecast,
            "proposed_target_cpa": format_float(new_tgt) if new_tgt else "",
            "proposed_daily_budget": format_float(new_bgt) if new_bgt else "",
        })

    # Print summary
    current_iso = trend_rows[0].get("current_iso_week", "?") if trend_rows else "?"
    print(f"\nBid/Budget Recommendations — W{current_iso}")
    print(f"  {len(changes)} changes  |  {len(holds)} holds  |  {len(skipped)} skipped\n")
    if changes:
        hdr = f"  {'Campaign':<45}  {'Action':<26}  {'Cur tCPA':>10}  {'New tCPA':>10}  {'Cur Bgt':>10}  {'New Bgt':>10}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for c in changes:
            print(
                f"  {c['campaign_name']:<45}  {c['action']:<26}  "
                f"{_fmt_display(c['current_target_cpa'], 'cost', _currency_symbol(profile.get('currency', '')))  :>10}  "
                f"{_fmt_display(c.get('proposed_target_cpa', 'NA'), 'cost', _currency_symbol(profile.get('currency', ''))):>10}  "
                f"{_fmt_display(c['current_daily_budget'], 'cost', _currency_symbol(profile.get('currency', ''))):>10}  "
                f"{_fmt_display(c.get('proposed_daily_budget', 'NA'), 'cost', _currency_symbol(profile.get('currency', ''))):>10}"
            )
            if 'Review guidance:' in c['rationale']:
                print('    ' + c['rationale'].split('Review guidance:', 1)[1].strip())

    if args.dry_run:
        print("\n[dry-run] no files written")
        return

    # Write CSV
    customer = customer_id or "unknown"
    date_str = today().isoformat()
    csv_path = Path(args.output).expanduser() if args.output else (
        account_processed_dir(customer, "bid-budget-recs") / f"{customer}_{date_str}.csv"
    )
    all_rows = [{**c, **{k: "" for k in BID_BUDGET_REC_COLUMNS if k not in c}} for c in changes]
    write_csv(csv_path, all_rows, BID_BUDGET_REC_COLUMNS)
    print(f"\nrecommendation CSV written: {csv_path}")

    # Write YAML plan
    wiki_base = account_wiki_dir(customer) if customer != "unknown" else STATE_ROOT / "wiki"
    yaml_path = Path(args.yaml_output).expanduser() if args.yaml_output else (
        wiki_base / "action-items" / f"bid-budget-{date_str}.yaml"
    )
    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import yaml as _yaml
        plan = {
            "decision_required": True,
            "generated": date_str,
            "customer_id": str(customer).replace("-", ""),
            "current_iso_week": int(current_iso) if str(current_iso).isdigit() else current_iso,
            "signal_basis": f"W{current_iso} CPI vs avg(prior 2 weeks)",
            "cac_ceiling": cac_ceiling,
            "change_pct": change_pct,
            "cooldown_days": cooldown_days,
            "changes": [
                {
                    "campaign_id": c["campaign_id"],
                    "campaign_name": c["campaign_name"],
                    "action": c["action"],
                    "field": "target_cpa" if "bid" in c["action"] else "daily_budget",
                    "current_target_cpa": number(c["current_target_cpa"]),
                    "proposed_target_cpa": number(c["proposed_target_cpa"]) if c.get("proposed_target_cpa") else None,
                    "current_daily_budget": number(c["current_daily_budget"]),
                    "proposed_daily_budget": number(c["proposed_daily_budget"]) if c.get("proposed_daily_budget") else None,
                    "campaign_budget_id": c.get("campaign_budget_id", ""),
                    "w0_cpi": number(c["w0_cpi"]),
                    "ref_cpi": number(c["ref_cpi"]),
                    "w0_cpm": number(c["w0_cpm"]),
                    "ref_cpm": number(c["ref_cpm"]),
                    "w0_conv_rate_pct": number(c.get("w0_conv_rate_pct", 0)),
                    "w1_conv_rate_pct": number(c.get("w1_conv_rate_pct", 0)),
                    "conv_rate_declining": c.get("conv_rate_declining", "False") == "True",
                    "last_bid_budget_change_date": c.get("last_bid_budget_change_date", "unknown"),
                    "days_since_last_change": c.get("days_since_last_change", "unknown"),
                    "cooldown_ok": c.get("cooldown_ok", "True") == "True",
                    "rationale": c["rationale"],
                    "forecast": c["forecast"],
                    "cac_guard_passed": c["cac_guard_passed"] == "True",
                }
                for c in changes
            ],
            "skipped": [{"campaign_id": s["campaign_id"], "campaign_name": s["campaign_name"], "reason": s["reason"]} for s in skipped],
            "applied": False,
            "applied_at": None,
            "applied_by": None,
        }
        import copy
        plan["baseline_changes"] = copy.deepcopy(plan["changes"])
        yaml_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
        print(f"mutation plan written: {yaml_path}")
        print(json.dumps(_write_plan_review(plan, yaml_path)))
    except ImportError:
        print("note: pyyaml not installed — YAML plan not written. Run: pip install pyyaml")


def bid_budget_propose(args: argparse.Namespace) -> None:
    """Save a discretionary final proposal without applying or approving it."""
    import json
    import math
    import yaml
    from .guards import plan_hash
    profile = load_profile(required=True)
    account = str(profile['google_ads_customer_id']).replace('-', '')
    original = Path(args.plan).resolve()
    target = Path(args.output).resolve()
    wiki = account_wiki_dir(account).resolve()
    if not original.is_relative_to(wiki) or not target.is_relative_to(wiki):
        die('baseline and final proposal must stay in the selected account wiki')
    plan = yaml.safe_load(original.read_text())
    if str(plan.get('customer_id', '')).replace('-', '') != account or plan.get('applied'):
        die('baseline must be unapplied and belong to the selected account')
    if plan.get('apply_results') or plan.get('applied_at'):
        die('execution has started; preserve receipts and reconcile or retry the existing plan')
    changes = json.loads(args.changes_json)
    allowed = {'campaign_id', 'campaign_name', 'action', 'proposed_target_cpa', 'proposed_daily_budget',
               'campaign_budget_id', 'rationale', 'forecast'}
    if not isinstance(changes, list) or len(changes) > 1000:
        die('changes must be a bounded list')
    baseline = {str(row['campaign_id']): row for row in plan.get('changes', [])}
    merged = []
    for change in changes:
        if not isinstance(change, dict):
            die('each proposal must be an object')
        base = baseline.get(str(change.get('campaign_id', '')), {})
        unexpected = set(change) - allowed - set(base)
        if unexpected:
            die('unsupported bid proposal fields: ' + ', '.join(sorted(unexpected)))
        change = dict(base, **change)
        if not change.get('rationale'):
            die('each proposal requires an evidence-backed rationale')
        if not str(change.get('campaign_id', '')).isdigit():
            die('each proposal requires an exact campaign ID')
        for field in ('proposed_target_cpa', 'proposed_daily_budget'):
            if change.get(field) is not None and not math.isfinite(float(change[field])):
                die('proposed values must be finite')
        merged.append(change)
    changes = merged
    if len({str(row['campaign_id']) for row in changes}) != len(changes):
        die('duplicate campaign actions')
    plan.setdefault('baseline_changes', plan.get('changes', []))
    plan.update(changes=changes, decision_required=True, applied=False)
    for field in ('approved_hash', 'apply_results', 'applied_at', 'applied_by', 'decision_id'):
        plan.pop(field, None)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))
    print(json.dumps({'proposal': str(target), **_write_plan_review(plan, target), 'plan_hash': plan_hash(plan),
                      'status': 'draft; requires decision and explicit approval; current state checked at apply'}))


def bid_budget_validate(args: argparse.Namespace) -> None:
    """Return an offline draft check and approval hash; live checks belong at apply."""
    import json
    import yaml
    from .guards import plan_hash
    plan = yaml.safe_load(Path(args.plan).read_text())
    profile = load_profile(required=True)
    customer = str(profile["google_ads_customer_id"]).replace("-", "")
    if str(plan.get('customer_id', '')).replace('-', '') != customer or plan.get('applied'):
        die('draft must be unapplied and belong to the selected account')
    changes = plan.get('changes')
    if not isinstance(changes, list) or not all(isinstance(row, dict) for row in changes):
        die('draft changes must be a list of objects')
    print(json.dumps({**_write_plan_review(plan, Path(args.plan)), 'plan_hash': plan_hash(plan), 'live_checked': False,
                      'status': 'Draft only; current campaign state is checked at apply.'}, indent=2))


def _mutate_checkpointed(mutate, customer_id, operations, prior, plan, path, client=None):
    """Persist intent before the request; ambiguity never authorizes a resend."""
    import os
    import yaml
    keys = {(cid, field) for _, cid, field, _, _ in operations}
    kept = [receipt for receipt in prior if (receipt.get("campaign_id"), receipt.get("field")) not in keys]
    pending = [{"campaign": name, "campaign_id": cid, "field": field, "value": value, "status": "unknown"}
               for name, cid, field, value, _ in operations]

    def checkpoint(receipts):
        plan["apply_results"] = receipts
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_text(yaml.safe_dump(plan, sort_keys=False))
        os.replace(temp, path)

    checkpoint(kept + pending)
    try:
        response = mutate(request={'customer_id': customer_id,
                                   'operations': [op for _, _, _, _, op in operations], 'partial_failure': True})
        returned = list(response.results)
        if len(returned) != len(operations):
            raise ValueError("mutation result count did not match the request")
        failures = {}
        status = getattr(response, 'partial_failure_error', None)
        if status and int(status.code):
            if client is None or not status.details:
                raise ValueError('partial failure could not be mapped; reconcile live state')
            failure_type = type(client.get_type('GoogleAdsFailure'))
            for detail in status.details:
                failure = (failure_type.deserialize(detail.value) if hasattr(failure_type, 'deserialize')
                           else failure_type.FromString(detail.value))
                for error in failure.errors:
                    indexes = [int(e.index) for e in error.location.field_path_elements if e.field_name == 'operations']
                    if not indexes or not 0 <= indexes[0] < len(operations):
                        raise ValueError('partial failure lacks an operation identity; reconcile live state')
                    failures.setdefault(indexes[0], []).append(str(error.message))
            if not failures:
                raise ValueError('partial failure has no operation details; reconcile live state')
        for index, (receipt, result, (_, _, _, _, operation)) in enumerate(zip(pending, returned, operations)):
            if index in failures:
                receipt.update(status='error', error='; '.join(failures[index]))
                continue
            if result.resource_name != operation.update.resource_name:
                raise ValueError("mutation resource did not match the request")
            receipt.update(status="ok", resource=result.resource_name,
                           executed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    except Exception as exc:
        try:
            from google.ads.googleads.errors import GoogleAdsException
            rejected = isinstance(exc, GoogleAdsException)
        except ImportError:
            rejected = False
        for receipt in pending:
            receipt.update(status="error" if rejected else "unknown", error=str(exc))
    receipts = kept + pending
    checkpoint(receipts)
    return receipts


def bid_budget_apply(args: argparse.Namespace) -> None:
    _require_write_permission()
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required. Install: pip install pyyaml")

    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        die(f"plan file not found: {plan_path}")

    plan = _yaml.safe_load(plan_path.read_text())
    if plan.get('decision_required') and not plan.get('decision_id'):
        die('Record and link the recommendation and prediction before applying this plan.')
    from .guards import plan_hash, read_live_state, validate_plan
    approved_hash = getattr(args, "approval_hash", None)
    if not approved_hash or approved_hash != plan_hash(plan):
        die("Explicit approval of this exact plan is required. Review the plan and supply --approval-hash from bid-budget-validate.")
    if any(result.get("status") == "unknown" for result in plan.get("apply_results", [])):
        die("An earlier mutation has an unknown outcome. Reconcile Google Ads before retrying.")
    retry_fields: set[tuple[str, str]] | None = None
    if plan.get("applied"):
        die("plan already applied; no operations will be resent")
    if plan.get("apply_results"):
        if any(not receipt.get("campaign_id") for receipt in plan["apply_results"]):
            die("legacy partial receipts lack campaign identities; reconcile before retrying")
        retry_fields = {(r["campaign_id"], r["field"]) for r in plan["apply_results"]
                        if r.get("status") in {"error", "not_sent", "held"}}

    if not plan.get("changes"):
        print("no changes in plan — nothing to apply")
        return

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
        from google.protobuf.field_mask_pb2 import FieldMask  # type: ignore
    except ImportError:
        die("google-ads library is required. Install: pip install google-ads")

    profile = load_profile(required=False)
    config_path = str(_runtime_write_config_path())
    customer_id = str(plan.get("customer_id", profile.get("google_ads_customer_id", ""))).replace("-", "")
    if customer_id != str(profile.get("google_ads_customer_id", "")).replace("-", ""):
        die("plan is outside the selected account")

    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as exc:
        die(f"failed to load Google Ads client: {exc}")

    live = read_live_state(client, customer_id, today(), int(profile.get("bid_budget_cooldown_days", 14)))
    pending = dict(plan)
    if retry_fields is not None:
        pending["changes"] = [change for change in plan["changes"]
                              if any(cid == str(change["campaign_id"]) for cid, _ in retry_fields)]
    verdicts = validate_plan(pending, profile, live, on_date=today(),
                             permission=os.getenv("BOB_ACCOUNT_PERMISSION", "read"),
                             applied_today=sum(state.last_change == today() for state in live.values()))
    denied = {verdict.campaign_id: verdict for verdict in verdicts if not verdict.allowed}
    receipts = {(str(r['campaign_id']), r['field']): dict(r) for r in plan.get('apply_results', [])}
    for change in pending['changes']:
        cid = str(change['campaign_id'])
        action = str(change.get('action', ''))
        fields = (['target_cpa'] if 'bid' in action else []) + (['daily_budget'] if 'budget' in action else [])
        for field in fields or ['proposal']:
            if retry_fields is not None and (cid, field) not in retry_fields:
                continue
            receipt = {'campaign': change.get('campaign_name', cid), 'campaign_id': cid, 'field': field,
                       'value': change.get('proposed_' + field), 'status': 'held' if cid in denied else 'not_sent'}
            if cid in denied:
                receipt['error'] = '; '.join(denied[cid].reasons)
            receipts[cid, field] = receipt
        if cid in denied:
            print(f"HELD {change.get('campaign_name', cid)} ({cid}): {'; '.join(denied[cid].reasons)}")
    results = list(receipts.values())
    if plan.get("decision_id"):
        from lib.bob.decisions.records import get, update
        get(STATE_ROOT, customer_id, plan["decision_id"])
        update(STATE_ROOT, customer_id, plan["decision_id"], "human",
               {"response": "approved", "plan_hash": approved_hash, "at": dt.datetime.now(dt.timezone.utc).isoformat()})

    campaign_ops: list = []
    budget_ops: list = []

    campaign_service = client.get_service("CampaignService")
    budget_service = client.get_service("CampaignBudgetService")

    for change in pending["changes"]:
        cid = str(change["campaign_id"])
        if cid in denied:
            continue
        cname = change.get("campaign_name", cid)
        action = change["action"]

        if retry_fields is None or (cid, "target_cpa") in retry_fields:
            should_apply_bid = "bid" in action and change.get("proposed_target_cpa")
        else:
            should_apply_bid = False

        if retry_fields is None or (cid, "daily_budget") in retry_fields:
            should_apply_budget = (
                "budget" in action
                and change.get("proposed_daily_budget")
                and change.get("campaign_budget_id")
            )
        else:
            should_apply_budget = False

        if should_apply_bid:
            op = client.get_type("CampaignOperation")
            camp = op.update
            camp.resource_name = campaign_service.campaign_path(customer_id, cid)
            camp.target_cpa.target_cpa_micros = int(float(change["proposed_target_cpa"]) * 1_000_000)
            field_mask = FieldMask()
            field_mask.paths.append("target_cpa.target_cpa_micros")
            op.update_mask.CopyFrom(field_mask)
            campaign_ops.append((cname, cid, "target_cpa", change["proposed_target_cpa"], op))

        if should_apply_budget:
            op = client.get_type("CampaignBudgetOperation")
            bgt = op.update
            bgt.resource_name = budget_service.campaign_budget_path(customer_id, str(change["campaign_budget_id"]))
            budget_amount = float(change["proposed_daily_budget"])
            bgt.amount_micros = int(round(budget_amount * 1_000_000))
            field_mask = FieldMask()
            field_mask.paths.append("amount_micros")
            op.update_mask.CopyFrom(field_mask)
            budget_ops.append((cname, cid, "daily_budget", budget_amount, op))

    for operations, mutate in ((campaign_ops, campaign_service.mutate_campaigns),
                               (budget_ops, budget_service.mutate_campaign_budgets)):
        if not operations:
            continue
        results = _mutate_checkpointed(mutate, customer_id, operations, results, plan, plan_path, client)
        if any(receipt["status"] == "unknown" for receipt in results):
            break
    errors = [r for r in results if r.get("status") != "ok"]

    # Mark plan as applied only when every requested mutation has succeeded.
    import datetime as _dt
    plan["applied"] = not errors
    plan["applied_at"] = max((receipt.get("executed_at", "") for receipt in results), default="") or _dt.datetime.now().isoformat(timespec="seconds")
    plan["applied_by"] = "bid-budget-apply"
    plan["apply_results"] = results
    plan_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
    if plan.get("decision_id"):
        update(STATE_ROOT, customer_id, plan["decision_id"], "execution",
               {"executed_at": plan["applied_at"], "plan": str(plan_path),
                "results": results, "complete": plan["applied"]})
    state = "applied" if plan["applied"] else "partially applied" if any(r['status'] == 'ok' for r in results) else 'not applied'
    print(f"\nplan marked {state}: {plan_path}")
    print(json.dumps(_write_plan_review(plan, plan_path)))
    for receipt in results:
        detail = receipt.get('error') or (f"applied {receipt.get('value')}" if receipt['status'] == 'ok'
                                         else 'not sent; an earlier mutation outcome requires reconciliation')
        print(f"{receipt['status'].upper()} {receipt.get('campaign', receipt['campaign_id'])} ({receipt['campaign_id']}) "
              f"{receipt['field']}: {detail}")

    if errors:
        print(f"{sum(r['status'] == 'ok' for r in results)} applied; {len(errors)} held, failed or unresolved — see review for details")
        raise SystemExit(2)


def bid_budget_retrospective(args: argparse.Namespace) -> None:
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required. Install: pip install pyyaml")

    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        die(f"plan file not found: {plan_path}")
    plan = _yaml.safe_load(plan_path.read_text())

    if not plan.get("applied"):
        die("plan has not been applied yet — nothing to evaluate")

    # The previous direction-only CPI verdict contradicted its own forecasts,
    # used one network row and could include pre-action days. Never emit it.
    if not plan.get("decision_id"):
        print("Inconclusive: this legacy plan has no recorded prediction. No causal or performance verdict can be inferred from its action name.")
        return
    print(f"Review the recorded prediction with ./bob decision review {plan['decision_id']} --source <exact-window processed CSV>.")
    return


__all__ = [name for name in globals() if not name.startswith("__")]
