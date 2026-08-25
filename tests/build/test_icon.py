import pytest
from PIL import Image

from exelent.build.icon import ICO_SIZES, ensure_ico


def _png(path, size=(512, 512), color=(200, 30, 30, 255)):
    Image.new("RGBA", size, color).save(path)
    return path


def test_png_is_converted_to_ico(tmp_path):
    src = _png(tmp_path / "logo.png")
    out = ensure_ico(src, tmp_path / "out.ico")
    assert out.exists() and out.suffix == ".ico"
    with Image.open(out) as img:
        assert img.format == "ICO"


def test_ico_contains_all_required_sizes(tmp_path):
    src = _png(tmp_path / "logo.png")
    out = ensure_ico(src, tmp_path / "out.ico")
    with Image.open(out) as img:
        available = {size[0] for size in img.info["sizes"]}
    assert set(ICO_SIZES) <= available


def test_existing_ico_is_copied_unchanged(tmp_path):
    src = tmp_path / "already.ico"
    Image.new("RGBA", (64, 64), (0, 0, 255, 255)).save(src, sizes=[(64, 64)])
    original = src.read_bytes()
    out = ensure_ico(src, tmp_path / "out.ico")
    assert out.read_bytes() == original


def test_non_square_image_is_padded_not_stretched(tmp_path):
    src = _png(tmp_path / "wide.png", size=(400, 100))
    out = ensure_ico(src, tmp_path / "out.ico")
    with Image.open(out) as img:
        assert img.size[0] == img.size[1]


def test_broken_file_raises_value_error(tmp_path):
    src = tmp_path / "nie-obrazek.png"
    src.write_bytes(b"to nie jest obrazek")
    with pytest.raises(ValueError):
        ensure_ico(src, tmp_path / "out.ico")
