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
VISUAL_REVIEW_CHECKS = (
    "brief_fidelity",
    "copy_accuracy",
    "brand_fidelity",
    "creative_transformation",
    "composition",
    "visual_integrity",
    "design_guidance",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _image_prompt(*parts: str) -> str:
    return "\n\n".join(str(part).strip() for part in parts if str(part).strip())


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


def _generation_request(
    model: str,
    prompt: str,
    sources: Path | list[Path],
    aspect_ratio: str,
) -> dict[str, Any]:
    source_paths = sources if isinstance(sources, list) else [sources]
    image_inputs = [
        {
            "type": "image",
            "reference": path.name,
            "mime_type": _mime_for(path),
        }
        for path in source_paths
    ]
    return {
        "model": model,
        "input": [*image_inputs, {"type": "text", "text": prompt}],
        "response_format": {"type": "image", "aspect_ratio": aspect_ratio},
    }


def _candidate_label(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("concept_id")
        or candidate.get("asset_id")
        or candidate.get("format")
        or "Creative output"
    )


def _visual_review_status(candidate: dict[str, Any]) -> str:
    review = candidate.get("visual_review")
    return str(review.get("status", "pending")) if isinstance(review, dict) else "pending"


def _write_visual_review_detail(run_dir: Path, candidate: dict[str, Any]) -> None:
    detail_page = candidate.get("detail_page")
    if not detail_page:
        return
    path = run_dir / str(detail_page)
    if not path.is_file():
        return
    text = re.sub(
        r"\n<!-- visual-review:start -->.*?<!-- visual-review:end -->\n?",
        "\n",
        path.read_text(),
        flags=re.DOTALL,
    ).rstrip()
    review = candidate.get("visual_review", {"status": "pending"})
    block = (
        "\n\n<!-- visual-review:start -->\n"
        "## Visual review\n\n"
        "```json\n"
        f"{json.dumps(review, indent=2, ensure_ascii=False)}\n"
        "```\n"
        "<!-- visual-review:end -->\n"
    )
    path.write_text(text + block)


def _write_candidate_details(run_dir: Path, candidates: list[dict[str, Any]]) -> None:
    details = run_dir / "details"
    details.mkdir(exist_ok=True)
    for candidate in candidates:
        detail_name = f"{Path(str(candidate['name'])).stem}.md"
        detail_path = details / detail_name
        label = _candidate_label(candidate)
        source_names = candidate.get("source_references") or (
            [candidate["source_reference"]] if candidate.get("source_reference") else []
        )
        lines = [
            f"# {label}",
            "",
            "Review-only output; nothing has been published.",
            "",
        ]
        for source_name in source_names:
            lines += [
                "## Source",
                "",
                f"![Source {label}](../references/{source_name})",
                "",
            ]
        lines += [
            "## Output",
            "",
            f"![Output {label}](../outputs/{candidate['name']})",
            "",
        ]
        production = candidate.pop("_production_record", None)
        request = candidate.pop("_generation_request", None)
        if production:
            lines += [
                "## Production method",
                "",
                "```json",
                json.dumps(production, indent=2, ensure_ascii=False),
                "```",
                "",
            ]
        if request:
            lines += [
                "## Generation request",
                "",
                "The API key and encoded image bytes are intentionally omitted.",
                "",
                "```json",
                json.dumps(request, indent=2, ensure_ascii=False),
                "```",
                "",
            ]
        else:
            lines += [
                "## Generation request",
                "",
                "No AI prompt was used; the production method above records the deterministic tool/script.",
                "",
            ]
        detail_path.write_text("\n".join(lines))
        candidate["detail_page"] = str(detail_path.relative_to(run_dir))
        _write_visual_review_detail(run_dir, candidate)


def _write_run_index(path: Path, customer_id: str, candidates: list[dict[str, Any]]) -> None:
    lines = [
        f"# Creative review · {customer_id}",
        "",
        "Review-only outputs; nothing has been published.",
        "",
    ]
    visible = [
        item for item in candidates
        if item.get("review_status") != "superseded"
        and _visual_review_status(item) == "passed"
    ]
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
            label = _candidate_label(item)
            source_names = item.get("source_references") or (
                [item["source_reference"]] if item.get("source_reference") else []
            )
            for source_name in source_names[:3]:
                lines += [f"### {label} · source", f"![Source {label}](references/{source_name})", ""]
            lines += [
                f"### {label} · {item.get('format', 'output')}",
                f"![{item['name']}](outputs/{item['name']})",
            ]
            if item.get("detail_page"):
                method = str(item.get("production_method") or "unknown").replace("_", " ")
                lines.append(
                    f"Production: {method} · [View generation details]({item['detail_page']}) · "
                    "Technical checks passed · Visual review passed"
                )
            else:
                lines.append("Technical checks passed · Visual review passed")
            lines.append("")
    path.write_text("\n".join(lines) + "\n")


def _index_label(value: str) -> str:
    return re.sub(r"[\[\]\r\n]+", " ", value).strip()[:100] or "Creative Review"


def _ensure_index_section(text: str, heading: str) -> str:
    if re.search(rf"(?m)^{re.escape(heading)}\s*$", text):
        return text
    backlog = re.search(r"(?m)^## Backlog\s*$", text)
    if backlog:
        return text[:backlog.start()] + f"{heading}\n\n" + text[backlog.start():]
    return text.rstrip() + f"\n\n{heading}\n"


def _insert_after_heading(text: str, heading: str, block: str) -> str:
    section = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
    insert_at = section.end() if section else len(text)
    return text[:insert_at] + f"\n\n{block}" + text[insert_at:]


def _normalize_account_index(index_path: Path, marker: str, row: str) -> str:
    text = index_path.read_text() if index_path.exists() else "# Bob — Wiki Index\n"
    text = _ensure_index_section(text, "## Action Items")
    text = _ensure_index_section(text, "## Design")

    creative_blocks: dict[str, str] = {}
    block_pattern = re.compile(r"(?m)^(<!-- creative-run:([^>]+) -->)\n(- [^\n]*)\n?")
    for match in block_pattern.finditer(text):
        creative_blocks[match.group(2)] = f"{match.group(1)}\n{match.group(3)}"
    creative_blocks[marker.removeprefix("<!-- creative-run:").removesuffix(" -->")] = (
        f"{marker}\n{row}"
    )
    text = block_pattern.sub("", text)

    design_row_pattern = re.compile(
        r"(?m)^- .*?(?:Account Design Guidance|design/DESIGN\.md).*?$\n?"
    )
    text = design_row_pattern.sub("", text)
    design = index_path.parent / "design" / "DESIGN.md"
    strategy = index_path.parent / "design" / "DESIGN_STRATEGY.md"
    if design.is_file() and strategy.is_file():
        design_row = (
            "- [DESIGN.md](design/DESIGN.md) · "
            "[DESIGN_STRATEGY.md](design/DESIGN_STRATEGY.md) — account design guidance"
        )
        text = _insert_after_heading(text, "## Design", design_row)

    if creative_blocks:
        text = _insert_after_heading(
            text,
            "## Action Items",
            "\n\n".join(creative_blocks.values()),
        )
    return text.rstrip() + "\n"


def _update_account_index(index_path: Path, manifest: dict[str, Any]) -> None:
    run_id = str(manifest["run_id"])
    marker = f"<!-- creative-run:{run_id} -->"
    active = sum(
        1 for item in manifest["candidates"]
        if item.get("review_status") != "superseded"
        and _visual_review_status(item) == "passed"
    )
    title = _index_label(str(manifest.get("title") or manifest.get("goal") or "Creative Review"))
    date = str(manifest.get("created_at") or "")[:10]
    dated_title = f"{title} — {date}" if date else title
    row = (
        f"- [{dated_title}](creative-runs/{run_id}/index.md) — "
        f"{active} review output{'s' if active != 1 else ''}; nothing published"
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(_normalize_account_index(index_path, marker, row))


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
        if item.get("review_status") != "pending" or _visual_review_status(item) != "passed":
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
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
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
    full_prompt = _image_prompt(
        f"Create one review-only {width}x{height} ad from the supplied LOW reference. "
        "Preserve its proposition, approved copy, branding, native dimensions, key subject, and "
        "broad composition, but create a visibly distinct controlled evolution. The requested "
        "improvement must be obvious at normal feed size; do not reproduce the source layout or "
        "styling pixel-for-pixel. Do not invent copy, claims, prices, offers, logos, or legal text.",
        prompt,
    )
    aspect_ratio = _aspect_ratio(width, height)
    image_bytes, returned_mime = caller(
        provider["api_key"], model, full_prompt, reference, aspect_ratio
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
        "visual_review": {"status": "pending"},
        "review_status": "pending",
        "published": False,
        "production_method": "gemini_generation",
        "_production_record": {
            "method": "ai_generation",
            "provider": "gemini",
            "model": model,
            "prompt_used": True,
        },
        "_generation_request": _generation_request(
            model, full_prompt, reference, aspect_ratio
        ),
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
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
    model: str,
) -> dict[str, Any]:
    concept_id = _safe_label(str(concept.get("concept_id", "")), "")
    if not concept_id:
        die("each concept must contain a concept_id")
    reference_names, source_paths, selected_assets = _copy_concept_references(
        concept, assets, references
    )
    instruction = str(concept.get("instruction") or concept.get("prompt") or "").strip()
    if not instruction:
        die(f"concept {concept_id} requires a concise generation instruction")
    prompt = _image_prompt(
        "Create one review-only 1200x1200 square ad using the supplied images for brand, product, "
        "and factual reference. Follow only explicit hard constraints and exact approved copy "
        "literally; treat other creative direction as an objective. Unless the instruction explicitly "
        "requests a close adaptation, develop a materially new focal idea, composition, subject "
        "arrangement, framing, and reading path rather than reusing a reference layout. Keep specified "
        "copy legible and requested brand and product roles accurate. Do not invent copy, claims, "
        "offers, logos, or legal text.",
        instruction,
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
        "visual_review": {"status": "pending"},
        "review_status": "pending",
        "published": False,
        "production_method": "gemini_generation",
        "_production_record": {
            "method": "ai_generation",
            "provider": "gemini",
            "model": model,
            "prompt_used": True,
        },
        "_generation_request": _generation_request(
            model, prompt, source_paths, "1:1"
        ),
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
            prompt = _image_prompt(
                f"Recompose the approved master as a {format_name} {target_width}x{target_height} advertising image. "
                "Preserve its concept, proposition, subjects, branding, copy, and legal meaning. "
                "Adapt the layout for the new ratio rather than stretching or blindly cropping it. "
                "Do not add unrequested copy, claims, offers, logos, or legal text.",
                str(request.get("instruction") or ""),
            )
            image_bytes, provider_mime = caller(
                provider["api_key"], model, prompt, source, _aspect_ratio(target_width, target_height)
            )
            qa = _save_exact_png(image_bytes, output, target_width, target_height)
            qa["adaptation_method"] = "ai_recomposition"
            generation_request = _generation_request(
                model, prompt, source, _aspect_ratio(target_width, target_height)
            )
            production_method = "gemini_recomposition"
            production_record = {
                "method": "ai_recomposition",
                "provider": "gemini",
                "model": model,
                "prompt_used": True,
                "source": source.name,
                "target": {
                    "format": format_name,
                    "width": target_width,
                    "height": target_height,
                },
            }
        else:
            try:
                qa = adapt_master_png(source, output, TARGET_FORMATS[format_name])
            except ValueError as exc:
                die(str(exc))
            generation_request = None
            target_width, target_height = TARGET_FORMATS[format_name]
            production_method = "python_adaptation"
            production_record = {
                "method": "deterministic_python_adaptation",
                "tool": "adapt_master_png",
                "prompt_used": False,
                "source": source.name,
                "target": {
                    "format": format_name,
                    "width": target_width,
                    "height": target_height,
                },
            }
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
            "visual_review": {"status": "pending"},
            "review_status": "pending",
            "published": False,
            "production_method": production_method,
            "_production_record": production_record,
            "_generation_request": generation_request,
        })
    return created


def _generate_low_stage(
    brief: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
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
            replacement, assets[asset_id], provider,
            references, outputs, caller, model,
        ))
    return generated


