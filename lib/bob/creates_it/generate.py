"""Generate review-only static replacements through a client creative provider."""

from __future__ import annotations

import base64
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
from lib.bob.creates_it.adapt import TARGET_FORMATS, adapt_master_png, normalize_generated_png

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
    source_path: Path | list[Path],
    aspect_ratio: str,
    opener: Callable[..., Any] = urlopen,
) -> tuple[bytes, str]:
    source_paths = source_path if isinstance(source_path, list) else [source_path]
    image_inputs = []
    for path in source_paths:
        source = path.read_bytes()
        if len(source) > MAX_SOURCE_BYTES:
            die(f"source image exceeds {MAX_SOURCE_BYTES // 1_000_000} MB: {path}")
        image_inputs.append({
            "type": "image",
            "mime_type": _mime_for(path),
            "data": base64.b64encode(source).decode(),
        })
    body = json.dumps({
        "model": model,
        "input": [*image_inputs, {"type": "text", "text": prompt}],
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
        return normalize_generated_png(image_bytes, output, (width, height))
    except ValueError as exc:
        die(str(exc))


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


def _safe_label(value: str, fallback: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or fallback


def _next_master_name(outputs: Path, concept_id: str) -> str:
    safe_id = _safe_label(concept_id, "concept")
    versions = []
    for path in outputs.glob(f"master-{safe_id}-v*.png"):
        match = re.search(r"-v(\d+)\.png$", path.name)
        if match:
            versions.append(int(match.group(1)))
    return f"master-{safe_id}-v{max(versions, default=0) + 1}.png"


def _next_adaptation_name(outputs: Path, concept_id: str, format_name: str) -> str:
    safe_id = _safe_label(concept_id, "concept")
    versions = []
    for path in outputs.glob(f"adapt-{safe_id}-{format_name}-v*.png"):
        match = re.search(r"-v(\d+)\.png$", path.name)
        if match:
            versions.append(int(match.group(1)))
    return f"adapt-{safe_id}-{format_name}-v{max(versions, default=0) + 1}.png"


def _write_run_index(path: Path, customer_id: str, candidates: list[dict[str, Any]]) -> None:
    lines = [
        f"# Creative review · {customer_id}",
        "",
        "Review-only outputs; nothing has been published.",
        "",
    ]
    visible = [item for item in candidates if item.get("review_status") != "superseded"]
    masters = [item for item in visible if item.get("candidate_type") == "master"]
    low = [item for item in visible if item.get("candidate_type") == "low_replacement"]
    adaptations = [item for item in visible if item.get("candidate_type") == "adaptation"]
    for title, items in (
        ("LOW replacements", low),
        ("Master concepts", masters),
        ("Approved adaptations", adaptations),
    ):
        if not items:
            continue
        lines += [f"## {title}", ""]
        for item in items:
            label = item.get("concept_id") or item.get("asset_id") or item["name"]
            source_names = item.get("source_references") or (
                [item["source_reference"]] if item.get("source_reference") else []
            )
            for source_name in source_names[:3]:
                lines += [f"### {label} · source", f"![Source {label}](references/{source_name})", ""]
            lines += [
                f"### {label} · {item.get('format', 'output')}",
                f"![{item['name']}](outputs/{item['name']})",
                f"[{item['name']}](outputs/{item['name']}) · QA passed",
                "",
            ]
    path.write_text("\n".join(lines) + "\n")


def _update_account_index(index_path: Path, run_id: str, candidates: list[dict[str, Any]]) -> None:
    text = index_path.read_text() if index_path.exists() else "# Bob — Wiki Index\n"
    heading = "## Static Replacements"
    if heading not in text:
        text = text.rstrip() + f"\n\n{heading}\n"
    marker = f"<!-- creative-run:{run_id} -->"
    active = sum(1 for item in candidates if item.get("review_status") != "superseded")
    row = f"- [{run_id}](creative-runs/{run_id}/index.md) — {active} review output{'s' if active != 1 else ''}"
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
        if item.get("candidate_type") == "master" and not item.get("approved_for_adaptation"):
            continue
        replacement_targets = item.get("replacement_targets")
        if isinstance(replacement_targets, list):
            for target in replacement_targets:
                if not isinstance(target, dict) or not _placements_publish_ready(target.get("placements", [])):
                    continue
                for placement in target["placements"]:
                    changes.append({
                        "asset_id": str(target.get("asset_id", "")),
                        "ad_group_id": placement["ad_group_id"],
                        "ad_id": placement["ad_id"],
                        "replacement_image": str(outputs / item["name"]),
                        "action": "replace",
                    })
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
        "Create one review-only, lightly modified advertising image based on the supplied LOW source. "
        f"Preserve its proposition, subjects, brand treatment, composition, and native {width}x{height} dimensions. "
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
        "candidate_type": "low_replacement",
        "format": "source dimensions",
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


def _copy_concept_references(
    concept: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    references: Path,
) -> tuple[list[str], list[Path], list[dict[str, Any]]]:
    source_ids = concept.get("source_asset_ids") or concept.get("reference_asset_ids") or []
    if not isinstance(source_ids, list) or not source_ids:
        die("each concept must contain source_asset_ids")
    normalized = [str(value) for value in source_ids]
    if len(normalized) != len(set(normalized)):
        die("concept source_asset_ids must be unique")
    source_paths: list[Path] = []
    selected_assets: list[dict[str, Any]] = []
    reference_names: list[str] = []
    for asset_id in normalized:
        asset = assets.get(asset_id)
        if not asset:
            die(f"concept source asset {asset_id} is not in the source manifest")
        source = _safe_state_file(
            str(asset.get("local_path", "")),
            f"source image for asset {asset_id}",
            allow_shared=True,
        )
        suffix = source.suffix.lower() or ".png"
        reference = references / f"source-{_safe_label(asset_id, 'asset')}{suffix}"
        if not reference.exists():
            shutil.copy2(source, reference)
        source_paths.append(reference)
        selected_assets.append(asset)
        reference_names.append(reference.name)
    return reference_names, source_paths, selected_assets


def _concept_placements(selected_assets: list[dict[str, Any]]) -> list[dict[str, str]]:
    placements: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for asset in selected_assets:
        asset_id = str(asset.get("asset_id", ""))
        for placement in _candidate_placements(asset):
            key = (
                asset_id,
                placement["campaign_id"],
                placement["ad_group_id"],
                placement["ad_id"],
            )
            if key in seen:
                continue
            seen.add(key)
            placements.append({"asset_id": asset_id, **placement})
    return placements


def _generate_master(
    concept: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    design: str,
    strategy: str,
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
    user_request: str,
    model: str,
) -> dict[str, Any]:
    concept_id = _safe_label(str(concept.get("concept_id", "")), "")
    if not concept_id:
        die("each concept must contain a concept_id")
    reference_names, source_paths, selected_assets = _copy_concept_references(
        concept, assets, references
    )
    instruction = str(concept.get("instruction") or concept.get("prompt") or "").strip()
    campaign_context = str(concept.get("campaign_context") or "").strip()
    ad_group_context = str(concept.get("ad_group_context") or "").strip()
    context = "\n".join(
        value for value in (
            f"Campaign context: {campaign_context}" if campaign_context else "",
            f"Ad-group context: {ad_group_context}" if ad_group_context else "",
        ) if value
    ) or "No campaign or ad-group context was supplied; use the mandatory brief and references."
    prompt = (
        "Create one review-only 1:1 master advertising concept at 1200x1200. "
        "Use the supplied references as visual evidence, not as a demand for pixel copying. "
        "Keep important subjects, branding, copy, and legal elements legible, with flexible background "
        "space that can support later aspect-ratio adaptation. Do not force every element into a rigid safe-area box. "
        "Do not add unrequested logos, claims, prices, offers, or legal copy.\n\n"
        f"USER EXPECTATION:\n{user_request[:12000]}\n\n"
        f"CONCEPT INSTRUCTION:\n{instruction[:12000]}\n\n"
        f"OPTIONAL ACCOUNT CONTEXT:\n{context[:4000]}\n\n"
        f"DESIGN SYSTEM:\n{design[:16000]}\n\nDESIGN STRATEGY:\n{strategy[:16000]}"
    )
    image_bytes, returned_mime = caller(
        provider["api_key"], model, prompt, source_paths, "1:1"
    )
    output_name = _next_master_name(outputs, concept_id)
    output = outputs / output_name
    qa = _save_exact_png(image_bytes, output, *TARGET_FORMATS["square"])
    return {
        "name": output_name,
        "candidate_type": "master",
        "concept_id": concept_id,
        "format": "square master",
        "source_asset_ids": [str(asset.get("asset_id", "")) for asset in selected_assets],
        "source_references": reference_names,
        "output": str(output.relative_to(outputs.parent)),
        "provider_mime": returned_mime,
        "model": model,
        "placements": _concept_placements(selected_assets),
        "publish_ready": False,
        "approved_for_adaptation": False,
        "qa": qa,
        "review_status": "pending",
        "published": False,
    }


def _asset_format(asset: dict[str, Any]) -> str:
    width = int(asset.get("width") or asset.get("image_width") or 0)
    height = int(asset.get("height") or asset.get("image_height") or 0)
    if not width or not height:
        return ""
    ratio = width / height
    return min(TARGET_FORMATS, key=lambda name: abs(
        TARGET_FORMATS[name][0] / TARGET_FORMATS[name][1] - ratio
    ))


def _replacement_targets(
    source_ids: list[str], assets: dict[str, dict[str, Any]], format_name: str
) -> list[dict[str, Any]]:
    targets = []
    for asset_id in source_ids:
        asset = assets.get(asset_id)
        if not asset or _asset_format(asset) != format_name:
            continue
        targets.append({
            "asset_id": asset_id,
            "placements": _candidate_placements(asset),
        })
    return targets


def _adapt_master(
    request: dict[str, Any],
    master: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    outputs: Path,
    design: str,
    strategy: str,
    user_request: str,
    provider: dict[str, str] | None,
    model: str,
    caller: Callable[..., tuple[bytes, str]],
) -> list[dict[str, Any]]:
    formats = request.get("formats") or []
    if not isinstance(formats, list) or not formats:
        die("each adaptation request must contain formats")
    unknown = {str(value) for value in formats} - set(TARGET_FORMATS)
    if unknown:
        die("unsupported adaptation formats: " + ", ".join(sorted(unknown)))
    method = str(request.get("method") or "python")
    if method not in {"python", "ai"}:
        die("adaptation method must be python or ai")
    if method == "ai" and not provider:
        die("AI adaptation requires the configured creative provider")
    source_ids = [str(value) for value in master.get("source_asset_ids", [])]
    source = outputs / str(master["name"])
    if not source.is_file():
        die(f"approved master output is missing: {source.name}")
    created: list[dict[str, Any]] = []
    for format_name in dict.fromkeys(str(value) for value in formats):
        targets = _replacement_targets(source_ids, assets, format_name)
        if format_name == "square":
            master["approved_for_adaptation"] = True
            master["replacement_targets"] = targets
            master["publish_ready"] = bool(targets) and all(
                _placements_publish_ready(item["placements"]) for item in targets
            )
            continue
        output_name = _next_adaptation_name(outputs, str(master.get("concept_id", "concept")), format_name)
        output = outputs / output_name
        provider_mime = ""
        if method == "ai":
            target_width, target_height = TARGET_FORMATS[format_name]
            prompt = (
                f"Recompose the approved master as a {format_name} {target_width}x{target_height} advertising image. "
                "Preserve its concept, proposition, subjects, branding, copy, and legal meaning. "
                "Adapt the layout for the new ratio rather than stretching or blindly cropping it. "
                "Do not add unrequested claims, offers, logos, or legal copy.\n\n"
                f"USER EXPECTATION:\n{user_request[:12000]}\n\n"
                f"ADAPTATION INSTRUCTION:\n{str(request.get('instruction') or '')[:12000]}\n\n"
                f"DESIGN SYSTEM:\n{design[:16000]}\n\nDESIGN STRATEGY:\n{strategy[:16000]}"
            )
            image_bytes, provider_mime = caller(
                provider["api_key"], model, prompt, source, _aspect_ratio(target_width, target_height)
            )
            qa = _save_exact_png(image_bytes, output, target_width, target_height)
            qa["adaptation_method"] = "ai_recomposition"
        else:
            try:
                qa = adapt_master_png(source, output, TARGET_FORMATS[format_name])
            except ValueError as exc:
                die(str(exc))
        created.append({
            "name": output_name,
            "candidate_type": "adaptation",
            "concept_id": master.get("concept_id", ""),
            "format": format_name,
            "master_name": master["name"],
            "source_asset_ids": source_ids,
            "source_references": master.get("source_references", []),
            "replacement_targets": targets,
            "output": str(output.relative_to(outputs.parent)),
            "provider_mime": provider_mime,
            "model": model if method == "ai" else "deterministic-python",
            "publish_ready": bool(targets) and all(
                _placements_publish_ready(item["placements"]) for item in targets
            ),
            "qa": qa,
            "review_status": "pending",
            "published": False,
        })
    return created


def _generate_low_stage(
    brief: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    design: str,
    strategy: str,
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
    goal: str,
    model: str,
) -> list[dict[str, Any]]:
    replacements = brief.get("replacements")
    if not isinstance(replacements, list) or not replacements or len(replacements) > MAX_REPLACEMENTS:
        die(f"LOW brief must contain 1–{MAX_REPLACEMENTS} replacements")
    replacement_ids = [
        str(item.get("asset_id", "")) for item in replacements if isinstance(item, dict)
    ]
    if len(replacement_ids) != len(replacements) or len(set(replacement_ids)) != len(replacements):
        die("LOW brief must name each source asset once")
    generated = []
    for replacement, asset_id in zip(replacements, replacement_ids):
        if asset_id not in assets:
            die(f"asset {asset_id} is not in the selected static source manifest")
        generated.append(_generate_one(
            replacement, assets[asset_id], design, strategy, provider,
            references, outputs, caller, goal or "Lightly improve this LOW image", model,
        ))
    return generated


def _generate_master_stage(
    brief: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    design: str,
    strategy: str,
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
    goal: str,
    model: str,
) -> list[dict[str, Any]]:
    concepts = brief.get("concepts")
    if not isinstance(concepts, list) or not concepts or len(concepts) > MAX_REPLACEMENTS:
        die(f"concept brief must contain 1–{MAX_REPLACEMENTS} concepts")
    concept_ids = [
        str(item.get("concept_id", "")) for item in concepts if isinstance(item, dict)
    ]
    if len(concept_ids) != len(concepts) or len(set(concept_ids)) != len(concepts):
        die("concept brief must name each concept once")
    return [
        _generate_master(
            concept, assets, design, strategy, provider, references,
            outputs, caller, goal, model,
        )
        for concept in concepts
    ]


def _generate_adaptation_stage(
    brief: dict[str, Any],
    run_manifest: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    outputs: Path,
    design: str,
    strategy: str,
    goal: str,
    provider: dict[str, str] | None,
    model: str,
    caller: Callable[..., tuple[bytes, str]],
) -> list[dict[str, Any]]:
    requests = brief.get("adaptations")
    if not isinstance(requests, list) or not requests or len(requests) > MAX_REPLACEMENTS:
        die(f"adaptation brief must contain 1–{MAX_REPLACEMENTS} adaptations")
    generated = []
    for request in requests:
        if not isinstance(request, dict):
            die("each adaptation must be a JSON object")
        master_name = str(request.get("master_name", ""))
        master = next(
            (
                item for item in run_manifest["candidates"]
                if item.get("candidate_type") == "master"
                and item.get("name") == master_name
                and item.get("review_status") == "pending"
            ),
            None,
        )
        if not master:
            die(f"pending master is not in this creative run: {master_name}")
        generated.extend(_adapt_master(
            request, master, assets, outputs, design, strategy, goal,
            provider, model, caller,
        ))
    return generated


def _supersede_prior_candidates(
    candidates: list[dict[str, Any]], generated: list[dict[str, Any]]
) -> None:
    regenerated_ids = {item.get("asset_id") for item in generated if item.get("asset_id")}
    regenerated_concepts = {
        (item.get("concept_id"), item.get("candidate_type"), item.get("format"))
        for item in generated if item.get("concept_id")
    }
    for existing in candidates:
        same_low = existing.get("asset_id") in regenerated_ids
        same_concept_output = (
            existing.get("concept_id"), existing.get("candidate_type"), existing.get("format")
        ) in regenerated_concepts
        if (same_low or same_concept_output) and existing.get("review_status") == "pending":
            existing["review_status"] = "superseded"


def _blocked_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    blocked = []
    for item in candidates:
        publish_surface = (
            item.get("candidate_type") in {"low_replacement", "adaptation"}
            or item.get("approved_for_adaptation")
        )
        if item.get("review_status") != "pending" or not publish_surface or item.get("publish_ready"):
            continue
        blocked.append({
            "asset_id": item.get("asset_id") or ",".join(item.get("source_asset_ids", [])),
            "reason": "Google Ads placement details are required before publishing this candidate",
        })
    return blocked


def create_static_replacements(args: Any, caller: Callable[..., tuple[bytes, str]] = _call_gemini) -> None:
    """Generate LOW edits, generic masters, or approved master adaptations."""
    customer_id = _selected_customer_id()
    brief_path = _safe_state_file(str(args.brief), "replacement brief")
    source_manifest_path = _safe_state_file(
        str(args.manifest), "static source manifest", allow_shared=True
    )
    brief = _read_json(brief_path, "replacement brief")
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
    assets = _asset_map(source_manifest)
    mode = str(brief.get("mode") or ("low_edit" if selection == "low" else "concept"))
    if mode not in {"low_edit", "concept"}:
        die("creative brief mode must be low_edit or concept")
    if mode == "low_edit" and selection != "low":
        die("low_edit mode requires a LOW source manifest")
    if mode == "concept" and selection == "low":
        die("LOW sources use low_edit mode; use campaign or assets for a new concept")
    stage = str(brief.get("stage") or ("edit" if mode == "low_edit" else "masters"))
    if stage not in {"edit", "masters", "adaptations"}:
        die("creative brief stage must be edit, masters, or adaptations")
    if mode == "low_edit" and stage != "edit":
        die("low_edit mode supports only the edit stage")
    if mode == "concept" and stage == "edit":
        die("concept mode supports masters or adaptations")
    goal = str(brief.get("user_request") or brief.get("goal") or "").strip()
    top_level_references = brief.get("reference_asset_ids") or brief.get("reference_images") or []
    if mode == "concept" and not goal and not top_level_references:
        die("concept brief requires user_request text or an explicit reference image")
    wiki = account_wiki_dir(customer_id)
    design_path = wiki / "design" / "DESIGN.md"
    strategy_path = wiki / "design" / "DESIGN_STRATEGY.md"
    if mode == "concept" and (not design_path.is_file() or not strategy_path.is_file()):
        die("create the selected account's DESIGN.md and DESIGN_STRATEGY.md before generating concepts")
    design = design_path.read_text() if design_path.is_file() else ""
    strategy = strategy_path.read_text() if strategy_path.is_file() else ""
    run_id = str(getattr(args, "run_id", "") or brief.get("run_id") or uuid.uuid4().hex[:12])
    if not re.fullmatch(r"[a-zA-Z0-9_-]{6,64}", run_id):
        die("run ID must contain only letters, numbers, underscores, or hyphens")
    run_dir = wiki / "creative-runs" / run_id
    references = run_dir / "references"
    outputs = run_dir / "outputs"
    references.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    existing_manifest = _read_json(manifest_path, "creative run manifest") if manifest_path.exists() else None
    provider: dict[str, str] | None = None
    model = ""
    adaptation_requests = brief.get("adaptations") if stage == "adaptations" else []
    needs_ai_adaptation = isinstance(adaptation_requests, list) and any(
        isinstance(item, dict) and str(item.get("method") or "python") == "ai"
        for item in adaptation_requests
    )
    if stage in {"edit", "masters"} or needs_ai_adaptation:
        provider = _provider_config()
        model = _image_model(brief)
    run_manifest = existing_manifest or {
        "run_id": run_id,
        "customer_id": customer_id,
        "status": "generating",
        "created_at": _now(),
        "source_manifest": str(source_manifest_path),
        "selection": selection,
        "mode": mode,
        "goal": goal,
        "provider": provider["provider"] if provider else "gemini",
        "model": model,
        "models_used": [model] if model else [],
        "candidates": [],
    }
    if (
        run_manifest.get("customer_id") != customer_id
        or run_manifest.get("source_manifest") != str(source_manifest_path)
        or run_manifest.get("mode") != mode
    ):
        die("existing creative run belongs to a different account or source selection")
    if stage == "adaptations" and not existing_manifest:
        die("adaptations require an existing creative run with an approved master")
    stored_brief = run_dir / "brief.json"
    if not stored_brief.exists():
        shutil.copy2(brief_path, stored_brief)
    briefs_dir = run_dir / "briefs"
    briefs_dir.mkdir(exist_ok=True)
    shutil.copy2(brief_path, briefs_dir / f"{uuid.uuid4().hex}.json")
    manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
    generated: list[dict[str, Any]] = []
    try:
        if stage == "edit":
            generated = _generate_low_stage(
                brief, assets, design, strategy, provider or {}, references,
                outputs, caller, goal, model,
            )
        elif stage == "masters":
            generated = _generate_master_stage(
                brief, assets, design, strategy, provider or {}, references,
                outputs, caller, goal, model,
            )
        else:
            generated = _generate_adaptation_stage(
                brief, run_manifest, assets, outputs, design, strategy, goal,
                provider, model, caller,
            )
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
    _supersede_prior_candidates(run_manifest["candidates"], generated)
    run_manifest["candidates"].extend(generated)
    if model:
        run_manifest["models_used"] = list(
            dict.fromkeys([*run_manifest.get("models_used", []), model])
        )
    run_manifest["status"] = {
        "edit": "ready_for_review",
        "masters": "masters_ready",
        "adaptations": "adaptations_ready",
    }[stage]
    run_manifest["updated_at"] = _now()
    manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
    _write_run_index(run_dir / "index.md", customer_id, run_manifest["candidates"])
    apply_plan = {
        "customer_id": customer_id,
        "manifest": str(source_manifest_path),
        "changes": _apply_changes(run_manifest["candidates"], outputs),
        "blocked_candidates": _blocked_candidates(run_manifest["candidates"]),
        "applied": False,
    }
    (run_dir / "apply-plan.yaml").write_text(json.dumps(apply_plan, indent=2) + "\n")
    _update_account_index(wiki / "Index.md", run_id, run_manifest["candidates"])
    print(f"creative outputs ready: {len(generated)}")
    print(
        f"[[artifact:wiki/{customer_id}/creative-runs/{run_id}/index.md|"
        "Open the full creative review]]"
    )
    for item in generated:
        print(f"wiki/{customer_id}/creative-runs/{run_id}/outputs/{item['name']}")
