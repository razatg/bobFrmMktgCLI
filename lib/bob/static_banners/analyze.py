"""Static-banner analysis and design-guide generation."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
from lib.bob.platform.data import *
from lib.bob.platform.google_ads import *
from lib.bob.platform.presentation import *
def _lang_canonical(ag_name: str) -> str:
    """Extract canonical language from ad group name (e.g. 'Tenglish' → 'Telugu')."""
    m = _LANG_RE.search(ag_name)
    return _LANG_CANONICAL.get(m.group(1).lower(), 'Other') if m else 'Other'


def _ad_group_theme(ag_name: str) -> str:
    """First-two-segment theme from ad group name: 'UseCase-Party', 'Transit-Bus', etc."""
    name = re.sub(r'[-_][A-Z][a-z]{2,4}\d{2,4}_?$', '', ag_name).strip()
    parts = re.split(r'[-_]+', name)
    return '-'.join(parts[:2]) if len(parts) >= 2 else name


def _asset_dimension(row: dict[str, Any], axis: str) -> int | None:
    keys = (
        f"image_{axis}",
        f"asset_image_{axis}",
        f"full_size_{axis}",
        f"{axis}_pixels",
        f"image_{axis}_pixels",
        f"asset_image_{axis}_pixels",
        axis,
    )
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "NA"):
            numeric = int(number(value))
            if numeric > 0:
                return numeric
    return None


def _asset_url(row: dict[str, Any]) -> str:
    for key in (
        "image_url",
        "asset_image_url",
        "full_size_url",
        "asset_image_full_size_url",
        "asset.image_asset.full_size.url",
        "url",
    ):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _ratio_bucket_from_dimensions(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "unknown"
    ratio_value = width / height
    if abs(ratio_value - (1200 / 628)) <= 0.08:
        return "horizontal"
    if abs(ratio_value - (4 / 5)) <= 0.05:
        return "vertical"
    if abs(ratio_value - 1.0) <= 0.05:
        return "square"
    return "unknown"


def _static_banner_ratio_bucket(row: dict[str, Any]) -> str:
    field_type = str(row.get("field_type", "")).upper()
    mapped = STATIC_IMAGE_FIELD_RATIOS.get(field_type)
    if mapped and mapped != "unknown":
        return mapped
    return _ratio_bucket_from_dimensions(
        _asset_dimension(row, "width"),
        _asset_dimension(row, "height"),
    )


def _is_static_image_asset(row: dict[str, Any]) -> bool:
    asset_type = str(row.get("asset_type", "")).upper()
    field_type = str(row.get("field_type", "")).upper()
    return asset_type == "IMAGE" or field_type in STATIC_IMAGE_FIELD_RATIOS


def _creative_file_period(path: Path) -> tuple[str, str]:
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return parts[1], parts[2]
    return "unknown", "unknown"


def _fresh_static_banner_guide_date(path: Path, max_age_days: int) -> dt.date | None:
    if not path.exists():
        return None
    text = path.read_text(errors="ignore")
    if "Static Banner Diagnostic" in text or "data-only diagnostic" in text:
        return None
    match = re.search(r"^date:\s*'?([0-9]{4}-[0-9]{2}-[0-9]{2})'?\s*$", text, re.MULTILINE)
    if match:
        try:
            written = dt.date.fromisoformat(match.group(1))
        except ValueError:
            written = dt.date.fromtimestamp(path.stat().st_mtime)
    else:
        written = dt.date.fromtimestamp(path.stat().st_mtime)
    return written if (today() - written).days < max_age_days else None


def _static_banner_asset(row: dict[str, Any], ratio_bucket: str, source_label: str) -> dict[str, Any]:
    return {
        "source_label": source_label,
        "ratio_bucket": ratio_bucket,
        "campaign_id": row.get("campaign_id", ""),
        "campaign_name": row.get("campaign_name", ""),
        "ad_group_id": row.get("ad_group_id", ""),
        "ad_group_name": row.get("ad_group_name", ""),
        "asset_id": row.get("asset_id", ""),
        "asset_name": row.get("asset_name", ""),
        "asset_type": row.get("asset_type", ""),
        "field_type": row.get("field_type", ""),
        "performance_label": row.get("performance_label", ""),
        "width": _asset_dimension(row, "width"),
        "height": _asset_dimension(row, "height"),
        "mime_type": row.get("mime_type", "") or row.get("image_mime_type", ""),
        "file_size_bytes": row.get("file_size_bytes", "") or row.get("image_file_size_bytes", ""),
        "source_url": _asset_url(row),
        "impressions": row.get("impressions", ""),
        "clicks": row.get("clicks", ""),
        "ctr_percent": row.get("ctr_percent", ""),
        "installs": row.get("installs", ""),
        "in_app_conversions": row.get("in_app_conversions", ""),
        "cti_percent": row.get("cti_percent", ""),
        "cpc": row.get("cpc", ""),
    }


def _static_banner_identity_key(asset: dict[str, Any]) -> tuple[str, str]:
    asset_id = str(asset.get("asset_id", "")).strip()
    if asset_id:
        return ("asset_id", asset_id)
    source_url = str(asset.get("source_url", "")).strip()
    if source_url:
        return ("source_url", source_url)
    fallback = "|".join(
        str(asset.get(key, "") or "")
        for key in ("asset_name", "width", "height", "file_size_bytes")
    )
    return ("fallback", fallback)


def _static_banner_placement(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "campaign_id": asset.get("campaign_id", ""),
        "campaign_name": asset.get("campaign_name", ""),
        "ad_group_id": asset.get("ad_group_id", ""),
        "ad_group_name": asset.get("ad_group_name", ""),
        "field_type": asset.get("field_type", ""),
        "impressions": asset.get("impressions", ""),
        "clicks": asset.get("clicks", ""),
        "installs": asset.get("installs", ""),
        "in_app_conversions": asset.get("in_app_conversions", ""),
        "ctr_percent": asset.get("ctr_percent", ""),
        "cti_percent": asset.get("cti_percent", ""),
        "cpc": asset.get("cpc", ""),
        "source_url": asset.get("source_url", ""),
    }


def _merge_static_banner_asset_group(assets: list[dict[str, Any]]) -> dict[str, Any]:
    ranked_assets = sorted(
        assets,
        key=lambda asset: (
            number(asset.get("in_app_conversions")),
            number(asset.get("installs")),
            number(asset.get("impressions")),
        ),
        reverse=True,
    )
    merged = dict(ranked_assets[0])
    placements = [_static_banner_placement(asset) for asset in ranked_assets]
    merged["duplicate_placements"] = placements
    merged["duplicate_placement_count"] = len(placements)
    merged["top_placement_campaign_name"] = placements[0].get("campaign_name", "")
    merged["top_placement_ad_group_name"] = placements[0].get("ad_group_name", "")
    for metric in ("impressions", "clicks", "installs", "in_app_conversions"):
        merged[metric] = sum(number(asset.get(metric)) for asset in assets)
    impressions = number(merged.get("impressions"))
    clicks = number(merged.get("clicks"))
    installs = number(merged.get("installs"))
    conversions = number(merged.get("in_app_conversions"))
    merged["ctr_percent"] = (clicks / impressions * 100) if impressions else ""
    merged["cti_percent"] = (installs / clicks * 100) if clicks else ""
    cpc_values = [number(asset.get("cpc")) for asset in assets if number(asset.get("cpc")) > 0]
    merged["cpc"] = (sum(cpc_values) / len(cpc_values)) if cpc_values else ""
    return merged


def _dedupe_static_banner_assets(assets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordered_keys: list[tuple[str, str]] = []
    for asset in assets:
        key = _static_banner_identity_key(asset)
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(key)
        grouped[key].append(asset)
    unique_assets = [_merge_static_banner_asset_group(grouped[key]) for key in ordered_keys]
    duplicate_groups = [
        {
            "asset_id": asset.get("asset_id", ""),
            "asset_name": asset.get("asset_name", ""),
            "source_url": asset.get("source_url", ""),
            "duplicate_placement_count": asset.get("duplicate_placement_count", 1),
            "placements": asset.get("duplicate_placements", []),
        }
        for asset in unique_assets
        if number(asset.get("duplicate_placement_count")) > 1
    ]
    return unique_assets, duplicate_groups


def _group_static_banner_assets(assets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {key: [] for key in STATIC_BANNER_SPECS}
    grouped["unknown"] = []
    for asset in assets:
        grouped.setdefault(asset["ratio_bucket"], []).append(asset)
    for ratio, rows in grouped.items():
        grouped[ratio] = sorted(
            rows,
            key=lambda r: (
                number(r.get("in_app_conversions")),
                number(r.get("installs")),
                number(r.get("impressions")),
            ),
            reverse=True,
        )
    return grouped


def _build_default_static_banner_strategy(grouped_assets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    themes: list[str] = []
    for ratio in ("horizontal", "vertical", "square"):
        for asset in grouped_assets.get(ratio, [])[:5]:
            theme = _ad_group_theme(asset.get("ad_group_name", ""))
            if theme and theme not in themes:
                themes.append(theme)
    theme_text = ", ".join(themes[:8]) if themes else "winning campaign/ad group contexts"
    return {
        "status": "data_only_pending_visual_review",
        "raw_asset_count": sum(len(grouped_assets.get(ratio, [])) for ratio in grouped_assets),
        "unique_image_count": sum(len(grouped_assets.get(ratio, [])) for ratio in grouped_assets),
        "winning_patterns": [
            f"Use the strongest observed campaign/ad group contexts as creative territories: {theme_text}.",
            "Keep each banner focused on one use case, one benefit, and one direct action.",
            "Prefer layouts that leave clear space for benefit copy and a short CTA.",
        ],
        "ratio_rules": {
            "horizontal": "Use a wide composition with the core message on one side and the product or context on the other.",
            "vertical": "Use stacked hierarchy: benefit first, product/context visual second, CTA last.",
            "square": "Keep the visual simple and centered; avoid dense text because the format has less horizontal room.",
        },
        "message_hierarchy": [
            "Primary use case, occasion, audience context, or need state.",
            "Specific benefit such as speed, savings, convenience, capacity, trust, quality, access, or a trial offer.",
            "Short CTA that works without surrounding copy.",
        ],
        "cta_rules": [
            "Use one CTA per banner.",
            "Keep CTA copy short enough to remain readable on mobile inventory.",
            "Do not let coupon text overpower the actual product or service benefit.",
        ],
        "brand_and_product_rules": [
            "Make the product or service signal visible without turning the banner into a logo-only ad.",
            "Use campaign/ad group context to choose the product or service focus and use context.",
        ],
        "visual_style": [
            "Prioritize legible contrast, simple foreground/background separation, and recognisable context.",
            "Avoid generic lifestyle imagery that does not communicate the use occasion.",
        ],
        "visual_language": [
            "Use one dominant reading path: claim first, proof second, action third.",
            "Keep the message inside a high-contrast block when the background is busy.",
            "Build separate compositions for horizontal, vertical, and square instead of resizing one master layout.",
        ],
        "brand_colors": {},
        "typography_signals": {},
        "component_patterns": [],
        "brand_signals": [],
        "token_confidence_notes": [],
        "avoid": [
            "Crowded text blocks.",
            "Multiple competing offers.",
            "Layouts that cannot adapt across horizontal, vertical, and square.",
            "Generic visual claims not supported by the campaign/ad group context.",
        ],
        "future_generation_contract_notes": [
            "Future generation must require campaign, ad group, and user brief before producing images.",
            "Start from the guide and brief, then say exactly which element cannot be faithfully generated if something is missing.",
            "Do not assume a fixed upload bundle; ask only for missing elements needed for fidelity or approval.",
        ],
    }


def _write_static_banner_index_entry(index_path: Path, entry: str, section: str = "Design") -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        text = index_path.read_text()
    else:
        text = "# Bob — Wiki Index\n\n## Analyses\n\n## Action Items\n\n## Design\n\n## Backlog\n"
    if f"## {section}" not in text:
        if "## Backlog" in text:
            text = text.replace("## Backlog", f"## {section}\n\n## Backlog", 1)
        else:
            text = text.rstrip() + f"\n\n## {section}\n"
    lines = text.splitlines()
    out: list[str] = []
    inserted = False
    in_target_section = False
    for line in lines:
        if line.startswith("## "):
            if in_target_section and not inserted:
                out.append(entry)
                inserted = True
            in_target_section = line.strip() == f"## {section}"
            out.append(line)
            continue
        if "Static Banner Design" in line:
            if not inserted:
                if in_target_section:
                    out.append(entry)
                    inserted = True
            continue
        out.append(line)
    if in_target_section and not inserted:
        out.append(entry)
    index_path.write_text("\n".join(out).rstrip() + "\n")


def _format_asset_metric_row(asset: dict[str, Any], currency: str) -> str:
    def _cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ").strip()

    label = asset.get("asset_name") or asset.get("asset_id") or "unknown"
    size = "unknown"
    if asset.get("width") and asset.get("height"):
        size = f"{asset['width']}x{asset['height']}"
    url = asset.get("source_url") or "unavailable"
    return (
        f"| {_cell(label)} | {_cell(asset.get('campaign_name', ''))} | {_cell(asset.get('ad_group_name', ''))} | "
        f"{_cell(asset.get('field_type', ''))} | {_cell(size)} | {_cell(asset.get('performance_label', ''))} | "
        f"{_fmt_display(asset.get('impressions'), 'count')} | "
        f"{_fmt_display(asset.get('clicks'), 'count')} | "
        f"{_fmt_display(asset.get('ctr_percent'), 'percent')} | "
        f"{_fmt_display(asset.get('installs'), 'count')} | "
        f"{_fmt_display(asset.get('in_app_conversions'), 'count')} | "
        f"{_fmt_display(asset.get('cti_percent'), 'percent')} | "
        f"{_fmt_display(asset.get('cpc'), 'cost', currency)} | {_cell(url)} |"
    )


def _format_repeated_placement_row(asset: dict[str, Any], placement: dict[str, Any], currency: str) -> str:
    asset_label = str(asset.get("asset_name") or asset.get("asset_id") or "unknown").replace("|", "\\|")
    campaign = str(placement.get("campaign_name", "") or "").replace("|", "\\|")
    ad_group = str(placement.get("ad_group_name", "") or "").replace("|", "\\|")
    return (
        f"| {asset_label} | {campaign} | {ad_group} | "
        f"{_fmt_display(placement.get('impressions'), 'count')} | "
        f"{_fmt_display(placement.get('clicks'), 'count')} | "
        f"{_fmt_display(placement.get('installs'), 'count')} | "
        f"{_fmt_display(placement.get('in_app_conversions'), 'count')} | "
        f"{_fmt_display(placement.get('cpc'), 'cost', currency)} |"
    )


def _static_banner_asset_filename(asset: dict[str, Any], index: int) -> str:
    source_url = asset.get("source_url") or ""
    suffix = Path(urllib.parse.urlparse(source_url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        mime = str(asset.get("mime_type") or "").lower()
        suffix = ".png" if "png" in mime else ".jpg"
    asset_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(asset.get("asset_id") or f"asset-{index}")).strip("-")
    return f"{index:03d}-{asset_id}{suffix}"


def _download_static_banner_assets(
    grouped_assets: dict[str, list[dict[str, Any]]],
    output_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded_grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in grouped_assets}
    manifest: list[dict[str, Any]] = []
    index = 1
    for ratio, assets in grouped_assets.items():
        for asset in assets:
            enriched = dict(asset)
            source_url = enriched.get("source_url") or ""
            local_path = ""
            status = "no_url"
            error = ""
            if source_url:
                filename = _static_banner_asset_filename(enriched, index)
                destination = output_dir / filename
                try:
                    urllib.request.urlretrieve(source_url, destination)
                    local_path = str(destination)
                    status = "downloaded"
                except Exception as exc:
                    status = "download_failed"
                    error = str(exc)
            enriched["local_path"] = local_path
            enriched["download_status"] = status
            enriched["download_error"] = error
            downloaded_grouped.setdefault(ratio, []).append(enriched)
            manifest.append(enriched)
            index += 1
    return downloaded_grouped, manifest


def _write_static_banner_manifest(run_dir: Path, payload: dict[str, Any]) -> Path:
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return manifest_path


def _strategy_has_visual_evidence(strategy: dict[str, Any]) -> bool:
    inspected = strategy.get("image_inspected_count")
    if number(inspected) > 0:
        return True
    inspected = strategy.get("unique_image_count")
    if number(inspected) > 0:
        return True
    observations = strategy.get("creative_observations") or strategy.get("per_creative_observations")
    return isinstance(observations, list) and len(observations) > 0


def _append_markdown_section(lines: list[str], title: str, values: Any, fallback: str = "- Not provided.") -> None:
    lines.extend(["", f"## {title}"])
    if isinstance(values, dict):
        if not values:
            lines.append(fallback)
            return
        for key, value in values.items():
            lines.append(f"- **{str(key).title()}:** {value}")
        return
    if isinstance(values, list):
        if not values:
            lines.append(fallback)
            return
        for value in values:
            lines.append(f"- {value}")
        return
    if values:
        lines.append(str(values))
        return
    lines.append(fallback)


def _strategy_visual_language_lines(strategy: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for value in strategy.get("visual_language") or []:
        if str(value).strip():
            lines.append(str(value).strip())
    return lines


def _strategy_list(strategy: dict[str, Any], key: str) -> list[str]:
    values = strategy.get(key) or []
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        text = str(value or "").replace("\n", " ").strip()
        if text:
            out.append(text)
    return out


def _strategy_dict(strategy: dict[str, Any], key: str) -> dict[str, Any]:
    values = strategy.get(key) or {}
    return values if isinstance(values, dict) else {}


def _design_token_value(token: Any) -> str:
    if isinstance(token, dict):
        value = token.get("value") or token.get("hex") or token.get("token")
        return str(value or "").strip()
    return str(token or "").strip()


def _design_token_note(token: Any) -> str:
    if not isinstance(token, dict):
        return ""
    note = token.get("note") or token.get("role") or token.get("confidence")
    return str(note or "").strip()


def _infer_design_name(customer_id: str) -> str:
    safe_id = str(customer_id or "advertiser").replace(" ", "-")
    return f"{safe_id} Static Banner Design System"


def _generic_design_content_rules() -> list[str]:
    return [
        "Lead with one short problem, benefit, or use-case trigger that reads in under two seconds.",
        "Support the headline with one concrete proof element such as speed, offer, destination, or product mode.",
        "Keep the primary proof visible in the image, not only in the copy.",
        "Use no more than one headline, one proof cue, and one CTA in the same frame.",
    ]


def _write_static_banner_strategy_markdown(
    path: Path,
    customer_id: str,
    period_start: str,
    period_end: str,
    grouped_assets: dict[str, list[dict[str, Any]]],
    secondary_assets: list[dict[str, Any]],
    strategy: dict[str, Any],
    strategy_input_path: Path,
    design_path: Path,
    currency: str,
    diagnostic: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    date_str = today().isoformat()
    refresh_after = today() + dt.timedelta(days=STATIC_BANNER_REFRESH_DAYS)
    unique_count = int(number(strategy.get("unique_image_count")) or sum(len(grouped_assets.get(r, [])) for r in ("horizontal", "vertical", "square")))
    lines: list[str] = [
        "---",
        f"date: {date_str}",
        "intent: static_banner_design",
        f"customer_id: {customer_id}",
        f"period: {period_start}–{period_end}",
        f"refresh_after: {refresh_after.isoformat()}",
        "---",
        "",
        "← [Wiki Index](../Index.md)",
        "",
        f"# {'Static Banner Diagnostic' if diagnostic else 'Static Banner Strategy'}: {date_str}",
        "",
        "## Summary",
        (
            "This is a data-only diagnostic, not a final strategy artifact. It is missing strategist visual analysis."
            if diagnostic
            else "This document captures the winning static-banner evidence for the current account. It keeps account-specific observations, duplicate-placement evidence, and strategist rationale separate from the reusable design spec."
        ),
        "",
        f"Unique visual families in scope: {unique_count}. Repeated placements are kept as evidence only.",
        "",
        f"Use [DESIGN.md]({design_path.name}) as the generation-oriented design spec. This strategy file is the audit trail and evidence base.",
        "",
        "## Image Specs",
        "| Format | Ratio | Recommended size | Minimum size | Max images | File rules |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for ratio, spec in STATIC_BANNER_SPECS.items():
        lines.append(
            f"| {ratio.title()} | {spec['ratio']} | {spec['recommended_size']} | "
            f"{spec['minimum_size']} | {spec['max_images']} | .jpg or .png, max 5MB |"
        )

    lines += [
        "",
        "## Winner References",
        "| Asset | Campaign | Ad group | Field | Size | Label | Impr. | Clicks | CTR | Installs | Conv. | CTI | CPC | Source |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for ratio in ("horizontal", "vertical", "square"):
        for asset in grouped_assets.get(ratio, [])[:STATIC_BANNER_SPECS[ratio]["max_images"]]:
            lines.append(_format_asset_metric_row(asset, currency))
    if not any(grouped_assets.get(ratio) for ratio in ("horizontal", "vertical", "square")):
        lines.append("| No BEST static image assets found |  |  |  |  |  |  |  |  |  |  |  |  |  |")

    if secondary_assets:
        lines += [
            "",
            "## Secondary GOOD References",
            "No BEST static image assets were available for every slot, so these GOOD assets are reference-only.",
            "",
            "| Asset | Campaign | Ad group | Field | Size | Label | Impr. | Clicks | CTR | Installs | Conv. | CTI | CPC | Source |",
            "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for asset in secondary_assets[:20]:
            lines.append(_format_asset_metric_row(asset, currency))

    repeated_assets = [
        asset
        for ratio in ("horizontal", "vertical", "square", "unknown")
        for asset in grouped_assets.get(ratio, [])
        if number(asset.get("duplicate_placement_count")) > 1
    ]
    if repeated_assets:
        lines += [
            "",
            "## Repeated Placement Evidence",
            "| Asset | Campaign | Ad group | Impr. | Clicks | Installs | Conv. | CPC |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
        for asset in repeated_assets:
            for placement in asset.get("duplicate_placements", []):
                lines.append(_format_repeated_placement_row(asset, placement, currency))

    observations = strategy.get("creative_observations") or strategy.get("per_creative_observations")
    if observations:
        lines += [
            "",
            "## Per-Creative Visual Observations",
            "| Asset | What it looks like | Layout | Message / CTA | Why it matters |",
            "|---|---|---|---|---|",
        ]
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            asset = obs.get("asset") or obs.get("asset_id") or obs.get("asset_name") or "unknown"
            looks = obs.get("visual_description") or obs.get("what_it_looks_like") or ""
            layout = obs.get("layout_notes") or obs.get("layout") or ""
            message = obs.get("message_cta_notes") or obs.get("message") or obs.get("cta") or ""
            rationale = obs.get("why_it_matters") or obs.get("performance_read") or ""
            safe = [str(v).replace("|", "\\|").replace("\n", " ") for v in (asset, looks, layout, message, rationale)]
            lines.append(f"| {safe[0]} | {safe[1]} | {safe[2]} | {safe[3]} | {safe[4]} |")

    _append_markdown_section(lines, "Winning Patterns", strategy.get("winning_patterns"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Visual Language", strategy.get("visual_language"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Ratio-Specific Layout Rules", strategy.get("ratio_rules"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Message Hierarchy", strategy.get("message_hierarchy"), "- Not provided by strategist.")
    _append_markdown_section(lines, "CTA Rules", strategy.get("cta_rules"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Brand And Product Rules", strategy.get("brand_and_product_rules"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Visual Style", strategy.get("visual_style"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Avoid", strategy.get("avoid"), "- Not provided by strategist.")

    lines += [
        "",
        "## Future Generation Contract",
        "- Use `DESIGN.md` plus a campaign brief for future image generation. Do not use this strategy file as the primary prompt.",
        "- Future generation must require campaign, ad group, and user brief/objective.",
        "- The model should start from the guide and the brief, then say exactly which element it cannot faithfully generate if something is missing.",
        "- Do not assume a fixed upload bundle.",
        "- Ask only for the missing elements needed for fidelity or approval.",
        "- Optional future inputs: ratios, count per ratio, language or locale, offer or coupon, must-use text, and must-avoid text.",
        "- Future output expectations: exact Google dimensions, .jpg or .png, under 5MB, review files only.",
        f"- Strategist input: `{strategy_input_path}`",
    ]
    for note in strategy.get("future_generation_contract_notes", []):
        lines.append(f"- {note}")

    if diagnostic or strategy.get("status") == "data_only_pending_visual_review":
        lines += [
            "",
            "## Strategist Status",
            "Visual strategist JSON was not supplied, so this file is diagnostic only. Refetch creative_period if image URLs are missing, then run the `bob-static-banners` skill with the strategist packet.",
        ]

    path.write_text("\n".join(lines) + "\n")


def _write_static_banner_design_md(
    path: Path,
    strategy: dict[str, Any],
    strategy_path: Path,
    customer_id: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    visual_language = _strategy_visual_language_lines(strategy)
    ratio_rules = _strategy_dict(strategy, "ratio_rules")
    brand_colors = _strategy_dict(strategy, "brand_colors")
    typography_signals = _strategy_dict(strategy, "typography_signals")
    brand_signals = _strategy_list(strategy, "brand_signals")
    component_patterns = _strategy_list(strategy, "component_patterns")
    token_confidence_notes = _strategy_list(strategy, "token_confidence_notes")
    design_name = str(strategy.get("design_system_name") or _infer_design_name(customer_id))

    frontmatter: list[str] = [
        "---",
        f"name: {design_name}",
    ]
    if brand_colors:
        frontmatter.append("colors:")
        for key, token in brand_colors.items():
            value = _design_token_value(token)
            if value:
                frontmatter.append(f"  {key}: \"{value}\"")
    if typography_signals:
        frontmatter.append("typography:")
        for key, token in typography_signals.items():
            if isinstance(token, dict):
                frontmatter.append(f"  {key}:")
                for subkey in ("fontFamily", "fontWeight", "fontStyle", "fontSize"):
                    subvalue = token.get(subkey)
                    if subvalue:
                        frontmatter.append(f"    {subkey}: {subvalue}")
            else:
                frontmatter.append(f"  {key}: \"{str(token)}\"")
    frontmatter += [
        "layout:",
        "  readingPath: claim -> proof -> action",
        "  density: promotional",
        "  splitLayout: preferred for horizontal",
        "components:",
        "  primary:",
        "    - headline block",
        "    - proof container",
        "    - CTA container",
        "    - hero subject or product proof",
        "content:",
        "  maxClaims: 1",
        "  proofElements: 1",
        "  ctaElements: 1",
        "---",
        "",
    ]

    lines: list[str] = [
        *frontmatter,
        "# Design System",
        "",
        "## Overview",
        "An advertiser-specific static-banner design spec distilled from reviewed winning creatives. Use this file as the primary generation context; keep the strategy document for evidence and placement history.",
        "",
        f"Source strategy: [{strategy_path.name}]({strategy_path.name})",
        "",
        "## Brand Signals",
    ]
    if brand_signals:
        for item in brand_signals:
            lines.append(f"- {item}")
    else:
        lines.append("- Use the recurring logo lockup, hero product styling, and repeated shape language visible in the reviewed creatives as the advertiser brand anchor.")

    lines += [
        "",
        "## Visual Language",
    ]
    if visual_language:
        for item in visual_language:
            lines.append(f"- {item}")
    else:
        lines.append("- Build one dominant reading path: claim first, proof second, action third.")
        lines.append("- Prefer high-contrast message containers when the background carries scene detail.")
        lines.append("- Design each ratio intentionally instead of resizing one master layout.")

    lines += [
        "",
        "## Colors",
    ]
    if brand_colors:
        for key, token in brand_colors.items():
            value = _design_token_value(token)
            note = _design_token_note(token)
            label = str(key).replace("_", " ").title()
            line = f"- **{label}**"
            if value:
                line += f" ({value})"
            if note:
                line += f": {note}"
            lines.append(line)
    else:
        lines.append("- Brand color extraction was not provided by the strategist. Use the dominant advertiser colors visible in the reviewed creatives and document any uncertainty.")

    lines += [
        "",
        "## Token Confidence",
    ]
    if token_confidence_notes:
        for item in token_confidence_notes:
            lines.append(f"- {item}")
    else:
        lines.append("- Treat exact token values as visual inferences unless approved brand assets are supplied.")

    lines += [
        "",
        "## Typography",
    ]
    if typography_signals:
        for key, token in typography_signals.items():
            label = str(key).replace("_", " ").title()
            if isinstance(token, dict):
                details = []
                for subkey in ("fontFamily", "fontWeight", "fontStyle", "fontSize", "note"):
                    subvalue = token.get(subkey)
                    if subvalue:
                        details.append(f"{subkey}: {subvalue}")
                lines.append(f"- **{label}:** " + ", ".join(details))
            else:
                lines.append(f"- **{label}:** {token}")
    else:
        lines += [
            "- Headlines should read in under two seconds and carry the primary promise or friction point.",
            "- Supporting proof should be shorter and more concrete than the headline.",
            "- Use large, bold type for the main claim and simpler supporting type for badges, proof, or CTA labels.",
            "- Decorative or casual type can appear as a supporting accent, not as the only readable layer.",
        ]

    lines += [
        "",
        "## Composition",
        "- Protect one clear text zone rather than placing the main message across busy scene detail.",
        "- In wide formats, prefer a split between message space and product or lifestyle proof.",
        "- Use device frames, posters, signs, placards, or notification cards as optional message containers when they improve clarity.",
        "- Keep the eye path deliberate: primary claim, secondary proof, then action.",
        "",
        "## Components",
    ]
    if component_patterns:
        for item in component_patterns:
            lines.append(f"- {item}")
    else:
        lines += [
            "- **Headline block:** carries the single main promise or problem statement.",
            "- **Proof container:** badge, device screen, signboard, poster, or caption block that makes the benefit concrete.",
            "- **CTA container:** button, badge, or imperative label when the concept needs an explicit action cue.",
            "- **Hero proof:** product, person, scene trigger, or object that visually proves the use case.",
        ]

    lines += [
        "",
        "## Imagery",
        "- Use contextual scenes that clearly explain why the ad exists: purchase moment, use occasion, audience need, location, urgency, event, routine, or another advertiser-specific context repeated in the winning set.",
        "- Keep the foreground proof crisp and the supporting scene simpler or softer so the message remains dominant.",
        "- Use human expression only when it reinforces the promise rather than adding noise.",
        "- Avoid generic lifestyle imagery that does not create a reason to act.",
        "",
        "## Ratio Rules",
    ]
    if ratio_rules:
        for key in ("horizontal", "square", "vertical"):
            value = ratio_rules.get(key)
            if value:
                lines.append(f"- **{key.title()}:** {value}")
    else:
        lines.append("- **Horizontal:** Use a split layout with one clear message zone and one proof zone.")
        lines.append("- **Square:** Reduce the claim count and keep one promise plus one proof element.")
        lines.append("- **Vertical:** Stack the reading path instead of cropping from wide layouts.")

    lines += [
        "",
        "## Content Rules",
    ]
    for item in _generic_design_content_rules():
        lines.append(f"- {item}")

    lines += [
        "",
        "## Theme Grammar",
        "- Convert campaign, ad group, and source-image context into a broad creative theme before writing the prompt.",
        "- Treat close concepts as semantic neighbors rather than exact text matches; for example, coupon, sale, discount, and offer can map to value incentive; trial, sample, demo, and first use can map to first-experience proof.",
        "- Use the theme to choose the problem, benefit, proof cue, and scene role; do not copy a winning creative only because it shares a keyword.",
        "- Keep the advertiser's brand system and product proof consistent while adapting the use case to the LOW source asset.",
        "",
        "## Source Reference Rules",
        "- For LOW replacement variants, inspect the source image before prompt construction and use it as the visual reference.",
        "- Preserve source elements by role unless the user marks them as hard SLA: product or service category, scene context, proof container, offer cue, human or use-case cue, and brand treatment.",
        "- Do not generate extra ratios; create only a same-size replacement for the flagged source asset.",
        "- If the source and design guide conflict, keep user-approved hard SLA constraints first, then source role preservation, then design-guide preferences.",
        "",
        "## Prompt Assembly Contract",
        "- Build future variant prompts from source image, LOW campaign/ad group metadata, native dimensions, theme, user-approved hard SLAs, soft preservation rules, and this design system.",
        "- Ask the user for hard SLA constraints before every regeneration.",
        "- Attach the LOW source image to the generation call whenever the task is a replacement variant.",
        "- State that output is preview-only unless a separate upload or replacement workflow is explicitly approved.",
        "",
        "## Constraint Classes",
        "- **Hard SLA:** user-confirmed requirements that must be preserved or reported as failed.",
        "- **Soft Preserve:** source-image roles to keep similar without exact pixel preservation.",
        "- **Design Guide:** reusable composition, hierarchy, brand, CTA, and readability rules from reviewed winners.",
        "- **Inferred Tokens:** colors, typography, logo treatment, product styling, and component patterns inferred from reviewed creatives rather than approved source-of-truth brand files.",
    ]

    lines += [
        "",
        "## CTA Rules",
    ]
    cta_rules = _strategy_list(strategy, "cta_rules")
    if cta_rules:
        for item in cta_rules:
            lines.append(f"- {item}")
    else:
        lines.append("- Use an explicit CTA only when the concept benefits from a direct action prompt.")
        lines.append("- Keep the CTA secondary to the core benefit.")

    lines += [
        "",
        "## Do's and Don'ts",
    ]
    for item in _strategy_list(strategy, "avoid"):
        lines.append(f"- {item.rstrip('.')}.")
    if not _strategy_list(strategy, "avoid"):
        lines.append("- Don't crop one composition blindly across ratios.")
        lines.append("- Don't let scene detail overpower the message.")
    lines += [
        "- Do keep the composition readable at feed size.",
        "- Do adapt the same visual language across ratios without copying the exact placement of every element.",
        "",
        "## Fidelity Rules",
        "- Start from this design system and the current campaign brief.",
        "- If a required element cannot be faithfully generated, say exactly what is missing instead of guessing.",
        "- Ask only for missing elements tied to fidelity, approval, or exactness.",
        "- Do not assume a fixed upload checklist.",
        "- Use reviewed creative evidence first for brand tokens; merge explicit brand assets or brand docs only when they are available.",
    ]
    for item in _strategy_list(strategy, "future_generation_contract_notes"):
        lines.append(f"- {item}")

    path.write_text("\n".join(lines) + "\n")


def _write_static_banner_overview_markdown(
    path: Path,
    strategy_path: Path,
    design_path: Path,
    unique_count: int,
    diagnostic: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    date_str = today().isoformat()
    lines = [
        "---",
        f"date: {date_str}",
        "intent: static_banner_design",
        "---",
        "",
        "← [Wiki Index](../Index.md)",
        "",
        f"# {'Static Banner Diagnostic' if diagnostic else 'Static Banner Design'}: {date_str}",
        "",
        "## Files",
        f"- [Strategy]({strategy_path.name}) — evidence, repeated-placement context, and per-creative observations for {unique_count} unique visual families.",
        f"- [DESIGN.md]({design_path.name}) — advertiser-specific thematic design-system spec for future source-guided generation.",
        "",
        "## How To Use",
        "- Read the strategy file when you need to understand what won and where it repeated.",
        "- Use `DESIGN.md` as the primary generation spec: theme grammar, source-reference rules, prompt assembly, constraint classes, and visual design rules.",
        "- For LOW static variants, start from the flagged source image and campaign/ad group metadata; do not generate from `DESIGN.md` alone.",
        "- Before each regeneration, ask the user for hard SLA constraints, then preserve source elements by role unless marked hard SLA.",
        "- If the strategist has not visually reviewed images yet, treat both files as incomplete.",
        "",
        "## Variant Generation Contract",
        "- Map metadata and source context into broad themes instead of exact keyword matches.",
        "- Generate only same-size replacement previews for flagged LOW static image assets.",
        "- Run spec-only QA on preview outputs; apply to Google Ads only through the separate approval-gated apply flow.",
    ]
    path.write_text("\n".join(lines) + "\n")


def suggest_static_banners(args: argparse.Namespace) -> None:
    """Prepare static banner image evidence or finalize the visual design guide."""
    explicit_customer = getattr(args, "customer", None)
    profile = load_profile(required=not bool(explicit_customer))
    if explicit_customer:
        customer_key = str(explicit_customer).replace("-", "")
        account_profile = ACCOUNTS_DIR / customer_key / "profile.json"
        if account_profile.exists():
            profile = json.loads(account_profile.read_text())
        else:
            profile = dict(profile)
            profile["google_ads_customer_id"] = explicit_customer
    customer_id = profile.get("google_ads_customer_id") or "unknown"
    currency = _currency_symbol(profile.get("currency", ""))
    wiki_base = account_wiki_dir(customer_id) if customer_id != "unknown" else STATE_ROOT / "wiki"
    design_dir = wiki_base / "design"
    strategy_guide_path = design_dir / "banner-design-strategy.md"
    design_md_path = design_dir / "DESIGN.md"
    guide_path = design_dir / "banner-design.md"
    strategy_input_path = design_dir / "banner-design-strategist-input.json"
    strategy_output_path = design_dir / "banner-design-strategy.json"
    strategy_json = getattr(args, "strategy_json", None)
    data_only_diagnostic = bool(getattr(args, "data_only_diagnostic", False))

    if not getattr(args, "force", False) and not strategy_json and not data_only_diagnostic:
        fresh_date = _fresh_static_banner_guide_date(strategy_guide_path if strategy_guide_path.exists() else guide_path, STATIC_BANNER_REFRESH_DAYS)
        if fresh_date:
            print(f"banner design guide is fresh from {fresh_date}: {strategy_guide_path if strategy_guide_path.exists() else guide_path}")
            print("use --force to regenerate before the 90-day refresh window")
            return

    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    creative_path = Path(args.input).expanduser() if getattr(args, "input", None) else newest_processed("creative", customer_id)
    rows = read_csv(creative_path)
    period_start, period_end = _creative_file_period(creative_path)
    eligible = [
        r for r in rows
        if _is_static_image_asset(r) and number(r.get("impressions")) >= min_imp
    ]
    best_assets_raw = [
        _static_banner_asset(r, _static_banner_ratio_bucket(r), "primary")
        for r in eligible
        if str(r.get("performance_label", "")).upper() == "BEST"
    ]
    good_assets_raw = [
        _static_banner_asset(r, _static_banner_ratio_bucket(r), "secondary")
        for r in eligible
        if str(r.get("performance_label", "")).upper() == "GOOD"
    ]
    if not best_assets_raw and not good_assets_raw:
        die(f"no BEST or GOOD static image assets found above {min_imp:.0f} impressions in {creative_path}")

    best_assets, best_duplicate_groups = _dedupe_static_banner_assets(best_assets_raw)
    good_assets, good_duplicate_groups = _dedupe_static_banner_assets(good_assets_raw)
    primary_assets = best_assets or good_assets
    secondary_assets = [] if best_assets else good_assets
    duplicate_groups = best_duplicate_groups if best_assets else good_duplicate_groups
    grouped = _group_static_banner_assets(primary_assets)
    design_dir.mkdir(parents=True, exist_ok=True)

    run_dir = design_dir / "static-banner-assets" / today().isoformat()
    grouped_with_downloads, manifest_assets = _download_static_banner_assets(grouped, run_dir)
    manifest_payload = {
        "customer_id": customer_id,
        "source_file": str(creative_path),
        "period": {"start": period_start, "end": period_end},
        "min_impressions": min_imp,
        "raw_asset_count": len(best_assets_raw) if best_assets_raw else len(good_assets_raw),
        "unique_image_count": len(primary_assets),
        "image_specs": STATIC_BANNER_SPECS,
        "assets": manifest_assets,
        "duplicate_groups": duplicate_groups,
    }
    manifest_path = _write_static_banner_manifest(run_dir, manifest_payload)

    strategy_payload = {
        "customer_id": customer_id,
        "source_file": str(creative_path),
        "period": {"start": period_start, "end": period_end},
        "min_impressions": min_imp,
        "raw_asset_count": len(best_assets_raw) if best_assets_raw else len(good_assets_raw),
        "unique_image_count": len(primary_assets),
        "image_specs": STATIC_BANNER_SPECS,
        "asset_manifest": str(manifest_path),
        "assets_by_ratio": grouped_with_downloads,
        "duplicate_groups": duplicate_groups,
        "secondary_good_assets": secondary_assets,
        "required_output_schema": {
            "status": "str",
            "image_inspected_count": "int",
            "raw_asset_count": "int",
            "unique_image_count": "int",
            "creative_observations": "list[dict]",
            "duplicate_groups": "list[dict]",
            "winning_patterns": "list[str]",
            "visual_language": "list[str]",
            "brand_colors": "dict[str, dict | str]",
            "typography_signals": "dict[str, dict | str]",
            "component_patterns": "list[str]",
            "brand_signals": "list[str]",
            "token_confidence_notes": "list[str]",
            "ratio_rules": "dict[str, str]",
            "message_hierarchy": "list[str]",
            "cta_rules": "list[str]",
            "brand_and_product_rules": "list[str]",
            "visual_style": "list[str]",
            "avoid": "list[str]",
            "future_generation_contract_notes": "list[str]",
        },
    }
    strategy_input_path.write_text(json.dumps(strategy_payload, indent=2, ensure_ascii=False) + "\n")

    strategy: dict[str, Any]
    if strategy_json:
        strategy_path = Path(strategy_json).expanduser()
        strategy = json.loads(strategy_path.read_text())
        if strategy_path != strategy_output_path:
            strategy_output_path.write_text(json.dumps(strategy, indent=2, ensure_ascii=False) + "\n")
        if not _strategy_has_visual_evidence(strategy):
            die(
                f"strategy JSON has no visual evidence: {strategy_path}. "
                "Expected image_inspected_count > 0 or creative_observations."
            )
    elif data_only_diagnostic:
        strategy = _build_default_static_banner_strategy(grouped_with_downloads)
    else:
        downloaded = sum(1 for asset in manifest_assets if asset.get("download_status") == "downloaded")
        with_url = sum(1 for asset in manifest_assets if asset.get("source_url"))
        print(f"static banner strategist packet written: {strategy_input_path}")
        print(f"asset manifest written:                  {manifest_path}")
        print(f"unique images downloaded: {downloaded}/{len(manifest_assets)}")
        print(f"unique visuals: {len(primary_assets)} | raw placements: {len(best_assets_raw) if best_assets_raw else len(good_assets_raw)}")
        if with_url == 0:
            print(
                "\nNo image URLs are present in the selected creative data, so I did not write the final strategy or design docs. "
                "Refetch creative_period with the updated query, aggregate it, "
                "then rerun this command."
            )
        else:
            print(
                "\nRun the bob-static-banners skill with the strategist packet, save its JSON as "
                f"{design_dir / 'banner-design-strategy.json'}, then finalize with:\n"
                f"  ./bob suggest-static-banners --customer {customer_id} --force "
                f"--strategy-json {design_dir / 'banner-design-strategy.json'}"
            )
        return

    _write_static_banner_strategy_markdown(
        strategy_guide_path,
        customer_id,
        period_start,
        period_end,
        grouped_with_downloads,
        secondary_assets,
        strategy,
        strategy_input_path,
        design_md_path,
        currency,
        diagnostic=data_only_diagnostic,
    )
    _write_static_banner_design_md(
        design_md_path,
        strategy,
        strategy_guide_path,
        customer_id,
    )
    _write_static_banner_overview_markdown(
        guide_path,
        strategy_guide_path,
        design_md_path,
        len(primary_assets),
        diagnostic=data_only_diagnostic,
    )
    entry = (
        f"- [{'Static Banner Diagnostic' if data_only_diagnostic else 'Static Banner Design'} — {today().isoformat()}](design/banner-design.md) — "
        f"strategy + DESIGN.md from {len(primary_assets)} unique {'BEST' if best_assets else 'GOOD'} visual families"
        + ("; GOOD fallback used" if not best_assets else "")
    )
    _write_static_banner_index_entry(wiki_base / "Index.md", entry, section="Design")

    print(f"{'banner diagnostic overview' if data_only_diagnostic else 'banner design overview'} written: {guide_path}")
    print(f"banner strategy written:     {strategy_guide_path}")
    print(f"design spec written:         {design_md_path}")
    print(f"strategist input written:    {strategy_input_path}")

__all__ = [name for name in globals() if not name.startswith("__")]
