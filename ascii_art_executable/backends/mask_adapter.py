"""mask_adapter —— 把 B 的 ``build_mask`` 通过依赖注入接进 C 的 ``shape_code``。

B (v2, ``codeart.shapes``) 产出的是 ``Mask``：``allowed[row][col]`` 为 True 表示
"这一格可以放墨"。C 的排版引擎消费的是冻结类型 ``PixelGrid``。本模块只做一层薄适配，
不改 ``shared/types.py``，也不改原有的图片路径（``build_grid``）。

命名对照（B / v1.3 → 本仓库）::

    fit_layout(...)       -> shape_code(...)
    mask_builder=         -> grid_builder=
    build_mask(...)       -> codeart.build_mask(ShapeSpec, SizeRequest, FontMetrics)

用法::

    from codeart import build_mask, SizeRequest
    from ascii_art_executable.backends import shape_code
    from ascii_art_executable.backends.mask_adapter import (
        make_mask_builder, natural_width)

    builder = make_mask_builder(build_mask, SizeRequest(32))
    sk, grid = shape_code(code, "cat", "cat_shaped.c", mode="v2",
                          max_w=natural_width("cat", SizeRequest(32)),
                          grid_builder=builder)

或者直接用一站式入口 :func:`shape_code_for_shape`。

重试契约：``shape_code`` 放不下时会按 ``LAYOUT_GROWTH`` 放大 ``max_w`` 重试。B 的掩码
宽度由高度决定（``cols = ceil(rows * ratio / aspect)``），所以本适配器把放大后的
``max_w`` 换算成"宽度不超过 max_w 的最大行数"，而不是每次都返回同一张网格。
``max_w`` 不超过基准宽度时，严格使用调用方给的 ``SizeRequest``（如 32 行 → 猫 64×32）。
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from shared.types import GridCell, PixelGrid

from codeart import FontMetrics, Mask, ShapeError, ShapeSpec, SizeRequest
from codeart import build_mask as _default_build_mask

from ascii_art_executable.backends.c_widthsafe import C_SAFE_CHARSET

__all__ = [
    "SHAPE_NAMES",
    "is_shape_name",
    "make_mask_builder",
    "mask_to_pixelgrid",
    "natural_width",
    "parse_shape",
    "shape_code_for_shape",
]

#: Shape identifiers B supports (case-insensitive; "CODE" == "code").
SHAPE_NAMES = ("circle", "cat", "code")

ShapeLike = Union[str, ShapeSpec]


def is_shape_name(value) -> bool:
    """True when ``value`` names one of B's built-in shapes (not an image path)."""
    if isinstance(value, ShapeSpec):
        return True
    return isinstance(value, str) and value.strip().lower() in SHAPE_NAMES


def parse_shape(shape: ShapeLike) -> ShapeSpec:
    """Turn ``"cat"`` / ``"CODE"`` / a ``ShapeSpec`` into a ``ShapeSpec``."""
    if isinstance(shape, ShapeSpec):
        return shape
    if not isinstance(shape, str):
        raise ShapeError("INVALID_SHAPE",
                         f"shape must be a name or ShapeSpec, got {type(shape).__name__}")
    kind = shape.strip().lower()
    if kind not in SHAPE_NAMES:
        raise ShapeError("INVALID_SHAPE",
                         f"unknown shape {shape!r}; expected one of {SHAPE_NAMES}")
    return ShapeSpec(kind, text="CODE" if kind == "code" else None)


