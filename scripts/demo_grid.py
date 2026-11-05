"""B's demo: draw a cat head, save as PNG, build the character grid, print it.

Run from the project root:
    python3 scripts/demo_grid.py [max_w]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from ascii_art_executable.grid import build_grid  # noqa: E402


def make_cat(path: Path, size: int = 560) -> Path:
    """Cat head + chest, white on black, with facial features.

    Dark features (eyes, nose, mouth, whiskers, inner ears) render as
    background holes; mid-gray tabby stripes exercise the density ramp.
    All coordinates are fractions of ``size``.
    """
    S = size
    im = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(im)
    white, dark, nose_g, stripe_g, shade_g = 255, 0, 60, 150, 222

    def pt(fx: float, fy: float):
        return (fx * S, fy * S)

    # --- ears (behind the head), with dark inner-ear cutouts -------------
    d.polygon([pt(0.17, 0.30), pt(0.22, 0.02), pt(0.45, 0.16)], fill=white)
    d.polygon([pt(0.83, 0.30), pt(0.78, 0.02), pt(0.55, 0.16)], fill=white)
    d.polygon([pt(0.25, 0.26), pt(0.27, 0.10), pt(0.38, 0.18)], fill=70)
    d.polygon([pt(0.75, 0.26), pt(0.73, 0.10), pt(0.62, 0.18)], fill=70)

    # --- head + chest -----------------------------------------------------
    d.ellipse([0.13 * S, 0.14 * S, 0.87 * S, 0.86 * S], fill=white)
    d.ellipse([0.32 * S, 0.74 * S, 0.68 * S, 1.06 * S], fill=white)

    # --- tabby stripes on the forehead (mid gray → mid-density chars) -----
    for x in (0.42, 0.50, 0.58):
        d.line([pt(x, 0.20), pt(x, 0.31)], fill=stripe_g, width=max(4, int(0.02 * S)))

    # --- soft cheek shading ------------------------------------------------
    # (removed: large anti-aliased ellipses turn into mottled noise at grid
    #  resolution; keep the face clean white and let features carry the look)

    # --- eyes: dark almond + white vertical slit pupil --------------------
    for cx in (0.32, 0.68):
        d.ellipse([(cx - 0.09) * S, 0.34 * S, (cx + 0.09) * S, 0.50 * S], fill=dark)
        d.line([pt(cx, 0.365), pt(cx, 0.475)], fill=white, width=max(4, int(0.022 * S)))

    # --- nose + compact w-mouth, snapped to 72x36 grid row boundaries ------
    # (row r of 36 spans y = r/36 .. (r+1)/36 of the image; keeping each
    #  feature inside whole rows stops BOX averaging from smearing it)
    d.polygon([pt(0.46, 0.5555), pt(0.54, 0.5555), pt(0.50, 0.6111)], fill=nose_g)
    d.line([pt(0.50, 0.6111), pt(0.455, 0.657), pt(0.405, 0.647)],
           fill=dark, width=max(6, int(0.02 * S)), joint="curve")
    d.line([pt(0.50, 0.6111), pt(0.545, 0.657), pt(0.595, 0.647)],
           fill=dark, width=max(6, int(0.02 * S)), joint="curve")

    # --- whiskers: 3 per side, centered on grid rows 20/21/22 ---------------
    # (a dark feature narrower than one cell (~S/72) or straddling a row
    #  boundary blurs into pale characters; keep it one row thick)
    for side in (-1, 1):
        for yf in (0.5694, 0.5972, 0.6249):
            d.line([pt(0.50 + side * 0.13, yf), pt(0.50 + side * 0.47, yf)],
                   fill=dark, width=max(6, int(0.022 * S)))

    im.save(path)
    return path


def main() -> None:
    max_w = int(sys.argv[1]) if len(sys.argv) > 1 else 72
    out = ROOT / "demo"
    out.mkdir(exist_ok=True)
    png = make_cat(out / "cat.png")

    grid = build_grid(png, max_w=max_w)
    print(f"# {png.name}  {grid.width}x{grid.height}  fg={grid.fg_count} ({grid.density:.1%})\n")
    print(grid.render())


if __name__ == "__main__":
    main()
