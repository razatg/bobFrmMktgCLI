"""Deterministic media finishing for review-only creative videos."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ValueError(f"{name} is required for video creation but is not installed")
    return path


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ValueError(f"video processing failed: {detail.strip()}") from exc


def probe_video(path: Path) -> dict[str, Any]:
    """Return the normalized streams needed for deterministic validation."""
    result = _run([
        _binary("ffprobe"), "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ])
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError("ffprobe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("ffprobe returned an invalid media description")
    return payload


def validate_video(path: Path, *, duration_seconds: int, aspect_ratio: str) -> dict[str, Any]:
    """Validate one finished MP4 without making creative judgements."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("video output is missing or empty")
    payload = probe_video(path)
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise ValueError("video output has no video stream")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("video output has invalid dimensions")
    expected = {"9:16": 9 / 16, "16:9": 16 / 9}.get(aspect_ratio)
    if expected is None:
        raise ValueError(f"unsupported video aspect ratio: {aspect_ratio}")
    actual = width / height
    if abs(actual - expected) / expected > 0.02:
        raise ValueError(f"video output ratio {width}x{height} does not match {aspect_ratio}")
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("video output has no readable duration") from exc
    if abs(duration - duration_seconds) > 0.15:
        raise ValueError(f"video duration {duration:.2f}s does not match {duration_seconds}s")
    return {
        "integrity": "passed",
        "dimensions": "passed",
        "duration": "passed",
        "audio_present": any(isinstance(item, dict) and item.get("codec_type") == "audio" for item in streams),
        "width": width,
        "height": height,
        "duration_seconds": duration,
        "bytes": path.stat().st_size,
    }


def render_overlay(output: Path, *, width: int, height: int, copy: dict[str, Any], logo: Path | None = None, opaque: bool = False) -> None:
    """Render an exact approved end-card composition."""
    canvas = Image.new("RGBA", (width, height), (12, 35, 64, 255) if opaque else (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    headline = str(copy.get("headline") or "").strip()
    supporting = str(copy.get("supporting_copy") or "").strip()
    cta = str(copy.get("cta") or "").strip()
    try:
        headline_font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(30, width // 17))
        body_font = ImageFont.truetype("DejaVuSans.ttf", max(20, width // 30))
    except OSError:
        headline_font = body_font = ImageFont.load_default()
    margin = max(36, width // 20)
    y = margin
    if logo:
        with Image.open(logo) as image:
            image.load()
            mark = image.convert("RGBA")
            mark.thumbnail((width // 4, height // 8))
            canvas.alpha_composite(mark, (width - margin - mark.width, margin))
    if headline:
        draw.text((margin, y), headline, font=headline_font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 180))
        y += int(headline_font.getbbox(headline)[3] * 1.25)
    if supporting:
        draw.text((margin, y), supporting, font=body_font, fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0, 180))
    if cta:
        box = draw.textbbox((0, 0), cta, font=body_font)
        padding = max(14, width // 65)
        cta_y = height - margin - (box[3] - box[1]) - padding * 2
        cta_width = box[2] - box[0] + padding * 2
        draw.rounded_rectangle((margin, cta_y, margin + cta_width, height - margin), radius=padding, fill=(250, 204, 0, 255))
        draw.text((margin + padding, cta_y + padding), cta, font=body_font, fill=(0, 0, 0, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG")


def finish_video(source: Path, output: Path, *, duration_seconds: int, aspect_ratio: str, music: Path | None = None, overlay: Path | None = None, overlay_start_seconds: float = 0) -> dict[str, Any]:
    """Finish a provider-duration video without changing its visual duration."""
    output.parent.mkdir(parents=True, exist_ok=True)
    validate_video(source, duration_seconds=duration_seconds, aspect_ratio=aspect_ratio)
    argv = [_binary("ffmpeg"), "-y", "-i", str(source)]
    if overlay:
        argv += ["-loop", "1", "-i", str(overlay)]
    if music:
        argv += ["-i", str(music)]
    music_index = 2 if overlay and music else 1 if music else None
    filters: list[str] = []
    if overlay:
        filters.append(f"[0:v][1:v]overlay=0:0:enable='gte(t,{overlay_start_seconds:g})':shortest=1[v]")
    if music_index is not None:
        filters.append(f"[{music_index}:a]volume=0.65[music]")
        filters.append("[0:a][music]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[ducked]")
        filters.append(f"[0:a][ducked]amix=inputs=2:duration=first,apad=whole_dur={duration_seconds},atrim=duration={duration_seconds}[a]")
    if filters:
        argv += ["-filter_complex", ";".join(filters)]
    argv += ["-map", "[v]" if overlay else "0:v:0"]
    if music_index is not None:
        argv += ["-map", "[a]"]
    argv += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if music_index is not None:
        argv += ["-c:a", "aac"]
    else:
        argv += ["-map", "0:a?", "-c:a", "aac"]
    argv.append(str(output))
    _run(argv)
    return validate_video(output, duration_seconds=duration_seconds, aspect_ratio=aspect_ratio)


def adapt_portrait_to_landscape(source: Path, output: Path, *, duration_seconds: int) -> dict[str, Any]:
    """Create a reviewable landscape canvas without stretching the portrait master."""
    output.parent.mkdir(parents=True, exist_ok=True)
    validate_video(source, duration_seconds=duration_seconds, aspect_ratio="9:16")
    filter_graph = (
        "[0:v]split=2[fg][bg];"
        "[bg]scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080,boxblur=24:8[canvas];"
        "[fg]scale=607:1080:force_original_aspect_ratio=decrease[portrait];"
        "[canvas][portrait]overlay=1313:0"
    )
    _run([
        _binary("ffmpeg"), "-y", "-i", str(source), "-filter_complex", filter_graph,
        "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ])
    return validate_video(output, duration_seconds=duration_seconds, aspect_ratio="16:9")