def mask_to_pixelgrid(mask: Mask, charset: Optional[str] = None,
                      source: Optional[str] = None) -> PixelGrid:
    """Convert B's boolean ``Mask`` into a ``PixelGrid`` of exactly the same size.

    No resize and no re-threshold: ``allowed[row][col] is True`` becomes a
    foreground cell at ``(x=col, y=row)``. Masks are binary, so every foreground
    cell gets the densest level; v2 replaces glyphs with its own distance-field
    shading anyway.
    """
    charset = charset or C_SAFE_CHARSET
    top = len(charset) - 1
    width, height = mask.width, mask.height
    if len(mask.allowed) != height or any(len(r) != width for r in mask.allowed):
        raise ValueError(f"mask.allowed does not match {width}x{height}")
    cells = []
    for y in range(height):
        row = mask.allowed[y]
        for x in range(width):
            fg = bool(row[x])
            cells.append(GridCell(x=x, y=y, fg=fg,
                                  level=top if fg else 0,
                                  ch=charset[top] if fg else " "))
    return PixelGrid(width=width, height=height, cells=tuple(cells),
                     charset=charset, source=source or f"shape:{mask.kind}",
                     threshold=128.0)


def natural_width(shape: ShapeLike, size_request: SizeRequest,
                  font_metrics: Optional[FontMetrics] = None,
                  build_mask: Callable = _default_build_mask) -> int:
    """Width B produces for ``shape`` at ``size_request`` (cat/circle 32 → 64, CODE → 178)."""
    fm = font_metrics or FontMetrics()
    return build_mask(parse_shape(shape), size_request, fm).width


def make_mask_builder(build_mask: Callable = _default_build_mask,
                      size_request: SizeRequest = SizeRequest(32),
                      font_metrics: Optional[FontMetrics] = None):
    """Wrap ``build_mask`` into the ``grid_builder`` protocol used by ``shape_code``.

    The returned callable has the signature
    ``builder(shape, charset=None, max_w=None) -> PixelGrid`` where ``shape`` is
    what ``shape_code`` receives as ``image_path`` — a shape name (``"cat"``,
    ``"circle"``, ``"CODE"``) or a ``ShapeSpec``.

    Height selection:
    * ``max_w`` is ``None`` or ≤ the base width → exactly ``size_request``;
    * ``max_w`` larger (``shape_code`` grew the canvas after a failed attempt) →
      the tallest height whose mask width still fits in ``max_w``.
    The height never drops below ``size_request.height_rows``.
    """
    fm = font_metrics or FontMetrics()
    base_rows = size_request.height_rows

    def _builder(shape, charset=None, max_w=None) -> PixelGrid:
        spec = parse_shape(shape)
        mask = build_mask(spec, size_request, fm)
        if max_w is not None and max_w > mask.width:
            # Width is monotonic in rows; estimate, then step to the exact fit.
            rows = max(base_rows, (max_w * base_rows) // mask.width)
            bigger = build_mask(spec, SizeRequest(rows), fm)
            while bigger.width > max_w and rows > base_rows:
                rows -= 1
                bigger = build_mask(spec, SizeRequest(rows), fm)
            while True:
                nxt = build_mask(spec, SizeRequest(rows + 1), fm)
                if nxt.width > max_w:
                    break
                rows, bigger = rows + 1, nxt
            mask = bigger
        return mask_to_pixelgrid(mask, charset, source=f"shape:{spec.kind}")

    return _builder


def shape_code_for_shape(code_text: str, shape: ShapeLike, out_path: str, *,
                         height_rows: int = 32, mode: str = "v2",
                         charset: str = C_SAFE_CHARSET,
                         build_mask: Callable = _default_build_mask,
                         font_metrics: Optional[FontMetrics] = None,
                         backend=None):
    """One-call entry: C code + B shape name → shaped C file.

    Starts at exactly ``SizeRequest(height_rows)`` (e.g. cat 64×32) and lets
    ``shape_code``'s bounded retry loop grow the mask if the code does not fit.
    Returns ``(CodeSkeleton, PixelGrid)`` like ``shape_code``.
    """
    from ascii_art_executable.backends.shaper import shape_code

    req = SizeRequest(height_rows)
    builder = make_mask_builder(build_mask, req, font_metrics)
    width = natural_width(shape, req, font_metrics, build_mask)
    return shape_code(code_text, shape, out_path, mode=mode, max_w=width,
                      charset=charset, grid_builder=builder, backend=backend)
