"""Tests for B's module: build_grid (image / slogan → PixelGrid).

pytest-compatible; also runnable standalone (no pytest needed):
    python3 tests/test_grid.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from ascii_art_executable.grid import DEFAULT_CHARSET, build_grid  # noqa: E402
from shared.types import PixelGrid  # noqa: E402


# ---------------------------------------------------------------- helpers --

def _circle(path: Path, size: int = 240) -> Path:
    """White filled circle on black — bright foreground, dark background."""
    im = Image.new("L", (size, size), 0)
    ImageDraw.Draw(im).ellipse([size * 0.12, size * 0.12, size * 0.88, size * 0.88], fill=255)
    im.save(path)
    return path


def _white_rect(path: Path, w: int = 240, h: int = 120) -> Path:
    im = Image.new("L", (w, h), 255)
    im.save(path)
    return path


# ------------------------------------------------------------------ tests --

def test_returns_pixelgrid_with_consistent_shape(tmp_path: Path) -> None:
    p = _circle(tmp_path / "c.png")
    g = build_grid(p, max_w=48)
    assert isinstance(g, PixelGrid)
    assert g.width <= 48 and g.height >= 1
    assert len(g.cells) == g.width * g.height
    assert len(g.render().splitlines()) == g.height


def test_width_capped_by_max_w(tmp_path: Path) -> None:
    p = _circle(tmp_path / "big.png", size=1200)
    assert build_grid(p, max_w=60).width == 60
    assert build_grid(p, max_w=20).width == 20


def test_fg_bg_marks_clear(tmp_path: Path) -> None:
    p = _circle(tmp_path / "c.png")  # white circle on black
    g = build_grid(p, max_w=48)
    cx, cy = g.width // 2, g.height // 2
    assert g.at(cx, cy).fg is True   # circle centre → 前景
    assert g.at(0, 0).fg is False    # corner → 背景
    assert 0.05 < g.density < 0.6


def test_rows_have_uniform_length(tmp_path: Path) -> None:
    g = build_grid(_circle(tmp_path / "c.png"), max_w=40)
    for y in range(g.height):
        assert len(g.row(y)) == g.width


def test_custom_charset_only_uses_given_chars(tmp_path: Path) -> None:
    g = build_grid(_circle(tmp_path / "c.png"), charset="X#", max_w=40)
    assert g.charset == "X#"
    assert set(g.render().replace("\n", "")) <= set("X# ")


def test_default_charset_is_sparse_to_dense() -> None:
    assert DEFAULT_CHARSET[0] == " " and len(DEFAULT_CHARSET) == 10


def test_invert_flips_fg_bg(tmp_path: Path) -> None:
    p = _circle(tmp_path / "c.png")
    normal = build_grid(p, max_w=40)
    inv = build_grid(p, max_w=40, invert=True)
    cx, cy = normal.width // 2, normal.height // 2
    assert normal.at(cx, cy).fg is True and inv.at(cx, cy).fg is False
    assert normal.at(0, 0).fg is False and inv.at(0, 0).fg is True


def test_slogan_text_becomes_grid(tmp_path: Path) -> None:
    g = build_grid("HELLO", max_w=60)
    assert isinstance(g, PixelGrid)
    assert g.width <= 60
    assert g.density > 0.02
    # letters occupy the vertical middle band — some fg must sit there
    mid = g.height // 2
    assert any(g.at(x, mid).fg for x in range(g.width))


def test_small_slogan_still_produces_fg() -> None:
    g = build_grid("A", max_w=20)
    assert g.density > 0.0


def test_deterministic_output(tmp_path: Path) -> None:
    p = _circle(tmp_path / "c.png")
    assert build_grid(p, max_w=40).render() == build_grid(p, max_w=40).render()


def test_cell_aspect_squashes_height(tmp_path: Path) -> None:
    # 240x120 (2:1) image at max_w=80 → 80 wide, round(80*120/240/2) = 20 tall
    g = build_grid(_white_rect(tmp_path / "r.png"), max_w=80)
    assert (g.width, g.height) == (80, 20)
    g1 = build_grid(_white_rect(tmp_path / "r2.png"), max_w=80, cell_aspect=1.0)
    assert (g1.width, g1.height) == (80, 40)


def test_image_smaller_than_max_w_is_not_upscaled(tmp_path: Path) -> None:
    g = build_grid(_white_rect(tmp_path / "tiny.png", w=30, h=10), max_w=80)
    assert g.width == 30


def test_empty_slogan_raises() -> None:
    try:
        build_grid("   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError for blank slogan")


# ------------------------------------------------------------- standalone --

if __name__ == "__main__":
    import inspect
    import tempfile
    import traceback

    tmp = Path(tempfile.mkdtemp(prefix="grid-test-"))
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failures = 0
    for fn in fns:
        try:
            takes_arg = len(inspect.signature(fn).parameters) > 0
            fn(tmp) if takes_arg else fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    raise SystemExit(1 if failures else 0)
