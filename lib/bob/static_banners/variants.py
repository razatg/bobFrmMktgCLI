"""Static-banner replacement preparation and application."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
from lib.bob.platform.data import *
from lib.bob.platform.google_ads import *
from lib.bob.platform.presentation import *
from .analyze import *
def suggest_static_variants(args: argparse.Namespace) -> None:
    """Prepare LOW static image candidates for source-guided same-size variants."""
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

    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    creative_path = Path(args.input).expanduser() if getattr(args, "input", None) else newest_processed("creative", customer_id)
    rows = read_csv(creative_path)
    period_start, period_end = _creative_file_period(creative_path)

    low_static_assets_raw = [
        _static_banner_asset(r, _static_banner_ratio_bucket(r), "low_static_variant_candidate")
        for r in rows
        if _is_static_image_asset(r)
        and str(r.get("performance_label", "")).upper() == "LOW"
        and number(r.get("impressions")) >= min_imp
    ]
    if not low_static_assets_raw:
        print(f"no LOW static image assets found above {min_imp:.0f} impressions in {creative_path}")
        return

    low_static_assets = sorted(
        low_static_assets_raw,
        key=lambda asset: (
            number(asset.get("impressions")),
            number(asset.get("clicks")),
            str(asset.get("asset_id", "")),
        ),
        reverse=True,
    )
    grouped = _group_static_banner_assets(low_static_assets)
    run_dir = design_dir / "low-static-variants" / today().isoformat()
    grouped_with_downloads, manifest_assets = _download_static_banner_assets(grouped, run_dir)

    manifest_payload = {
        "customer_id": customer_id,
        "source_file": str(creative_path),
        "period": {"start": period_start, "end": period_end},
        "min_impressions": min_imp,
        "workflow": "low_static_variant_preview",
        "status": "prepared_candidates_only",
        "candidate_count": len(manifest_assets),
        "image_specs": STATIC_BANNER_SPECS,
        "design_references": {
            "landing": str(design_dir / "banner-design.md"),
            "design": str(design_dir / "DESIGN.md"),
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
    print(f"LOW static variant candidates written: {manifest_path}")
    print(f"candidate images downloaded: {downloaded}/{len(manifest_assets)}")
    print(f"source URLs present: {with_url}/{len(manifest_assets)}")
    print("next: use the bob-static-banners LOW Static Variant Workflow with this manifest; ask for hard SLA constraints before each generation")


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
        return plan, changes, plan_path

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


def _static_variant_manifest_assets(manifest_path: Path) -> dict[str, dict[str, Any]]:
    if not manifest_path.exists():
        die(f"manifest file not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    assets = manifest.get("assets") or []
    if not isinstance(assets, list):
        die(f"manifest has no assets list: {manifest_path}")
    return {str(asset.get("asset_id", "")): asset for asset in assets if asset.get("asset_id")}


def static_variants_apply(args: argparse.Namespace) -> None:
    _require_write_permission()
    """Upload generated static variant images and swap them into matching app ads."""
    plan, changes, plan_path = _load_static_variant_apply_changes(args)
    if not changes:
        print("no static image replacements in plan — nothing to apply")
        return

    manifest_text = str(getattr(args, "manifest", None) or plan.get("manifest") or "")
    if not manifest_text:
        die("static variant apply requires a manifest path")
    manifest_path = Path(manifest_text).expanduser()
    if not manifest_path.is_absolute() and plan_path:
        manifest_path = (plan_path.parent / manifest_path).resolve()
    manifest_base = manifest_path.parent
    manifest_assets = _static_variant_manifest_assets(manifest_path)

    profile = load_profile(required=False)
    customer_id = str(plan.get("customer_id") or profile.get("google_ads_customer_id", "")).replace("-", "")
    if not customer_id:
        die("customer_id missing from plan and profile")

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
        prepared.append({
            "asset_id": asset_id,
            "old_asset_resource": f"customers/{customer_id}/assets/{asset_id}",
            "replacement_path": str(replacement_path),
            "image_info": info,
            "campaign_name": source.get("campaign_name", ""),
            "ad_group_id": str(source.get("ad_group_id", "")),
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

    for item in prepared:
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
        except Exception as exc:
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": f"fetch app ad: {exc}"})
            print(f"  ✗ {item['asset_id']} — could not fetch app ad: {exc}")
            continue

        matched_ad = None
        matched_images: list[str] = []
        for row in rows:
            image_assets = [img.asset for img in row.ad_group_ad.ad.app_ad.images]
            if item["old_asset_resource"] in image_assets:
                matched_ad = row.ad_group_ad
                matched_images = image_assets
                break
        if not matched_ad:
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": "source image asset not found in app ad"})
            print(f"  ✗ {item['asset_id']} — source image asset not found in app ad")
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
    plan["apply_results"] = [
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
