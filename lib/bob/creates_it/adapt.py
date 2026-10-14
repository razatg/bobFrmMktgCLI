"""Pure raster normalization and conservative creative adaptations."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Final

from PIL import Image, ImageFilter, ImageOps


TARGET_FORMATS: Final[dict[str, tuple[int, int]]] = {
    "horizontal": (1200, 628),
    "square": (1200, 1200),
    "vertical": (1200, 1500),
}

MAX_GOOGLE_IMAGE_BYTES: Final = 5_000_000
# Gemini's nearest landscape generation ratio is 16:9 while Google App
# Campaign horizontal images are 1.91:1. Permit that modest crop, but reject
# materially different geometry instead of stretching it.
ASPECT_TOLERANCE: Final = 0.12


def _aspect(size: tuple[int, int]) -> float:
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    return width / height


def _save_checked(image: Image.Image, output: Path, *, source_size: tuple[int, int], method: str) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)
    with Image.open(output) as checked:
        checked.verify()
    with Image.open(output) as checked:
        final_size = checked.size
    data = output.read_bytes()
    if len(data) > MAX_GOOGLE_IMAGE_BYTES:
        output.unlink(missing_ok=True)
        raise ValueError(f"generated image exceeds the 5 MB Google Ads limit: {output.name}")
    return {
        "source_dimensions": list(source_size),
        "final_dimensions": list(final_size),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "PNG",
        "integrity": "passed",
        "dimensions": "passed",
        "adaptation_method": method,
    }


def normalize_generated_png(image_bytes: bytes, output: Path, target_size: tuple[int, int]) -> dict[str, object]:
    """Normalize a provider image without distorting its geometry."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            source_size = image.size
            delta = abs(_aspect(source_size) - _aspect(target_size)) / _aspect(target_size)
            if delta > ASPECT_TOLERANCE:
                raise ValueError(
                    f"provider returned {source_size[0]}x{source_size[1]} for "
                    f"a {target_size[0]}x{target_size[1]} target"
                )
            normalized = ImageOps.fit(
                image.convert("RGB"), target_size, method=Image.Resampling.LANCZOS
            )
    except (OSError, ValueError) as exc:
        raise ValueError(f"generated image failed integrity validation: {exc}") from exc
    return _save_checked(normalized, output, source_size=source_size, method="provider_ratio_normalized")


def adapt_master_png(source: Path, output: Path, target_size: tuple[int, int]) -> dict[str, object]:
    """Preserve the complete master over a softly extended background."""
    try:
        with Image.open(source) as image:
            image.load()
            source_size = image.size
            foreground = ImageOps.contain(
                image.convert("RGB"), target_size, method=Image.Resampling.LANCZOS
            )
            background = ImageOps.fit(
                image.convert("RGB"), target_size, method=Image.Resampling.LANCZOS
            ).filter(ImageFilter.GaussianBlur(radius=max(target_size) / 45))
            left = (target_size[0] - foreground.width) // 2
            top = (target_size[1] - foreground.height) // 2
            background.paste(foreground, (left, top))
    except OSError as exc:
        raise ValueError(f"could not adapt master image {source}: {exc}") from exc
    return _save_checked(
        background,
        output,
        source_size=source_size,
        method="contain_over_blurred_extension",
    )
