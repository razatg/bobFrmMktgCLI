"""Manual validation and configuration checks for performance analysis."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *  # noqa: F403
from lib.bob.platform.presentation import *  # noqa: F403

def load_mapping(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    mapping_path = Path(path).expanduser()
    if not mapping_path.exists():
        die(f"mapping file not found: {mapping_path}")
    mapping: dict[str, str] = {}
    for raw_line in mapping_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            die(f"invalid mapping line: {raw_line}")
        key, value = line.split(":", 1)
        mapping[key.strip()] = value.strip().strip('"').strip("'")
    return mapping


def indexed(rows: list[dict[str, str]], grain: str) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row.get(grain)
        if key:
            output[key] = row
    return output


def compare_status(metric: str, bob: float, manual: float, diff: float) -> tuple[str, float | str]:
    mode, threshold = DEFAULT_TOLERANCES.get(metric, ("relative", 0.1))
    if mode == "absolute":
        value = abs(diff)
        return ("pass" if value <= threshold else "fail", value)
    if manual == 0:
        value = 0 if bob == 0 else math.inf
        return ("pass" if bob == 0 else "fail", value)
    value = abs(diff / manual * 100)
    return ("pass" if value <= threshold else "fail", value)


def likely_causes(failed_metrics: set[str]) -> list[str]:
    causes: list[str] = []
    traffic = {"impressions", "clicks"}
    conversions = {"installs", "in_app_conversions", "cti_percent", "conversion_rate_percent"}
    if failed_metrics & conversions and not (failed_metrics & traffic):
        causes.append("Conversion action inclusion, biddable-vs-all conversion choice, or conversion lag.")
    if "cost" in failed_metrics and not (failed_metrics & traffic):
        causes.append("Cost unit, currency, or manual export rounding.")
    if failed_metrics & traffic:
        causes.append("Date range, timezone, customer ID, campaign type, or campaign status filter mismatch.")
    if not causes and failed_metrics:
        causes.append("Column mapping, rounding, or manual export formatting mismatch.")
    return causes


def validate_manual(args: argparse.Namespace) -> None:
    bob_path = Path(args.bob).expanduser()
    manual_path = Path(args.manual).expanduser()
    if not bob_path.exists():
        die(f"Bob aggregate not found: {bob_path}")
    if not manual_path.exists():
        die(f"manual aggregate not found: {manual_path}")

    mapping = load_mapping(args.mapping)
    grain = args.grain
    bob_rows = indexed(read_csv(bob_path), grain)
    manual_rows_raw = read_csv(manual_path)
    manual_rows: dict[str, dict[str, str]] = {}
    manual_grain = mapping.get(grain, grain)
    for row in manual_rows_raw:
        key = row.get(manual_grain)
        if key:
            manual_rows[key] = row

    metrics = [m for m in ACCOUNT_DAILY_COLUMNS if m != grain]
    comparison_rows: list[dict[str, Any]] = []
    failed: set[str] = set()

    for key in sorted(set(bob_rows) | set(manual_rows)):
        bob_row = bob_rows.get(key, {})
        manual_row = manual_rows.get(key, {})
        for metric in metrics:
            manual_col = mapping.get(metric, metric)
            if metric not in bob_row or manual_col not in manual_row:
                continue
            bob_value = number(bob_row.get(metric))
            manual_value = number(manual_row.get(manual_col))
            diff = bob_value - manual_value
            status, tolerance_value = compare_status(metric, bob_value, manual_value, diff)
            if status != "pass":
                failed.add(metric)
            rel = "NA" if manual_value == 0 else format_float(diff / manual_value * 100)
            comparison_rows.append(
                {
                    grain: key,
                    "metric": metric,
                    "bob_value": format_float(bob_value),
                    "manual_value": format_float(manual_value),
                    "absolute_diff": format_float(diff),
                    "relative_diff_percent": rel,
                    "tolerance_check_value": "inf" if tolerance_value == math.inf else format_float(float(tolerance_value)),
                    "status": status,
                }
            )

    if args.output_prefix:
        prefix = Path(args.output_prefix).expanduser()
    else:
        prefix = REPORTS_DIR / f"{bob_path.stem}_validation"
    csv_path = prefix.with_suffix(".csv")
    md_path = prefix.with_suffix(".md")
    fields = [
        grain, "metric", "bob_value", "manual_value",
        "absolute_diff", "relative_diff_percent", "tolerance_check_value", "status",
    ]
    write_csv(csv_path, comparison_rows, fields)
    write_validation_md(md_path, bob_path, manual_path, comparison_rows, failed, grain)
    print(f"validation CSV written: {csv_path}")
    print(f"validation report written: {md_path}")
    if failed:
        print(f"validation failed metrics: {', '.join(sorted(failed))}")
        raise SystemExit(2)
    print("validation passed")


def check_config(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    migration_notes = [] if args.config else _normalize_account_config_files(profile)
    config = args.config or _profile_read_config_value(profile)
    if not config:
        die("I need the Google Ads developer token from Google Ads > Admin > API Center before I can fetch data from Google Ads.", error_code="GOOGLE_AUTH_REQUIRED")
    config_path = _resolve_state_path(config)
    if not config_path.exists():
        die(f"Google Ads GARF config not found: {config_path}\nExpected at {config_path} — create it or set google_ads_read_config_path in your account profile (.bob/accounts/<id>/profile.json)")
    text = config_path.read_text()
    keys = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        keys[key.strip()] = value.strip().strip("\"'")

    if migration_notes:
        for note in migration_notes:
            print(f"updated: {note}")

    # GARF read config — no OAuth client credentials required
    expected = ["developer_token", "login_customer_id"]
    print(f"GARF read config: {config_path}")
    for key in expected:
        value = keys.get(key, "")
        if not value:
            print(f"{key}: MISSING")
        elif key == "login_customer_id":
            normalized = value.replace("-", "")
            shape = "SET_WITH_HYPHENS" if "-" in value else "SET"
            print(f"{key}: {shape} length={len(normalized)}")
        else:
            print(f"{key}: SET")
    account = str(args.account or profile.get("google_ads_customer_id") or "").replace("-", "")
    print(f"target_customer_id: {'SET length=' + str(len(account)) if account else 'MISSING'}")
    if keys.get("login_customer_id") and account and keys["login_customer_id"].replace("-", "") == account:
        print("note: login_customer_id equals target_customer_id; omit login_customer_id unless this is a manager account.")

    write_path = _resolve_profile_config_path(profile, write=True)
    write_config = str(profile.get("google_ads_write_config_path", "") or "").strip()
    if write_config or write_path.exists():
        print(f"\nwrite config (bid-budget-apply): {write_path}")
        if not write_path.exists():
            print("  STATUS: FILE NOT FOUND")
            print("  Run this to generate write credentials (one-time OAuth2 flow):")
            print("    python3 lib/datapull.py setup-write-credentials")
            print("  The command prints a single-line OAuth URL. Open it in your browser to authorize.")
            print("  Once authorized, the file is saved automatically and bid-budget-apply will work.")
        else:
            wtext = write_path.read_text()
            wkeys: dict = {}
            for raw_line in wtext.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                wkeys[k.strip()] = v.strip().strip("\"'")
            for key in ["developer_token", "client_id", "client_secret", "refresh_token", "login_customer_id"]:
                val = wkeys.get(key, "")
                if not val:
                    print(f"  {key}: MISSING")
                elif key == "login_customer_id":
                    normalized = val.replace("-", "")
                    print(f"  {key}: SET length={len(normalized)}")
                else:
                    print(f"  {key}: SET")


def write_validation_md(
    path: Path,
    bob_path: Path,
    manual_path: Path,
    rows: list[dict[str, Any]],
    failed: set[str],
    grain: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(rows)
    failures = sum(1 for row in rows if row["status"] != "pass")
    lines = [
        "# Manual Validation Report",
        "",
        f"- Bob aggregate: `{bob_path}`",
        f"- Manual aggregate: `{manual_path}`",
        f"- Grain: `{grain}`",
        f"- Checks: {total}",
        f"- Failures: {failures}",
        "",
        "## Status",
        "",
        "PASS" if failures == 0 else "FAIL",
        "",
    ]
    if failed:
        lines.extend(["## Failed Metrics", ""])
        for metric in sorted(failed):
            lines.append(f"- `{metric}`")
        lines.extend(["", "## Likely Causes", ""])
        for cause in likely_causes(failed):
            lines.append(f"- {cause}")
        lines.append("")

    lines.extend([
        "## Largest Differences",
        "",
        "| Grain | Metric | Bob | Manual | Diff | Rel Diff % | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ])
    for row in sorted(rows, key=lambda r: abs(number(r["absolute_diff"])), reverse=True)[:25]:
        lines.append(
            f"| {row[grain]} | {row['metric']} | {row['bob_value']} | {row['manual_value']} | "
            f"{row['absolute_diff']} | {row['relative_diff_percent']} | {row['status']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines))

__all__ = [name for name in globals() if not name.startswith("__")]
