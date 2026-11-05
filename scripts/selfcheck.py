"""selfcheck - one-click, zero-input verification using only the bundled demo files.

You do not need to find any code or image: this script builds a fixed set of
cases from the files already shipped in ``demo/`` and the built-in shape names,
compiles and runs each generated program, and compares its stdout with the
original program. It prints a PASS/FAIL table and a full sample showing the
original C source, the cat-shaped generated C source, and the program output.

Run it from anywhere (the project root is resolved from this file):

    python scripts/selfcheck.py

Exit code is 0 only when every case compiles, runs and matches the original
output. The temporary build folder is removed when the script finishes.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ascii_art_executable.backends.c_backend import CBackend  # noqa: E402
from ascii_art_executable.backends.c_tokenfill import recommend_width_for  # noqa: E402
from ascii_art_executable.backends.mask_adapter import shape_code_for_shape  # noqa: E402
from ascii_art_executable.backends.shaper import shape_code  # noqa: E402

# (label, kind: image|shape, target, relative path of the C source)
CASES = [
    ("cat image",   "image", "demo/cat.png",   "demo/table_input.c"),
    ("donut image", "image", "demo/donut.png", "demo/donut_input.c"),
    ("heart image", "image", "demo/heart.png", "demo/verify_input.c"),
    ("circle mask", "shape", "circle",         "demo/table_input.c"),
    ("cat mask",    "shape", "cat",            "demo/table_input.c"),
    ("CODE mask",   "shape", "CODE",           "demo/donut_input.c"),
]


def compile_and_run(ci, src: Path, work: Path, name: str):
    """Compile a source with -std=c11 and run it; return (ok, stdout, error)."""
    exe = work / name
    build = subprocess.run(
        [ci.path, "-std=c11", str(src), "-o", str(exe)],
        capture_output=True, text=True, errors="replace")
    if build.returncode != 0:
        return False, "", build.stderr.strip()[:300]
    run = subprocess.run([str(exe)], capture_output=True, text=True,
                         errors="replace")
    if run.returncode != 0:
        return False, "", run.stderr.strip()[:300]
    return True, run.stdout, ""


def run_case(ci, case, work: Path):
    label, kind, target, code_rel = case
    code_path = ROOT / code_rel
    code_text = code_path.read_text(encoding="utf-8")

    # Reference output: the original program, compiled and run the same way.
    orig_ok, expected, orig_err = compile_and_run(
        ci, code_path, work, "orig_" + label.split()[0])
    if not orig_ok:
        return dict(label=label, ok=False, error="original build failed: " + orig_err)

    out = work / (label.replace(" ", "_") + ".c")
    if kind == "shape":
        sk, grid = shape_code_for_shape(
            code_text, target, str(out), mode="v2", height_rows=32)
    else:
        max_w = recommend_width_for(code_text, str(ROOT / target))
        sk, grid = shape_code(code_text, str(ROOT / target), str(out),
                              mode="v2", max_w=max_w)

    report = CBackend().verify(
        str(out), grid, start_line=sk.start_line, start_column=sk.start_column)
    shape = report["shape"]
    actual = report.get("actual_stdout")
    behavior_ok = (
        report["compile_ok"] and report["run_ok"] and actual == expected)
    return dict(
        label=label, ok=bool(behavior_ok), grid=f"{grid.width}x{grid.height}",
        recall=f"{shape.recall:.1%}", precision=f"{shape.precision:.1%}",
        shape_pass=shape.passed, stdout=actual,
        expected=expected, orig_text=code_text,
        shaped_text=out.read_text(encoding="utf-8"))


def main() -> int:
    ci = CBackend.detect_compiler()
    if not ci.path:
        print("No gcc/clang found. Install a compiler or use the Dev-C++ "
              "bundled gcc, then rerun.")
        return 2

    print("=" * 78)
    print(" ASCII Art Executable - self check (no input needed)")
    print("=" * 78)
    print(f" compiler: {ci.path}")

    rows = []
    with tempfile.TemporaryDirectory(prefix="ascii_selfcheck_") as tmp:
        work = Path(tmp)
        for case in CASES:
            rows.append(run_case(ci, case, work))

    header = f"{'case':<13}{'grid':>9}{'recall':>9}{'precision':>11}" \
             f"{'shape':>7}{'behavior':>10}"
    print("\n" + header)
    print("-" * len(header))
    all_ok = True
    sample = None
    for r in rows:
        if "recall" not in r:
            print(f"{r['label']:<13}  ERROR: {r.get('error', 'unknown')}")
            all_ok = False
            continue
        behavior = "PASS" if r["ok"] else "FAIL"
        shape = "PASS" if r["shape_pass"] else "fail"
        all_ok = all_ok and r["ok"]
        print(f"{r['label']:<13}{r['grid']:>9}{r['recall']:>9}"
              f"{r['precision']:>11}{shape:>7}{behavior:>10}")
        if r["label"] == "cat mask":
            sample = r

    if sample is not None:
        print("\n" + "=" * 78)
        print(" STEP 1 - ORIGINAL C source (ordinary layout, before shaping)")
        print("=" * 78)
        print(sample["orig_text"].rstrip())

        print("\n" + "=" * 78)
        print(" STEP 2 - GENERATED source: the SAME real C code, arranged in the")
        print(" cat shape (every visible character is compilable C; it compiles)")
        print("=" * 78)
        print(sample["shaped_text"].rstrip())

        print("\n" + "=" * 78)
        print(" STEP 3 - Running the shaped code: behavior is unchanged")
        print("=" * 78)
        print(sample["stdout"].rstrip())

    print("\n" + "=" * 78)
    if all_ok:
        print(f" RESULT: ALL {len(rows)} CASES PASS - shaped code compiles, "
              "runs and matches the original behavior.")
    else:
        print(" RESULT: FAILURE - see the rows marked FAIL above.")
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
