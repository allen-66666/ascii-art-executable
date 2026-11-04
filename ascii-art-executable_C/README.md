# ASCII Art Executable — Layout & Auto-scaling (Role C Deliverable, v1.3)

> A six-person course project · 25 days of agentic coding. The role contract is in the project
> startup plan and the engineering requirements follow task revision **v1.3**, documented in
> **《代码图案排版工具项目计划与六人分工_v1.3.docx》** (located under `..\..\方案\`).
> This package builds on the runnable baselines of **B (pattern input & character grid)** and
> **F (detector + shape preservation)**, and fulfils **C's v1.3 role "Layout & Auto-scaling"**
> (the `fit_layout` task), while fixing B's `shape_ok` type-annotation bug.
>
> Naming note: `CBackend` and the `backends/` package are the concrete code modules that carry
> this role; the role/task name follows v1.3.
>
> In one sentence: **give it code + an image → it produces a C source file that behaves identically,
> looks like the image, and still compiles and runs.**
> The image is not limited to a cat — whatever shape you provide is the shape you get.
>
> 中文说明见 [`README.zh-CN.md`](README.zh-CN.md).

---

## 1. What is in this package

```
ascii-art-executable_C/
├─ run.py                  ← [C] double-click interactive launcher
├─ README.md               ← this file (how to run + what C did)
├─ README.zh-CN.md         ← Chinese version
├─ FILE_GUIDE.md           ← file-by-file explanation
├─ C_对接说明.md           ← integration contract for D/E
├─ requirements.txt        ← dependencies: Pillow, pytest
├─ shared/                 ← five shared types (B/F/C)
├─ ascii_art_executable/
│   ├─ grid.py             ← [B] build_grid -> PixelGrid
│   ├─ shapecheck.py       ← [F] check_shape / detect / render_report
│   └─ backends/
│       ├─ base.py         ← [C] Backend abstract base
│       ├─ c_widthsafe.py  ← [C] fixed-width cleaning + safe charset
│       ├─ c_seam.py       ← [C] column-preserving seams (statements in shape)
│       ├─ c_doc.py        ← [C] English comments that explain the code
│       ├─ c_parser.py     ← [C] parse real C source into a skeleton
│       ├─ c_fill.py       ← [C] block-comment fill + assembly (v0/v1a/v1b)
│       ├─ c_backend.py    ← [C] CBackend: fill / verify / compiler detection
│       ├─ c_tokenfill.py  ← [C] v2 + v1.3: distance-field shading, feature & silhouette tools
│       └─ shaper.py       ← [C] high-level entry: code + image -> shaped code
├─ scripts/
│   ├─ build_shaped.py     ← [C] any image + code -> shaped code (CLI)
│   ├─ demo_c.py           ← [C] cat demo
│   ├─ demo_grid.py        ← [B] demo
│   └─ demo_bf.py          ← [F] demo
└─ tests/                  ← 59 tests (B + F + C)
```

---

## 2. Setup (first time)

```powershell
cd <this project directory>
python -m pip install -r requirements.txt
```

> The `.venv` shipped with B's original project is in macOS format and does not work on Windows;
> just use the system Python.

---

## 3. The easiest way: double-click `run.py`

`run.py` is an interactive launcher for users who do not want to remember command-line flags.
Double-click it (`.py` is associated with Python) and answer the five prompts:

1. path to the image
2. path to the C source file
3. output file
4. mode (recommended `v2`)
5. width (`auto` or a number)

It then builds the file, runs the shape check and the compile-and-run verification, and prints the
output path. Either `/` or `\` separators work, and surrounding quotes are optional. **Every answer is
required**: pressing Enter on an empty line does not take a default — it prints "No input received.
Please enter a value." and asks again.

If double-click does nothing, right-click `run.py` → Open with → Python, or run `python run.py`.

---

## 4. Command-line usage

```powershell
# Any image + code -> shaped code; arguments: <image> [code.c] [out.c] [mode] [max_w]
python scripts/build_shaped.py demo/donut.png demo/donut_input.c demo/donut_v2.c v2 60
python scripts/build_shaped.py demo/cat.png demo/table_input.c demo/table_output.c v2
python scripts/build_shaped.py demo/heart.png demo/verify_input.c demo/heart_v2.c v2 60
```

When no width is given, `build_shaped.py` uses `recommend_width_for` (it also prints the internal
feature report); an explicit width that makes a feature too small triggers a WARNING.

### Compile and run the generated .c directly

```powershell
& "C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\gcc.exe" demo/donut_v2.c -o donut
.\donut.exe
```

---

## 5. Task revision v1.3: what C landed

### 5.1 Engineering requirements (landed)

1. **Dependency injection.** `shape_code(..., grid_builder=None, backend=None)` defaults to the real
   B grid builder and C backend, but a fake builder or backend can be injected to test the layout in
   isolation. `recommend_feature_width(..., grid_builder=None)` supports injection too.
2. **Quantitative width estimation.** `recommend_width(code_text, *, run_fraction=0.28, min_w=40,
   max_w=LAYOUT_MAX_WIDTH)` derives the width from the longest token divided by the side-run
   fraction, then clamps to `[40, 200]` (donut input → 65).
3. **Formal layout limits & unified failure (v1.4).** `LAYOUT_MAX_WIDTH = 200`,
   `LAYOUT_MAX_ATTEMPTS = 12`, `LAYOUT_GROWTH = 1.25`, and a structured
   `LayoutLimitError(RuntimeError)`. A failed attempt grows the width and retries; each attempt is
   recorded. On success the records are on `sk.attempt_history`; when the limits are exhausted the
   error's `code` and `details["attempt_history"]` carry the same records, instead of a silent bad
   file or a bare `IndexError`.
4. **Minimal separation.** `_needs_space(prev, tok)` inserts a space only when joining two tokens
   would change the lexing; every other boundary relies on C's whitespace insensitivity.

### 5.2 v2 shading: distance-field driven (shape independent)

The current shading does **not** use a directional light. It is driven by a distance field so it works
for any shape:

- `distance_field(grid)`: a two-pass chamfer scan giving, for every foreground cell, the distance to
  the nearest background cell (background cells are the zero sources; foreground cells start at
  infinity and relax; diagonal step √2).
- `shade_char(x, y)`: `t = min(1, dist/_D0)`, `b = _FLOOR + (1-_FLOOR)*t`, then maps `b` onto the
  16-level ramp. Parameters **`_FLOOR = 0.55`, `_D0 = 6.0`**.
- Result: edges (small distance) use sparse characters and the interior smoothly grows denser, so the
  body stays full; there is no directional shadow and no monotone row of one character.

### 5.3 Key internal features are preserved (cat eyes)

- `internal_holes(grid)`: background connected components that never touch the grid border (flood
  fill, purely geometric).
- `recommend_feature_width(..., min_hole_cells=10, ref_w=160, ref_min=12)`: filters noise at a high
  reference resolution and binary-searches the smallest width that keeps every meaningful hole.
- `recommend_width_for(code_text, image_path)`: the **max** of the token width and the feature width.
- `feature_report(..., min_hole_cells=10, noise_floor=4)`: lists all hole sizes and flags undersized.
- The cat auto-selects width 81; each eye is 64 cells and the feature report is ok.

### 5.4 Outer silhouette repair

`repair_outer_silhouette(grid, *, max_notch=6)` builds a per-row edge envelope (the edge can move
inward by at most `max_notch`, relaxed in two passes) and promotes only the outer edge-band
background cells; it never touches internal holes or the small whisker gaps. In `shape_code` it runs
before filling (guarded by `isinstance`), and `render_v2` keeps one idempotent call. The cat's
whisker left edge moves from column 30 back to 17–23 while the internal holes stay unchanged.

### 5.5 v1.3 items not adopted (not applicable / over-engineered)

- Splitting the fill step into D with this role doing layout only: the actual implementation merges
  layout and fill in one codebase, so the role split is not applied.
- Mandatory libclang lexing: the regex tokenizer is sufficient and avoids a heavy dependency.
- Hard 800×600 / 5-second / monotonic-clock RunContext cancellation and timing-bearing
  AttemptRecords are over-design for a small deterministic offline tool.

---

## 6. The modes (mapping the startup plan's v0 / v1 / v2)

| Mode | How the shape is carried | Measured result |
|---|---|---|
| **v2** | Real code tokens paired with English comments laid out along the outline; the remaining cells are shaded by the distance field (edges sparse, interior dense) via the 16-level ramp | cat 99.1% matched / precision 100%; donut 97.6%; heart 98.2%; all compile and run |
| v1b | Real statements `*/ statement /*` embedded in the blank seams | recall 100%; the extra cells are required real code |
| v1a | Pattern in a block comment, statements after it | recall = precision = 100%, extra = 0 (the safety line) |
| v0 | Pattern printed line by line by executable `printf` | shape comes from really executed code; inherently shape-preserving |

> `mode="auto"` tries v1b and degrades to v1a; pass `v2` explicitly for the token-outline art.

---

## 7. About gcc

`CBackend` probes `gcc`/`clang` on PATH and then the known Dev-C++ bundled path.
- **Found** → compile → run → compare stdout → check shape.
- **Not found** → only shape and structural checks, marked "compilation skipped" (a degradation, not
  a failure).

Dev-C++ 5.11 ships MinGW64 gcc 4.9.2 at `C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\gcc.exe`; the
path is built in and tested, so no extra software is needed. Compilation uses the full `ci.path`
(independent of PATH) and subprocess output is read with `errors="replace"` to survive GBK consoles.

> Clarification: the output is plain text with no real light. The "shading" is a deterministic
> function choosing characters; the sense of depth is carried entirely by character density and
> character choice, never by adjusting real brightness.

---

## 8. Local verification results (2026-11-04)

- `python -m pytest tests -q` → **59 passed, 5 subtests passed**.
- Cat (auto width 81): 1468/1482 matched (99.1%), precision 100%, contour closed, eye holes clear;
  gcc runs the multiplication table correctly.
- Donut (width 60): 680/697 (97.6%), precision 100%; gcc outputs total = 91.
- Heart (width 60): 656/668 (98.2%); gcc outputs sum = 15.
- The remaining missing cells are isolated single-cell runs (length 1, cannot hold a `/*` marker)
  surrounded by background; they are not on the outer contour and do not affect closure.
