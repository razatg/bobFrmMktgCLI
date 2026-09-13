"""Authoritative local data and pull-history manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
from lib.bob.platform.dates import *
def _manifest_pull_status(customer_id: str, query_filter: str, start_filter: dt.date | None, end_filter: dt.date | None) -> list[dict[str, Any]]:
    """Return compact matching pull history without exposing raw JSONL records."""
    matches: list[dict[str, Any]] = []
    normalized_filter = query_filter.replace("_", "-")
    for path in _pull_log_candidates():
        if not path.exists():
            continue
        with path.open() as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                    query = str(entry.get("query", ""))
                    account = str(entry.get("account", "")).replace("-", "")
                    from_date = parse_date(str(entry.get("from_date", "")))
                    to_date = parse_date(str(entry.get("to_date", "")))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if account != customer_id or (normalized_filter and normalized_filter not in query.lower().replace("_", "-")):
                    continue
                if start_filter and (not to_date or to_date < start_filter):
                    continue
                if end_filter and (not from_date or from_date > end_filter):
                    continue
                matches.append({
                    "query": query,
                    "from": entry.get("from_date"),
                    "to": entry.get("to_date"),
                    "outcome": entry.get("outcome", ""),
                    "timestamp": entry.get("timestamp", ""),
                })
    matches.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return matches[:10]


def data_manifest(args: argparse.Namespace) -> None:
    """Describe available local data without printing rows or loading full CSVs."""
    profile = load_profile(required=False)
    customer_id = (args.account or profile.get("google_ads_customer_id", "")).replace("-", "")
    if not customer_id:
        raise SystemExit("data-manifest requires an active account or --account")
    query_filter = (args.query or "").strip().lower()
    start_filter = parse_date(args.from_date) if args.from_date else None
    end_filter = parse_date(args.to) if args.to else None
    groups: dict[str, dict[str, Any]] = {}
    roots = [RAW_DIR, PROCESSED_DIR / customer_id]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.csv")):
            if customer_id not in path.name and root == RAW_DIR:
                continue
            query = path.parent.name
            query_name = {
                "account-network": "account_network_period",
                "campaign-network": "campaign_network_period",
                "campaign-trend": "campaign_weekly_trend",
                "campaign-reach": "campaign_reach_period",
                "adgroup-network": "adgroup_network_period",
                "creative": "creative_period",
            }.get(query, query)
            normalized_query = query_name.lower().replace("_", "-")
            if query_filter and query_filter.replace("_", "-") not in normalized_query:
                continue
            match = re.search(rf"{re.escape(customer_id)}_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})", path.name)
            window = (match.group(1), match.group(2)) if match else (None, None)
            if start_filter and (not window[0] or dt.date.fromisoformat(window[1]) < start_filter):
                continue
            if end_filter and (not window[1] or dt.date.fromisoformat(window[0]) > end_filter):
                continue
            key = query_name
            item = groups.setdefault(key, {"files": 0, "windows": [], "latest": None, "columns": []})
            item["files"] += 1
            if window[0] and window not in item["windows"]:
                item["windows"].append(window)
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).isoformat()
            if not item["latest"] or modified > item["latest"]:
                item["latest"] = modified
            if not item["columns"]:
                try:
                    with path.open(newline="") as handle:
                        item["columns"] = next(csv.reader(handle), [])
                except OSError:
                    item["columns"] = []
    for item in groups.values():
        item["windows"].sort()
        item["columns"] = item["columns"][:30]
    pulls = _manifest_pull_status(customer_id, query_filter, start_filter, end_filter)
    print(json.dumps({
        "client_instance_id": os.getenv("BOB_CLIENT_INSTANCE_ID", ""),
        "account": customer_id,
        "filters": {"query": query_filter or None, "from": args.from_date or None, "to": args.to or None},
        "data": groups,
        "pulls": pulls,
    }, separators=(",", ":")))

__all__ = [name for name in globals() if not name.startswith("__")]
