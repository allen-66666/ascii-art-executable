"""Tests for injecting B's ``build_mask`` into C's ``shape_code`` (mask_adapter)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from codeart import FontMetrics, Mask, ShapeError, ShapeSpec, SizeRequest, build_mask  # noqa: E402
from shared.types import PixelGrid  # noqa: E402

from ascii_art_executable.backends import shape_code  # noqa: E402
from ascii_art_executable.backends.c_backend import CBackend  # noqa: E402
from ascii_art_executable.backends.c_tokenfill import LayoutLimitError  # noqa: E402
from ascii_art_executable.backends.mask_adapter import (  # noqa: E402
    is_shape_name,
    make_mask_builder,
    mask_to_pixelgrid,
    natural_width,
    parse_shape,
    shape_code_for_shape,
)

CODE = """#include <stdio.h>
int main(void) {
    int total = 0;
    for (int i = 1; i <= 6; i++) {
        total += i * i;
        printf("row %d -> %d\\n", i, i * i);
    }
    printf("total = %d\\n", total);
    return 0;
}
"""


def _fake_mask(width=64, height=32):
    """A known 64x32 mask: a filled rectangle with a 4x4 hole in the middle."""
    allowed = tuple(
        tuple((4 <= x < width - 4 and 2 <= y < height - 2)
              and not (30 <= x < 34 and 14 <= y < 18) for x in range(width))
        for y in range(height))
    return Mask(kind="fake", width=width, height=height, allowed=allowed,
                spans=tuple(() for _ in range(height)), scale=height / 2,
                font_metrics=FontMetrics())


# ------------------------------------------------------------- converter --

def test_mask_to_pixelgrid_preserves_cells_exactly():
    mask = _fake_mask()
    grid = mask_to_pixelgrid(mask, " .:O")
    assert isinstance(grid, PixelGrid)
    assert (grid.width, grid.height) == (64, 32)
    for y in range(32):
        for x in range(64):
            cell = grid.at(x, y)
            assert cell.fg == mask.allowed[y][x]
            assert cell.ch == ("O" if cell.fg else " ")
            assert cell.level == (3 if cell.fg else 0)


@pytest.mark.parametrize("kind,size", [("circle", (64, 32)), ("cat", (64, 32)),
                                       ("code", (178, 32))])
def test_b_sizes_for_size_request_32(kind, size):
    builder = make_mask_builder(build_mask, SizeRequest(32))
    grid = builder(kind)
    assert (grid.width, grid.height) == size
    assert natural_width(kind, SizeRequest(32)) == size[0]


def test_parse_shape_names():
    assert parse_shape("CODE") == ShapeSpec("code", text="CODE")
    assert parse_shape(" Cat ").kind == "cat"
    assert is_shape_name("circle") and not is_shape_name("demo/cat.png")
    with pytest.raises(ShapeError):
        parse_shape("dog")


# --------------------------------------------------------- injection path --

def test_fake_build_mask_injected_into_shape_code(tmp_path):
    calls = []

    def fake_build_mask(spec, req, fm):
        calls.append((spec, req, fm))
        return _fake_mask()

    builder = make_mask_builder(fake_build_mask, SizeRequest(32))
    sk, grid = shape_code(CODE, "cat", str(tmp_path / "out.c"), mode="v1a",
                          max_w=64, grid_builder=builder)
    assert isinstance(grid, PixelGrid)
    assert (grid.width, grid.height) == (64, 32)
    assert calls and calls[0][0] == ShapeSpec("cat") and calls[0][1] == SizeRequest(32)
    assert (tmp_path / "out.c").is_file()


def test_retry_grows_mask_height(tmp_path):
    """A failed attempt must lead to a bigger mask, not the same grid again."""
    seen = []

    class FlakyBackend(CBackend):
        def fill(self, grid, sk, mode="auto", plan=None):
            seen.append((grid.width, grid.height))
            if len(seen) == 1:
                raise LayoutLimitError("too small")
            return super().fill(grid, sk, mode=mode)

    builder = make_mask_builder(build_mask, SizeRequest(32))
    sk, grid = shape_code(CODE, "cat", str(tmp_path / "out.c"), mode="v1a",
                          max_w=64, grid_builder=builder, backend=FlakyBackend())
    assert seen[0] == (64, 32)
    assert seen[1][1] > 32 and seen[1][0] <= 80
    assert len(sk.attempt_history) == 1


def test_image_path_unchanged(tmp_path):
    """The default grid_builder is still B's image build_grid."""
    sk, grid = shape_code(CODE, str(ROOT / "demo" / "cat.png"),
                          str(tmp_path / "img.c"), mode="v1a", max_w=60)
    assert grid.width <= 60 and grid.source.endswith("cat.png")


# ------------------------------------------------------------ end to end --

@pytest.mark.parametrize("shape", ["circle", "cat", "CODE"])
@pytest.mark.parametrize("mode", ["v2", "v1a"])
def test_real_shapes_verify(tmp_path, shape, mode):
    out = tmp_path / f"{shape}_{mode}.c"
    sk, grid = shape_code_for_shape(CODE, shape, str(out), mode=mode)
    report = CBackend().verify(str(out), grid, start_line=sk.start_line,
                               start_column=sk.start_column)
    assert report["shape"].precision == 1.0
    if mode == "v1a":
        # v1a keeps every target cell; v2 may leave a few lexically required
        # spaces inside foreground (same as the image path), so only precision.
        assert report["shape"].passed and report["shape"].missing_pixels == 0
    if report["compile_ok"] is None:
        pytest.skip("no C compiler available: shape check only")
    assert report["compile_ok"] and report["run_ok"]

    ci = CBackend.detect_compiler()
    exe = tmp_path / "orig"
    src = tmp_path / "orig.c"
    src.write_text(CODE, encoding="utf-8")
    # Match the engine's build flags: the old bundled gcc defaults to gnu90 and
    # rejects C99 for-loop declarations without an explicit standard.
    subprocess.run([ci.path, "-std=c11", str(src), "-o", str(exe)], check=True)
    expected = subprocess.run([str(exe)], capture_output=True, text=True).stdout
    assert report["actual_stdout"] == expected
