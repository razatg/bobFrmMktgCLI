"""Raw-to-processed aggregation for performance analysis."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *  # noqa: F403
from lib.bob.platform.presentation import *  # noqa: F403


def ensure_processed_file_for_period(
    grain: str,
    subdir: str,
    start: dt.date,
    end: dt.date,
    customer_id: str | None,
    primary_goal: str,
    force: bool = False,
) -> Path | None:
    """Return a processed period file, aggregating the exact raw window when available."""
    found = find_processed_files_for_period(subdir, [(start, end)], customer_id)[0]
    if found and not force:
        return found
    raw_paths = find_raw_files_for_range(grain, start, end, customer_id)
    if not raw_paths:
        return None
    aggregate(argparse.Namespace(
        grain=grain,
        source=None,
        goal=primary_goal,
        input=None,
        input_paths=[str(path) for path in raw_paths],
        customer=customer_id,
        output=None,
        from_date=start.isoformat(),
        to=end.isoformat(),
    ))
    return find_processed_files_for_period(subdir, [(start, end)], customer_id)[0]


def aggregate(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    grain = args.grain
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"

    if grain == "account_daily":
        _agg_account_daily(args, profile, primary_goal)
    elif grain in _NETWORK_PERIOD_KEY_COLS:
        _agg_network_period(args, profile, grain, primary_goal)
    elif grain == "creative_period":
        _agg_creative_period(args, profile, primary_goal)
    elif grain == "campaign_weekly_trend":
        _agg_campaign_weekly_trend(args, profile, primary_goal)
    else:
        die(f"unknown grain: {grain}")


def _agg_account_daily(
    args: argparse.Namespace, profile: dict, primary_goal: str
) -> None:
    source = args.source or "campaign_daily"
    input_path = Path(args.input).expanduser() if args.input else newest_raw(source)
    rows = read_csv(input_path)
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        date = row.get("date")
        if not date:
            continue
        if date not in grouped:
            grouped[date] = {m: 0.0 for m in SUM_METRICS}
        for m in SUM_METRICS:
            grouped[date][m] += number(row.get(m))

    out_rows: list[dict[str, Any]] = []
    for date in sorted(grouped):
        row_out: dict[str, Any] = {"date": date}
        row_out.update(_derive_metrics(grouped[date], primary_goal))
        out_rows.append(row_out)

    customer = args.customer or profile.get("google_ads_customer_id") or "unknown"
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        start = out_rows[0]["date"] if out_rows else "empty"
        end = out_rows[-1]["date"] if out_rows else "empty"
        output_path = account_processed_dir(customer, "account") / f"account_daily_{customer}_{start}_{end}.csv"
    write_csv(output_path, out_rows, ACCOUNT_DAILY_COLUMNS)
    print(f"processed aggregate written: {output_path}")
    if not out_rows:
        print("WARNING: aggregate account_daily produced 0 rows.", file=sys.stderr)


def _agg_network_period(
    args: argparse.Namespace, profile: dict, grain: str, primary_goal: str
) -> None:
    source = args.source or grain
    # Normalize to the hyphen-stripped form used by the processed dir, the raw
    # files, and find_processed_files_for_period — otherwise a hyphenated prefix
    # creates a duplicate file for the same window and the date-keyed selector
    # picks one at random.
    customer = (args.customer or profile.get("google_ads_customer_id") or "unknown").replace("-", "")
    from_date = getattr(args, "from_date", None)
    to_date = getattr(args, "to", None)
    input_paths: list[Path]
    range_start: dt.date | None = None
    range_end: dt.date | None = None
    if from_date and to_date:
        try:
            range_start = dt.date.fromisoformat(from_date)
            range_end = dt.date.fromisoformat(to_date)
        except ValueError:
            die("--from and --to must be ISO dates: YYYY-MM-DD")
    if args.input:
        input_paths = [Path(args.input).expanduser()]
    elif getattr(args, "input_paths", None):
        input_paths = [Path(path).expanduser() for path in args.input_paths]
    elif from_date or to_date:
        if not from_date or not to_date:
            die("aggregate period selection requires both --from and --to")
        input_paths = find_raw_files_for_range(source, range_start, range_end, customer) or []
        if not input_paths:
            missing = next(
                (f"{start}–{end}" for start, end in split_date_range(range_start, range_end)
                 if not find_raw_file_for_period(source, start, end, customer)),
                f"{range_start}–{range_end}",
            )
            die(f"no raw CSV found for {source} chunk {missing} for account {customer}")
    else:
        input_paths = [newest_raw(source)]
    rows: list[dict[str, Any]] = []
    for input_path in input_paths:
        rows.extend(read_csv(input_path))
    # Reach is optional; network is only present for the network-split grains.
    for row in rows:
        if "network" in row:
            row["network"] = _canonical_network(row.get("network", ""))
    extra_metrics = ["primary_conversions"] if grain in {
        "campaign_primary_conversion_period", "adgroup_primary_conversion_period",
    } else []
    out_rows = _aggregate_period_rows(
        rows, _NETWORK_PERIOD_KEY_COLS[grain], primary_goal, extra_metrics,
    )

    if range_start and range_end:
        file_start, file_end = range_start.isoformat(), range_end.isoformat()
    else:
        parts = input_paths[-1].stem.split("_")
        file_start = parts[1] if len(parts) >= 3 else "unknown"
        file_end = parts[2] if len(parts) >= 3 else "unknown"
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        subdir = _NETWORK_PERIOD_SUBDIR[grain]
        output_path = account_processed_dir(customer, subdir) / f"{customer}_{file_start}_{file_end}.csv"
    fields = _NETWORK_PERIOD_COLUMNS[grain]
    # Aggregation calculates the normal internal metric set before writing. A
    # registered grain may intentionally expose a smaller schema (for example,
    # the generic primary-conversion datasets); write only that contract.
    write_csv(output_path, [{field: row.get(field, "") for field in fields} for row in out_rows], fields)
    print(f"processed aggregate written: {output_path}")
    if not out_rows:
        print(
            f"WARNING: aggregate {grain} produced 0 rows from {len(input_paths)} raw file(s).",
            file=sys.stderr,
        )


def _agg_creative_period(
    args: argparse.Namespace, profile: dict, primary_goal: str
) -> None:
    source = args.source or "creative_period"
    range_start: dt.date | None = None
    range_end: dt.date | None = None
    customer = (args.customer or profile.get("google_ads_customer_id") or "unknown").replace("-", "")
    if getattr(args, "from_date", None) and getattr(args, "to", None):
        try:
            range_start = dt.date.fromisoformat(args.from_date)
            range_end = dt.date.fromisoformat(args.to)
        except ValueError:
            die("--from and --to must be ISO dates: YYYY-MM-DD")
    if args.input:
        input_paths = [Path(args.input).expanduser()]
    elif getattr(args, "input_paths", None):
        input_paths = [Path(path).expanduser() for path in args.input_paths]
    elif getattr(args, "from_date", None) or getattr(args, "to", None):
        if not args.from_date or not args.to:
            die("aggregate period selection requires both --from and --to")
        input_paths = find_raw_files_for_range(source, range_start, range_end, customer) or []
        if not input_paths:
            die(f"no complete raw CSV range found for {source} {range_start}–{range_end}")
    else:
        input_paths = [newest_raw(source)]
    rows: list[dict[str, Any]] = []
    for input_path in input_paths:
        rows.extend(read_csv(input_path))
    key_cols = [
        "customer_id", "campaign_id", "campaign_name",
        "ad_group_id", "ad_group_name",
        "asset_view_resource_name", "asset_resource_name",
        "asset_id", "asset_name", "asset_type", "asset_text", "video_id", "field_type", "performance_label",
        "image_url", "image_width", "image_height", "mime_type", "file_size_bytes",
    ]
    out_rows = _aggregate_period_rows(rows, key_cols, primary_goal)
    min_imp = int(profile.get("creative_min_impressions", DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    out_rows = [r for r in out_rows if number(r.get("impressions")) >= min_imp]

    if range_start and range_end:
        file_start, file_end = range_start.isoformat(), range_end.isoformat()
    else:
        parts = input_paths[-1].stem.split("_")
        file_start = parts[1] if len(parts) >= 3 else "unknown"
        file_end = parts[2] if len(parts) >= 3 else "unknown"
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        suffix = f"_{source}" if source in CREATIVE_ASSET_QUERIES.values() else ""
        output_path = account_processed_dir(customer, "creative") / f"{customer}_{file_start}_{file_end}{suffix}.csv"
    write_csv(output_path, out_rows, CREATIVE_PERIOD_COLUMNS)
    print(f"processed aggregate written: {output_path} ({len(out_rows)} creatives >= {min_imp} impressions)")
    if not out_rows:
        print(
            f"WARNING: aggregate creative_period produced 0 rows above {min_imp} impressions.",
            file=sys.stderr,
        )


def _agg_campaign_weekly_trend(
    args: argparse.Namespace, profile: dict, primary_goal: str
) -> None:
    source = args.source or "campaign_network_period"
    customer = str(args.customer or profile.get("google_ads_customer_id") or "").replace("-", "")
    if not customer:
        die("campaign_weekly_trend requires --customer or google_ads_customer_id in the active profile")
    windows = bid_budget_week_windows()
    period_files = [find_raw_file_for_period(source, start, end, customer) for start, end in windows]
    missing = [f"{start}..{end}" for (start, end), path in zip(windows, period_files) if path is None]
    if missing:
        die(
            f"missing exact {source} windows for account {customer}: {', '.join(missing)}. "
            "Run: ./bob resolve-dates --period bid-budget-weeks, then fetch the missing windows"
        )

    campaign_key_cols = ["customer_id", "campaign_id", "campaign_name", "campaign_status"]
    week_data: list[tuple[int, str, str, dict[str, dict]]] = []
    for path, (start, end) in zip(period_files, windows):
        assert path is not None
        rows = read_csv(path)
        foreign_accounts = sorted({
            str(row.get("customer_id", "")).replace("-", "")
            for row in rows
            if str(row.get("customer_id", "")).replace("-", "") not in {"", customer}
        })
        if foreign_accounts:
            die(
                f"{path.name} contains rows for another account: {', '.join(foreign_accounts)}; "
                f"expected only {customer}"
            )
        w_start, w_end = start.isoformat(), end.isoformat()
        # Keep the established W<ISO> column compatibility, labelling each rolling
        # period by its end date's ISO week so W0 remains the current period label.
        iso_week = end.isocalendar().week
        agg = _aggregate_period_rows(rows, campaign_key_cols, primary_goal)
        week_data.append((iso_week, w_start, w_end, {r["campaign_id"]: r for r in agg}))

    w0_iso, w0_start, w0_end, w0 = week_data[0]
    w1_iso, w1_start, w1_end, w1 = week_data[1]
    w2_iso, w2_start, w2_end, w2 = week_data[2]
    goal_col = "installs" if primary_goal == "installs" else "in_app_conversions"

    def cpi(r: dict) -> float:
        cost = number(r.get("cost", 0))
        goal = number(r.get(goal_col, 0))
        return cost / goal if goal > 0 else 0.0

    def week_prefixed(iso_w: int, start: str, end: str, r: dict) -> dict:
        p = f"w{iso_w}"
        return {
            f"{p}_start": start,
            f"{p}_end": end,
            f"{p}_impressions": r.get("impressions", "0"),
            f"{p}_clicks": r.get("clicks", "0"),
            f"{p}_cost": r.get("cost", "0"),
            f"{p}_installs": r.get("installs", "0"),
            f"{p}_in_app_conversions": r.get("in_app_conversions", "0"),
            f"{p}_cpm": ratio(number(r.get("cost", 0)), number(r.get("impressions", 0)), 1000),
            f"{p}_ctr_percent": r.get("ctr_percent", "NA"),
            f"{p}_cpc": r.get("cpc", "NA"),
            f"{p}_cti_percent": r.get("cti_percent", "NA"),
            f"{p}_conversion_rate_percent": r.get("conversion_rate_percent", "NA"),
        }

    all_ids = set(w0) | set(w1) | set(w2)
    out_rows = []
    for cid in sorted(all_ids):
        r0, r1, r2 = w0.get(cid, {}), w1.get(cid, {}), w2.get(cid, {})
        rep = r0 or r1 or r2
        c0, c1, c2 = cpi(r0), cpi(r1), cpi(r2)

        # CPI lower = better; w0 is most recent
        if c0 > 0 and c1 > 0 and c2 > 0:
            w0_better = c0 < c1
            w1_better = c1 < c2
            if w0_better and w1_better:
                trend, signal = "improving", "confirmed"
            elif not w0_better and not w1_better:
                trend, signal = "deteriorating", "confirmed"
            elif w0_better and not w1_better:
                trend, signal = "improving", "early"
            else:
                trend, signal = "deteriorating", "blip"
        elif c0 > 0 and c1 > 0:
            trend = "improving" if c0 < c1 else "deteriorating"
            signal = "early"
        else:
            trend, signal = "stable", "early"

        row_out: dict[str, Any] = {
            "customer_id": rep.get("customer_id", ""),
            "campaign_id": cid,
            "campaign_name": rep.get("campaign_name", ""),
            "campaign_status": rep.get("campaign_status", ""),
            "current_iso_week": w0_iso,
            "prior1_iso_week": w1_iso,
            "prior2_iso_week": w2_iso,
        }
        row_out.update(week_prefixed(w0_iso, w0_start, w0_end, r0))
        row_out.update(week_prefixed(w1_iso, w1_start, w1_end, r1))
        row_out.update(week_prefixed(w2_iso, w2_start, w2_end, r2))
        row_out["trend_direction"] = trend
        row_out["signal_strength"] = signal
        out_rows.append(row_out)

    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        output_path = account_processed_dir(customer, "campaign-trend") / f"{customer}_{w0_start}_{w0_end}.csv"
    trend_cols = _weekly_trend_columns([w0_iso, w1_iso, w2_iso])
    write_csv(output_path, out_rows, trend_cols)
    print(f"processed aggregate written: {output_path} ({len(out_rows)} campaigns)")
    if not out_rows:
        print(
            "WARNING: aggregate campaign_weekly_trend produced 0 rows.",
            file=sys.stderr,
        )

__all__ = [name for name in globals() if not name.startswith("__")]
