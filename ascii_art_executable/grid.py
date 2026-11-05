"""B's module: image / slogan → character grid (图案输入与字符画).

Contract (启动方案 §六·三, owner B):

    build_grid(src, charset, max_w) -> PixelGrid

- ``src``     : image file path (PNG/JPG/…) **or** slogan text (anything that is
                not an existing file path is treated as text).
- ``charset`` : density ramp, sparse → dense; first char is treated as blank.
- ``max_w``   : resolution cap — the grid width never exceeds it (分辨率上限).

Backward-compatible extras (defaults keep the contract behaviour):
- ``threshold``   : gray level 0-255 splitting 前景 from 背景; bright ≥ threshold
                    is foreground by default.
- ``invert``      : flip the fg/bg decision (dark subject on a light background).
- ``cell_aspect`` : terminal character cells are ~2x taller than wide; dividing
                    the target height by this keeps the rendered art from
                    looking squashed. Default 2.0.

Skeleton-phase acceptance (启动方案 §四·二):
- arbitrary PNG in → size-controlled grid out, fg/bg marks clear, deterministic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from shared.types import GridCell, PixelGrid

DEFAULT_CHARSET = " .:-=+*#%@"  # sparse → dense, index 0 = blank

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",   # macOS
    "/System/Library/Fonts/Helvetica.ttc",                  # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",                         # Windows
)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def build_grid(
    src: "str | Path",
    charset: str = DEFAULT_CHARSET,
    max_w: int = 80,
    threshold: float = 128.0,
    invert: bool = False,
    cell_aspect: float = 2.0,
) -> PixelGrid:
    """Downsample an image or slogan into a fg/bg-marked character grid."""
    if not charset:
        raise ValueError("charset must not be empty")
    max_w = max(1, int(max_w))
    threshold = min(255.0, max(0.0, float(threshold)))

    path = Path(src) if isinstance(src, (str, Path)) else None
    if path is not None and path.is_file():
        image = Image.open(path).convert("L")
        source = str(path)
    else:
        text = src if isinstance(src, str) else str(src)
        if not text.strip():
            raise ValueError("slogan text is empty")
        image = _render_slogan(text, max_w)
        source = text

    return _grid_from_image(image, charset, max_w, threshold, invert, cell_aspect, source)


# ---------------------------------------------------------------------------
# image → grid
# ---------------------------------------------------------------------------

def _grid_from_image(
    im: Image.Image,
    charset: str,
    max_w: int,
    threshold: float,
    invert: bool,
    cell_aspect: float,
    source: str,
) -> PixelGrid:
    g = im.convert("L")
    tw = min(g.width, max_w)
    th = max(1, round(tw * g.height / g.width / max(1.0, cell_aspect)))
    if (tw, th) != (g.width, g.height):
        g = g.resize((tw, th), Image.BOX if tw < g.width else Image.NEAREST)

    n = len(charset)
    cells: list[GridCell] = []
    px = g.load()
    for y in range(th):
        for x in range(tw):
            v = px[x, y]
            fg = (v >= threshold) ^ bool(invert)
            level = 0 if n == 1 else min(n - 1, int(round(v / 255 * (n - 1))))
            ch = charset[level] if fg else " "
            cells.append(GridCell(x=x, y=y, fg=fg, level=level, ch=ch))

    return PixelGrid(
        width=tw,
        height=th,
        cells=tuple(cells),
        charset=charset,
        source=source,
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# slogan text → image (white text on black, so "bright = foreground" holds)
# ---------------------------------------------------------------------------

def _render_slogan(text: str, max_w: int) -> Image.Image:
    """Render slogan white-on-black at the largest readable size that fits.

    Size budgets (canvas px, 1px ≈ 1 grid column):
    - width  ≤ max_w       (grid width cap — the contract)
    - height ≤ max_w // 2  (grid rows ≤ max_w / 4, keeps slogans compact)
    Words wrap at spaces; a single overflowing word falls back to the
    legacy single-line fit-to-width path.
    """
    words = text.split()
    budget_w = int(max_w)
    budget_h = max(max_w // 2, 24)
    for size in range(48, 7, -1):
        font = _font_at(size)
        lines = _wrap_words(words, font, budget_w)
        if lines is None or len(lines) * int(size * 1.25) > budget_h:
            continue
        return _draw_lines(lines, font)
    return _render_slogan_fit(text, max_w)


def _font_at(size: int):
    for cand in _FONT_CANDIDATES:
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    return _default_font(size)


def _wrap_words(words: list[str], font, budget_w: float) -> "list[str] | None":
    """Greedy word wrap measured with the real font; None if a word overflows."""
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = w if not cur else cur + " " + w
        if probe.textlength(trial, font=font) <= budget_w:
            cur = trial
        elif cur:
            lines.append(cur)
            cur = w
        elif probe.textlength(w, font=font) > budget_w:
            return None
        else:
            lines.append(w)
            cur = ""
    if cur:
        lines.append(cur)
    return lines


def _draw_lines(lines: list[str], font) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    bboxes = [probe.textbbox((0, 0), line, font=font) for line in lines]
    widths = [b[2] - b[0] for b in bboxes]
    line_h = max(b[3] - b[1] for b in bboxes)
    pad = max(2, int(line_h * 0.25))
    canvas = Image.new("L", (max(widths) + 2 * pad, line_h * len(lines) + 2 * pad), 0)
    d = ImageDraw.Draw(canvas)
    y = pad
    for line, b, w in zip(lines, bboxes, widths):
        d.text((pad + (max(widths) - w) // 2 - b[0], y - b[1]), line, font=font, fill=255)
        y += line_h
    return canvas


def _render_slogan_fit(text: str, max_w: int) -> Image.Image:
    """Legacy fallback: single line squeezed to fit max_w (last resort)."""
    font = _fit_font(text, max_w)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    bbox = probe.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = max(2, th // 8)
    canvas = Image.new("L", (tw + 2 * pad, th + 2 * pad), 0)
    ImageDraw.Draw(canvas).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)
    return canvas


def _fit_font(text: str, target_w: int) -> ImageFont.FreeTypeFont:
    """Pick a bold TTF size whose text width ≈ 0.9 * target_w, else default font."""
    for cand in _FONT_CANDIDATES:
        if Path(cand).exists():
            try:
                factory = lambda s: ImageFont.truetype(cand, s)  # noqa: E731
                size = _search_size(text, target_w, 8, 400, factory)
                return factory(size)
            except OSError:
                continue
    size = _search_size(text, target_w, 8, 400, _default_font)
    return _default_font(size)


def _default_font(size: int) -> ImageFont.ImageFont:
    try:  # Pillow ≥ 10.1 can scale the bundled default font
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _search_size(text: str, target_w: int, lo: int, hi: int, font_factory) -> int:
    """Binary-search a font size so the rendered width ≈ 0.9 * target_w."""
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))

    def width_at(size: int) -> float:
        return probe.textlength(text, font=font_factory(size))

    if width_at(hi) <= target_w * 0.9:
        return hi
    if width_at(lo) >= target_w * 0.9:
        return lo
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if width_at(mid) < target_w * 0.9:
            lo = mid
        else:
            hi = mid
    return lo
