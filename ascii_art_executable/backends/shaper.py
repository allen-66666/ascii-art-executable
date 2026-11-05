"""shaper —— 高层入口：给一段 C 代码 + 一张图片，生成功能相同、形状像图片的 C 源文件。

这是对用户核心问题"如何实现给他一段代码和一张图片，生成功能相同且有猫形状的代码"
的直接回答。流程：
1. c_parser.extract_main_parts：从完整程序里取出预处理行与 main 内的真实语句；
2. build_grid：把任意图片降采样成 PixelGrid（不限于猫，给什么图就成什么形状）；
3. CBackend.fill：把图案与真实语句组装成可编译、能运行、行为不变的 C 源文件，
   真实语句带英文解释注释。

用法见 scripts/build_shaped.py。
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Optional

from shared.types import CodeSkeleton, PixelGrid, Statement

from ascii_art_executable.grid import build_grid
from ascii_art_executable.backends.c_backend import CBackend
from ascii_art_executable.backends.c_parser import (
    extract_main_parts,
    validate_c_source,
)
from ascii_art_executable.backends.c_tokenfill import (
    LAYOUT_GROWTH,
    LAYOUT_MAX_ATTEMPTS,
    LAYOUT_MAX_WIDTH,
    LayoutLimitError,
    repair_outer_silhouette,
)
from ascii_art_executable.backends.c_widthsafe import C_SAFE_CHARSET


def _next_width(width: int) -> int:
    """Grow the width by LAYOUT_GROWTH, capped at LAYOUT_MAX_WIDTH."""
    if width >= LAYOUT_MAX_WIDTH:
        return LAYOUT_MAX_WIDTH
    grown = max(width + 1, int(math.ceil(width * LAYOUT_GROWTH)))
    return min(LAYOUT_MAX_WIDTH, grown)


def shape_code(code_text: str, image_path: str, out_path: str, *,
               mode: str = "auto", max_w: int = 72,
               charset: str = C_SAFE_CHARSET,
               grid_builder=None, backend=None) -> tuple[CodeSkeleton, object]:
    """Build a shaped, functionally-equivalent C file from code text and an image.

    Returns the filled CodeSkeleton (output_path/start_line/used_mode/attempt_history
    are set) and the PixelGrid used for the shape. The generated file is written to
    out_path.

    ``grid_builder`` and ``backend`` are optional injection points (v1.3): they
    default to the real B grid builder and C backend, but a fake mask builder or a
    test backend can be passed in to debug the layout in isolation.

    Retry contract (v1.4): a single layout attempt that cannot fit raises
    ``LayoutLimitError``; the width is then grown by ``LAYOUT_GROWTH`` and the
    attempt is retried, up to ``LAYOUT_MAX_ATTEMPTS`` / ``LAYOUT_MAX_WIDTH``. Each
    attempt is recorded; on success the records are returned as
    ``sk.attempt_history``, and if every attempt fails they are attached to the
    final error's ``details["attempt_history"]``.
    """
    validate_c_source(code_text, filename=out_path)
    pre, body = extract_main_parts(code_text)
    sk = CodeSkeleton(source_path=out_path, lang="c")
    line = 1
    for p in pre:
        sk.statements.append(Statement(text=p, start_line=line, end_line=line,
                                       kind="preprocessor"))
        line += 1
    for b in body:
        sk.statements.append(Statement(text=b, start_line=line, end_line=line,
                                       kind="code"))
        line += 1
    sk.output_path = out_path

    builder = grid_builder if grid_builder is not None else build_grid
    engine = backend if backend is not None else CBackend(safe_charset=charset)

    attempts: list[dict] = []
    width = max_w
    grid = None
    for _ in range(LAYOUT_MAX_ATTEMPTS):
        t0 = time.perf_counter()
        grid = builder(image_path, charset=charset, max_w=width)
        if mode == "v2" and isinstance(grid, PixelGrid):
            # Bound deep outer-silhouette notches before both layout and verification.
            grid = repair_outer_silhouette(grid)
        try:
            sk = engine.fill(grid, sk, mode=mode)
            sk.attempt_history = attempts
            return sk, grid
        except LayoutLimitError as exc:
            attempts.append({
                "scale": round(width / max_w, 4) if max_w else 1.0,
                "width": width,
                "height": getattr(grid, "height", 0),
                "failure_token_index": None,
                "reason": str(exc),
                "elapsed_s": round(time.perf_counter() - t0, 6),
            })
            nxt = _next_width(width)
            if nxt <= width:
                break
            width = nxt

    raise LayoutLimitError(
        "layout could not fit within the width/attempt limits",
        code="LAYOUT_LIMIT", details={"attempt_history": attempts})