def _generate_master_stage(
    brief: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    provider: dict[str, str],
    references: Path,
    outputs: Path,
    caller: Callable[..., tuple[bytes, str]],
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
            concept, assets, provider, references,
            outputs, caller, model,
        )
        for concept in concepts
    ]


def _generate_adaptation_stage(
    brief: dict[str, Any],
    run_manifest: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    outputs: Path,
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
                and _visual_review_status(item) == "passed"
            ),
            None,
        )
        if not master:
            die(f"pending master is not in this creative run: {master_name}")
        generated.extend(_adapt_master(
            request, master, assets, outputs, provider, model, caller,
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
        if item.get("review_status") != "pending" or not publish_surface:
            continue
        if _visual_review_status(item) != "passed":
            blocked.append({
                "asset_id": item.get("asset_id") or ",".join(item.get("source_asset_ids", [])),
                "reason": "visual review must pass before publishing this candidate",
            })
            continue
        if item.get("publish_ready"):
            continue
        blocked.append({
            "asset_id": item.get("asset_id") or ",".join(item.get("source_asset_ids", [])),
            "reason": "Google Ads placement details are required before publishing this candidate",
        })
    return blocked


def _write_apply_plan(
    run_dir: Path,
    manifest: dict[str, Any],
    outputs: Path,
) -> None:
    plan = {
        "customer_id": manifest["customer_id"],
        "manifest": manifest["source_manifest"],
        "changes": _apply_changes(manifest["candidates"], outputs),
        "blocked_candidates": _blocked_candidates(manifest["candidates"]),
        "applied": False,
    }
    (run_dir / "apply-plan.yaml").write_text(json.dumps(plan, indent=2) + "\n")


def _validated_review(item: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(item, dict):
        die("each visual review must be a JSON object")
    name = str(item.get("name", "")).strip()
    checks = item.get("checks")
    issues = item.get("issues")
    if not name or not isinstance(checks, dict) or not isinstance(issues, list):
        die("each visual review requires name, checks, and issues")
    if set(checks) != set(VISUAL_REVIEW_CHECKS):
        die("visual review checks must contain exactly: " + ", ".join(VISUAL_REVIEW_CHECKS))
    normalized_checks = {key: str(checks[key]).lower() for key in VISUAL_REVIEW_CHECKS}
    if any(value not in {"passed", "failed"} for value in normalized_checks.values()):
        die("each visual review check must be passed or failed")
    normalized_issues = [str(issue).strip() for issue in issues if str(issue).strip()]
    status = "failed" if "failed" in normalized_checks.values() else "passed"
    if status == "failed" and not normalized_issues:
        die("a failed visual review must explain at least one issue")
    if status == "passed" and normalized_issues:
        die("a passed visual review cannot contain unresolved issues")
    return name, {
        "status": status,
        "checks": normalized_checks,
        "issues": normalized_issues,
        "reviewed_at": _now(),
    }


def _record_visual_reviews(args: Any) -> None:
    customer_id = _selected_customer_id()
    run_id = str(getattr(args, "run_id", "") or "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{6,64}", run_id):
        die("visual review requires a valid run ID")
    review_path = _safe_state_file(str(args.visual_review), "visual review")
    payload = _read_json(review_path, "visual review")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        die("visual review must contain a non-empty reviews list")
    run_dir = account_wiki_dir(customer_id) / "creative-runs" / run_id
    manifest_path = run_dir / "manifest.json"
    manifest = _read_json(manifest_path, "creative run manifest")
    if manifest.get("customer_id") != customer_id:
        die("creative run belongs to a different account")
    pending = {
        str(candidate.get("name")): candidate
        for candidate in manifest.get("candidates", [])
        if isinstance(candidate, dict)
        and candidate.get("review_status") == "pending"
        and _visual_review_status(candidate) == "pending"
    }
    validated = [_validated_review(item) for item in reviews]
    names = [name for name, _review in validated]
    if len(names) != len(set(names)):
        die("visual review must name each candidate once")
    if set(names) != set(pending):
        missing = sorted(set(pending) - set(names))
        unknown = sorted(set(names) - set(pending))
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        die("visual review must cover every pending output: " + "; ".join(details))
    for name, review in validated:
        pending[name]["visual_review"] = review
        _write_visual_review_detail(run_dir, pending[name])
    passed = [candidate for candidate in pending.values() if _visual_review_status(candidate) == "passed"]
    if not passed:
        manifest["status"] = "visual_review_failed"
    elif all(candidate.get("candidate_type") == "master" for candidate in passed):
        manifest["status"] = "masters_ready"
    elif all(candidate.get("candidate_type") == "adaptation" for candidate in passed):
        manifest["status"] = "adaptations_ready"
    else:
        manifest["status"] = "ready_for_review"
    manifest["updated_at"] = _now()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    _write_run_index(run_dir / "index.md", customer_id, manifest["candidates"])
    _write_apply_plan(run_dir, manifest, run_dir / "outputs")
    print(f"visual review passed: {len(passed)}; failed: {len(pending) - len(passed)}")
    if passed:
        _update_account_index(account_wiki_dir(customer_id) / "Index.md", manifest)
        print(
            f"[[artifact:wiki/{customer_id}/creative-runs/{run_id}/index.md|"
            "Open the full creative review]]"
        )


def create_static_replacements(args: Any, caller: Callable[..., tuple[bytes, str]] = _call_gemini) -> None:
    """Generate LOW edits, generic masters, or approved master adaptations."""
    if getattr(args, "visual_review", None):
        _record_visual_reviews(args)
        return
    customer_id = _selected_customer_id()
    if not getattr(args, "brief", None) or not getattr(args, "manifest", None):
        die("generation requires --manifest and --brief")
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
    run_id = str(getattr(args, "run_id", "") or brief.get("run_id") or uuid.uuid4().hex[:12])
    if not re.fullmatch(r"[a-zA-Z0-9_-]{6,64}", run_id):
        die("run ID must contain only letters, numbers, underscores, or hyphens")
    run_dir = wiki / "creative-runs" / run_id
    manifest_path = run_dir / "manifest.json"
    existing_manifest = _read_json(manifest_path, "creative run manifest") if manifest_path.exists() else None
    new_run = bool(getattr(args, "new_run", False))
    if existing_manifest and new_run:
        die("creative run already exists; continue the task without --new-run")
    if not existing_manifest and not new_run:
        die("creative run does not exist; start the task with --new-run")
    references = run_dir / "references"
    outputs = run_dir / "outputs"
    references.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
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
        "title": str(brief.get("title") or "").strip(),
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
                brief, assets, provider or {}, references,
                outputs, caller, model,
            )
        elif stage == "masters":
            generated = _generate_master_stage(
                brief, assets, provider or {}, references,
                outputs, caller, model,
            )
        else:
            generated = _generate_adaptation_stage(
                brief, run_manifest, assets, outputs,
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
    _write_candidate_details(run_dir, generated)
    _supersede_prior_candidates(run_manifest["candidates"], generated)
    run_manifest["candidates"].extend(generated)
    if model:
        run_manifest["models_used"] = list(
            dict.fromkeys([*run_manifest.get("models_used", []), model])
        )
    run_manifest["status"] = "visual_review_pending"
    run_manifest["updated_at"] = _now()
    manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
    _write_run_index(run_dir / "index.md", customer_id, run_manifest["candidates"])
    _write_apply_plan(run_dir, run_manifest, outputs)
    print(f"creative outputs ready: {len(generated)}")
    print(f"visual review required: {len(generated)}")
    for item in generated:
        print(f"wiki/{customer_id}/creative-runs/{run_id}/outputs/{item['name']}")
