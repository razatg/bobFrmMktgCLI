"""Account-scoped image-to-video creation and storyboard lifecycle."""

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

from lib.bob.creates_it.generate import _call_gemini, _mime_for, _provider_config
from lib.bob.creates_it.video_media import adapt_portrait_to_landscape, finish_video, probe_video, render_overlay, validate_video
from lib.bob.platform.core import STATE_ROOT, account_wiki_dir, die, load_profile


VIDEO_REVIEW_CHECKS = (
    "storyboard_fidelity",
    "temporal_coherence",
    "brand_fidelity",
    "copy_accuracy",
    "composition",
    "audio_fit",
    "visual_integrity",
)
VIDEO_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
MAX_SOURCE_BYTES = 20_000_000
CLEAN_PANEL_PREFIX = (
    "Create one high-fidelity storyboard panel from the supplied reference. Preserve only the "
    "approved scene, people, products, and composition needed for the motion. Do not reproduce "
    "or add readable copy, logos, CTAs, offer badges, legal text, UI, or watermarks. "
)


class ProviderPolicyBlocked(Exception):
    """A provider declined a creative direction and supplied safe user feedback."""

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        self.message = message
        super().__init__(message)


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
        die("video creation requires a selected account")
    return customer_id


def _safe_state_file(value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if STATE_ROOT.resolve() not in path.parents or not path.is_file() or path.is_symlink():
        die(f"{label} must be a file inside Bob's state root")
    return path


def _catalog_section(name: str) -> dict[str, Any]:
    try:
        catalog = yaml.safe_load(Path(__file__).with_name("models.yaml").read_text())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        die(f"creative model catalog unavailable: {exc}")
    section = catalog.get(name) if isinstance(catalog, dict) else None
    if not isinstance(section, dict) or section.get("enabled") is not True:
        die(f"{name} creation is not enabled")
    allowed = section.get("allowed")
    default = section.get("default")
    if not isinstance(allowed, list) or default not in allowed or any(not isinstance(item, str) for item in allowed):
        die(f"creative model catalog has an invalid {name} allowlist")
    return section


def _model(name: str, brief: dict[str, Any]) -> str:
    section = _catalog_section(name)
    value = str(brief.get(f"{name}_model") or section["default"])
    if value not in section["allowed"]:
        die(f"{name} model is not approved in creative model catalog: {value}")
    return value


def _video_duration(brief: dict[str, Any]) -> int:
    """Return the provider-native duration; it is not a request parameter."""
    section = _catalog_section("video")
    duration = section.get("native_duration_seconds")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        die("creative model catalog has no valid fixed video duration")
    requested = brief.get("duration_seconds")
    if requested is not None and requested != duration:
        die(f"the selected video model produces a fixed {duration}-second master")
    return duration


def _safe_run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", value):
        die("run ID must contain only letters, numbers, underscores, or hyphens")
    return value


def _storyboard_sections(brief: dict[str, Any]) -> list[dict[str, str]]:
    sections = brief.get("storyboard")
    if not isinstance(sections, list) or not sections:
        die("video brief requires one or more narrative storyboard sections")
    normalized: list[dict[str, str]] = []
    for item in sections:
        if not isinstance(item, dict):
            die("each storyboard section must be an object")
        title = str(item.get("title") or "").strip()
        action = str(item.get("action") or "").strip()
        risk = str(item.get("risk") or "standard").strip().lower()
        if not title or not action or risk not in {"standard", "high"}:
            die("each storyboard section requires title, action, and standard/high risk")
        normalized.append({"title": title, "action": action, "risk": risk})
    return normalized


def _storyboard_panels(brief: dict[str, Any]) -> list[dict[str, str]]:
    raw = brief.get("panels")
    if not isinstance(raw, list) or len(raw) < 2:
        die("video storyboard requires at least two pictorial panels")
    panels: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            die("each storyboard panel must be an object")
        title = str(item.get("title") or "").strip()
        visual = str(item.get("visual") or "").strip()
        camera = str(item.get("camera") or "").strip()
        dialogue = str(item.get("dialogue") or "").strip()
        speaker = str(item.get("speaker") or "").strip()
        voice = str(item.get("voice") or "").strip()
        kind = str(item.get("kind") or "scene").strip()
        if not title or not visual or not camera or kind not in {"scene", "end_card"}:
            die("each storyboard panel requires title, visual, camera, and scene/end_card kind")
        if bool(dialogue) != bool(speaker) or (dialogue and not voice):
            die("storyboard panel dialogue requires its named speaker and voice")
        panels.append({"title": title, "visual": visual, "camera": camera, "dialogue": dialogue, "speaker": speaker, "voice": voice, "kind": kind})
    if panels[-1]["kind"] != "end_card" or sum(item["kind"] == "scene" for item in panels) < 2:
        die("storyboard requires two scene panels followed by one end-card panel")
    return panels


def _storyboard_hash(sections: list[dict[str, str]], brief: dict[str, Any]) -> str:
    stable = {
        "storyboard": sections,
        "copy": brief.get("copy") or {},
        "sfx": brief.get("sfx") or [],
        "music": brief.get("music") or {},
        "panels": brief.get("panels") or [],
        "end_card": brief.get("end_card") or {},
        "duration_seconds": brief.get("duration_seconds"),
        "aspect_ratio": brief.get("aspect_ratio"),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _panel_fingerprint(source: Path, *, image_model: str, panels: list[dict[str, str]], ratio: str) -> str:
    return hashlib.sha256(json.dumps({
        "source_sha256": _file_digest(source),
        "image_model": image_model,
        "panels": panels,
        "aspect_ratio": ratio,
    }, sort_keys=True).encode()).hexdigest()


def _master_fingerprint(brief: dict[str, Any], source: Path, *, video_model: str, image_model: str, duration: int, ratio: str) -> str:
    """Identify the exact approved provider request without retaining secrets or paths."""
    stable = {
        "source_sha256": _file_digest(source),
        "panel_fingerprint": brief.get("panel_fingerprint"),
        "video_prompt": brief.get("video_prompt"),
        "video_model": video_model,
        "image_model": image_model,
        "duration_seconds": duration,
        "aspect_ratio": ratio,
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def _native_video_prompt(base: str, panels: list[dict[str, str]]) -> str:
    """Attach approved cast/audio intent to the video request, not to a separate TTS route."""
    dialogue = [
        f"{panel['speaker']} ({panel['voice']}) says exactly: \"{panel['dialogue']}\""
        for panel in panels if panel["kind"] == "scene" and panel.get("dialogue")
    ]
    rules = [
        "[# Sources <FIRST_FRAME>@Image1 <LAST_FRAME>@Image2]",
        "Use Image1 as the opening composition and Image2 as the closing composition.",
        "Create one full-frame continuous progression between them; no collage, split-screen, storyboard layout, text, logo, CTA, offer, or end card.",
        "Generate only native scene audio and the approved spoken lines. Do not add narration, music, or another speaker.",
    ]
    if dialogue:
        rules.append("Dialogue casting: " + " ".join(dialogue))
    return "\n\n".join([base, *rules])


def _music_prompt(music: dict[str, Any]) -> str:
    direction = str(music.get("direction") or "").strip()
    lyrics = str(music.get("lyrics") or "").strip()
    if not direction:
        return ""
    return f"{direction}\n\nLyrics:\n{lyrics}" if lyrics else direction


def _music_fingerprint(prompt: str, model: str | None) -> str | None:
    if not prompt or not model:
        return None
    return hashlib.sha256(json.dumps({"prompt": prompt, "model": model}, sort_keys=True).encode()).hexdigest()


def _end_card_start(brief: dict[str, Any], duration: int) -> float:
    value = (brief.get("end_card") or {}).get("start_seconds", max(0, duration - 1.5)) if isinstance(brief.get("end_card") or {}, dict) else None
    try:
        start = float(value)
    except (TypeError, ValueError):
        die("end-card start must be a number")
    if start < 0 or start >= duration:
        die("end-card start must be within the video duration")
    return start


def _checkpoint_file(run_dir: Path, checkpoint: dict[str, Any], key: str) -> Path | None:
    value = checkpoint.get(key)
    if not isinstance(value, str):
        return None
    path = (run_dir / value).resolve()
    root = run_dir.resolve()
    return path if root in path.parents and path.is_file() and not path.is_symlink() and path.stat().st_size else None


def _save_master_checkpoint(manifest_path: Path, manifest: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    manifest["master_checkpoint"] = checkpoint
    manifest["status"] = "master_checkpointed"
    manifest["updated_at"] = _now()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def _write_index(path: Path, manifest: dict[str, Any]) -> None:
    brief = manifest["storyboard"]
    lines = [
        "<!-- bob-video-storyboard -->",
        f"# Video storyboard · {manifest['customer_id']}",
        "",
        f"Status: **{manifest['status'].replace('_', ' ')}**",
        "",
        "This is review-only. Editing this artifact changes the next draft, not an already approved generation.",
        "",
        "## Narrative sections",
        "",
    ]
    for section in brief["sections"]:
        risk = " · isolated controlled clip" if section["risk"] == "high" else ""
        lines += [f"### {section['title']}{risk}", section["action"], ""]
    panels = brief.get("panels") if isinstance(brief.get("panels"), list) else []
    panel_files = brief.get("panel_files") if isinstance(brief.get("panel_files"), list) else []
    if panels:
        lines += ["## Pictorial storyboard", ""]
        for index, panel in enumerate(panels):
            lines += [f"### {panel['title']}"]
            if index < len(panel_files):
                lines.append(f"![{panel['title']}]({panel_files[index]})")
            lines += [f"- Visual: {panel['visual']}", f"- Camera: {panel['camera']}"]
            if panel.get("dialogue"):
                lines.append(f"- Native dialogue — {panel['speaker']} ({panel['voice']}): {panel['dialogue']}")
            lines.append("")
    lines += ["## Exact copy", ""]
    copy = brief.get("copy") if isinstance(brief.get("copy"), dict) else {}
    if copy:
        for key, value in copy.items():
            lines.append(f"- **{str(key).replace('_', ' ').title()}:** {value}")
    else:
        lines.append("- No text overlays specified.")
    lines += ["", "## Sound", ""]
    sfx = brief.get("sfx") if isinstance(brief.get("sfx"), list) else []
    lines.extend([f"- SFX: {item}" for item in sfx] or ["- SFX: none specified."])
    music = brief.get("music") if isinstance(brief.get("music"), dict) else {}
    lines += [f"- Music: {music.get('direction', 'none specified')}"]
    if music.get("lyrics"):
        lines.append(f"- Lyrics: {music['lyrics']}")
    lines.append("- Dialogue: generated natively by Omni from the approved pictorial panels.")
    lines += [""]
    end_card = brief.get("end_card") if isinstance(brief.get("end_card"), dict) else {}
    lines += ["## Deterministic end card", "", f"- Final copy, logo, and CTA are added after motion generation from {end_card.get('start_seconds', 'the final 1–2 seconds') } seconds.", ""]
    lines += ["## Output plan", "", f"- {brief['duration_seconds']} second {brief['aspect_ratio']} master", "- 16:9 adaptation only after master approval", ""]
    policy = manifest.get("provider_policy") if isinstance(manifest.get("provider_policy"), dict) else {}
    if policy:
        stage = str(policy.get("stage") or "generation")
        message = str(policy.get("message") or "The provider rejected this direction.")
        lines += ["## Direction revision needed", "", f"- The provider rejected the {stage} direction: {message}", "- Edit the direction, then explicitly approve the revised storyboard to retry only the blocked stage.", ""]
    if manifest.get("storyboard_hash"):
        lines += ["## Approved snapshot", "", f"- Revision: {manifest.get('storyboard_revision', 1)}", f"- Snapshot: `{manifest['storyboard_hash'][:12]}`", ""]
    candidates = manifest.get("candidates") if isinstance(manifest.get("candidates"), list) else []
    if candidates:
        lines += ["## Review outputs", ""]
        for candidate in candidates:
            if candidate.get("review_status") != "passed":
                continue
            lines += [f"### {candidate['name']}", f"[Watch {candidate['name']}](outputs/{candidate['name']})", ""]
            if candidate.get("detail_page"):
                lines.append(f"[View generation details]({candidate['detail_page']})")
                lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n")


def _update_account_index(path: Path, manifest: dict[str, Any]) -> None:
    text = path.read_text() if path.exists() else "# Bob — Wiki Index\n"
    heading = "## Action Items"
    if heading not in text:
        text = text.rstrip() + f"\n\n{heading}\n"
    marker = f"<!-- creative-run:{manifest['run_id']} -->"
    title = re.sub(r"[\[\]\r\n]+", " ", str(manifest.get("title") or "Video storyboard")).strip()
    date = str(manifest["created_at"])[:10]
    row = f"- [{title} — {date}](creative-runs/{manifest['run_id']}/index.md) — video storyboard; review-only"
    text = re.sub(rf"(?m)^{re.escape(marker)}\n- .*\n?", "", text)
    match = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
    insert = match.end() if match else len(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((text[:insert] + f"\n\n{marker}\n{row}" + text[insert:]).rstrip() + "\n")


def _extract_video(payload: Any) -> tuple[bytes, str]:
    candidates: list[tuple[str, str]] = []
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            mime = str(value.get("mime_type") or value.get("mimeType") or "")
            data = value.get("data") or value.get("inline_data")
            if mime.startswith("video/") and isinstance(data, str):
                candidates.append((data, mime))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(payload)
    if not candidates:
        die("Gemini returned no inline video")
    try:
        value = base64.b64decode(candidates[0][0], validate=True)
    except ValueError as exc:
        die(f"Gemini returned invalid video data: {exc}")
    if not value or len(value) > 200_000_000:
        die("Gemini returned an empty or oversized video")
    return value, candidates[0][1]


def _extract_audio(payload: Any, *, label: str) -> tuple[bytes, str]:
    candidates: list[tuple[str, str]] = []
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            mime = str(value.get("mime_type") or value.get("mimeType") or "")
            kind = str(value.get("type") or "")
            data = value.get("data") or value.get("inline_data")
            if (mime.startswith("audio/") or kind == "audio") and isinstance(data, str):
                candidates.append((data, mime or "audio/mpeg"))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(payload)
    if not candidates:
        die(f"{label} returned no inline audio")
    try:
        return base64.b64decode(candidates[0][0], validate=True), candidates[0][1]
    except ValueError as exc:
        die(f"{label} returned invalid audio data: {exc}")


def _call_omni(api_key: str, model: str, prompt: str, source: Path, aspect_ratio: str, last_frame: Path | None = None) -> tuple[bytes, str]:
    source_bytes = source.read_bytes()
    if len(source_bytes) > MAX_SOURCE_BYTES or (last_frame and last_frame.stat().st_size > MAX_SOURCE_BYTES):
        die("video source image exceeds 20 MB")
    inputs = [{"type": "image", "mime_type": _mime_for(source), "data": base64.b64encode(source_bytes).decode()}]
    if last_frame:
        inputs.append({"type": "image", "mime_type": _mime_for(last_frame), "data": base64.b64encode(last_frame.read_bytes()).decode()})
    inputs.append({"type": "text", "text": prompt})
    body = json.dumps({
        "model": model,
        "input": inputs,
        "response_format": {"type": "video", "aspect_ratio": aspect_ratio},
    }).encode()
    request = Request(VIDEO_URL, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, method="POST")
    try:
        with urlopen(request, timeout=360) as response:
            return _extract_video(json.loads(response.read().decode()))
    except HTTPError as exc:
        detail = exc.read(2048).decode(errors="replace")
        try:
            error = json.loads(detail).get("error", {})
        except ValueError:
            error = {}
        if error.get("code") == "content_blocked":
            raise ProviderPolicyBlocked("video", str(error.get("message") or "The provider rejected this video direction."))
        die(f"Gemini video generation failed ({exc.code}): {detail}")
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        die(f"Gemini video generation failed: {exc}")


def _call_lyria(api_key: str, model: str, prompt: str) -> tuple[bytes, str]:
    body = json.dumps({
        "model": model,
        "input": [{"type": "text", "text": prompt}],
    }).encode()
    request = Request(VIDEO_URL, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, method="POST")
    try:
        with urlopen(request, timeout=180) as response:
            return _extract_audio(json.loads(response.read().decode()), label="Lyria")
    except HTTPError as exc:
        detail = exc.read(2048).decode(errors="replace")
        try:
            error = json.loads(detail).get("error", {})
        except ValueError:
            error = {}
        if error.get("code") == "content_blocked":
            raise ProviderPolicyBlocked("music", str(error.get("message") or "The provider rejected this music direction."))
        die(f"Lyria music generation failed ({exc.code}): {detail}")
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        die(f"Lyria music generation failed: {exc}")


def _next_name(outputs: Path, prefix: str) -> str:
    versions = [int(match.group(1)) for path in outputs.glob(f"{prefix}-v*.mp4") if (match := re.search(r"-v(\d+)\.mp4$", path.name))]
    return f"{prefix}-v{max(versions, default=0) + 1}.mp4"


def _candidate_detail(run_dir: Path, candidate: dict[str, Any]) -> None:
    details = run_dir / "details"
    details.mkdir(exist_ok=True)
    path = details / f"{Path(candidate['name']).stem}.md"
    production = {"method": candidate["production_method"], "model": candidate.get("model"), "prompt_used": bool(candidate.get("request"))}
    path.write_text(
        f"# {candidate['name']}\n\n## Production method\n\n```json\n{json.dumps(production, indent=2)}\n```\n\n"
        + (f"## Generation request\n\n```json\n{json.dumps(candidate['request'], indent=2)}\n```\n" if candidate.get("request") else "## Generation request\n\nNo AI prompt was used; this is a deterministic FFmpeg adaptation.\n")
    )
    candidate["detail_page"] = str(path.relative_to(run_dir))


def _pause_for_policy(
    manifest_path: Path,
    manifest: dict[str, Any],
    checkpoint: dict[str, Any],
    run_dir: Path,
    blocked: ProviderPolicyBlocked,
    retained: str,
) -> None:
    """Persist a provider-policy pause without discarding completed paid work."""
    manifest.update({
        "status": f"{blocked.stage}_direction_needed",
        "updated_at": _now(),
        "master_checkpoint": checkpoint,
        "provider_policy": {
            "stage": blocked.stage,
            "message": blocked.message,
            "retained": retained,
        },
    })
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    _write_index(run_dir / "index.md", manifest)
    die(
        f"provider policy rejected the {blocked.stage} direction: {blocked.message} "
        f"Checkpointed work retained: {retained}. Ask the user for a different {blocked.stage} direction and wait for approval before retrying."
    )


def _stage_storyboard(customer_id: str, run_id: str, brief: dict[str, Any], image_caller: Callable[..., tuple[bytes, str]]) -> None:
    sections = _storyboard_sections(brief)
    panels = _storyboard_panels(brief)
    duration = _video_duration(brief)
    ratio = str(brief.get("aspect_ratio") or "")
    if ratio != "9:16":
        die("the initial video route supports a 9:16 master")
    if brief.get("preview_confirmed") is not True:
        die("pictorial storyboard previews require preview_confirmed: true after agreeing the direction")
    source = _safe_state_file(str(brief.get("source_image") or ""), "storyboard source image")
    logo_path = _safe_state_file(str(brief["logo_image"]), "approved logo") if brief.get("logo_image") else None
    image_model = str(brief.get("image_model") or "gemini-3.1-flash-image")
    preview_mode = str(brief.get("storyboard_fidelity") or "high_fidelity")
    if preview_mode not in {"low_fidelity", "high_fidelity"}:
        die("storyboard fidelity must be low_fidelity or high_fidelity")
    run_dir = account_wiki_dir(customer_id) / "creative-runs" / run_id
    manifest_path = run_dir / "manifest.json"
    existing = _read_json(manifest_path, "video run manifest") if manifest_path.exists() else {}
    revision = int(existing.get("storyboard_revision") or 0) + 1
    run_dir.mkdir(parents=True, exist_ok=True)
    references = run_dir / "references"; references.mkdir(exist_ok=True)
    panel_files: list[str] = []
    for index, panel in enumerate(panels, start=1):
        path = references / f"storyboard-panel-{index}.png"
        if panel["kind"] == "end_card":
            render_overlay(path, width=720, height=1280, copy=brief.get("copy") or {}, logo=logo_path, opaque=True)
        elif preview_mode == "high_fidelity":
            prompt = CLEAN_PANEL_PREFIX + panel["visual"] + " Camera: " + panel["camera"]
            image_bytes, _ = image_caller(_provider_config()["api_key"], image_model, prompt, source, ratio)
            path.write_bytes(image_bytes)
        else:
            shutil.copyfile(source, path)
        panel_files.append(str(path.relative_to(run_dir)))
    manifest = {
        "run_id": run_id, "customer_id": customer_id, "title": str(brief.get("title") or "Video storyboard"),
        "created_at": existing.get("created_at") or _now(), "updated_at": _now(), "status": "storyboard_ready",
        "storyboard_revision": revision,
        "storyboard": {"sections": sections, "panels": panels, "panel_files": panel_files, "copy": brief.get("copy") or {}, "sfx": brief.get("sfx") or [], "music": brief.get("music") or {}, "end_card": brief.get("end_card") or {}, "duration_seconds": duration, "aspect_ratio": ratio, "video_model": _model("video", brief)},
        "candidates": existing.get("candidates") or [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    _write_index(run_dir / "index.md", manifest)
    _update_account_index(account_wiki_dir(customer_id) / "Index.md", manifest)
    print(f"[[artifact:wiki/{customer_id}/creative-runs/{run_id}/index.md|Open the video storyboard]]")


def _stage_master(customer_id: str, run_id: str, brief: dict[str, Any], caller: Callable[..., tuple[bytes, str]], music_caller: Callable[..., tuple[bytes, str]]) -> None:
    run_dir = account_wiki_dir(customer_id) / "creative-runs" / run_id
    manifest_path = run_dir / "manifest.json"
    manifest = _read_json(manifest_path, "video run manifest")
    if manifest.get("customer_id") != customer_id or manifest.get("status") not in {
        "storyboard_ready", "video_review_failed", "master_checkpointed",
        "video_direction_needed", "music_direction_needed",
    }:
        die("video master requires the selected account's editable storyboard draft")
    if brief.get("confirmed") is not True:
        die("video master requires confirmed: true after storyboard approval")
    sections = _storyboard_sections(brief)
    expected_hash = _storyboard_hash(sections, brief)
    duration, ratio = _video_duration(brief), str(brief.get("aspect_ratio") or "")
    if ratio != "9:16":
        die("the initial video route supports a 9:16 master")
    video_model = _model("video", brief)
    music = brief.get("music") if isinstance(brief.get("music"), dict) else {}
    music_request = _music_prompt(music)
    music_model = _model("music", brief) if music_request else None
    logo_path = _safe_state_file(str(brief["logo_image"]), "approved logo") if brief.get("logo_image") else None
    if brief.get("require_logo") is True and logo_path is None:
        die("video master requires an approved logo_image")
    base_prompt = str(brief.get("video_prompt") or "").strip()
    if not base_prompt:
        die("video master requires a confirmed video_prompt")
    storyboard = manifest.get("storyboard") if isinstance(manifest.get("storyboard"), dict) else {}
    panels = storyboard.get("panels") if isinstance(storyboard.get("panels"), list) else []
    panel_files = storyboard.get("panel_files") if isinstance(storyboard.get("panel_files"), list) else []
    scene_files = [run_dir / panel_files[index] for index, panel in enumerate(panels) if panel.get("kind") == "scene" and index < len(panel_files)]
    if len(scene_files) < 2 or any(not path.is_file() for path in scene_files):
        die("video master requires an approved pictorial storyboard with two scene panels")
    panel_fingerprint = hashlib.sha256(json.dumps({
        "panels": panels, "files": [_file_digest(path) for path in scene_files],
    }, sort_keys=True).encode()).hexdigest()
    prompt = _native_video_prompt(base_prompt, panels)
    fingerprint = _master_fingerprint(
        {**brief, "panel_fingerprint": panel_fingerprint},
        _safe_state_file(str(brief.get("source_image") or ""), "video source image"),
        video_model=video_model, image_model="storyboard-panels", duration=duration, ratio=ratio,
    )
    outputs = run_dir / "outputs"; references = run_dir / "references"; briefs = run_dir / "briefs"
    outputs.mkdir(exist_ok=True); references.mkdir(exist_ok=True); briefs.mkdir(exist_ok=True)
    existing_checkpoint = manifest.get("master_checkpoint") if isinstance(manifest.get("master_checkpoint"), dict) else {}
    checkpoint = existing_checkpoint if existing_checkpoint.get("fingerprint") == fingerprint else {
        "fingerprint": fingerprint,
        "approved_brief": f"briefs/master-{fingerprint[:12]}.json",
        "raw_video": f"references/generated-video-{fingerprint[:12]}.mp4",
        "music": None,
        "panel_fingerprint": panel_fingerprint,
    }
    requested_music_fingerprint = _music_fingerprint(music_request, music_model)
    if checkpoint.get("music_fingerprint") != requested_music_fingerprint:
        checkpoint["music"] = None
        checkpoint["music_fingerprint"] = requested_music_fingerprint
    snapshot = run_dir / checkpoint["approved_brief"]
    if not snapshot.exists():
        snapshot.write_text(json.dumps(brief, indent=2) + "\n")
    raw = _checkpoint_file(run_dir, checkpoint, "raw_video")
    if raw is not None:
        try:
            validate_video(raw, duration_seconds=duration, aspect_ratio=ratio)
        except ValueError:
            raw = None
    if raw is None:
        try:
            video_bytes, mime = caller(_provider_config()["api_key"], video_model, prompt, scene_files[0], ratio, scene_files[-1])
        except ProviderPolicyBlocked as blocked:
            _pause_for_policy(manifest_path, manifest, checkpoint, run_dir, blocked, "approved storyboard panels")
        if mime != "video/mp4":
            die(f"unsupported generated video MIME type: {mime}")
        raw = run_dir / checkpoint["raw_video"]
        raw.write_bytes(video_bytes)
        _save_master_checkpoint(manifest_path, manifest, checkpoint)
    music_path = _checkpoint_file(run_dir, checkpoint, "music") if music_request else None
    if music_request and music_path is None:
        try:
            music_bytes, music_mime = music_caller(_provider_config()["api_key"], str(music_model), music_request)
        except ProviderPolicyBlocked as blocked:
            _pause_for_policy(manifest_path, manifest, checkpoint, run_dir, blocked, "approved storyboard panels and raw video")
        suffix = ".wav" if music_mime in {"audio/wav", "audio/x-wav"} else ".mp3"
        music_path = references / f"music-{fingerprint[:12]}{suffix}"; music_path.write_bytes(music_bytes)
        checkpoint["music"] = str(music_path.relative_to(run_dir))
        _save_master_checkpoint(manifest_path, manifest, checkpoint)
    copy = brief.get("copy") if isinstance(brief.get("copy"), dict) else {}
    overlay_path: Path | None = None
    end_card_start = _end_card_start(brief, duration)
    if copy or logo_path:
        probe = probe_video(raw)
        streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
        stream = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
        if not isinstance(stream, dict) or not int(stream.get("width") or 0) or not int(stream.get("height") or 0):
            die("generated video has no readable dimensions for deterministic overlays")
        overlay_path = references / "master-overlay.png"
        render_overlay(overlay_path, width=int(stream["width"]), height=int(stream["height"]), copy=copy, logo=logo_path, opaque=True)
    name = _next_name(outputs, "master-9x16")
    qa = finish_video(raw, outputs / name, duration_seconds=duration, aspect_ratio=ratio, music=music_path, overlay=overlay_path, overlay_start_seconds=end_card_start)
    candidate = {"name": name, "candidate_type": "video_master", "production_method": "ai_generation", "model": video_model, "review_status": "pending", "qa": qa, "request": {"storyboard_panels": panels, "video_prompt": prompt, "native_dialogue": True, "model": video_model, "music_model": music_model, "music_prompt": music_request or None, "deterministic_overlay": {"copy": copy, "logo_supplied": bool(logo_path), "start_seconds": end_card_start}, "duration_seconds": duration, "aspect_ratio": ratio}}
    _candidate_detail(run_dir, candidate)
    manifest.update({
        "status": "video_review_pending", "updated_at": _now(), "storyboard_hash": expected_hash,
        "storyboard_revision": int(manifest.get("storyboard_revision") or 1),
        "approved_brief": checkpoint["approved_brief"], "candidates": [*manifest.get("candidates", []), candidate],
        "storyboard": {**storyboard, "sections": sections, "copy": brief.get("copy") or {}, "sfx": brief.get("sfx") or [], "music": brief.get("music") or {}, "end_card": {"start_seconds": end_card_start}, "duration_seconds": duration, "aspect_ratio": ratio, "video_model": video_model},
    })
    manifest.pop("provider_policy", None)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    _write_index(run_dir / "index.md", manifest)
    print(f"video output ready: {name}")


def _record_visual_review(customer_id: str, run_id: str, path_text: str) -> None:
    review_path = _safe_state_file(path_text, "video visual review")
    payload = _read_json(review_path, "video visual review")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        die("video visual review must contain a non-empty reviews list")
    run_dir = account_wiki_dir(customer_id) / "creative-runs" / run_id
    manifest_path = run_dir / "manifest.json"; manifest = _read_json(manifest_path, "video run manifest")
    pending = {str(item.get("name")): item for item in manifest.get("candidates", []) if item.get("review_status") == "pending"}
    submitted: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict):
            die("video visual review items must be objects")
        name = str(review.get("name") or "")
        checks = review.get("checks")
        issues = review.get("issues") or []
        if name not in pending or name in submitted or not isinstance(checks, dict) or set(checks) != set(VIDEO_REVIEW_CHECKS):
            die("video visual review must cover each pending output once with every required check")
        if any(value not in {"passed", "failed"} for value in checks.values()) or not isinstance(issues, list):
            die("video visual review checks must be passed/failed and issues must be a list")
        failed = "failed" in checks.values()
        if failed and not issues:
            die("a failed video visual review needs an issue")
        if not failed and issues:
            die("a passed video visual review cannot have unresolved issues")
        pending[name]["review_status"] = "failed" if failed else "passed"
        pending[name]["visual_review"] = {"checks": checks, "issues": issues, "reviewed_at": _now()}
        submitted.add(name)
    if submitted != set(pending):
        die("video visual review must cover every pending output")
    passed = [item for item in manifest["candidates"] if item.get("review_status") == "passed"]
    if not passed:
        manifest["status"] = "video_review_failed"
    elif all(item.get("candidate_type") == "video_master" for item in passed):
        manifest["status"] = "video_master_ready"
    else:
        manifest["status"] = "video_adaptations_ready"
    manifest["updated_at"] = _now(); manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    _write_index(run_dir / "index.md", manifest)
    if passed:
        print(f"[[artifact:wiki/{customer_id}/creative-runs/{run_id}/index.md|Open the video review]]")


def _stage_adaptation(customer_id: str, run_id: str, brief: dict[str, Any]) -> None:
    run_dir = account_wiki_dir(customer_id) / "creative-runs" / run_id
    manifest_path = run_dir / "manifest.json"; manifest = _read_json(manifest_path, "video run manifest")
    if brief.get("confirmed") is not True or manifest.get("status") != "video_master_ready":
        die("video adaptation requires an explicitly approved, visually reviewed master")
    master_name = str(brief.get("master_name") or "")
    master = next((item for item in manifest["candidates"] if item.get("name") == master_name and item.get("candidate_type") == "video_master" and item.get("review_status") == "passed"), None)
    if not master:
        die("video adaptation requires a passed master_name from this run")
    output = run_dir / "outputs" / _next_name(run_dir / "outputs", "adapt-16x9")
    qa = adapt_portrait_to_landscape(run_dir / "outputs" / master_name, output, duration_seconds=int(manifest["storyboard"]["duration_seconds"]))
    candidate = {"name": output.name, "candidate_type": "video_adaptation", "production_method": "ffmpeg_adaptation", "model": None, "review_status": "pending", "qa": qa, "request": None}
    _candidate_detail(run_dir, candidate)
    manifest["candidates"].append(candidate); manifest["status"] = "video_review_pending"; manifest["updated_at"] = _now()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n"); _write_index(run_dir / "index.md", manifest)
    print(f"video adaptation ready: {candidate['name']}")


def create_video(args: Any, caller: Callable[..., tuple[bytes, str]] = _call_omni, image_caller: Callable[..., tuple[bytes, str]] = _call_gemini, music_caller: Callable[..., tuple[bytes, str]] = _call_lyria) -> None:
    """Create or update one review-only image-to-video run."""
    customer_id = _selected_customer_id()
    if getattr(args, "visual_review", None):
        _record_visual_review(customer_id, _safe_run_id(str(args.run_id or "")), str(args.visual_review))
        return
    if not getattr(args, "brief", None):
        die("video-create requires a private storyboard brief")
    brief_path = _safe_state_file(str(args.brief), "video brief")
    brief = _read_json(brief_path, "video brief")
    if brief.get("customer_id") and re.sub(r"\D", "", str(brief["customer_id"])) != customer_id:
        die("video brief belongs to a different account")
    run_id = _safe_run_id(str(getattr(args, "run_id", "") or brief.get("run_id") or uuid.uuid4().hex[:12]))
    stage = str(brief.get("stage") or "storyboard")
    if stage == "storyboard":
        _stage_storyboard(customer_id, run_id, brief, image_caller)
        return
    if stage == "master":
        _stage_master(customer_id, run_id, brief, caller, music_caller)
        return
    if stage == "adaptation":
        _stage_adaptation(customer_id, run_id, brief)
        return
    die("video brief stage must be storyboard, master, or adaptation")
