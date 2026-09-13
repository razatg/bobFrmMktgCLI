"""Creative performance slicing for performance analysis."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *  # noqa: F403
from lib.bob.platform.data import *  # noqa: F403
from lib.bob.platform.presentation import *  # noqa: F403

def slice_creatives(args: argparse.Namespace) -> None:
    """Filter creative processed CSV to LOW-label assets, flag Low-Action, show patterns."""
    profile = load_profile(required=False)
    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", 50000))
    primary_goal = profile.get("primary_goal", "in_app_conversions")
    currency = _currency_symbol(profile.get("currency", ""))
    customer_id = profile.get("google_ads_customer_id")

    creative_paths = _creative_processed_paths(customer_id)
    creative_path = creative_paths[-1]
    rows = []
    for creative_path in creative_paths:
        rows.extend(read_csv(creative_path))
    rows = _dedupe_creative_rows(rows)
    if not rows:
        print(
            f"No creative data in {creative_path.name} (account {customer_id}). "
            f"Nothing to slice.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Step 1: filter to min impressions only
    eligible = [r for r in rows if number(r.get("impressions", 0)) >= min_imp]
    # Step 2: filter to LOW label only
    low_rows = [r for r in eligible if r.get("performance_label", "").upper() == "LOW"]

    if not low_rows:
        print(f"No LOW-label creatives above {min_imp:.0f} minimum impressions.")
        return

    # Build per-(campaign, asset_type) aggregates so text/video/image are compared fairly
    conv_col = "in_app_conversions" if primary_goal == "in_app_conversions" else "installs"
    camp_agg: dict[tuple, dict] = {}
    for r in eligible:
        key = (r.get("campaign_name", ""), r.get("asset_type", ""))
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

    # Count assets per (campaign, asset_type) so we know when comparison is meaningful
    type_counts_per_camp: dict[tuple, int] = {}
    for r in eligible:
        key = (r.get("campaign_name", ""), r.get("asset_type", ""))
        type_counts_per_camp[key] = type_counts_per_camp.get(key, 0) + 1

    # Flag each LOW creative: low-action = 2+ metrics worse than campaign+asset_type avg
    results = []
    for r in low_rows:
        cname = r.get("campaign_name", "")
        atype = r.get("asset_type", "")
        cm = camp_agg.get((cname, atype), {})

        asset_ctr = number(r.get("ctr_percent", 0))
        asset_cti = number(r.get("cti_percent", 0))
        asset_cpc = number(r.get("cpc", 0))

        worse_ctr = asset_ctr < cm.get("ctr", 0) * 0.90 if cm.get("ctr", 0) > 0 else False
        worse_cti = asset_cti < cm.get("cti", 0) * 0.90 if cm.get("cti", 0) > 0 else False
        worse_cpc = asset_cpc > cm.get("cpc", 0) * 1.10 if cm.get("cpc", 0) > 0 else False

        peers = type_counts_per_camp.get((cname, atype), 0)
        if peers <= 1:
            # Only asset of its type in this campaign — can't compare; trust the API LOW label
            flag = "low-action"
            worse_ctr = worse_cti = worse_cpc = False
        else:
            flag = "low-action" if sum([worse_ctr, worse_cti, worse_cpc]) >= 2 else "low-watch"
        results.append({
            "flag": flag,
            "campaign_name": cname,
            "ad_group_name": r.get("ad_group_name", ""),
            "asset_id": r.get("asset_id", ""),
            "asset_name": r.get("asset_name", ""),
            "asset_type": r.get("asset_type", ""),
            "field_type": r.get("field_type", ""),
            "impressions": r.get("impressions", ""),
            "cost": r.get("cost", ""),
            "ctr_percent": r.get("ctr_percent", ""),
            "type_avg_ctr": format_float(cm.get("ctr", 0)),
            "cti_percent": r.get("cti_percent", ""),
            "type_avg_cti": format_float(cm.get("cti", 0)),
            "cpc": r.get("cpc", ""),
            "type_avg_cpc": format_float(cm.get("cpc", 0)),
            "installs": r.get("installs", ""),
            "in_app_conversions": r.get("in_app_conversions", ""),
            "worse_ctr": str(worse_ctr),
            "worse_cti": str(worse_cti),
            "worse_cpc": str(worse_cpc),
        })

    text_low_action = [r for r in results if r["flag"] == "low-action" and r["asset_type"] == "TEXT"]
    text_low_watch = [r for r in results if r["flag"] == "low-watch" and r["asset_type"] == "TEXT"]
    media_low = [r for r in results if r["asset_type"] in ("YOUTUBE_VIDEO", "IMAGE", "MEDIA_BUNDLE")]

    print(f"\n[Creative Underperformance — LOW label, ≥{min_imp:.0f} impressions]\n")
    print(f"  {len(results)} LOW total | {len(text_low_action)} text low-action | {len(text_low_watch)} text low-watch | {len(media_low)} video/image LOW\n")

    # Section 1: Text low-action (2+ metrics worse than same-type campaign avg)
    if text_low_action:
        print(f"  TEXT LOW-ACTION ({len(text_low_action)} — CTR/CTI/CPC worse vs same-type campaign avg)")
        hdr = (f"  {'Asset/ID':<28}  {'Field':<14}  "
               f"{'CTR%':>6}  {'TypeAvg':>8}  {'CTI%':>6}  {'TypeAvg':>8}  "
               f"{'CPC':>8}  {'TypeAvg':>8}")
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for r in text_low_action:
            label = (r["asset_name"] or r["asset_id"] or "—")[:26]
            print(
                f"  {label:<28}  {r['field_type']:<14}  "
                f"{_fmt_display(r['ctr_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_ctr'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cti_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_cti'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cpc'], 'cost', currency):>8}  "
                f"{_fmt_display(r['type_avg_cpc'], 'cost', currency):>8}"
            )

    # Section 2: Video / Image LOW (always surfaced — production cost to replace)
    if media_low:
        print(f"\n  VIDEO / IMAGE LOW ({len(media_low)} — API signal; review for refresh)")
        hdr2 = (f"  {'Asset name/ID':<36}  {'Type':<14}  "
                f"{'CTR%':>6}  {'TypeAvg':>8}  {'CTI%':>6}  {'TypeAvg':>8}  "
                f"{'CPC':>8}  {'TypeAvg':>8}")
        print(hdr2)
        print("  " + "─" * (len(hdr2) - 2))
        for r in media_low:
            label = (r["asset_name"] or r["asset_id"] or "—")[:34]
            print(
                f"  {label:<36}  {r['asset_type']:<14}  "
                f"{_fmt_display(r['ctr_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_ctr'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cti_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_cti'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cpc'], 'cost', currency):>8}  "
                f"{_fmt_display(r['type_avg_cpc'], 'cost', currency):>8}"
            )

    if text_low_watch:
        print(f"\n  TEXT LOW-WATCH ({len(text_low_watch)} — only 1 metric worse; monitor):")
        for r in text_low_watch[:10]:  # cap at 10 to avoid wall of text
            label = (r["asset_name"] or r["asset_id"] or "—")[:40]
            print(f"    {r['field_type']:<14}  {label}")
        if len(text_low_watch) > 10:
            print(f"    … and {len(text_low_watch) - 10} more (use --output to save full list)")

    # Pattern analysis on all low-action assets (text + media)
    all_low_action = text_low_action + media_low
    if all_low_action:
        from collections import Counter
        type_counts: Counter = Counter(r["asset_type"] for r in all_low_action)
        field_counts: Counter = Counter(r["field_type"] for r in all_low_action)

        # Mine asset_name tokens (populated for images/videos)
        name_words: Counter = Counter()
        for r in all_low_action:
            for src in (r.get("asset_name") or "", r.get("ad_group_name") or ""):
                for tok in src.replace("-", " ").replace("_", " ").split():
                    if len(tok) >= 4:
                        name_words[tok.lower()] += 1

        # Ad-group patterns (always populated — describes creative theme)
        adgroup_counts: Counter = Counter(r.get("ad_group_name", "") for r in all_low_action if r.get("ad_group_name"))

        print("\n  [Patterns in Low-Action creatives]")
        print(f"  Asset types : {', '.join(f'{t}×{c}' for t, c in type_counts.most_common())}")
        print(f"  Field types : {', '.join(f'{f}×{c}' for f, c in field_counts.most_common())}")
        common_tokens = [(w, c) for w, c in name_words.most_common(8) if c >= 3]
        if common_tokens:
            print(f"  Common terms: {', '.join(f'{w}({c})' for w, c in common_tokens)}")
        top_adgroups = adgroup_counts.most_common(5)
        if top_adgroups:
            print(f"  Top ad groups with Low-Action creatives:")
            for ag, c in top_adgroups:
                print(f"    {c:>3}× {ag}")

    if getattr(args, "output", None):
        out = Path(args.output).expanduser()
        cols = ["flag", "campaign_name", "ad_group_name", "asset_id", "asset_name",
                "asset_type", "field_type", "impressions", "cost",
                "ctr_percent", "type_avg_ctr", "cti_percent", "type_avg_cti",
                "cpc", "type_avg_cpc", "installs", "in_app_conversions",
                "worse_ctr", "worse_cti", "worse_cpc"]
        write_csv(out, results, cols)
        print(f"\n  full CSV written: {out}")


_LANG_CANONICAL: dict = {
    'english': 'English', 'eng': 'English',
    'hindi': 'Hindi',
    'hinglish': 'Hinglish', 'nagpurihinglish': 'Hinglish',
    'bengali': 'Bengali',
    'telugu': 'Telugu', 'tenglish': 'Telugu',
    'tamil': 'Tamil', 'tanglish': 'Tamil',
    'gujarati': 'Gujarati', 'gujrati': 'Gujarati', 'gujlish': 'Gujarati',
    'marathi': 'Marathi',
    'malayalam': 'Malayalam', 'manglish': 'Malayalam',
    'odia': 'Odia',
    'kannada': 'Kannada',
}
_LANG_RE = re.compile(
    r'\b(' + '|'.join(_LANG_CANONICAL) + r')\b', re.IGNORECASE
)

__all__ = [name for name in globals() if not name.startswith("__")]
