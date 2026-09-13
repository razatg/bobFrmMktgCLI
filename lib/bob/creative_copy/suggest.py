"""Creative-copy recommendation planning."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
from lib.bob.platform.data import *
from lib.bob.platform.google_ads import *
from lib.bob.platform.presentation import *
def _fetch_asset_texts(client, customer_id: str, asset_ids: list) -> dict:
    """Fetch text content directly from the Asset resource as a fallback."""
    if not asset_ids:
        return {}
    ga_service = client.get_service("GoogleAdsService")
    id_list = ", ".join(str(i) for i in asset_ids[:500])
    query = (
        "SELECT asset.id, asset.text_asset.text "
        "FROM asset "
        "WHERE asset.type = 'TEXT' "
        f"AND asset.id IN ({id_list})"
    )
    result = {}
    try:
        response = ga_service.search(customer_id=customer_id, query=query)
        for row in response:
            result[str(row.asset.id)] = row.asset.text_asset.text or ""
    except Exception as exc:
        print(f"  warning: could not fetch asset text: {exc}")
    return result


def _creative_ad_id(asset_view_resource_name: Any) -> str:
    """Extract the ad ID from an ad-group-ad-asset-view resource name."""
    tail = str(asset_view_resource_name or "").rsplit("/", 1)[-1]
    parts = tail.split("~")
    return parts[1] if len(parts) == 4 and parts[1].isdigit() else ""


def suggest_creative_copy(args: argparse.Namespace) -> None:
    """Generate a copy plan YAML + compact agent-agnostic prompt for LOW-action text assets."""
    import datetime as _dt
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required: pip install pyyaml")

    profile = load_profile(required=False)
    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", 50000))
    primary_goal = profile.get("primary_goal", "in_app_conversions")
    customer_id = profile.get("google_ads_customer_id", "unknown")

    creative_paths = _creative_processed_paths(customer_id)
    rows = []
    for creative_path in creative_paths:
        rows.extend(read_csv(creative_path))
    rows = _dedupe_creative_rows(rows)
    eligible = [r for r in rows if number(r.get("impressions", 0)) >= min_imp]

    # Campaign-level averages per (campaign_id, asset_type)
    camp_agg: dict[tuple, dict] = {}
    for r in eligible:
        key = (r.get("campaign_id", ""), r.get("campaign_name", ""), r.get("asset_type", ""))
        if key not in camp_agg:
            camp_agg[key] = {"imp": 0.0, "clicks": 0.0, "installs": 0.0, "cost": 0.0}
        camp_agg[key]["imp"] += number(r.get("impressions", 0))
        camp_agg[key]["clicks"] += number(r.get("clicks", 0))
        camp_agg[key]["installs"] += number(r.get("installs", 0))
        camp_agg[key]["cost"] += number(r.get("cost", 0))
    for m in camp_agg.values():
        m["ctr"] = m["clicks"] / m["imp"] * 100 if m["imp"] > 0 else 0.0
        m["cti"] = m["installs"] / m["clicks"] * 100 if m["clicks"] > 0 else 0.0
        m["cpc"] = m["cost"] / m["clicks"] if m["clicks"] > 0 else 0.0

    # Peer counts per (campaign_id, asset_type) for meaningful comparison
    peer_counts: dict[tuple, int] = {}
    for r in eligible:
        key = (r.get("campaign_id", ""), r.get("campaign_name", ""), r.get("asset_type", ""))
        peer_counts[key] = peer_counts.get(key, 0) + 1

    # Current asset count per (ad_group_id, field_type) — used for limit check in apply
    ag_field_counts: dict[tuple, int] = {}
    for r in rows:  # full set, not just eligible
        key = (r.get("ad_group_id", ""), r.get("field_type", ""))
        ag_field_counts[key] = ag_field_counts.get(key, 0) + 1

    # LOW-action TEXT candidates (same 2-metric test as slice_creatives)
    low_rows = [r for r in eligible if r.get("performance_label", "").upper() == "LOW" and r.get("asset_type", "") == "TEXT"]
    changes = []
    for r in low_rows:
        cid = r.get("campaign_id", "")
        cname = r.get("campaign_name", "")
        ft = r.get("field_type", "")
        cm = camp_agg.get((cid, cname, "TEXT"), {})
        peers = peer_counts.get((cid, cname, "TEXT"), 0)

        asset_ctr = number(r.get("ctr_percent", 0))
        asset_cti = number(r.get("cti_percent", 0))
        asset_cpc = number(r.get("cpc", 0))
        worse_ctr = asset_ctr < cm.get("ctr", 0) * 0.90 if cm.get("ctr", 0) > 0 else False
        worse_cti = asset_cti < cm.get("cti", 0) * 0.90 if cm.get("cti", 0) > 0 else False
        worse_cpc = asset_cpc > cm.get("cpc", 0) * 1.10 if cm.get("cpc", 0) > 0 else False

        is_low_action = peers <= 1 or sum([worse_ctr, worse_cti, worse_cpc]) >= 2
        if not is_low_action:
            continue

        # Primary failing metric for prompt (most actionable signal)
        if worse_ctr:
            metric_note = f"CTR {asset_ctr:.1f}% vs avg {cm.get('ctr', 0):.1f}%"
        elif worse_cti:
            metric_note = f"CTI {asset_cti:.1f}% vs avg {cm.get('cti', 0):.1f}%"
        else:
            metric_note = f"CPC {asset_cpc:.2f} vs avg {cm.get('cpc', 0):.2f}"

        changes.append({
            "campaign_id": cid,
            "campaign_name": cname,
            "ad_group_id": r.get("ad_group_id", ""),
            "ad_group_name": r.get("ad_group_name", ""),
            "ad_id": _creative_ad_id(r.get("asset_view_resource_name", "")),
            "asset_id": r.get("asset_id", ""),
            "field_type": ft,
            "current_text": r.get("asset_text", ""),
            "current_asset_count": ag_field_counts.get((r.get("ad_group_id", ""), ft), 0),
            "ctr_percent": format_float(asset_ctr),
            "campaign_avg_ctr": format_float(cm.get("ctr", 0)),
            "cti_percent": format_float(asset_cti),
            "campaign_avg_cti": format_float(cm.get("cti", 0)),
            "cpc": format_float(asset_cpc),
            "campaign_avg_cpc": format_float(cm.get("cpc", 0)),
            "_metric_note": metric_note,  # used for prompt only, not written to YAML
            "suggested_text": None,
            "action": "replace",
        })

    invalid_sources = [
        c["asset_id"] for c in changes
        if not str(c.get("current_text", "")).strip() or not c.get("ad_id")
    ]
    if invalid_sources:
        die(
            "creative copy plan blocked: exact ad identity or asset text is missing for asset IDs "
            + ", ".join(map(str, invalid_sources[:20]))
            + ". Refresh the creative data and regenerate the plan."
        )

    # Assign 1-based index to each change so the subagent can reference by number
    for i, c in enumerate(changes, 1):
        c["change_index"] = i

    today = _dt.date.today().isoformat()
    out_dir = Path(getattr(args, "output_dir", None) or STATE_ROOT / "wiki" / "action-items")
    out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = out_dir / f"creative-copy-{today}.yaml"
    prompt_path = out_dir / f"creative-copy-{today}-prompt.txt"

    # Strip internal keys before writing YAML
    _strip = {"_metric_note"}
    yaml_changes = [{k: v for k, v in c.items() if k not in _strip} for c in changes]
    plan = {
        "date": today,
        "customer_id": customer_id,
        "changes": yaml_changes,
        "applied": False,
        "applied_at": None,
    }
    with open(yaml_path, "w") as f:
        _yaml.dump(plan, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    _rules_header = [
        "App campaign copy rules:",
        "- HEADLINE ≤ 30 chars, DESCRIPTION ≤ 90 chars",
        "- Lead with a specific app benefit — not a generic phrase",
        "- Each asset must work standalone AND in combination with other assets and images",
        "- Every DESCRIPTION must end with punctuation (. or !) — max 1 exclamation mark per asset",
        "- Do not copy text already GOOD or BEST in the same ad group",
        "- If the current text contains a proper noun (place name, landmark, neighbourhood — e.g. \"Dum Dum airport\", \"Kalighat\"), keep it in the replacement. Tweak the surrounding copy, never swap the proper noun for a generic term.",
        "",
        "For each numbered asset below write one replacement following the rules above.",
        "Do NOT reuse the current text. Stay within the character limit for the field type.",
        "",
    ]

    batch_size = getattr(args, "batch_size", 25)
    batches = [changes[i:i + batch_size] for i in range(0, len(changes), batch_size)]
    prompt_paths = []
    for b_idx, batch in enumerate(batches, 1):
        b_path = out_dir / f"creative-copy-{today}-batch-{b_idx:03d}.txt"
        b_lines = list(_rules_header)
        for c in batch:
            b_lines.append(
                f'{c["change_index"]}. [{c["campaign_name"]} / {c["field_type"]}]'
                f'  ad_group: {c["ad_group_name"]}'
            )
            if c.get("current_text"):
                b_lines.append(f'   Current: "{c["current_text"][:60]}" — {c["_metric_note"]}')
        first_id = batch[0]["change_index"]
        last_id = batch[-1]["change_index"]
        b_lines += ['', f'Output ONLY: [{{"id":{first_id},"text":"..."}},{{"id":{last_id},"text":"..."}}]']
        b_path.write_text("\n".join(b_lines))
        prompt_paths.append((b_path, first_id, last_id))

    print(f"\nPlan:    {yaml_path}")
    print(f"Batches: {len(batches)} prompt files ({batch_size} assets each, last may be smaller)")
    for b_path, fid, lid in prompt_paths:
        print(f"  {b_path}  (assets {fid}–{lid})")
    print(f"\n{len(changes)} assets across {len({c['campaign_id'] for c in changes})} campaigns.")
    print("Use the bob-creative-copy skill — spawn one Agent call per batch file, then run:")
    print(f'  python3 lib/datapull.py creative-copy-apply --plan {yaml_path} --suggestions \'[...json...]\' ')

__all__ = [name for name in globals() if not name.startswith("__")]
