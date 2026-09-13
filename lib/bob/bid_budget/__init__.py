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

def bid_budget_recommend(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    cac_ceiling = float(args.cac_ceiling or profile.get("cac_ceiling", 200))
    change_pct = min(float(args.change_pct or profile.get("bid_budget_change_pct", 10)), 20)
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
    cooldown_cutoff = (today() - dt.timedelta(days=cooldown_days)).isoformat()

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
        if w0_cpa > 0:
            cac_ok = w0_cpa <= cac_ceiling
        elif target_cpa_bid > 0:
            cac_ok = target_cpa_bid <= cac_ceiling  # bid above ceiling = skip
        else:
            cac_ok = False  # no conversion data and no bid → skip

        # Volume guard
        vol_ok = w0_inst >= min_installs

        # Cooldown guard: skip if campaign was changed within cooldown_days
        last_change = ch_index.get(cid, "")
        cooldown_ok = not last_change or last_change < cooldown_cutoff
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

        if not vol_ok:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": f"W{w0_iso} installs {w0_inst:.0f} below minimum {min_installs}"})
            continue
        if not cac_ok:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": f"W{w0_iso} CPA {w0_cpa:.2f} exceeds CAC ceiling {cac_ceiling:.0f}"})
            continue
        if not cooldown_ok:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": f"changed {days_since_change}d ago ({last_change}) — within {cooldown_days}-day cooldown"})
            continue
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
        yaml_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
        print(f"mutation plan written: {yaml_path}")
    except ImportError:
        print("note: pyyaml not installed — YAML plan not written. Run: pip install pyyaml")


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
    retry_fields: set[tuple[str, str]] | None = None
    if plan.get("applied"):
        prior_errors = [
            r for r in plan.get("apply_results", [])
            if r.get("status") == "error" and r.get("campaign") and r.get("field")
        ]
        if not prior_errors:
            die(f"plan already applied on {plan['applied_at']} by {plan['applied_by']}")
        retry_fields = {(r["campaign"], r["field"]) for r in prior_errors}
        print(f"retrying {len(retry_fields)} failed mutation(s) from partial apply")

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

    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as exc:
        die(f"failed to load Google Ads client: {exc}")

    results: list[dict] = []
    campaign_ops: list = []
    budget_ops: list = []
    campaign_ids_for_budget: list[tuple] = []

    campaign_service = client.get_service("CampaignService")
    budget_service = client.get_service("CampaignBudgetService")

    for change in plan["changes"]:
        cid = str(change["campaign_id"])
        cname = change["campaign_name"]
        action = change["action"]

        if retry_fields is None or (cname, "target_cpa") in retry_fields:
            should_apply_bid = "bid" in action and change.get("proposed_target_cpa")
        else:
            should_apply_bid = False

        if retry_fields is None or (cname, "daily_budget") in retry_fields:
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
            budget_amount = int(round(float(change["proposed_daily_budget"])))
            bgt.amount_micros = budget_amount * 1_000_000
            field_mask = FieldMask()
            field_mask.paths.append("amount_micros")
            op.update_mask.CopyFrom(field_mask)
            budget_ops.append((cname, cid, "daily_budget", budget_amount, op))

    # Apply campaign (Target CPA) mutations
    if campaign_ops:
        try:
            response = campaign_service.mutate_campaigns(
                customer_id=customer_id,
                operations=[op for _, _, _, _, op in campaign_ops],
            )
            for (cname, cid, field, val, _), result in zip(campaign_ops, response.results):
                results.append({"campaign": cname, "field": field, "value": val, "status": "ok", "resource": result.resource_name})
                print(f"  ✓ {cname} — target_cpa → {val}")
        except Exception as exc:
            for cname, cid, field, val, _ in campaign_ops:
                results.append({"campaign": cname, "field": field, "value": val, "status": "error", "error": str(exc)})
            print(f"  ✗ campaign mutations failed: {exc}")

    # Apply budget mutations
    if budget_ops:
        try:
            response = budget_service.mutate_campaign_budgets(
                customer_id=customer_id,
                operations=[op for _, _, _, _, op in budget_ops],
            )
            for (cname, cid, field, val, _), result in zip(budget_ops, response.results):
                results.append({"campaign": cname, "field": field, "value": val, "status": "ok", "resource": result.resource_name})
                print(f"  ✓ {cname} — daily_budget → {val}")
        except Exception as exc:
            for cname, cid, field, val, _ in budget_ops:
                results.append({"campaign": cname, "field": field, "value": val, "status": "error", "error": str(exc)})
            print(f"  ✗ budget mutations failed: {exc}")

    prior_results = plan.get("apply_results", [])
    if retry_fields:
        results = [
            r for r in prior_results
            if (r.get("campaign"), r.get("field")) not in retry_fields
        ] + results

    errors = [r for r in results if r.get("status") == "error"]

    # Mark plan as applied only when every requested mutation has succeeded.
    import datetime as _dt
    plan["applied"] = not errors
    plan["applied_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    plan["applied_by"] = "bid-budget-apply"
    plan["apply_results"] = results
    plan_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
    state = "applied" if plan["applied"] else "partially applied"
    print(f"\nplan marked {state}: {plan_path}")

    if errors:
        print(f"{len(errors)} mutation(s) failed — see plan file for details")
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

    applied_date = dt.date.fromisoformat(plan["applied_at"][:10])
    cal = applied_date.isocalendar()
    base_week, base_year = cal.week, cal.year

    # Find W+1 and W+2 processed campaign-network files
    w1_start, w1_end = iso_week_to_dates(base_week, base_year)
    w2_week = base_week + 1
    w2_year = base_year
    if w2_week > dt.date(base_year, 12, 28).isocalendar().week:
        w2_week = 1
        w2_year = base_year + 1
    w2_start, w2_end = iso_week_to_dates(w2_week, w2_year)

    profile = load_profile(required=False)
    retro_customer_id = profile.get("google_ads_customer_id")
    found = find_processed_files_for_period("campaign-network", [(w1_start, w1_end), (w2_start, w2_end)], retro_customer_id)
    w1_path, w2_path = found[0], found[1]

    if not w1_path:
        print(f"\nW+1 data not yet available (need {w1_start}–{w1_end})")
        print(f"Run: python3 lib/datapull.py fetch --query campaign_network_period --from {w1_start} --to {w1_end}")
        print("     python3 lib/datapull.py aggregate --grain campaign_network_period")
        print("\nToo early to evaluate — check back after W+1 data is available.")
        return

    primary_goal = profile.get("primary_goal") or "in_app_conversions"
    w1_rows = read_csv(w1_path)
    w2_rows = read_csv(w2_path) if w2_path else []

    def _cpi_from_rows(rows: list[dict], cid: str) -> float:
        for r in rows:
            if str(r.get("campaign_id", "")).replace("-", "") == cid:
                cost = number(r.get("cost", 0))
                inst = number(r.get("installs", 0))
                return cost / inst if inst > 0 else 0.0
        return 0.0

    verdicts: list[dict] = []
    for change in plan.get("changes", []):
        cid = str(change["campaign_id"])
        cname = change["campaign_name"]
        action = change["action"]
        baseline_cpi = float(change.get("w0_cpi", 0) or 0)
        expected = "lower" if "increase" in action else "higher"

        w1_cpi = _cpi_from_rows(w1_rows, cid)
        w2_cpi = _cpi_from_rows(w2_rows, cid) if w2_rows else 0.0

        w1_moved = (w1_cpi < baseline_cpi) if expected == "lower" else (w1_cpi > baseline_cpi)
        w2_moved = (w2_cpi < baseline_cpi) if expected == "lower" else (w2_cpi > baseline_cpi)

        if w2_cpi > 0 and w1_moved and w2_moved:
            verdict = "working"
        elif not w2_path or w2_cpi == 0:
            verdict = "too_early"
        else:
            verdict = "not_working"

        verdicts.append({
            "campaign": cname,
            "action": action,
            "baseline_cpi": baseline_cpi,
            "w1_cpi": w1_cpi,
            "w2_cpi": w2_cpi if w2_cpi > 0 else None,
            "expected": expected,
            "verdict": verdict,
        })

    sym = _currency_symbol(profile.get("currency", ""))
    total = len(verdicts)
    working = sum(1 for v in verdicts if v["verdict"] == "working")
    early = sum(1 for v in verdicts if v["verdict"] == "too_early")
    not_wk = sum(1 for v in verdicts if v["verdict"] == "not_working")

    print(f"\nBid/Budget Retrospective — changes applied {plan['applied_at'][:10]}")
    print(f"  {working}/{total} working  |  {early} too early  |  {not_wk} not working\n")

    hdr = f"  {'Campaign':<45}  {'Action':<26}  {'Baseline CPI':>12}  {'W+1 CPI':>10}  {'W+2 CPI':>10}  {'Verdict':<12}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for v in verdicts:
        w2_str = _fmt_display(v["w2_cpi"], "cost", sym) if v["w2_cpi"] else "—"
        print(
            f"  {v['campaign']:<45}  {v['action']:<26}  "
            f"{_fmt_display(v['baseline_cpi'], 'cost', sym):>12}  "
            f"{_fmt_display(v['w1_cpi'], 'cost', sym):>10}  "
            f"{w2_str:>10}  "
            f"{v['verdict']:<12}"
        )

__all__ = [name for name in globals() if not name.startswith("__")]
