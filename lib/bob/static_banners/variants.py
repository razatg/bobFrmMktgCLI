"""Static-banner replacement preparation and application."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
from lib.bob.platform.data import *
from lib.bob.platform.google_ads import *
from lib.bob.platform.presentation import *
from .analyze import *

def _select_static_rows(rows: list[dict[str, Any]], args: argparse.Namespace, min_imp: float) -> list[dict[str, Any]]:
    selection = getattr(args, "selection", "low") or "low"
    if selection not in {"low", "campaign", "assets"}:
        die("static image selection must be low, campaign, or assets")
    campaign_id = str(getattr(args, "campaign_id", "") or "").strip()
    asset_ids = {value.strip() for value in str(getattr(args, "asset_ids", "") or "").split(",") if value.strip()}
    if selection == "campaign" and (not campaign_id or asset_ids):
        die("campaign selection requires --campaign-id and no --asset-ids")
    if selection == "assets" and (not asset_ids or campaign_id):
        die("assets selection requires --asset-ids and no --campaign-id")
    if selection == "low" and (campaign_id or asset_ids):
        die("use --selection campaign or assets with explicit selectors")

    static_rows = [row for row in rows if _is_static_image_asset(row)]
    if selection == "low":
        return [row for row in static_rows if str(row.get("performance_label", "")).upper() == "LOW"
                and number(row.get("impressions")) >= min_imp]
    if selection == "campaign":
        return [row for row in static_rows if str(row.get("campaign_id", "")).strip() == campaign_id]
    found = {str(row.get("asset_id", "")).strip() for row in static_rows if str(row.get("asset_id", "")).strip() in asset_ids}
    if found != asset_ids:
        die("static image asset IDs not found in the selected inventory: " + ", ".join(sorted(asset_ids - found)))
    return [row for row in static_rows if str(row.get("asset_id", "")).strip() in asset_ids]

def suggest_static_variants(args: argparse.Namespace) -> None:
    """Prepare selected static images for source-guided review-only variants."""
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
    wiki_base = account_wiki_dir(customer_id) if customer_id != "unknown" else STATE_ROOT / "wiki"
    design_dir = wiki_base / "design"

    selection = getattr(args, "selection", "low") or "low"
    min_imp = float(getattr(args, "min_impressions", None) if getattr(args, "min_impressions", None) is not None
                    else profile.get("creative_min_impressions", DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    subdir = "creative" if selection == "low" else "creative-inventory"
    creative_path = Path(args.input).expanduser() if getattr(args, "input", None) else newest_processed(subdir, customer_id)
    if selection != "low" and creative_path.parent.name != "creative-inventory":
        die("campaign and named-asset selection require a processed creative image inventory")
    rows = read_csv(creative_path)
    period_start, period_end = _creative_file_period(creative_path)
    foreign = {str(row.get("customer_id", "")).replace("-", "") for row in rows
               if str(row.get("customer_id", "")).replace("-", "") != str(customer_id).replace("-", "")}
    if foreign:
        die("creative source contains rows outside the selected account")
    selected_rows = _select_static_rows(rows, args, min_imp)
    if not selected_rows:
        print(f"no {selection} static image assets found in {creative_path}")
        return
    source_label = "low_static_variant_candidate" if selection == "low" else "requested_static_refresh"
    selected_assets, _duplicates = _dedupe_static_banner_assets([
        _static_banner_asset(row, _static_banner_ratio_bucket(row), source_label) for row in selected_rows
    ])
    selected_assets = sorted(
        selected_assets,
        key=lambda asset: (
            number(asset.get("impressions")),
            number(asset.get("clicks")),
            str(asset.get("asset_id", "")),
        ),
        reverse=True,
    )
    grouped = _group_static_banner_assets(selected_assets)
    run_dir = (design_dir / "low-static-variants" / today().isoformat() if selection == "low"
               else design_dir / "creative-sources" / uuid.uuid4().hex[:12])
    grouped_with_downloads, manifest_assets = _download_static_banner_assets(grouped, run_dir)

    manifest_payload = {
        "customer_id": customer_id,
        "source_file": str(creative_path),
        "period": {"start": period_start, "end": period_end},
        "min_impressions": min_imp if selection == "low" else None,
        "selection": selection,
        "selector": ({"campaign_id": str(args.campaign_id).strip()} if selection == "campaign" else
                     {"asset_ids": sorted(value.strip() for value in str(args.asset_ids).split(",") if value.strip())}
                     if selection == "assets" else {}),
        "workflow": "low_static_variant_preview" if selection == "low" else "static_creative_refresh",
        "status": "prepared_candidates_only",
        "candidate_count": len(manifest_assets),
        "image_specs": STATIC_BANNER_SPECS,
        "design_references": {
            "design": str(design_dir / "DESIGN.md"),
            "strategy": str(design_dir / "DESIGN_STRATEGY.md"),
        },
        "generation_contract": {
            "source_visual_step": "inspect each local_path with the runtime's visual-input capability before prompt construction",
            "hard_sla_step": "ask the user for hard SLA constraints before every regeneration",
            "output_size_rule": "generate exactly one replacement variant at the source asset native dimensions",
            "qa_scope": "spec-only: readable output, width match, height match, output path recorded, no Google Ads mutation",
            "upload_scope": "preview only; do not upload or replace Google Ads assets",
        },
        "assets_by_ratio": grouped_with_downloads,
        "assets": manifest_assets,
    }
    manifest_path = _write_static_banner_manifest(run_dir, manifest_payload)

    downloaded = sum(1 for asset in manifest_assets if asset.get("download_status") == "downloaded")
    with_url = sum(1 for asset in manifest_assets if asset.get("source_url"))
    print(f"{selection} static image sources written: {manifest_path}")
    print(f"candidate images downloaded: {downloaded}/{len(manifest_assets)}")
    print(f"source URLs present: {with_url}/{len(manifest_assets)}")
    print("next: use the bob-creates-it static replacement workflow with this manifest")


def _image_file_info(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24:
            die(f"invalid PNG image: {path}")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return {"data": data, "width": width, "height": height, "mime": "IMAGE_PNG", "bytes": len(data)}
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            i += 2
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if i + 2 > len(data):
                break
            segment_len = int.from_bytes(data[i:i + 2], "big")
            if segment_len < 2 or i + segment_len > len(data):
                break
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                height = int.from_bytes(data[i + 3:i + 5], "big")
                width = int.from_bytes(data[i + 5:i + 7], "big")
                return {"data": data, "width": width, "height": height, "mime": "IMAGE_JPEG", "bytes": len(data)}
            i += segment_len
        die(f"could not read JPEG dimensions: {path}")
    die(f"unsupported image format for Google Ads upload: {path} (use PNG or JPEG)")


def _apply_change_key(change: dict[str, Any]) -> str:
    return json.dumps({
        "asset_id": str(change.get("asset_id", "")),
        "ad_group_id": str(change.get("ad_group_id", "")),
        "ad_id": str(change.get("ad_id", "")),
        "replacement_image": str(change.get("replacement_image") or change.get("replacement_path") or change.get("image") or ""),
    }, sort_keys=True)


def _resolve_relative_path(path_text: str, base_dir: Path) -> Path:
    path = Path(str(path_text)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _load_static_variant_apply_changes(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], Path | None]:
    plan_path: Path | None = Path(args.plan).expanduser() if getattr(args, "plan", None) else None
    if plan_path:
        if not plan_path.exists():
            die(f"plan file not found: {plan_path}")
        try:
            import yaml as _yaml
        except ImportError:
            die("pyyaml is required for --plan. Install: pip install pyyaml")
        plan = _yaml.safe_load(plan_path.read_text()) or {}
        if plan.get("applied"):
            die(f"plan already applied on {plan.get('applied_at')}")
        changes = plan.get("changes") or plan.get("replacements") or []
        if not isinstance(changes, list):
            die("static variant apply plan must contain changes: [...]")
        previous = plan.get("apply_results") or []
        if any(item.get("status") == "replaced" and not item.get("plan_key") for item in previous):
            die("this partially applied plan predates safe retry tracking; review it before another apply")
        applied_keys = {str(item["plan_key"]) for item in previous if item.get("status") == "replaced"}
        return plan, [change for change in changes if _apply_change_key(change) not in applied_keys], plan_path

    manifest_arg = getattr(args, "manifest", None)
    asset_id_arg = getattr(args, "asset_id", None)
    replacement_arg = getattr(args, "replacement", None)
    if not manifest_arg or not asset_id_arg or not replacement_arg:
        die("provide either --plan or all of --manifest, --asset-id, and --replacement")
    plan = {
        "customer_id": "",
        "manifest": manifest_arg,
        "changes": [
            {
                "asset_id": str(asset_id_arg),
                "replacement_image": replacement_arg,
                "action": "replace",
            }
        ],
        "applied": False,
    }
    return plan, plan["changes"], None


def _static_variant_manifest_assets(manifest_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not manifest_path.exists():
        die(f"manifest file not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    assets = manifest.get("assets") or []
    if not isinstance(assets, list):
        die(f"manifest has no assets list: {manifest_path}")
    return manifest, {str(asset.get("asset_id", "")): asset for asset in assets if asset.get("asset_id")}


def _matching_app_ad(rows: list[Any], old_asset: str, requested_ad_id: str) -> tuple[Any, list[str]]:
    matches = []
    for row in rows:
        ad = row.ad_group_ad
        if requested_ad_id and str(ad.ad.id) != requested_ad_id:
            continue
        images = [image.asset for image in ad.ad.app_ad.images]
        if old_asset in images:
            matches.append((ad, images))
    if len(matches) != 1:
        raise ValueError("source image is missing from the requested ad" if not matches
                         else "source image matches several ads; name an exact ad ID")
    return matches[0]


def static_variants_apply(args: argparse.Namespace) -> None:
    _require_write_permission()
    """Upload generated static variant images and swap them into matching app ads."""
    plan, changes, plan_path = _load_static_variant_apply_changes(args)
    blocked = plan.get("blocked_candidates") or []
    if blocked:
        print("cannot publish all requested candidates until their Google Ads placements are resolved:")
        for item in blocked:
            print(f"  - asset {item.get('asset_id', 'unknown')}: {item.get('reason', 'placement details missing')}")
        return
    if not changes:
        if plan_path and not plan.get("applied") and plan.get("changes"):
            plan["applied"] = True
            plan["applied_at"] = datetime.now().isoformat(timespec="seconds")
            plan_path.write_text(json.dumps(plan, indent=2) + "\n")
        print("no static image replacements in plan — nothing to apply")
        return

    manifest_text = str(getattr(args, "manifest", None) or plan.get("manifest") or "")
    if not manifest_text:
        die("static variant apply requires a manifest path")
    manifest_path = Path(manifest_text).expanduser()
    if not manifest_path.is_absolute() and plan_path:
        manifest_path = (plan_path.parent / manifest_path).resolve()
    manifest_base = manifest_path.parent
    source_manifest, manifest_assets = _static_variant_manifest_assets(manifest_path)

    profile = load_profile(required=False)
    customer_id = str(plan.get("customer_id") or profile.get("google_ads_customer_id", "")).replace("-", "")
    if not customer_id:
        die("customer_id missing from plan and profile")
    if str(source_manifest.get("customer_id", "")).replace("-", "") != customer_id:
        die("static source manifest belongs to a different account")

    prepared: list[dict[str, Any]] = []
    for idx, change in enumerate(changes, 1):
        if str(change.get("action", "replace")) != "replace":
            continue
        asset_id = str(change.get("asset_id", "")).strip()
        replacement_text = change.get("replacement_image") or change.get("replacement_path") or change.get("image")
        if not asset_id or not replacement_text:
            die(f"change #{idx} must include asset_id and replacement_image")
        source = manifest_assets.get(asset_id)
        if not source:
            die(f"asset_id {asset_id} not found in manifest {manifest_path}")
        placements = source.get("duplicate_placements") or [source]
        requested_group = str(change.get("ad_group_id", "") or "")
        requested_ad = str(change.get("ad_id", "") or "")
        if requested_group or requested_ad:
            if not any(
                str(placement.get("ad_group_id", "")) == requested_group
                and (not requested_ad or str(placement.get("ad_id", "")) == requested_ad)
                for placement in placements if isinstance(placement, dict)
            ):
                die(f"asset {asset_id} is not linked to the requested ad placement")
        elif len(placements) > 1:
            die(f"asset {asset_id} has several placements; apply plan must name the ad group and ad")
        replacement_path = _resolve_relative_path(str(replacement_text), manifest_base)
        if not replacement_path.exists():
            die(f"replacement image not found for asset {asset_id}: {replacement_path}")
        info = _image_file_info(replacement_path)
        source_width = int(number(source.get("width")) or 0)
        source_height = int(number(source.get("height")) or 0)
        if source_width and info["width"] != source_width:
            die(f"width mismatch for asset {asset_id}: source {source_width}, replacement {info['width']}")
        if source_height and info["height"] != source_height:
            die(f"height mismatch for asset {asset_id}: source {source_height}, replacement {info['height']}")
        if info["bytes"] > 5_000_000:
            die(f"replacement image exceeds 5MB Google image asset limit: {replacement_path}")
        resolved_group = requested_group or str(source.get("ad_group_id", ""))
        resolved_ad = requested_ad or str(source.get("ad_id", ""))
        if not resolved_group.isdigit() or (resolved_ad and not resolved_ad.isdigit()):
            die(f"asset {asset_id} needs numeric ad group and ad IDs for Google Ads apply")
        prepared.append({
            "plan_key": _apply_change_key(change),
            "asset_id": asset_id,
            "old_asset_resource": f"customers/{customer_id}/assets/{asset_id}",
            "replacement_path": str(replacement_path),
            "image_info": info,
            "campaign_name": source.get("campaign_name", ""),
            "ad_group_id": resolved_group,
            "ad_id": resolved_ad,
            "ad_group_name": source.get("ad_group_name", ""),
            "field_type": source.get("field_type", ""),
            "source_width": source_width,
            "source_height": source_height,
            "asset_name": source.get("asset_name", ""),
        })

    if not prepared:
        print("no replace actions in plan — nothing to apply")
        return

    print(f"\n{'#':<3}  {'Campaign':<28}  {'Ad group':<28}  {'Asset':<16}  {'Size':>11}  Replacement")
    print("─" * 120)
    for idx, item in enumerate(prepared, 1):
        size = f"{item['image_info']['width']}x{item['image_info']['height']}"
        print(
            f"{idx:<3}  {item['campaign_name'][:28]:<28}  {item['ad_group_name'][:28]:<28}  "
            f"{item['asset_id']:<16}  {size:>11}  {item['replacement_path']}"
        )

    if getattr(args, "dry_run", False):
        print("\n[dry-run] no Google Ads changes applied")
        return

    print("\nApprove upload + app-ad image replacement? [y/n]: ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return
    if answer != "y":
        print("Aborted — no changes applied.")
        return

    try:
        import yaml as _yaml
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        from google.protobuf.field_mask_pb2 import FieldMask  # type: ignore
    except ImportError:
        die("google-ads and pyyaml are required for static-variants-apply")

    config_path = str(_runtime_write_config_path())
    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as exc:
        die(f"failed to load Google Ads client: {exc}")

    ga_svc = client.get_service("GoogleAdsService")
    ad_svc = client.get_service("AdService")
    asset_svc = client.get_service("AssetService")
    results: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    for item in prepared:
        gaql = (
            "SELECT ad_group_ad.resource_name,"
            " ad_group_ad.ad.id,"
            " ad_group_ad.ad.app_ad.images"
            " FROM ad_group_ad"
            f" WHERE ad_group.id = {item['ad_group_id']}"
            " AND ad_group_ad.status != 'REMOVED'"
        )
        try:
            rows = list(ga_svc.search(customer_id=customer_id, query=gaql))
            _matching_app_ad(rows, item["old_asset_resource"], item["ad_id"])
        except Exception as exc:
            results.append({**item, "status": "error", "error": f"verify current app ad: {exc}"})
            print(f"  ✗ {item['asset_id']} — could not verify current app ad: {exc}")
            continue
        verified.append(item)

    if results:
        raise SystemExit(2)

    for item in verified:
        asset_op = client.get_type("AssetOperation")
        created_asset = asset_op.create
        source_name = item.get("asset_name") or item["asset_id"]
        created_asset.name = f"Bob static variant {source_name} {today().isoformat()}"
        created_asset.image_asset.data = item["image_info"]["data"]
        created_asset.image_asset.mime_type = getattr(client.enums.MimeTypeEnum, item["image_info"]["mime"])
        try:
            asset_response = asset_svc.mutate_assets(customer_id=customer_id, operations=[asset_op])
            new_asset_resource = asset_response.results[0].resource_name
        except GoogleAdsException as exc:
            err_msg = "; ".join(e.message for e in exc.failure.errors)
            results.append({**item, "status": "error", "error": f"upload image asset: {err_msg}"})
            print(f"  ✗ {item['asset_id']} — image upload failed: {err_msg}")
            continue
        except Exception as exc:
            results.append({**item, "status": "error", "error": f"upload image asset: {exc}"})
            print(f"  ✗ {item['asset_id']} — image upload failed: {exc}")
            continue

        # Read the current ad again: an earlier change in this plan may already
        # have replaced another image in the same ad.
        gaql = (
            "SELECT ad_group_ad.resource_name, ad_group_ad.ad.id, ad_group_ad.ad.app_ad.images"
            " FROM ad_group_ad"
            f" WHERE ad_group.id = {item['ad_group_id']}"
            " AND ad_group_ad.status != 'REMOVED'"
        )
        try:
            matched_ad, matched_images = _matching_app_ad(
                list(ga_svc.search(customer_id=customer_id, query=gaql)),
                item["old_asset_resource"], item["ad_id"],
            )
        except Exception as exc:
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource,
                            "error": f"verify current app ad after upload: {exc}"})
            print(f"  ✗ {item['asset_id']} — current ad changed: {exc}")
            continue
        replaced_images = [
            new_asset_resource if asset == item["old_asset_resource"] else asset
            for asset in matched_images
        ]
        ad_id = matched_ad.ad.id
        ad_rn = ad_svc.ad_path(customer_id, str(ad_id))
        ad_op = client.get_type("AdOperation")
        ad_update = ad_op.update
        ad_update.resource_name = ad_rn
        for asset_resource in replaced_images:
            image_asset = client.get_type("AdImageAsset")
            image_asset.asset = asset_resource
            ad_update.app_ad.images.append(image_asset)
        mask = FieldMask()
        mask.paths.append("app_ad.images")
        ad_op.update_mask.CopyFrom(mask)

        try:
            ad_svc.mutate_ads(customer_id=customer_id, operations=[ad_op])
            results.append({
                **item,
                "status": "replaced",
                "ad_id": ad_id,
                "ad_resource": ad_rn,
                "new_asset_resource": new_asset_resource,
            })
            print(f"  ✓ {item['asset_id']} — uploaded {new_asset_resource} and replaced in ad {ad_id}")
        except GoogleAdsException as exc:
            err_msg = "; ".join(e.message for e in exc.failure.errors)
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": f"update app ad: {err_msg}"})
            print(f"  ✗ {item['asset_id']} — app ad update failed: {err_msg}")
        except Exception as exc:
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": f"update app ad: {exc}"})
            print(f"  ✗ {item['asset_id']} — app ad update failed: {exc}")

    errors = [r for r in results if r.get("status") == "error"]
    import datetime as _dt
    plan["applied"] = not errors
    plan["applied_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    plan["applied_by"] = "static-variants-apply"
    plan["apply_results"] = (plan.get("apply_results") or []) + [
        {k: v for k, v in r.items() if k != "image_info"}
        for r in results
    ]
    if plan_path:
        plan_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
        print(f"\nplan updated: {plan_path}")

    n_replaced = sum(1 for r in results if r.get("status") == "replaced")
    print(f"\n{n_replaced} static image replacement(s) live, {len(errors)} error(s)")
    if errors:
        raise SystemExit(2)

__all__ = [name for name in globals() if not name.startswith("__")]
