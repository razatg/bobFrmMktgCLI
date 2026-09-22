"""CSV boundaries, metric presentation, and comparison primitives."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

from .core import *  # noqa: F403

def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            first_line = sample.splitlines()[0] if sample.splitlines() else ""
            if first_line.count(",") >= first_line.count("\t") and "," in first_line:
                dialect = csv.excel
            else:
                dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
        except Exception:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹", "USD": "$", "EUR": "€", "GBP": "£",
    "AUD": "A$", "CAD": "C$", "SGD": "S$",
}

# (display label, metric key in aggregated row, format kind)
METRIC_DISPLAY_SPEC: list[tuple[str, str, str]] = [
    ("Users",        "reach",                   "count"),
    ("Impressions",  "impressions",              "count"),
    ("Cost",         "cost",                     "cost"),
    ("CPM",          "cpm",                      "cost"),
    ("Frequency",    "frequency",                "ratio"),
    ("Clicks",       "clicks",                   "count"),
    ("CTR %",        "ctr_percent",              "percent"),
    ("CPC",          "cpc",                      "cost"),
    ("Installs",     "installs",                 "count"),
    ("CTI %",        "cti_percent",              "percent"),
    ("Conversions",  "goal_conversions",         "count"),
    ("Conv %",       "conversion_rate_percent",  "percent"),
    ("CPA",          "cpa",                      "cost"),
    ("CPI",          "cpi",                      "cost"),
]


def _metric_display_spec(include_reach: bool) -> list[tuple[str, str, str]]:
    if include_reach:
        return METRIC_DISPLAY_SPEC
    return [
        (label, key, kind)
        for label, key, kind in METRIC_DISPLAY_SPEC
        if key not in ("reach", "frequency")
    ]


def _currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get((currency or "").upper(), "")


def _fmt_display(val: Any, kind: str, sym: str = "") -> str:
    if str(val).upper() in ("NA", "", "NAN", "NONE"):
        return "NA"
    v = number(val)
    if v == 0 and kind in ("ratio", "frequency"):
        return "NA"
    if kind == "count":
        if v >= 1_000_000:
            return f"{v / 1_000_000:,.2f}M"
        return f"{v:,.0f}"
    if kind == "cost":
        if v >= 1_000_000:
            return f"{sym}{v / 1_000_000:,.2f}M"
        if v >= 1_000:
            return f"{sym}{v:,.2f}"
        return f"{sym}{v:.2f}"
    if kind == "percent":
        return f"{v:.2f}%"
    return f"{v:.2f}"  # ratio


def _fmt_delta_display(cur: Any, base: Any) -> str:
    if str(cur).upper() in ("NA", "", "NAN") or str(base).upper() in ("NA", "", "NAN"):
        return "NA"
    c, b = number(cur), number(base)
    if b == 0:
        return "NA" if c == 0 else "+∞"
    pct = (c - b) / b * 100
    return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"


def _print_metric_table(
    cur: dict[str, Any],
    base: dict[str, Any],
    cur_label: str,
    base_label: str,
    currency_sym: str,
    include_reach: bool = True,
) -> None:
    spec = _metric_display_spec(include_reach)
    col_m = max(len(s[0]) for s in spec) + 1
    col_v = max(18, len(cur_label) + 2, len(base_label) + 2)
    col_d = 10
    hdr = f"  {'Metric':<{col_m}}  {cur_label:>{col_v}}  {base_label:>{col_v}}  {'Δ %':>{col_d}}"
    sep = "  " + "─" * col_m + "──" + "─" * col_v + "──" + "─" * col_v + "──" + "─" * col_d
    print(hdr)
    print(sep)
    for label, key, kind in spec:
        cur_fmt = _fmt_display(cur.get(key, "NA"), kind, currency_sym)
        base_fmt = _fmt_display(base.get(key, "NA"), kind, currency_sym)
        delta_fmt = _fmt_delta_display(cur.get(key, "NA"), base.get(key, "NA"))
        print(f"  {label:<{col_m}}  {cur_fmt:>{col_v}}  {base_fmt:>{col_v}}  {delta_fmt:>{col_d}}")


def _delta_pct(current: float, baseline: float) -> str:
    if baseline == 0:
        return "NA" if current == 0 else "+inf"
    return format_float((current - baseline) / baseline * 100)


def _date_label(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return f"{parts[1]}–{parts[2]}"
    return path.name


def _period_window_from_path(path: Path) -> tuple[dt.date, dt.date] | None:
    parts = path.stem.split("_")
    if len(parts) < 3:
        return None
    try:
        return dt.date.fromisoformat(parts[1]), dt.date.fromisoformat(parts[2])
    except ValueError:
        return None


def _build_comparison_rows(
    current_rows: list[dict],
    baseline_rows: list[dict],
    key_cols: list[str],
    primary_goal: str,
) -> list[dict[str, Any]]:
    """Aggregate both sets by key_cols, join, and compute delta_pct columns."""
    def _canonicalize_network_rows(rows: list[dict]) -> list[dict]:
        if "network" not in key_cols:
            return rows
        out = []
        for row in rows:
            normalized = dict(row)
            normalized["network"] = _canonical_network(row.get("network", ""))
            out.append(normalized)
        return out

    def _canonicalize_key_cols(row: dict) -> dict:
        out = {col: row.get(col, "") for col in key_cols}
        if "network" in out:
            out["network"] = _canonical_network(out["network"])
        return out

    current_rows = _canonicalize_network_rows(current_rows)
    baseline_rows = _canonicalize_network_rows(baseline_rows)
    cur_agg = {
        tuple(r.get(c, "") for c in key_cols): r
        for r in _aggregate_period_rows(current_rows, key_cols, primary_goal)
    }
    base_agg = {
        tuple(r.get(c, "") for c in key_cols): r
        for r in _aggregate_period_rows(baseline_rows, key_cols, primary_goal)
    }
    out: list[dict[str, Any]] = []
    for key in sorted(set(cur_agg) | set(base_agg)):
        cur = cur_agg.get(key, {})
        base = base_agg.get(key, {})
        rep = cur or base
        row: dict[str, Any] = _canonicalize_key_cols(rep)
        for m in _COMPARISON_VOLUME_METRICS:
            # Reach is optional: if absent, keep it as NA (not 0).
            if m == "reach" and ("reach" not in cur or "reach" not in base) and ("reach" not in rep):
                row["current_reach"] = "NA"
                row["baseline_reach"] = "NA"
                row["delta_reach_pct"] = "NA"
                continue
            c_val = number(cur.get(m, 0))
            b_val = number(base.get(m, 0))
            row[f"current_{m}"] = format_float(c_val)
            row[f"baseline_{m}"] = format_float(b_val)
            row[f"delta_{m}_pct"] = _delta_pct(c_val, b_val)
        for m in _COMPARISON_RATIO_METRICS:
            row[f"current_{m}"] = cur.get(m, "NA")
            row[f"baseline_{m}"] = base.get(m, "NA")
        out.append(row)
    return out


def _write_filtered_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    write_csv(path, [{field: row.get(field, "") for field in fields} for row in rows], fields)


def _print_compact_comparison(
    grain_name: str,
    key_cols: list[str],
    rows: list[dict[str, Any]],
    total_current: dict[str, Any],
    total_base: dict[str, Any],
    goal_col: str,
    currency_sym: str,
    cur_label: str,
    base_label: str,
    name_filter: str,
    top_n: int,
    output_path: str | None,
    output_account_path: str | None,
) -> None:
    """Print only the evidence needed for a first-pass answer.

    The complete comparison remains available through --output; this renderer is
    deliberately small because Codex sees stdout as context.
    """
    rows = sorted(
        rows,
        key=lambda r: abs(number(r.get(f"current_{goal_col}", 0)) - number(r.get(f"baseline_{goal_col}", 0))),
        reverse=True,
    )
    top_n = max(1, top_n)
    print(f"\n{grain_name} summary")
    print(f"Period: {cur_label} vs {base_label}")
    if name_filter:
        print(f"Filter: {name_filter}")
    print(
        f"Total {goal_col}: {_fmt_display(total_current.get(goal_col, '0'), 'count')} vs "
        f"{_fmt_display(total_base.get(goal_col, '0'), 'count')} "
        f"({_fmt_delta_display(total_current.get(goal_col, '0'), total_base.get(goal_col, '0'))})"
    )
    print(
        f"Total cost: {_fmt_display(total_current.get('cost', '0'), 'cost', currency_sym)} vs "
        f"{_fmt_display(total_base.get('cost', '0'), 'cost', currency_sym)} "
        f"({_fmt_delta_display(total_current.get('cost', '0'), total_base.get('cost', '0'))})"
    )
    print(f"Top {min(top_n, len(rows))} drivers:")
    for index, row in enumerate(rows[:top_n], 1):
        labels = []
        for key in ("campaign_name", "ad_group_name", "network"):
            if key in key_cols and row.get(key):
                labels.append(_display_network(row[key]) if key == "network" else str(row[key]))
        label = " / ".join(labels) or grain_name
        print(
            f"{index}. {label}: {goal_col} "
            f"{_fmt_display(row.get(f'current_{goal_col}', '0'), 'count')} vs "
            f"{_fmt_display(row.get(f'baseline_{goal_col}', '0'), 'count')} "
            f"({_fmt_delta_display(row.get(f'current_{goal_col}', '0'), row.get(f'baseline_{goal_col}', '0'))}); "
            f"cost {_fmt_delta_display(row.get('current_cost', '0'), row.get('baseline_cost', '0'))}"
        )
    if output_path:
        fields = ADGROUP_NETWORK_COMPARISON_COLUMNS if grain_name == "adgroup_network_period" else (
            CAMPAIGN_NETWORK_COMPARISON_COLUMNS if "network" in key_cols else CAMPAIGN_WEEK_COMPARISON_COLUMNS
        )
        _write_filtered_csv(Path(output_path).expanduser(), rows, fields)
        print(f"Full comparison written: {output_path}")
    if output_account_path:
        _write_filtered_csv(Path(output_account_path).expanduser(), rows, ACCOUNT_WEEK_COMPARISON_COLUMNS)
        print(f"Full account comparison written: {output_account_path}")


def _aggregate_period_rows(
    rows: list[dict],
    key_cols: list[str],
    primary_goal: str,
    extra_sum_metrics: list[str] | None = None,
) -> list[dict]:
    """Group by key_cols, sum SUM_METRICS, recalculate derived metrics."""
    # reach (unique_users) is summed only when the source actually provides it
    # — i.e. the reach grain, which has no network split. Network/adgroup grains
    # never fetch unique_users, so reach stays absent here → NA in _derive_metrics,
    # preserving the "no reach for network/adgroup breakdowns" rule.
    reach_present = any(
        str(r.get("reach", "")).upper() not in ("", "NA", "NONE") for r in rows
    )
    sum_metrics = SUM_METRICS + (["reach"] if reach_present else []) + list(extra_sum_metrics or [])
    grouped: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(col, "") for col in key_cols)
        if key not in grouped:
            grouped[key] = {col: row.get(col, "") for col in key_cols}
            for m in sum_metrics:
                grouped[key][m] = 0.0
        for m in sum_metrics:
            grouped[key][m] += number(row.get(m))
    out = []
    for key in sorted(grouped):
        g = grouped[key]
        row_out = {col: g[col] for col in key_cols}
        row_out.update(_derive_metrics(g, primary_goal))
        for metric in extra_sum_metrics or []:
            row_out[metric] = format_float(g[metric])
        if "primary_conversions" in (extra_sum_metrics or []):
            row_out["primary_cpa"] = ratio(g["cost"], g["primary_conversions"])
        out.append(row_out)
    return out

__all__ = [name for name in globals() if not name.startswith("__")]
