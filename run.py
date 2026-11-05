"""Interactive launcher: double-click this file, then follow the prompts.

It asks for an image and a C source file, builds the image-shaped executable C
code, and prints where the result was written. Every answer is required: an
empty entry is rejected and the question is asked again. Paths may be pasted
with or without surrounding quotes, and either "/" or "\\" separators work.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable regardless of the current working directory.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ascii_art_executable.backends.shaper import shape_code          # noqa: E402
from ascii_art_executable.backends.c_backend import CBackend         # noqa: E402
from ascii_art_executable.backends.c_tokenfill import (              # noqa: E402
    recommend_width_for,
)
from ascii_art_executable.backends.mask_adapter import (
    is_shape_name, shape_code_for_shape,
)
from ascii_art_executable.shapecheck import render_report            # noqa: E402


def _clean(raw: str) -> str:
    """Trim whitespace and surrounding quotes from a pasted path."""
    return raw.strip().strip('"').strip("'").strip()


def ask_required(prompt: str, *, check_file: bool = False) -> str:
    """Prompt until a non-empty, valid value is entered.

    An empty entry never silently takes a default: the user is told nothing was
    entered and is asked again. When ``check_file`` is set, the value must also
    point to an existing file.
    """
    while True:
        raw = _clean(input(prompt))
        if not raw:
            print("  No input received. Please enter a value.\n")
            continue
        if check_file and not Path(raw).is_file():
            print(f"  File not found: {raw}\n  Please check the path and try again.\n")
            continue
        return raw


def main() -> None:
    print("=" * 64)
    print(" ASCII Art Executable - interactive launcher")
    print("=" * 64)
    print("Paste a path with '/' or '\\'; surrounding quotes are optional.\n")

    while True:
        image = ask_required(
            "1) Path to the image (png/jpg/...), or a built-in shape "
            "(circle / cat / CODE):\n   > ")
        if is_shape_name(image) or Path(image).is_file():
            break
        print(f"  File not found: {image}\n  Please check the path and try again.\n")
    use_shape = is_shape_name(image) and not Path(image).is_file()
    code_path = ask_required(
        "2) Path to the C source file:\n   > ", check_file=True)
    code_text = Path(code_path).read_text(encoding="utf-8")

    suggested = ROOT / "demo" / "shaped" / f"{Path(image).stem}_interactive.c"
    out_path = ask_required(
        f"3) Output file (suggested: {suggested}):\n   > ")

    mode = ask_required(
        "4) Mode (v2/v1a/v1b/v0; recommended v2):\n   > ")

    if use_shape:
        width_raw = ask_required(
            "5) Shape height in rows (type 'auto' for 32, or a number):\n   > ")
    else:
        width_raw = ask_required(
            "5) Width in columns (type 'auto' or a number):\n   > ")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    print("\nBuilding ...\n")
    if use_shape:
        rows = 32 if width_raw.lower() == "auto" else int(width_raw)
        sk, grid = shape_code_for_shape(code_text, image, out_path, mode=mode,
                                        height_rows=rows)
    else:
        max_w = recommend_width_for(code_text, image) \
            if width_raw.lower() == "auto" else int(width_raw)
        sk, grid = shape_code(code_text, image, out_path, mode=mode, max_w=max_w)

    backend = CBackend()
    report = backend.verify(out_path, grid, start_line=sk.start_line,
                            start_column=sk.start_column)
    print("--- shape check ---")
    print(render_report(report["shape"]))
    print("\n--- end to end ---")
    if report["note"]:
        print(report["note"])
    else:
        print(f"compile_ok={report['compile_ok']} run_ok={report['run_ok']}")
        print(f"program output={report['actual_stdout']!r}")

    print("\n" + "=" * 64)
    print(f"Done. Open the shaped source here:\n{out_path}")
    print("=" * 64)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nSomething went wrong: {exc}")
    input("\nPress Enter to close this window ...")
