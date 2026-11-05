"""build_shaped —— 命令行：给一张图片和一段 C 代码，生成功能相同、形状像图片的 C 文件。

用法（在项目根目录）：
    python scripts/build_shaped.py <image> [code.c] [out.c] [mode] [max_w]

- <image>  : 任意图片（猫、狗、字母、Logo……给什么图就成什么形状），必填；
             也可以直接写 B 的内置形状名 circle / cat / CODE（走 build_mask 掩码）
- [code.c] : 描述"想要的功能"的 C 源文件；省略则用内置的 hello 程序
- [out.c]  : 输出文件；省略则写到 demo/shaped/<图片名>.c
- [mode]   : auto（默认）| v1a | v1b | v0
- [max_w]  : 图案宽度，默认 72；形状名模式下这里是掩码高度（行数），默认 32

示例：
    python scripts/build_shaped.py demo/cat.png
    python scripts/build_shaped.py my_logo.png my_program.c out.c v1a 80
    python scripts/build_shaped.py cat demo/donut_input.c out.c v2 32
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ascii_art_executable.backends import shape_code  # noqa: E402
from ascii_art_executable.backends.c_backend import CBackend  # noqa: E402
from ascii_art_executable.backends.c_tokenfill import (  # noqa: E402
    recommend_width_for, feature_report,
)
from ascii_art_executable.backends.mask_adapter import (  # noqa: E402
    is_shape_name, shape_code_for_shape,
)
from ascii_art_executable.shapecheck import render_report  # noqa: E402

DEFAULT_CODE = """#include <stdio.h>
int main(void) {
    puts("hello");
    return 0;
}
"""


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    use_shape = is_shape_name(sys.argv[1]) and not Path(sys.argv[1]).is_file()
    image = Path(sys.argv[1]) if use_shape else Path(sys.argv[1]).resolve()
    if not use_shape and not image.is_file():
        print(f"image not found: {image}")
        raise SystemExit(1)

    if len(sys.argv) >= 3:
        code = Path(sys.argv[2]).read_text(encoding="utf-8")
    else:
        code = DEFAULT_CODE

    if len(sys.argv) >= 4:
        out = Path(sys.argv[3]).resolve()
    else:
        out = ROOT / "demo" / "shaped" / (image.stem + ".c")
    out.parent.mkdir(parents=True, exist_ok=True)

    mode = sys.argv[4] if len(sys.argv) >= 5 else "auto"
    width_explicit = len(sys.argv) >= 6
    if use_shape:
        # B's mask path: the 5th argument is the mask height in rows (default 32).
        rows = int(sys.argv[5]) if width_explicit else 32
        sk, grid = shape_code_for_shape(code, str(image), str(out), mode=mode,
                                        height_rows=rows)
    else:
        if width_explicit:
            max_w = int(sys.argv[5])
        else:
            # Auto width must fit the longest token and keep internal features
            # (eyes, holes, ...) recognizable, instead of a fixed 72-column guess.
            max_w = recommend_width_for(code, str(image))
        sk, grid = shape_code(code, str(image), str(out), mode=mode, max_w=max_w)
    print(f"image={image.name}  mode={sk.used_mode}  grid={grid.width}x{grid.height}  "
          f"fg={grid.fg_count} -> {out.name}  width={'explicit' if width_explicit else 'auto'}\n")

    features = feature_report(grid)
    if features["holes"]:
        state = "ok" if features["ok"] else "UNDER-SIZED"
        print(f"--- internal features: {features['holes']} hole(s) "
              f"sizes={features['sizes']} -> {state} (min 10 cells each) ---\n")
    if width_explicit and not features["ok"]:
        print("WARNING: the explicit width leaves key internal features below 10 "
              "cells; rerun without a width to use the recommended size.\n")

    backend = CBackend()
    shape = backend.verify(str(out), grid, start_line=sk.start_line,
                           start_column=sk.start_column)
    print("--- F check_shape ---")
    print(render_report(shape["shape"]))

    if shape["note"]:
        print("\n--- e2e ---\n" + shape["note"])
    else:
        print("\n--- e2e (gcc) ---")
        print(f"compile_ok={shape['compile_ok']} run_ok={shape['run_ok']} "
              f"output_match={shape['output_match']} stdout={shape['actual_stdout']!r}")

    print("\n--- generated C source ---")
    print(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
