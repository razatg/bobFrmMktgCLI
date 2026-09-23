"""Processed-data discovery shared by action skills."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from .core import *  # noqa: F403

def newest_processed(subdir: str, customer_id: str | None = None) -> Path:
    proc_dir = _resolve_processed_dir(subdir, customer_id)
    files = sorted(proc_dir.glob("*.csv"), key=lambda p: p.stem.split("_")[1] if len(p.stem.split("_")) >= 2 else "", reverse=True)
    if not files:
        die(f"no processed file found in {proc_dir}")
    return files[0]


def bid_budget_trend_path(customer_id: str, explicit: str | None = None) -> tuple[Path, list[tuple[dt.date, dt.date]]]:
    """Resolve the exact current bid/budget trend rather than a merely newer-looking file."""
    normalized_customer = str(customer_id).replace("-", "")
    if not normalized_customer:
        die("bid-budget-recommend requires an active account")
    windows = bid_budget_week_windows()
    expected_start, expected_end = windows[0]
    path = Path(explicit).expanduser() if explicit else find_processed_files_for_period(
        "campaign-trend", [(expected_start, expected_end)], normalized_customer
    )[0]
    if path is None or not path.exists():
        die(
            f"missing exact campaign-trend for account {normalized_customer}: "
            f"{expected_start}..{expected_end}. Run: ./bob aggregate --grain campaign_weekly_trend"
        )
    parts = path.stem.split("_")
    if len(parts) < 3 or parts[0].replace("-", "") != normalized_customer:
        die(f"campaign-trend file does not belong to account {normalized_customer}: {path.name}")
    if (parts[1], parts[2]) != (expected_start.isoformat(), expected_end.isoformat()):
        die(
            f"campaign-trend file covers {parts[1]}..{parts[2]}, expected "
            f"{expected_start}..{expected_end}: {path.name}"
        )
    return path, windows


def validate_bid_budget_trend_rows(
    rows: list[dict[str, str]], customer_id: str, windows: list[tuple[dt.date, dt.date]]
) -> None:
    """Fail closed when a trend does not encode the exact account and rolling windows."""
    if not rows:
        die("campaign-trend file contains no campaign rows")
    normalized_customer = str(customer_id).replace("-", "")
    foreign_accounts = sorted({
        str(row.get("customer_id", "")).replace("-", "")
        for row in rows
        if str(row.get("customer_id", "")).replace("-", "") != normalized_customer
    })
    if foreign_accounts:
        die(
            "campaign-trend contains missing or foreign customer IDs: "
            + ", ".join(account or "<missing>" for account in foreign_accounts[:10])
        )
    first = rows[0]
    week_fields = ("current_iso_week", "prior1_iso_week", "prior2_iso_week")
    for field, (start, end) in zip(week_fields, windows):
        iso_week = end.isocalendar().week
        if str(first.get(field, "")) != str(iso_week):
            die(f"campaign-trend {field} is {first.get(field, '<missing>')}, expected {iso_week}")
        if first.get(f"w{iso_week}_start") != start.isoformat() or first.get(f"w{iso_week}_end") != end.isoformat():
            die(
                f"campaign-trend W{iso_week} dates do not match the required window "
                f"{start}..{end}"
            )


def _creative_processed_paths(customer_id: str) -> list[Path]:
    """Choose the newest processed file for each creative asset query."""
    creative_dir = account_processed_dir(customer_id, "creative")
    specialised = list(creative_dir.glob(f"{str(customer_id).replace('-', '')}_*creative_*_period.csv"))
    if not specialised:
        return [newest_processed("creative", customer_id)]

    def sort_key(path: Path):
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", path.stem)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        return (dates[-1] if dates else "", dates[0] if dates else "", mtime, path.name)

    latest: dict[str, Path] = {}
    for path in specialised:
        match = re.search(r"_creative_(headline|description|image|video)_period(?:_|$)", path.stem)
        asset_kind = match.group(1) if match else path.stem
        if asset_kind not in latest or sort_key(path) > sort_key(latest[asset_kind]):
            latest[asset_kind] = path
    return sorted(latest.values(), key=lambda path: path.name)


def _dedupe_creative_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one row per ad-level asset identity, preferring populated text."""
    result: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        asset_view = str(row.get("asset_view_resource_name", "")).strip()
        key = ("asset_view", asset_view) if asset_view else (
            "legacy", row.get("campaign_id", ""), row.get("ad_group_id", ""),
            row.get("asset_id", ""), row.get("asset_type", ""), row.get("field_type", ""),
        )
        existing = result.get(key)
        if existing is None or (
            not str(existing.get("asset_text", "")).strip()
            and str(row.get("asset_text", "")).strip()
        ):
            result[key] = row
    return list(result.values())

__all__ = [name for name in globals() if not name.startswith("__")]
