"""PNG/JPG to multi-size ICO.

Without a full set of sizes Windows scales a single image and the icon looks
bad on the taskbar, so we generate all standard variants.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, UnidentifiedImageError

ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)


def _square(image: Image.Image) -> Image.Image:
    """Adds transparent margins instead of stretching the image."""
    if image.width == image.height:
        return image
    side = max(image.width, image.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas


def ensure_ico(source: Path, dest: Path) -> Path:
    source = Path(source)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if source.suffix.lower() == ".ico":
        shutil.copyfile(source, dest)
        return dest

    try:
        with Image.open(source) as raw:
            image = _square(raw.convert("RGBA"))
            image.save(dest, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"failed to read image: {source.name}") from exc

    return dest
