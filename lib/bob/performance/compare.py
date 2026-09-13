"""Period and segment comparisons for performance analysis."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *  # noqa: F403
from lib.bob.platform.presentation import *  # noqa: F403
from .aggregate import ensure_processed_file_for_period

def correlate_change_history(
    campaign_id: str,
    start_date: str,
    end_date: str,
    change_history_path: Path,
) -> list[dict]:
    """Return change events for a campaign within a date window, for diagnostic overlay."""
    if not change_history_path.exists():
        return []
    target = str(campaign_id).replace("-", "")
    results = []
    for row in read_csv(change_history_path):
        row_campaign = str(row.get("campaign_id", "")).replace("-", "")
        changed_at = row.get("changed_at", "")[:10]
        if row_campaign == target and start_date <= changed_at <= end_date:
            results.append(row)
    return results


def _print_grain_results(
    grain_name: str,
    key_cols: list[str],
    cur_rows: list[dict],
    base_rows: list[dict],
    cur_reach_rows: list[dict] | None,
    base_reach_rows: list[dict] | None,
    primary_goal: str,
    all_metrics: bool,
    currency_sym: str,
    cur_label: str,
    base_label: str,
    name_filter: str,
    output_path: str | None,
    output_account_path: str | None,
    reach_metrics: bool = True,
    summary: bool = False,
    top_n: int = 10,
) -> None:
    goal_col = "installs" if primary_goal == "installs" else "in_app_conversions"
    rows = _build_comparison_rows(cur_rows, base_rows, key_cols, primary_goal)
    include_campaign_reach = (
        grain_name == "campaign_network_period"
        and reach_metrics
        and cur_reach_rows is not None
        and base_reach_rows is not None
    )
    cur_reach_by_campaign: dict[str, dict] = {}
    base_reach_by_campaign: dict[str, dict] = {}
    if include_campaign_reach:
        cur_reach_by_campaign = {
            r.get("campaign_id", ""): r
            for r in _aggregate_period_rows(cur_reach_rows or [], ["campaign_id"], primary_goal)
        }
        base_reach_by_campaign = {
            r.get("campaign_id", ""): r
            for r in _aggregate_period_rows(base_reach_rows or [], ["campaign_id"], primary_goal)
        }
        for row in rows:
            campaign_id = row.get("campaign_id", "")
            cur_reach = cur_reach_by_campaign.get(campaign_id, {})
            base_reach = base_reach_by_campaign.get(campaign_id, {})
            row["current_reach"] = cur_reach.get("reach", "NA")
            row["baseline_reach"] = base_reach.get("reach", "NA")
            row["delta_reach_pct"] = _delta_pct(number(row["current_reach"]), number(row["baseline_reach"]))
            row["current_frequency"] = cur_reach.get("frequency", "NA")
            row["baseline_frequency"] = base_reach.get("frequency", "NA")
    total_cur = _aggregate_period_rows(cur_rows, ["customer_id"], primary_goal)
    total_base = _aggregate_period_rows(base_rows, ["customer_id"], primary_goal)
    tc = total_cur[0] if total_cur else {}
    tb = total_base[0] if total_base else {}

    if summary:
        _print_compact_comparison(
            grain_name, key_cols, rows, tc, tb, goal_col, currency_sym,
            cur_label, base_label, name_filter, top_n, output_path, output_account_path,
        )
        return

    _all_metric_keys = [m for _, m, _ in METRIC_DISPLAY_SPEC]

    def _row_to_period_dicts(r: dict, include_reach: bool = True) -> tuple[dict, dict]:
        cur_d = {m: r.get(f"current_{m}", "NA") for m in _all_metric_keys}
        base_d = {m: r.get(f"baseline_{m}", "NA") for m in _all_metric_keys}
        if not include_reach:
            for d in (cur_d, base_d):
                d["reach"] = "NA"
                d["frequency"] = "NA"
        return cur_d, base_d

    def _mask_network_reach(row: dict) -> dict:
        masked = dict(row)
        for key in ("current_reach", "baseline_reach", "delta_reach_pct", "current_frequency", "baseline_frequency"):
            if key in masked:
                masked[key] = "NA"
        return masked

    if grain_name == "account_network_period":
        if all_metrics:
            print(f"\nAccount Summary — all metrics")
            _print_metric_table(tc, tb, cur_label, base_label, currency_sym, include_reach=False)
            for row in rows:
                network = _display_network(row.get("network", ""))
                cur_net, base_net = _row_to_period_dicts(row, include_reach=False)
                print(f"\nNetwork: {network}")
                _print_metric_table(cur_net, base_net, cur_label, base_label, currency_sym, include_reach=False)

        print(f"\nAccount × Network")
        hdr = f"  {'Network':<16}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for row in rows:
            g_cur = row[f'current_{goal_col}']
            g_base = row[f'baseline_{goal_col}']
            c_cur = row['current_cost']
            c_base = row['baseline_cost']
            print(
                f"  {_display_network(row.get('network', '')):<16}  "
                f"{_fmt_display(g_cur, 'count'):>12}  "
                f"{_fmt_display(g_base, 'count'):>12}  "
                f"{_fmt_delta_display(g_cur, g_base):>8}  "
                f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
                f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
                f"{_fmt_delta_display(c_cur, c_base):>8}"
            )
        print(
            f"  {'TOTAL':<16}  "
            f"{_fmt_display(tc.get(goal_col, '0'), 'count'):>12}  "
            f"{_fmt_display(tb.get(goal_col, '0'), 'count'):>12}  "
            f"{_fmt_delta_display(tc.get(goal_col, '0'), tb.get(goal_col, '0')):>8}  "
            f"{_fmt_display(tc.get('cost', '0'), 'cost', currency_sym):>12}  "
            f"{_fmt_display(tb.get('cost', '0'), 'cost', currency_sym):>12}  "
            f"{_fmt_delta_display(tc.get('cost', '0'), tb.get('cost', '0')):>8}"
        )
        if output_account_path:
            write_csv(Path(output_account_path).expanduser(), [_mask_network_reach(r) for r in rows], ACCOUNT_WEEK_COMPARISON_COLUMNS)
            print(f"account comparison written: {output_account_path}")

    elif grain_name == "campaign_network_period":
        rows.sort(
            key=lambda r: abs(number(r[f"current_{goal_col}"]) - number(r[f"baseline_{goal_col}"])),
            reverse=True,
        )
        n = len(rows)
        if "network" in key_cols:
            distinct_campaigns = len({r.get("campaign_id", "") for r in rows})
            n_label = f"{n} campaign-network rows across {distinct_campaigns} campaigns"
        else:
            n_label = f"{n} campaigns"
        if name_filter:
            n_label += f" matching '{name_filter}'"
        if all_metrics:
            print(f"\nCampaign Segment Summary — all metrics ({n_label})")
            _print_metric_table(tc, tb, cur_label, base_label, currency_sym, include_reach=False)
            for row in rows:
                cur_campaign, base_campaign = _row_to_period_dicts(row, include_reach=include_campaign_reach)
                if "network" in row:
                    print(f"\nCampaign: {row.get('campaign_name', '')} | Network: {_display_network(row.get('network', ''))}")
                else:
                    print(f"\nCampaign: {row.get('campaign_name', '')}")
                _print_metric_table(
                    cur_campaign,
                    base_campaign,
                    cur_label,
                    base_label,
                    currency_sym,
                    include_reach=include_campaign_reach,
                )

        print(f"\nCampaigns ({n_label}) — sorted by |goal Δ|")
        if "network" in key_cols:
            hdr = f"  {'Campaign':<45}  {'Network':<16}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
        else:
            hdr = f"  {'Campaign':<45}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for row in rows:
            g_cur = row[f'current_{goal_col}']
            g_base = row[f'baseline_{goal_col}']
            c_cur = row['current_cost']
            c_base = row['baseline_cost']
            if "network" in key_cols:
                print(
                    f"  {row['campaign_name']:<45}  "
                    f"{_display_network(row.get('network', '')):<16}  "
                    f"{_fmt_display(g_cur, 'count'):>12}  "
                    f"{_fmt_display(g_base, 'count'):>12}  "
                    f"{_fmt_delta_display(g_cur, g_base):>8}  "
                    f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
                    f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
                    f"{_fmt_delta_display(c_cur, c_base):>8}"
                )
            else:
                print(
                    f"  {row['campaign_name']:<45}  "
                    f"{_fmt_display(g_cur, 'count'):>12}  "
                    f"{_fmt_display(g_base, 'count'):>12}  "
                    f"{_fmt_delta_display(g_cur, g_base):>8}  "
                    f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
                    f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
                    f"{_fmt_delta_display(c_cur, c_base):>8}"
                )
        if "network" in key_cols:
            print(
                f"  {'— TOTAL —':<45}  "
                f"{'':<16}  "
                f"{_fmt_display(tc.get(goal_col, '0'), 'count'):>12}  "
                f"{_fmt_display(tb.get(goal_col, '0'), 'count'):>12}  "
                f"{_fmt_delta_display(tc.get(goal_col, '0'), tb.get(goal_col, '0')):>8}  "
                f"{_fmt_display(tc.get('cost', '0'), 'cost', currency_sym):>12}  "
                f"{_fmt_display(tb.get('cost', '0'), 'cost', currency_sym):>12}  "
                f"{_fmt_delta_display(tc.get('cost', '0'), tb.get('cost', '0')):>8}"
            )
        else:
            print(
                f"  {'— TOTAL —':<45}  "
                f"{_fmt_display(tc.get(goal_col, '0'), 'count'):>12}  "
                f"{_fmt_display(tb.get(goal_col, '0'), 'count'):>12}  "
                f"{_fmt_delta_display(tc.get(goal_col, '0'), tb.get(goal_col, '0')):>8}  "
                f"{_fmt_display(tc.get('cost', '0'), 'cost', currency_sym):>12}  "
                f"{_fmt_display(tb.get('cost', '0'), 'cost', currency_sym):>12}  "
                f"{_fmt_delta_display(tc.get('cost', '0'), tb.get('cost', '0')):>8}"
            )
        if output_path:
            fields = CAMPAIGN_NETWORK_COMPARISON_COLUMNS if "network" in key_cols else CAMPAIGN_WEEK_COMPARISON_COLUMNS
            _write_filtered_csv(Path(output_path).expanduser(), rows, fields)
            print(f"\ncampaign comparison written: {output_path}")

    elif grain_name == "adgroup_network_period":
        rows.sort(
            key=lambda r: abs(number(r[f"current_{goal_col}"]) - number(r[f"baseline_{goal_col}"])),
            reverse=True,
        )
        n_label = f"{len(rows)} adgroup-network rows"
        if name_filter:
            n_label += f" matching '{name_filter}'"
        if all_metrics:
            print(f"\nAd Group × Network — all metrics ({n_label})")
            for row in rows:
                cur_ag, base_ag = _row_to_period_dicts(row, include_reach=False)
                print(
                    f"\nCampaign: {row.get('campaign_name', '')} | "
                    f"Ad group: {row.get('ad_group_name', '')} | "
                    f"Network: {_display_network(row.get('network', ''))}"
                )
                _print_metric_table(cur_ag, base_ag, cur_label, base_label, currency_sym, include_reach=False)

        print(f"\nAd Group × Network ({n_label}) — sorted by |goal Δ|")
        hdr = f"  {'Campaign':<32}  {'Ad Group':<32}  {'Network':<16}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for row in rows:
            g_cur = row[f"current_{goal_col}"]
            g_base = row[f"baseline_{goal_col}"]
            c_cur = row["current_cost"]
            c_base = row["baseline_cost"]
            print(
                f"  {row.get('campaign_name', ''):<32.32}  "
                f"{row.get('ad_group_name', ''):<32.32}  "
                f"{_display_network(row.get('network', '')):<16}  "
                f"{_fmt_display(g_cur, 'count'):>12}  "
                f"{_fmt_display(g_base, 'count'):>12}  "
                f"{_fmt_delta_display(g_cur, g_base):>8}  "
                f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
                f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
                f"{_fmt_delta_display(c_cur, c_base):>8}"
            )
        if output_path:
            _write_filtered_csv(Path(output_path).expanduser(), rows, ADGROUP_NETWORK_COMPARISON_COLUMNS)
            print(f"\nadgroup × network comparison written: {output_path}")


def _print_segment_network_results(
    cur_rows: list[dict],
    base_rows: list[dict],
    primary_goal: str,
    currency_sym: str,
    cur_label: str,
    base_label: str,
    all_metrics: bool,
    output_path: str | None,
) -> None:
    goal_col = "installs" if primary_goal == "installs" else "in_app_conversions"
    rows = _build_comparison_rows(
        cur_rows,
        base_rows,
        ["customer_id", "campaign_id", "campaign_name", "campaign_status", "network"],
        primary_goal,
    )
    rows.sort(
        key=lambda r: (
            r.get("campaign_name", ""),
            _display_network(r.get("network", "")),
        ),
    )
    segment_rows = _build_comparison_rows(
        cur_rows,
        base_rows,
        ["customer_id", "network"],
        primary_goal,
    )
    segment_rows.sort(
        key=lambda r: abs(number(r[f"current_{goal_col}"]) - number(r[f"baseline_{goal_col}"])),
        reverse=True,
    )
    total_cur = _aggregate_period_rows(cur_rows, ["customer_id"], primary_goal)
    total_base = _aggregate_period_rows(base_rows, ["customer_id"], primary_goal)
    tc = total_cur[0] if total_cur else {}
    tb = total_base[0] if total_base else {}

    if all_metrics:
        print(f"\nCampaign × Network — all metrics")
        for row in rows:
            network = _display_network(row.get("network", ""))
            cur_net = {m: row.get(f"current_{m}", "NA") for _, m, _ in METRIC_DISPLAY_SPEC}
            base_net = {m: row.get(f"baseline_{m}", "NA") for _, m, _ in METRIC_DISPLAY_SPEC}
            for d in (cur_net, base_net):
                d["reach"] = "NA"
                d["frequency"] = "NA"
            print(f"\nCampaign: {row.get('campaign_name', '')} | Network: {network}")
            _print_metric_table(cur_net, base_net, cur_label, base_label, currency_sym, include_reach=False)

    print(f"\nCampaign × Network")
    hdr = f"  {'Campaign':<45}  {'Network':<16}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for row in rows:
        g_cur = row[f"current_{goal_col}"]
        g_base = row[f"baseline_{goal_col}"]
        c_cur = row["current_cost"]
        c_base = row["baseline_cost"]
        print(
            f"  {row.get('campaign_name', ''):<45}  "
            f"  {_display_network(row.get('network', '')):<16}  "
            f"{_fmt_display(g_cur, 'count'):>12}  "
            f"{_fmt_display(g_base, 'count'):>12}  "
            f"{_fmt_delta_display(g_cur, g_base):>8}  "
            f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
            f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
            f"{_fmt_delta_display(c_cur, c_base):>8}"
        )

    print(f"\nSegment × Network")
    hdr = f"  {'Network':<16}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for row in segment_rows:
        g_cur = row[f"current_{goal_col}"]
        g_base = row[f"baseline_{goal_col}"]
        c_cur = row["current_cost"]
        c_base = row["baseline_cost"]
        print(
            f"  {_display_network(row.get('network', '')):<16}  "
            f"{_fmt_display(g_cur, 'count'):>12}  "
            f"{_fmt_display(g_base, 'count'):>12}  "
            f"{_fmt_delta_display(g_cur, g_base):>8}  "
            f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
            f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
            f"{_fmt_delta_display(c_cur, c_base):>8}"
        )
    print(
        f"  {'TOTAL':<16}  "
        f"{_fmt_display(tc.get(goal_col, '0'), 'count'):>12}  "
        f"{_fmt_display(tb.get(goal_col, '0'), 'count'):>12}  "
        f"{_fmt_delta_display(tc.get(goal_col, '0'), tb.get(goal_col, '0')):>8}  "
        f"{_fmt_display(tc.get('cost', '0'), 'cost', currency_sym):>12}  "
        f"{_fmt_display(tb.get('cost', '0'), 'cost', currency_sym):>12}  "
        f"{_fmt_delta_display(tc.get('cost', '0'), tb.get('cost', '0')):>8}"
    )
    if output_path:
        _write_filtered_csv(Path(output_path).expanduser(), rows, CAMPAIGN_NETWORK_COMPARISON_COLUMNS)
        print(f"\ncampaign × network comparison written: {output_path}")


def slice_campaigns(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    currency_sym = _currency_symbol(profile.get("currency", ""))
    pattern = (args.name_contains or "").lower()
    all_metrics = getattr(args, "all_metrics", False)
    reach_metrics = getattr(args, "reach_metrics", False)
    network_split = getattr(args, "network_split", False)
    customer_id = profile.get("google_ads_customer_id")
    windows: list[tuple[dt.date, dt.date]] | None = None

    if args.current and args.baseline:
        current_path: Path | None = Path(args.current).expanduser()
        baseline_path: Path | None = Path(args.baseline).expanduser()
        cur_window = _period_window_from_path(current_path)
        base_window = _period_window_from_path(baseline_path)
        if cur_window and base_window:
            windows = [cur_window, base_window]
    else:
        period = args.period or "yesterday_vs_sdlw"
        windows = resolve_period_dates(period)
        found = find_processed_files_for_period("campaign-network", [windows[0], windows[1]], customer_id)
        current_path, baseline_path = found[0], found[1]
        if not current_path or not baseline_path:
            missing = []
            if not current_path:
                missing.append(f"{windows[0][0]}_{windows[0][1]}")
            if not baseline_path:
                missing.append(f"{windows[1][0]}_{windows[1][1]}")
            die(
                f"processed campaign-network files not found for: {', '.join(missing)}\n"
                "Run: python3 lib/datapull.py aggregate --grain campaign_network_period"
            )

    all_cur = read_csv(current_path)
    all_base = read_csv(baseline_path)
    cur_label = _date_label(current_path)
    base_label = _date_label(baseline_path)
    if not all_cur or not all_base:
        empty_sides = []
        if not all_cur:
            empty_sides.append(cur_label)
        if not all_base:
            empty_sides.append(base_label)
        print(
            f"No data for {', '.join(empty_sides)} (account {customer_id}). "
            f"Nothing to compare.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    cur_rows = [r for r in all_cur if pattern in r.get("campaign_name", "").lower()]
    base_rows = [r for r in all_base if pattern in r.get("campaign_name", "").lower()]

    if not cur_rows and not base_rows:
        print(
            f"No campaigns matching {args.name_contains!r} in either period.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(f"\nCampaign slice: name contains '{args.name_contains}'")
    print(f"Current: {cur_label}  |  Baseline: {base_label}")

    cur_reach_rows = None
    base_reach_rows = None
    if all_metrics and reach_metrics:
        if not windows:
            die("reach metrics require processed filenames with YYYY-MM-DD_YYYY-MM-DD windows, or use --period")
        reach_subdir = _NETWORK_PERIOD_SUBDIR["campaign_reach_period"]
        reach_cur_path = ensure_processed_file_for_period(
            "campaign_reach_period",
            reach_subdir,
            windows[0][0],
            windows[0][1],
            customer_id,
            primary_goal,
        )
        reach_base_path = ensure_processed_file_for_period(
            "campaign_reach_period",
            reach_subdir,
            windows[1][0],
            windows[1][1],
            customer_id,
            primary_goal,
        )
        if not reach_cur_path or not reach_base_path:
            missing = []
            if not reach_cur_path:
                missing.append(f"{windows[0][0]}–{windows[0][1]}")
            if not reach_base_path:
                missing.append(f"{windows[1][0]}–{windows[1][1]}")
            print(f"\n[campaign_reach_period] processed files missing for: {', '.join(missing)}")
            print("Fetch and aggregate:")
            for start, end in windows:
                raw_path = find_raw_file_for_period("campaign_reach_period", start, end, customer_id)
                if not raw_path:
                    print(f"  python3 lib/datapull.py fetch --query campaign_reach_period --from {start} --to {end}")
                print(f"  python3 lib/datapull.py aggregate --grain campaign_reach_period --from {start} --to {end}")
            raise SystemExit(1)
        cur_reach_all = read_csv(reach_cur_path)
        base_reach_all = read_csv(reach_base_path)
        cur_ids = {r.get("campaign_id", "") for r in cur_rows}
        base_ids = {r.get("campaign_id", "") for r in base_rows}
        cur_reach_rows = [r for r in cur_reach_all if r.get("campaign_id", "") in cur_ids]
        base_reach_rows = [r for r in base_reach_all if r.get("campaign_id", "") in base_ids]

    _print_grain_results(
        "campaign_network_period",
        ["customer_id", "campaign_id", "campaign_name", "campaign_status"],
        cur_rows, base_rows, cur_reach_rows, base_reach_rows, primary_goal, all_metrics, currency_sym,
        cur_label, base_label, pattern,
        args.output, None, reach_metrics,
        getattr(args, "summary", False),
        getattr(args, "top", 10),
    )
    if network_split and not getattr(args, "summary", False):
        _print_segment_network_results(
            cur_rows,
            base_rows,
            primary_goal,
            currency_sym,
            cur_label,
            base_label,
            all_metrics,
            getattr(args, "output_network", None),
        )


def compare_weeks(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    currency_sym = _currency_symbol(profile.get("currency", ""))
    name_filter = (args.name_contains or "").lower()
    all_metrics = getattr(args, "all_metrics", False)
    reach_metrics = getattr(args, "reach_metrics", False)
    network_split = getattr(args, "network_split", False)
    customer_id = profile.get("google_ads_customer_id")

    ref = today()
    if args.week:
        cur_week, cur_year = args.week, (args.year or ref.isocalendar().year)
    else:
        cur_week, cur_year = last_complete_iso_week(ref)

    if args.vs:
        base_week = args.vs
        base_year = cur_year if base_week <= cur_week else cur_year - 1
    else:
        base_week = cur_week - 1
        base_year = cur_year
        if base_week < 1:
            prev = cur_year - 1
            base_week = dt.date(prev, 12, 28).isocalendar().week
            base_year = prev

    cur_start, cur_end = iso_week_to_dates(cur_week, cur_year)
    base_start, base_end = iso_week_to_dates(base_week, base_year)
    cur_label = f"W{cur_week} ({cur_start}–{cur_end})"
    base_label = f"W{base_week} ({base_start}–{base_end})"

    print(f"\nISO week comparison:  W{cur_week} {cur_year} ({cur_start}–{cur_end})  vs  W{base_week} {base_year} ({base_start}–{base_end})")
    if name_filter:
        print(f"Campaign filter: name contains '{args.name_contains}'")

    grains: list[tuple[str, list[str]]] = []
    if args.grain in ("account", "both"):
        grains.append(("account_network_period", ["customer_id", "customer_name", "network"]))
    if args.grain in ("campaign", "both"):
        campaign_keys = ["customer_id", "campaign_id", "campaign_name", "campaign_status"]
        if network_split:
            campaign_keys.append("network")
        grains.append(("campaign_network_period", campaign_keys))
    if args.grain == "adgroup":
        grains.append((
            "adgroup_network_period",
            ["customer_id", "campaign_id", "campaign_name", "ad_group_id", "ad_group_name", "ad_group_status", "network"],
        ))

    all_ok = True
    for grain_name, key_cols in grains:
        subdir = _NETWORK_PERIOD_SUBDIR[grain_name]
        found = find_processed_files_for_period(subdir, [(cur_start, cur_end), (base_start, base_end)], customer_id)
        cur_path, base_path = found[0], found[1]

        if not cur_path or not base_path:
            all_ok = False
            missing_windows = []
            if not cur_path:
                missing_windows.append((cur_week, cur_start, cur_end))
            if not base_path:
                missing_windows.append((base_week, base_start, base_end))
            missing = [f"W{week} ({start}–{end})" for week, start, end in missing_windows]
            print(f"\n[{grain_name}] processed files missing for: {', '.join(missing)}")
            print("Fetch and aggregate:")
            for _, start, end in missing_windows:
                raw_path = find_raw_file_for_period(grain_name, start, end, customer_id)
                if not raw_path:
                    print(f"  python3 lib/datapull.py fetch --query {grain_name} --from {start} --to {end}")
                print(f"  python3 lib/datapull.py aggregate --grain {grain_name} --from {start} --to {end}")
            continue

        cur_rows = read_csv(cur_path)
        base_rows = read_csv(base_path)
        if not cur_rows or not base_rows:
            empty_sides = []
            if not cur_rows:
                empty_sides.append(cur_label)
            if not base_rows:
                empty_sides.append(base_label)
            print(
                f"\n[{grain_name}] No data for {', '.join(empty_sides)} "
                f"(account {customer_id}). Nothing to compare.",
                file=sys.stderr,
            )
            all_ok = False
            continue
        if grain_name == "campaign_network_period" and name_filter:
            cur_rows = [r for r in cur_rows if name_filter in r.get("campaign_name", "").lower()]
            base_rows = [r for r in base_rows if name_filter in r.get("campaign_name", "").lower()]
            if not cur_rows and not base_rows:
                print(
                    f"\n[{grain_name}] no campaigns matching '{args.name_contains}' in either week.",
                    file=sys.stderr,
                )
                all_ok = False
                continue
        if grain_name == "adgroup_network_period" and name_filter:
            cur_rows = [r for r in cur_rows if name_filter in r.get("campaign_name", "").lower()]
            base_rows = [r for r in base_rows if name_filter in r.get("campaign_name", "").lower()]
            if not cur_rows and not base_rows:
                print(
                    f"\n[{grain_name}] no ad groups under campaigns matching '{args.name_contains}' in either week.",
                    file=sys.stderr,
                )
                all_ok = False
                continue

        # Optional: reach-only grain for campaign segment metric table.
        cur_reach_rows = None
        base_reach_rows = None
        if grain_name == "campaign_network_period" and all_metrics and reach_metrics:
            reach_found = find_processed_files_for_period(
                _NETWORK_PERIOD_SUBDIR["campaign_reach_period"],
                [(cur_start, cur_end), (base_start, base_end)],
                customer_id,
            )
            reach_cur_path, reach_base_path = reach_found[0], reach_found[1]
            if not reach_cur_path or not reach_base_path:
                missing = []
                if not reach_cur_path:
                    missing.append(f"W{cur_week} ({cur_start}–{cur_end})")
                if not reach_base_path:
                    missing.append(f"W{base_week} ({base_start}–{base_end})")
                print(f"\n[campaign_reach_period] processed files missing for: {', '.join(missing)}")
                print("Fetch and aggregate:")
                for start, end in [(cur_start, cur_end), (base_start, base_end)]:
                    raw_path = find_raw_file_for_period("campaign_reach_period", start, end, customer_id)
                    if not raw_path:
                        print(f"  python3 lib/datapull.py fetch --query campaign_reach_period --from {start} --to {end}")
                    print(f"  python3 lib/datapull.py aggregate --grain campaign_reach_period --from {start} --to {end}")
                all_ok = False
            else:
                cur_reach_rows = read_csv(reach_cur_path)
                base_reach_rows = read_csv(reach_base_path)

        _print_grain_results(
            grain_name, key_cols, cur_rows, base_rows, cur_reach_rows, base_reach_rows,
            primary_goal, all_metrics, currency_sym,
            cur_label, base_label, name_filter,
            args.output if grain_name in ("campaign_network_period", "adgroup_network_period") else None,
            args.output_account if grain_name == "account_network_period" else None,
            reach_metrics,
            getattr(args, "summary", False),
            getattr(args, "top", 10),
        )

    if not all_ok:
        raise SystemExit(1)


def _month_date_range(
    month: int, year: int, full: bool, reference: dt.date
) -> tuple[dt.date, dt.date]:
    """Return (start, end) for a calendar month.

    full=True  → 1st of month to last day of month (or yesterday if current month)
    full=False → MTD: 1st of month to the minimum of (same day-of-month as yesterday, last day of month)
    """
    import calendar as _cal
    first = dt.date(year, month, 1)
    last_day = _cal.monthrange(year, month)[1]
    last = dt.date(year, month, last_day)
    yesterday = reference - dt.timedelta(days=1)
    if full:
        end = min(last, yesterday)
    else:
        target_day = min(yesterday.day, last_day)
        end = dt.date(year, month, target_day)
    return first, end


def compare_months(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    currency_sym = _currency_symbol(profile.get("currency", ""))
    name_filter = (args.name_contains or "").lower()
    all_metrics = getattr(args, "all_metrics", False)
    reach_metrics = getattr(args, "reach_metrics", False)
    network_split = getattr(args, "network_split", False)
    customer_id = profile.get("google_ads_customer_id")

    ref = today()
    cur_month = args.month or ref.month
    cur_year = args.year or ref.year

    if args.vs:
        base_month = args.vs
        base_year = cur_year if base_month <= cur_month else cur_year - 1
    else:
        base_month = cur_month - 1
        base_year = cur_year
        if base_month < 1:
            base_month = 12
            base_year = cur_year - 1

    cur_start, cur_end = _month_date_range(cur_month, cur_year, args.full, ref)
    base_start, base_end = _month_date_range(base_month, base_year, args.full, ref)

    import calendar as _cal
    cur_label = f"{_cal.month_abbr[cur_month]} {cur_year} ({cur_start}–{cur_end})"
    base_label = f"{_cal.month_abbr[base_month]} {base_year} ({base_start}–{base_end})"
    mode = "full month" if args.full else "MTD"
    print(f"\nMonth comparison ({mode}):  {cur_label}  vs  {base_label}")
    if name_filter:
        print(f"Campaign filter: name contains '{args.name_contains}'")

    grains: list[tuple[str, list[str]]] = []
    if args.grain in ("account", "both"):
        grains.append(("account_network_period", ["customer_id", "customer_name", "network"]))
    if args.grain in ("campaign", "both"):
        campaign_keys = ["customer_id", "campaign_id", "campaign_name", "campaign_status"]
        if network_split:
            campaign_keys.append("network")
        grains.append(("campaign_network_period", campaign_keys))
    if args.grain == "adgroup":
        grains.append((
            "adgroup_network_period",
            ["customer_id", "campaign_id", "campaign_name", "ad_group_id", "ad_group_name", "ad_group_status", "network"],
        ))

    all_ok = True
    for grain_name, key_cols in grains:
        subdir = _NETWORK_PERIOD_SUBDIR[grain_name]
        cur_path = ensure_processed_file_for_period(
            grain_name, subdir, cur_start, cur_end, customer_id, primary_goal
        )
        base_path = ensure_processed_file_for_period(
            grain_name, subdir, base_start, base_end, customer_id, primary_goal
        )

        if not cur_path or not base_path:
            all_ok = False
            missing = []
            if not cur_path:
                missing.append(f"{_cal.month_abbr[cur_month]} ({cur_start}–{cur_end})")
            if not base_path:
                missing.append(f"{_cal.month_abbr[base_month]} ({base_start}–{base_end})")
            print(f"\n[{grain_name}] processed files missing for: {', '.join(missing)}")
            print("Fetch and aggregate:")
            for start, end in [(cur_start, cur_end), (base_start, base_end)]:
                print(f"  python3 lib/datapull.py fetch --query {grain_name} --from {start} --to {end}")
                print(f"  python3 lib/datapull.py aggregate --grain {grain_name} --from {start} --to {end}")
            continue

        cur_rows = read_csv(cur_path)
        base_rows = read_csv(base_path)
        if not cur_rows or not base_rows:
            empty_sides = []
            if not cur_rows:
                empty_sides.append(cur_label)
            if not base_rows:
                empty_sides.append(base_label)
            print(
                f"\n[{grain_name}] No data for {', '.join(empty_sides)} "
                f"(account {customer_id}). Nothing to compare.",
                file=sys.stderr,
            )
            all_ok = False
            continue

        if grain_name == "campaign_network_period" and name_filter:
            cur_rows = [r for r in cur_rows if name_filter in r.get("campaign_name", "").lower()]
            base_rows = [r for r in base_rows if name_filter in r.get("campaign_name", "").lower()]
            if not cur_rows and not base_rows:
                print(
                    f"\n[{grain_name}] no campaigns matching '{args.name_contains}' in either month.",
                    file=sys.stderr,
                )
                all_ok = False
                continue
        if grain_name == "adgroup_network_period" and name_filter:
            cur_rows = [r for r in cur_rows if name_filter in r.get("campaign_name", "").lower()]
            base_rows = [r for r in base_rows if name_filter in r.get("campaign_name", "").lower()]
            if not cur_rows and not base_rows:
                print(
                    f"\n[{grain_name}] no ad groups under campaigns matching '{args.name_contains}' in either month.",
                    file=sys.stderr,
                )
                all_ok = False
                continue

        cur_reach_rows = None
        base_reach_rows = None
        if grain_name == "campaign_network_period" and all_metrics and reach_metrics:
            reach_subdir = _NETWORK_PERIOD_SUBDIR["campaign_reach_period"]
            reach_cur_path = ensure_processed_file_for_period(
                "campaign_reach_period", reach_subdir, cur_start, cur_end, customer_id, primary_goal
            )
            reach_base_path = ensure_processed_file_for_period(
                "campaign_reach_period", reach_subdir, base_start, base_end, customer_id, primary_goal
            )
            if not reach_cur_path or not reach_base_path:
                missing = []
                if not reach_cur_path:
                    missing.append(f"{cur_label}")
                if not reach_base_path:
                    missing.append(f"{base_label}")
                print(f"\n[campaign_reach_period] processed files missing for: {', '.join(missing)}")
                print("Fetch and aggregate:")
                for start, end in [(cur_start, cur_end), (base_start, base_end)]:
                    print(f"  python3 lib/datapull.py fetch --query campaign_reach_period --from {start} --to {end}")
                    print(f"  python3 lib/datapull.py aggregate --grain campaign_reach_period --from {start} --to {end}")
                all_ok = False
            else:
                cur_reach_rows = read_csv(reach_cur_path)
                base_reach_rows = read_csv(reach_base_path)

        _print_grain_results(
            grain_name, key_cols, cur_rows, base_rows, cur_reach_rows, base_reach_rows,
            primary_goal, all_metrics, currency_sym,
            cur_label, base_label, name_filter,
            args.output if grain_name in ("campaign_network_period", "adgroup_network_period") else None,
            args.output_account if grain_name == "account_network_period" else None,
            reach_metrics,
            getattr(args, "summary", False),
            getattr(args, "top", 10),
        )

    if not all_ok:
        raise SystemExit(1)

__all__ = [name for name in globals() if not name.startswith("__")]
