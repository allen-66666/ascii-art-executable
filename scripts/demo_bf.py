"""Exercise B -> F with an explicit mock layout, without a C/D backend."""

from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ascii_art_executable.grid import build_grid
from ascii_art_executable.shapecheck import check_shape, detect, render_report


def main():
    out = ROOT / "demo" / "bf"
    out.mkdir(parents=True, exist_ok=True)
    grid = build_grid(ROOT / "demo" / "cat.png", max_w=48)
    rows = [
        "".join("#" if grid.at(x, y).fg else " " for x in range(grid.width))
        for y in range(grid.height)
    ]
    target = out / "target_mask.txt"
    target.write_text("\n".join(rows) + "\n", encoding="utf-8")
    source = out / "mock_layout.c"
    source.write_text("/*\n" + "\n".join(rows) +
                      '\n*/\n#include <stdio.h>\nint main(void) { puts("hello"); return 0; }\n',
                      encoding="utf-8")
    shape = check_shape(source, grid, start_line=2, min_precision=1)
    detection = detect(source)
    print("B -> F demo (mock layout; not C backend output)\n")
    print(render_report(shape))
    print()
    print(render_report(detection))
    (out / "report.json").write_text(
        json.dumps({"shape": asdict(shape), "detect": asdict(detection)},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Damage one real foreground cell to demonstrate a failing comparison.
    cell = next(c for c in grid.cells if c.fg)
    rows[cell.y] = rows[cell.y][:cell.x] + " " + rows[cell.y][cell.x + 1:]
    broken = out / "mock_damaged.c"
    broken.write_text("/*\n" + "\n".join(rows) + "\n*/\n", encoding="utf-8")
    failed = check_shape(broken, grid, start_line=2)
    print("\nAfter removing one foreground character:")
    print(render_report(failed))
    if not shape.passed or failed.passed:
        raise SystemExit("unexpected demo result")


if __name__ == "__main__":
    main()
