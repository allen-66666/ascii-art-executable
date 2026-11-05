"""C 后端演示：画猫 -> CBackend.fill 生成 C 源文件 -> F 的 check_shape 保形校验
-> （有编译器时）gcc 编译运行并比对 stdout。

用法（在项目根目录）：
    python scripts/demo_c.py [max_w] [mode: auto|v1a|v1b|v0] [text]
默认：72 宽的猫，mode=auto（先试 v1b，缝不够宽自动降级 v1a），输出 "hello"。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from ascii_art_executable.grid import build_grid  # noqa: E402
from ascii_art_executable.backends import CBackend, make_hello_skeleton  # noqa: E402
from ascii_art_executable.shapecheck import render_report  # noqa: E402


def make_cat(path: Path, size: int = 560) -> Path:
    """复用 B 的演示猫：白猫黑背景，带五官与花纹。"""
    S = size
    im = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(im)
    white, dark, nose_g, stripe_g = 255, 0, 60, 150

    def pt(fx, fy):
        return (fx * S, fy * S)

    d.polygon([pt(0.17, 0.30), pt(0.22, 0.02), pt(0.45, 0.16)], fill=white)
    d.polygon([pt(0.83, 0.30), pt(0.78, 0.02), pt(0.55, 0.16)], fill=white)
    d.ellipse([0.13 * S, 0.14 * S, 0.87 * S, 0.86 * S], fill=white)
    d.ellipse([0.32 * S, 0.74 * S, 0.68 * S, 1.06 * S], fill=white)
    for x in (0.42, 0.50, 0.58):
        d.line([pt(x, 0.20), pt(x, 0.31)], fill=stripe_g, width=max(4, int(0.02 * S)))
    for cx in (0.32, 0.68):
        d.ellipse([(cx - 0.09) * S, 0.34 * S, (cx + 0.09) * S, 0.50 * S], fill=dark)
        d.line([pt(cx, 0.365), pt(cx, 0.475)], fill=white, width=max(4, int(0.022 * S)))
    d.polygon([pt(0.46, 0.5555), pt(0.54, 0.5555), pt(0.50, 0.6111)], fill=nose_g)
    d.line([pt(0.50, 0.6111), pt(0.455, 0.657), pt(0.405, 0.647)],
           fill=dark, width=max(6, int(0.02 * S)), joint="curve")
    d.line([pt(0.50, 0.6111), pt(0.545, 0.657), pt(0.595, 0.647)],
           fill=dark, width=max(6, int(0.02 * S)), joint="curve")
    for side in (-1, 1):
        for yf in (0.5694, 0.5972, 0.6249):
            d.line([pt(0.50 + side * 0.13, yf), pt(0.50 + side * 0.47, yf)],
                   fill=dark, width=max(6, int(0.022 * S)))
    im.save(path)
    return path


def main() -> None:
    max_w = int(sys.argv[1]) if len(sys.argv) > 1 else 72
    mode = sys.argv[2] if len(sys.argv) > 2 else "auto"
    text = sys.argv[3] if len(sys.argv) > 3 else "hello"

    out = ROOT / "demo" / "c"
    out.mkdir(parents=True, exist_ok=True)
    png = make_cat(out / "cat.png")

    grid = build_grid(png, max_w=max_w)
    skeleton = make_hello_skeleton(str(out / "skeleton"), text=text)
    backend = CBackend()

    skeleton = backend.fill(grid, skeleton, mode=mode)
    src = Path(skeleton.output_path)
    print(f"C demo  mode={skeleton.used_mode}  grid={grid.width}x{grid.height}  "
          f"fg={grid.fg_count} ({grid.density:.1%})  ->  {src.name}\n")

    # 图案网格（安全字符集）可视化
    print("--- target grid (fg/#) ---")
    for y in range(grid.height):
        print("".join("#" if grid.at(x, y).fg else " " for x in range(grid.width)))

    # F 的保形校验
    shape = backend_shape_check(backend, src, grid, skeleton)
    print("\n--- F check_shape ---")
    print(render_report(shape))

    # 端到端（有编译器才执行）
    verify = backend.verify(str(src), grid, start_line=skeleton.start_line,
                            start_column=skeleton.start_column,
                            expected_stdout=text + "\n")
    if verify["note"]:
        print("\n--- e2e ---\n" + verify["note"])
    else:
        print("\n--- e2e (gcc) ---")
        print(f"compile_ok={verify['compile_ok']} run_ok={verify['run_ok']} "
              f"output_match={verify['output_match']} "
              f"stdout={verify['actual_stdout']!r}")

    print("\n--- generated C source ---")
    print(src.read_text(encoding="utf-8"))


def backend_shape_check(backend, src, grid, skeleton):
    from ascii_art_executable.shapecheck import check_shape
    return check_shape(str(src), grid, start_line=skeleton.start_line,
                       start_column=skeleton.start_column)


if __name__ == "__main__":
    main()
