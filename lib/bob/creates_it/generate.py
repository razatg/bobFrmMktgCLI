"""Generate review-only static replacements through a client creative provider."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

from lib.bob.platform.core import STATE_ROOT, account_wiki_dir, die, load_profile

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
MAX_REPLACEMENTS = 20
MAX_SOURCE_BYTES = 10_000_000
MAX_OUTPUT_BYTES = 10_000_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        die(f"could not read {label}: {path}: {exc}")
    if not isinstance(value, dict):
        die(f"{label} must contain a JSON object: {path}")
    return value


def _selected_customer_id() -> str:
    selected = re.sub(r"\D", "", os.getenv("BOB_SELECTED_CUSTOMER_ID", ""))
    profile = load_profile(required=not bool(selected))
    customer_id = selected or re.sub(r"\D", "", str(profile.get("google_ads_customer_id", "")))
    if not customer_id:
        die("create-static-replacements requires a selected account")
    return customer_id


def _provider_config() -> dict[str, str]:
    raw_path = os.getenv("BOB_CREATIVE_PROVIDER_CONFIG", "").strip()
    if not raw_path:
        die("creative generation is not configured for this client; ask an admin to configure Gemini")
    config = _read_json(Path(raw_path), "creative provider configuration")
    provider = str(config.get("provider", "")).strip().lower()
    api_key = str(config.get("api_key", "")).strip()
    if provider != "gemini" or not api_key:
        die("creative provider configuration is incomplete; ask an admin to configure Gemini")
    return {"provider": provider, "api_key": api_key}


def _image_model(brief: dict[str, Any]) -> str:
    try:
        catalog = yaml.safe_load(Path(__file__).with_name("models.yaml").read_text())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        die(f"creative model catalog unavailable: {exc}")
    if not isinstance(catalog, dict) or catalog.get("version") != 1:
        die("unsupported creative model catalog version")
    image = catalog.get("image")
    if not isinstance(image, dict) or not isinstance(image.get("allowed"), list):
        die("creative model catalog has no image allowlist")
    allowed = image["allowed"]
    default = image.get("default")
    if not allowed or default not in allowed or any(not isinstance(value, str) for value in allowed):
        die("creative model catalog has an invalid image default or allowlist")
    model = str(brief.get("model") or default)
    if model not in allowed:
        die(f"image model is not approved in creative model catalog v1: {model}")
    return model


def _safe_state_file(path_text: str, label: str, *, allow_shared: bool = False) -> Path:
    path = Path(path_text).expanduser().resolve()
    allowed_roots = [STATE_ROOT.resolve()]
    shared_root = os.getenv("BOB_SHARED_STATE_ROOT", "").strip()
    if allow_shared and shared_root:
        allowed_roots.append(Path(shared_root).expanduser().resolve())
    if not any(path == root or root in path.parents for root in allowed_roots):
        die(f"{label} must be inside Bob's state root")
    if not path.is_file() or path.is_symlink():
        die(f"{label} not found: {path}")
    return path


def _mime_for(path: Path) -> str:
    header = path.read_bytes()[:16]
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    die(f"unsupported source image: {path}")


def _source_dimensions(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except (ImportError, OSError, ValueError) as exc:
        die(f"could not validate source image {path}: {exc}")


def _aspect_ratio(width: int, height: int) -> str:
    ratio = width / height
    choices = {
        "1:1": 1.0,
        "4:5": 0.8,
        "3:4": 0.75,
        "2:3": 2 / 3,
        "9:16": 9 / 16,
        "16:9": 16 / 9,
        "3:2": 1.5,
        "4:3": 4 / 3,
        "5:4": 1.25,
        "21:9": 21 / 9,
    }
    return min(choices, key=lambda name: abs(choices[name] - ratio))


def _extract_output_image(payload: Any) -> tuple[bytes, str]:
    candidates: list[tuple[str, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            data = value.get("data")
            mime = value.get("mime_type") or value.get("mimeType") or ""
            if isinstance(data, str) and str(mime).startswith("image/"):
                candidates.append((data, str(mime)))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if not candidates:
        die("Gemini returned no image")
    try:
        image = base64.b64decode(candidates[0][0], validate=True)
    except ValueError as exc:
        die(f"Gemini returned invalid image data: {exc}")
    if not image or len(image) > MAX_OUTPUT_BYTES:
        die("Gemini returned an empty or oversized image")
    return image, candidates[0][1]


def _call_gemini(
    api_key: str,
    model: str,
    prompt: str,
    source_path: Path,
    aspect_ratio: str,
    opener: Callable[..., Any] = urlopen,
) -> tuple[bytes, str]:
    source = source_path.read_bytes()
    if len(source) > MAX_SOURCE_BYTES:
        die(f"source image exceeds {MAX_SOURCE_BYTES // 1_000_000} MB: {source_path}")
    body = json.dumps({
        "model": model,
        "input": [
            {"type": "image", "mime_type": _mime_for(source_path), "data": base64.b64encode(source).decode()},
            {"type": "text", "text": prompt},
        ],
        # Let Gemini choose any supported response MIME for this model. The
        # output is decoded and normalized to the artifact format below.
        "response_format": {"type": "image", "aspect_ratio": aspect_ratio},
    }).encode()
    request = Request(
        GEMINI_INTERACTIONS_URL,
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with opener(request, timeout=120) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read(2048).decode(errors="replace")
        die(f"Gemini image generation failed ({exc.code}): {detail}")
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        die(f"Gemini image generation failed: {exc}")
    return _extract_output_image(payload)


def _save_exact_png(image_bytes: bytes, output: Path, width: int, height: int) -> dict[str, Any]:
    try:
        from PIL import Image
        from io import BytesIO
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            source_size = image.size
            converted = image.convert("RGB")
            if converted.size != (width, height):
                converted = converted.resize((width, height), Image.Resampling.LANCZOS)
            converted.save(output, format="PNG", optimize=True)
        with Image.open(output) as checked:
            checked.verify()
        with Image.open(output) as checked:
            final_size = checked.size
    except (ImportError, OSError, ValueError) as exc:
        die(f"generated image failed integrity validation: {exc}")
    data = output.read_bytes()
    if len(data) > 5_000_000:
        die(f"generated image exceeds the 5 MB Google Ads limit: {output.name}")
    return {
        "source_dimensions": list(source_size),
        "final_dimensions": list(final_size),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "PNG",
        "integrity": "passed",
        "dimensions": "passed" if final_size == (width, height) else "failed",
    }


def _asset_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        die("static source manifest has no assets list")
    return {str(asset.get("asset_id", "")): asset for asset in assets if isinstance(asset, dict) and asset.get("asset_id")}


def _next_output_name(outputs: Path, asset_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", asset_id).strip("-") or "asset"
    versions = []
    for path in outputs.glob(f"static-{safe_id}-v*.png"):
        match = re.search(r"-v(\d+)\.png$", path.name)
        if match:
            versions.append(int(match.group(1)))
    return f"static-{safe_id}-v{max(versions, default=0) + 1}.png"


def _write_run_index(path: Path, customer_id: str, candidates: list[dict[str, Any]]) -> None:
    lines = [f"# Static replacements · {customer_id}", "", "Review-only outputs; nothing has been published.", ""]
    for candidate in candidates:
        lines += [f"- [{candidate['name']}](outputs/{candidate['name']})", f"  - Replaces asset `{candidate['asset_id']}`; QA passed."]
    path.write_text("\n".join(lines) + "\n")


def _update_account_index(index_path: Path, run_id: str, candidates: list[dict[str, Any]]) -> None:
    text = index_path.read_text() if index_path.exists() else "# Bob — Wiki Index\n"
    heading = "## Static Replacements"
    if heading not in text:
        text = text.rstrip() + f"\n\n{heading}\n"
    marker = f"<!-- creative-run:{run_id} -->"
    links = " · ".join(f"[{item['name']}](creative-runs/{run_id}/outputs/{item['name']})" for item in candidates)
    row = f"- {run_id}: {links}"
    if marker not in text:
        text = text.rstrip() + f"\n\n{marker}\n{row}\n"
    else:
        text = re.sub(rf"(?m)^- {re.escape(run_id)}:.*$", lambda _match: row, text)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(text)


def _candidate_placements(asset: dict[str, Any]) -> list[dict[str, str]]:
    placements = asset.get("duplicate_placements") or [asset]
    return [
        {
            "campaign_id": str(item.get("campaign_id", "")),
            "ad_group_id": str(item.get("ad_group_id", "")),
            "ad_id": str(item.get("ad_id", "")),
        }
        for item in placements if isinstance(item, dict)
    ]


def _placements_publish_ready(placements: list[dict[str, str]]) -> bool:
    if not placements or any(not placement["ad_group_id"].isdigit() for placement in placements):
        return False
    if len(placements) > 1 and any(not placement["ad_id"].isdigit() for placement in placements):
        return False
    return all(not placement["ad_id"] or placement["ad_id"].isdigit() for placement in placements)


def _apply_changes(candidates: list[dict[str, Any]], outputs: Path) -> list[dict[str, str]]:
    changes = []
    for item in candidates:
        if item.get("review_status") != "pending":
            continue
        placements = item.get("placements", [])
        if not _placements_publish_ready(placements):
            continue
        for placement in placements:
            changes.append({
                "asset_id": item["asset_id"],
                "ad_group_id": placement["ad_group_id"],
                "ad_id": placement["ad_id"],
                "replacement_image": str(outputs / item["name"]),
                "action": "replace",
            })
    return changes


def _generate_one(
    replacement: dict[str, Any],
    asset: dict[str, Any],
    design: str,
    strategy: str,
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
    goal: str,
    model: str,
) -> dict[str, Any]:
    asset_id = str(asset.get("asset_id", ""))
    source = _safe_state_file(
        str(asset.get("local_path", "")),
        f"source image for asset {asset_id}",
        allow_shared=True,
    )
    width, height = _source_dimensions(source)
    reference = references / f"source-{asset_id}{source.suffix.lower()}"
    if not reference.exists():
        shutil.copy2(source, reference)
    prompt = str(replacement.get("prompt", "")).strip()
    if not prompt:
        die(f"replacement brief is missing a prompt for asset {asset_id}")
    full_prompt = (
        "Create one review-only advertising image based on the supplied source. "
        f"Preserve the native {width}x{height} composition and required product/brand meaning. "
        "Do not add unrequested logos, claims, prices, offers, or legal copy.\n\n"
        f"GOAL:\n{goal[:2000]}\n\nREQUEST:\n{prompt[:12000]}\n\nDESIGN SYSTEM:\n{design[:16000]}\n\n"
        f"DESIGN STRATEGY:\n{strategy[:16000]}"
    )
    image_bytes, returned_mime = caller(
        provider["api_key"], model, full_prompt, reference, _aspect_ratio(width, height)
    )
    output_name = _next_output_name(outputs, asset_id)
    output = outputs / output_name
    qa = _save_exact_png(image_bytes, output, width, height)
    return {
        "name": output_name,
        "asset_id": asset_id,
        "source_reference": str(reference.name),
        "output": str(output.relative_to(outputs.parent)),
        "provider_mime": returned_mime,
        "model": model,
        "campaign_name": asset.get("campaign_name", ""),
        "ad_group_name": asset.get("ad_group_name", ""),
        "placements": _candidate_placements(asset),
        "publish_ready": _placements_publish_ready(_candidate_placements(asset)),
        "qa": qa,
        "review_status": "pending",
        "published": False,
    }


def create_static_replacements(args: Any, caller: Callable[..., tuple[bytes, str]] = _call_gemini) -> None:
    """Generate account-scoped, review-only replacements from a confirmed JSON brief."""
    customer_id = _selected_customer_id()
    provider = _provider_config()
    brief_path = _safe_state_file(str(args.brief), "replacement brief")
    source_manifest_path = _safe_state_file(
        str(args.manifest), "static source manifest", allow_shared=True
    )
    brief = _read_json(brief_path, "replacement brief")
    model = _image_model(brief)
    source_manifest = _read_json(source_manifest_path, "static source manifest")
    if brief.get("confirmed") is not True:
        die("replacement brief must contain confirmed: true")
    if re.sub(r"\D", "", str(source_manifest.get("customer_id", ""))) != customer_id:
        die("static source manifest belongs to a different account")
    if brief.get("customer_id") and re.sub(r"\D", "", str(brief["customer_id"])) != customer_id:
        die("creative brief belongs to a different account")
    selection = str(source_manifest.get("selection") or "low")
    if selection not in {"low", "campaign", "assets"}:
        die("unsupported static source selection")
    if brief.get("selection") and brief["selection"] != selection:
        die("creative brief selection does not match the source manifest")
    goal = str(brief.get("goal") or "Improve this static image for the user-requested purpose").strip()
    replacements = brief.get("replacements")
    if not isinstance(replacements, list) or not replacements or len(replacements) > MAX_REPLACEMENTS:
        die(f"replacement brief must contain 1–{MAX_REPLACEMENTS} replacements")
    replacement_ids = [str(item.get("asset_id", "")) for item in replacements if isinstance(item, dict)]
    if len(replacement_ids) != len(replacements) or len(set(replacement_ids)) != len(replacements):
        die("creative brief must name each source asset once")
    assets = _asset_map(source_manifest)
    for asset_id in replacement_ids:
        asset = assets.get(asset_id)
        if not asset:
            die(f"asset {asset_id} is not in the selected static source manifest")
    wiki = account_wiki_dir(customer_id)
    design_path = wiki / "design" / "DESIGN.md"
    strategy_path = wiki / "design" / "DESIGN_STRATEGY.md"
    if not design_path.is_file() or not strategy_path.is_file():
        die("create the selected account's DESIGN.md and DESIGN_STRATEGY.md before generating replacements")
    run_id = str(getattr(args, "run_id", "") or brief.get("run_id") or uuid.uuid4().hex[:12])
    if not re.fullmatch(r"[a-zA-Z0-9_-]{6,64}", run_id):
        die("run ID must contain only letters, numbers, underscores, or hyphens")
    run_dir = wiki / "creative-runs" / run_id
    references = run_dir / "references"
    outputs = run_dir / "outputs"
    references.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    run_manifest = _read_json(manifest_path, "creative run manifest") if manifest_path.exists() else {
        "run_id": run_id,
        "customer_id": customer_id,
        "status": "generating",
        "created_at": _now(),
        "source_manifest": str(source_manifest_path),
        "selection": selection,
        "goal": goal,
        "provider": provider["provider"],
        "model": model,
        "models_used": [model],
        "candidates": [],
    }
    if run_manifest.get("customer_id") != customer_id or run_manifest.get("source_manifest") != str(source_manifest_path):
        die("existing creative run belongs to a different account or source selection")
    stored_brief = run_dir / "brief.json"
    if not stored_brief.exists():
        shutil.copy2(brief_path, stored_brief)
    briefs_dir = run_dir / "briefs"
    briefs_dir.mkdir(exist_ok=True)
    shutil.copy2(brief_path, briefs_dir / f"{uuid.uuid4().hex}.json")
    manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
    generated: list[dict[str, Any]] = []
    try:
        for replacement in replacements:
            if not isinstance(replacement, dict):
                die("each replacement must be a JSON object")
            asset_id = str(replacement.get("asset_id", ""))
            if asset_id not in assets:
                die(f"asset {asset_id} is not in the selected static source manifest")
            generated.append(_generate_one(
                replacement, assets[asset_id], design_path.read_text(), strategy_path.read_text(),
                provider, references, outputs, caller, goal, model,
            ))
    except BaseException:
        for item in generated:
            (outputs / item["name"]).unlink(missing_ok=True)
        run_manifest["status"] = "failed"
        run_manifest["updated_at"] = _now()
        manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
        raise
    hashes = [item["qa"]["sha256"] for item in generated]
    previous_hashes = {
        str(item.get("qa", {}).get("sha256", ""))
        for item in run_manifest["candidates"]
        if isinstance(item, dict)
    }
    if len(hashes) != len(set(hashes)) or any(value in previous_hashes for value in hashes):
        for item in generated:
            (outputs / item["name"]).unlink(missing_ok=True)
        run_manifest["status"] = "failed"
        run_manifest["updated_at"] = _now()
        manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
        die("duplicate generated outputs detected; the run was not presented")
    regenerated_ids = {item["asset_id"] for item in generated}
    for existing in run_manifest["candidates"]:
        if existing.get("asset_id") in regenerated_ids and existing.get("review_status") == "pending":
            existing["review_status"] = "superseded"
    run_manifest["candidates"].extend(generated)
    run_manifest["models_used"] = list(dict.fromkeys([*run_manifest.get("models_used", []), model]))
    run_manifest["status"] = "ready_for_review"
    run_manifest["updated_at"] = _now()
    manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
    _write_run_index(run_dir / "index.md", customer_id, run_manifest["candidates"])
    apply_plan = {
        "customer_id": customer_id,
        "manifest": str(source_manifest_path),
        "changes": _apply_changes(run_manifest["candidates"], outputs),
        "blocked_candidates": [
            {
                "asset_id": item["asset_id"],
                "reason": "Google Ads placement details are required before publishing this candidate",
            }
            for item in run_manifest["candidates"]
            if not item.get("publish_ready") and item.get("review_status") == "pending"
        ],
        "applied": False,
    }
    (run_dir / "apply-plan.yaml").write_text(json.dumps(apply_plan, indent=2) + "\n")
    _update_account_index(wiki / "Index.md", run_id, run_manifest["candidates"])
    print(f"static replacements ready: {len(generated)}")
    for item in generated:
        print(f"wiki/{customer_id}/creative-runs/{run_id}/outputs/{item['name']}")
