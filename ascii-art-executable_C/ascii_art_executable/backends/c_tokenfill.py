"""c_tokenfill -- v2: arrange REAL C tokens to trace the target shape.

Unlike v1 (which keeps the picture inside a block comment), v2 reflows the actual
code tokens. C is whitespace-insensitive between tokens, so a line break and
indentation may be inserted at almost any token boundary. We pack tokens into the
foreground runs of the PixelGrid so the outer contour matches the image, while the
program stays compilable and behaves identically.

Rules that keep the generated code valid:
- preprocessor lines are atomic and stay at column 0;
- string/char literals are atomic (never split);
- line comments are removed; only block comments are allowed (atomic);
- a space is inserted only when two tokens would otherwise merge or re-lex;
- any foreground cells left after the last real token are filled with ONE balanced
  block comment that carries readable English text (visible, non-space chars).
"""

from __future__ import annotations

from collections import deque
import math
import os
import re
from pathlib import Path

from shared.types import CodeSkeleton, GridCell, PixelGrid

# Density ramp (sparse -> dense) used to fake 3D shading inside block comments.
# It deliberately excludes '*', '/', '?', '\' so it can never break a comment or
# trigger a trigraph. '$' and '&' are safe inside a comment and add denser levels.
_SHADE_RAMP = ".,:;irsx=+o$%&#@"

# Formal layout limits (v1.3): the engine never grows a canvas without bound.
# These are deliberately generous for an offline source-art tool.
LAYOUT_MAX_WIDTH = 200
LAYOUT_MAX_ATTEMPTS = 12
# Width growth factor for a retry when one layout attempt cannot fit (v1.4 retry).
LAYOUT_GROWTH = 1.25
# Side runs of an annular grid are roughly this fraction of the canvas width.
_RUN_FRACTION = 0.28


class LayoutLimitError(RuntimeError):
    """Raised when the content cannot fit inside the layout limits.

    Carries a machine-readable ``code`` and a ``details`` dict (which holds the
    structured ``attempt_history`` on failure), mirroring the v1.4 Diagnostic
    contract while remaining a plain RuntimeError so existing callers and
    ``except RuntimeError`` branches keep working.
    """

    def __init__(self, message: str = "", *, code: str = "LAYOUT_LIMIT",
                 stage: str = "layout", line: int | None = None,
                 column: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.stage = stage
        self.line = line
        self.column = column
        self.details = dict(details) if details else {}


def recommend_width(code_text: str, *, run_fraction: float = _RUN_FRACTION,
                    min_w: int = 40, max_w: int = LAYOUT_MAX_WIDTH) -> int:
    """Deterministic starting width for a shaped layout.

    The longest atomic token (e.g. a string literal) must fit inside a side run,
    which is roughly ``run_fraction`` of the width. So width >= longest / fraction.
    This replaces blind trial-and-error growth with a single computed estimate.
    """
    longest = max((len(tok) for tok, _kind in tokenize_c(code_text)), default=1)
    w = int(math.ceil(longest / run_fraction))
    return max(min_w, min(max_w, w))

# --------------------------------------------------------------------------- #
# Tokenizer
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(
    r"""
      (?P<block> /\*.*?\*/ )
    | (?P<pre>   ^[ \t]*\#[^\n]* )
    | (?P<str>   "(?:\\.|[^"\\])*" )
    | (?P<char>  '(?:\\.|[^'\\])*' )
    | (?P<num>   (?:\d+\.\d+|\d+)[uUlLfF]* )
    | (?P<id>    [A-Za-z_]\w* )
    | (?P<multi> <<=|>>=|->|==|!=|<=|>=|\+\+|--|&&|\|\||<<|>>|
                  \+=|-=|\*=|/=|%=|&=|\|=|\^=|\.\.\. )
    | (?P<punct> [{}()\[\];,.+\-*/%=<>!&|~^?:] )
    """,
    re.VERBOSE | re.DOTALL | re.MULTILINE,
)

_KIND_BY_GROUP = ("block", "pre", "str", "char", "num", "id", "multi", "punct")


def tokenize_c(source: str) -> list[tuple[str, str]]:
    """Return an ordered list of (token_text, kind). Line comments are dropped."""
    source = re.sub(r"//[^\n]*", "", source)
    out: list[tuple[str, str]] = []
    for m in _TOKEN_RE.finditer(source):
        kind = next(k for k in _KIND_BY_GROUP if m.group(k) is not None)
        out.append((m.group(), kind))
    return out


def _is_word_kind(kind: str) -> bool:
    return kind in ("id", "num")


def _needs_space(prev: tuple[str, str], tok: tuple[str, str]) -> bool:
    """Whether a whitespace gap is mandatory to keep the same token sequence."""
    p_text, p_kind = prev
    t_text, t_kind = tok
    # Two word-ish tokens would merge (return 0, int x, 123 abc).
    if _is_word_kind(p_kind) and _is_word_kind(t_kind):
        return True
    # A word token followed by an identifier-start punctuation? punctuation never
    # starts an identifier, so no. But an identifier right after a number is covered
    # above. A block comment already acts as a separator.
    if p_kind == "block" or t_kind == "block":
        return False
    # Two punctuation tokens could re-lex into a multi-char operator (++ <= -- ...).
    if not _is_word_kind(p_kind) and not _is_word_kind(t_kind):
        if (p_text + t_text) in _MULTI_FORMS:
            return True
    return False


_MULTI_FORMS = {
    "++", "--", "==", "!=", "<=", ">=", "&&", "||", "->", "<<", ">>",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "...",
}


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def foreground_runs(grid: PixelGrid) -> list[list[tuple[int, int]]]:
    """Per-row list of (start, end_exclusive) foreground runs."""
    runs: list[list[tuple[int, int]]] = []
    for y in range(grid.height):
        row_runs: list[tuple[int, int]] = []
        s = None
        for x in range(grid.width):
            if grid.at(x, y).fg:
                if s is None:
                    s = x
            elif s is not None:
                row_runs.append((s, x))
                s = None
        if s is not None:
            row_runs.append((s, grid.width))
        runs.append(row_runs)
    return runs


def distance_field(grid: PixelGrid) -> list[list[float]]:
    """Chamfer distance of every foreground cell to its nearest background cell.

    This is shape-agnostic: it works for a ring, a cat, a heart, or any input
    image. Background cells hold 0; the value grows smoothly toward the interior
    of the shape, so it identifies silhouette edges without hardcoding a donut.
    """
    W, H = grid.width, grid.height
    inf = float(W + H)
    # Background cells are the distance sources (0); foreground cells start
    # unknown and are relaxed toward the nearest background cell.
    d = [[0.0 if not grid.at(x, y).fg else inf for x in range(W)]
         for y in range(H)]
    sq2 = math.sqrt(2.0)

    def relax(y: int, x: int, sy: int, sx: int, diagonal: bool) -> None:
        ny, nx = y + sy, x + sx
        if 0 <= ny < H and 0 <= nx < W:
            d[y][x] = min(d[y][x], d[ny][nx] + (sq2 if diagonal else 1.0))

    # forward pass (top-left -> bottom-right)
    for y in range(H):
        for x in range(W):
            if d[y][x] == 0.0:
                continue
            relax(y, x, 0, -1, False)
            relax(y, x, -1, 0, False)
            relax(y, x, -1, -1, True)
            relax(y, x, -1, 1, True)
    # backward pass (bottom-right -> top-left)
    for y in range(H - 1, -1, -1):
        for x in range(W - 1, -1, -1):
            if d[y][x] == 0.0:
                continue
            relax(y, x, 0, 1, False)
            relax(y, x, 1, 0, False)
            relax(y, x, 1, 1, True)
            relax(y, x, 1, -1, True)
    return d


def internal_holes(grid: PixelGrid) -> list[list[tuple[int, int]]]:
    """Return the internal background connected components (enclosed holes).

    A background component that touches the grid border is the outer background;
    every other background component is an enclosed hole (eyes, the donut hole,
    a letter counter, ...). This is purely geometric and never hardcodes a shape.
    """
    W, H = grid.width, grid.height
    seen = [[False] * W for _ in range(H)]
    holes: list[list[tuple[int, int]]] = []
    for sy in range(H):
        for sx in range(W):
            if seen[sy][sx] or grid.at(sx, sy).fg:
                continue
            q: deque[tuple[int, int]] = deque([(sx, sy)])
            seen[sy][sx] = True
            cells: list[tuple[int, int]] = []
            touches_border = False
            while q:
                x, y = q.popleft()
                cells.append((x, y))
                if x == 0 or y == 0 or x == W - 1 or y == H - 1:
                    touches_border = True
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < W and 0 <= ny < H and not seen[ny][nx]
                            and not grid.at(nx, ny).fg):
                        seen[ny][nx] = True
                        q.append((nx, ny))
            if not touches_border:
                holes.append(cells)
    return holes


def recommend_feature_width(image_path: str, *, grid_builder=None,
                            min_hole_cells: int = 10, ref_w: int = 160,
                            ref_min: int = 12, min_w: int = 40,
                            max_w: int = LAYOUT_MAX_WIDTH) -> int:
    """Smallest grid width that keeps every meaningful internal hole recognizable.

    Meaningful holes are those that already have ``ref_min`` cells at a high
    reference resolution (this filters noise). The candidate width must leave at
    least that many holes with ``min_hole_cells`` cells, so small key features
    (e.g. a cat's eyes) cannot silently disappear. Shapes with no holes return
    ``min_w`` and let the token-based width decide.
    """
    if grid_builder is None:
        from ascii_art_executable.grid import build_grid as grid_builder
    ref = grid_builder(image_path, max_w=ref_w)
    need = sum(1 for h in internal_holes(ref) if len(h) >= ref_min)
    if need == 0:
        return min_w

    def preserves(width: int) -> bool:
        g = grid_builder(image_path, max_w=width)
        return sum(1 for h in internal_holes(g) if len(h) >= min_hole_cells) >= need

    if not preserves(max_w):
        return max_w
    lo, hi = min_w, max_w
    while lo < hi:
        mid = (lo + hi) // 2
        if preserves(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def feature_report(grid: PixelGrid, *, min_hole_cells: int = 10,
                   noise_floor: int = 4) -> dict:
    """Summarize internal-hole preservation for a built grid (general check).

    Holes smaller than ``noise_floor`` are downsampling artifacts and ignored;
    a hole is undersized when it is a real feature (>= noise_floor) but still
    below ``min_hole_cells``, so the check matches the recommendation logic.
    """
    holes = internal_holes(grid)
    sizes = sorted((len(h) for h in holes), reverse=True)
    undersized = [s for s in sizes if noise_floor <= s < min_hole_cells]
    return {
        "holes": len(holes),
        "sizes": sizes,
        "undersized": len(undersized),
        "ok": not undersized,
    }


def recommend_width_for(code_text: str, image_path: str, *,
                        grid_builder=None) -> int:
    """Width that fits both the longest token and the image's internal features."""
    token_w = recommend_width(code_text)
    feature_w = recommend_feature_width(image_path, grid_builder=grid_builder)
    return max(token_w, feature_w)


def repair_outer_silhouette(grid: PixelGrid, *, max_notch: int = 6) -> PixelGrid:
    """Bound deep notches on the OUTER silhouette (general shape-fidelity repair).

    Downsampling can erase thin protruding features (e.g. a cat's whiskers), so a
    row's outer edge may recede far past its neighbors and read as a large opening.
    The edge is allowed to move inward at most ``max_notch`` cells per row; cells
    in the resulting edge bands are promoted to foreground. Only the outer bands
    are touched, so internal holes (eyes, ...) and small gaps are preserved.
    """
    from dataclasses import replace
    W, H = grid.width, grid.height
    left: list[int | None] = [None] * H
    right: list[int | None] = [None] * H
    for y in range(H):
        xs = [x for x in range(W) if grid.at(x, y).fg]
        if xs:
            left[y], right[y] = min(xs), max(xs)
    le, ri = list(left), list(right)
    for _ in range(2):                                  # relax the edge envelope
        for y in range(1, H):
            if le[y] is not None and le[y - 1] is not None:
                le[y] = min(le[y], le[y - 1] + max_notch)
        for y in range(H - 2, -1, -1):
            if le[y] is not None and le[y + 1] is not None:
                le[y] = min(le[y], le[y + 1] + max_notch)
        for y in range(1, H):
            if ri[y] is not None and ri[y - 1] is not None:
                ri[y] = max(ri[y], ri[y - 1] - max_notch)
        for y in range(H - 2, -1, -1):
            if ri[y] is not None and ri[y + 1] is not None:
                ri[y] = max(ri[y], ri[y + 1] - max_notch)

    new_cells = []
    for y in range(H):
        for x in range(W):
            old = grid.at(x, y)
            in_left_band = le[y] is not None and le[y] <= x < left[y]
            in_right_band = ri[y] is not None and right[y] < x <= ri[y]
            if not old.fg and (in_left_band or in_right_band):
                new_cells.append(GridCell(x, y, True, old.level, "#"))
            else:
                new_cells.append(old)
    return replace(grid, cells=tuple(new_cells))


# --------------------------------------------------------------------------- #
# v2 render
# --------------------------------------------------------------------------- #
from ascii_art_executable.backends import c_doc  # noqa: E402

_HEADER = (
    "/* Token-shaped C source: real code tokens trace the target image, and each "
    "statement is paired with an English explanation. The program compiles, runs, "
    "and keeps its original behavior. */"
)


def render_v2(pre_lines: list[str], body: list, grid: PixelGrid
              ) -> tuple[list[str], int, int]:
    # Close deep outer-silhouette notches (e.g. whisker gaps) while keeping
    # internal holes and small gaps intact.
    grid = repair_outer_silhouette(grid)
    # Build an ordered item stream: meaningful block comment + its code, paired.
    items: list[tuple] = []

    def add_comment(sentence: str) -> None:
        items.append(("m", "/*" + sentence + "*/"))

    def add_code(snippet: str) -> None:
        for text, kind in tokenize_c(snippet):
            items.append(("c", text, kind))

    add_comment("Entry point")
    add_code("int main(void){")
    for st in body:
        add_comment(c_doc.short_explain(st.text))
        add_code(st.text)
    add_comment("Return success")
    add_code("return 0;")
    add_code("}")

    W, H = grid.width, grid.height
    canvas = [[" "] * W for _ in range(H)]
    runs = foreground_runs(grid)

    # Flatten foreground cells, tagged with a run id so tokens never split across
    # the donut hole and run boundaries act as implicit whitespace.
    pos: list[tuple[int, int, int]] = []
    rid = 0
    for y, row_runs in enumerate(runs):
        for (s, e) in row_runs:
            for x in range(s, e):
                pos.append((x, y, rid))
            rid += 1

    def _run_end(index: int) -> int:
        r = index
        while r < len(pos) and pos[r][2] == pos[index][2]:
            r += 1
        return r

    def _write_char(index: int, ch: str) -> int:
        x, y, _ = pos[index]
        canvas[y][x] = ch
        return index + 1

    def _write_marker(index: int, marker: str) -> int:
        """Write a 2-char marker, moving to the next run if the current one is
        too short so the marker is never split across the donut hole."""
        if index >= len(pos):
            raise LayoutLimitError("v2 content exceeds the available foreground runs")
        if _run_end(index) - index < 2:
            index = _run_end(index)
            if index >= len(pos):
                raise LayoutLimitError("v2 marker has no room in the remaining runs")
        index = _write_char(index, marker[0])
        index = _write_char(index, marker[1])
        return index

    def place_comment(index: int, inner: str) -> int:
        """Write a balanced comment across runs, re-opening it on the next run
        when a hole interrupts a physical line. If the shape cannot hold all of
        the text, the text is truncated; every comment is always closed and the
        index never leaves the foreground cells."""
        idx = 0
        while True:
            if index >= len(pos):
                return index                       # no room; last comment is closed
            if pos[index][1] in feature_rows:
                index = _run_end(index)            # keep feature rows comment-free
                continue
            if _run_end(index) - index < 2:
                nxt = _run_end(index)
                if nxt >= len(pos):
                    return index
                index = nxt
                continue
            index = _write_marker(index, "/*")
            avail = _run_end(index) - index
            remaining = len(inner) - idx
            if remaining <= avail - 2:             # room for text + closing
                for k in range(remaining):
                    ch = inner[idx]
                    if ch == " ":
                        cx, cy, _ = pos[index]
                        if _on_outer_contour(cx, cy):
                            ch = "_"
                    index = _write_char(index, ch)
                    idx += 1
                index = _write_marker(index, "*/")
                return index
            take = max(0, avail - 2)               # fill run, then close it
            for k in range(take):
                ch = inner[idx]
                if ch == " ":
                    cx, cy, _ = pos[index]
                    if _on_outer_contour(cx, cy):
                        ch = "_"
                index = _write_char(index, ch)
                idx += 1
            index = _write_marker(index, "*/")

    # Smooth, general shading driven by the distance field. The field is
    # shape-agnostic: it measures how far each foreground cell is from the
    # nearest background cell, so the same code works for a ring, a cat, a heart,
    # or any input image. Cells on the silhouette darken (sparser characters);
    # the interior grows smoothly dense, giving a continuous 3D curvature without
    # a directional shadow or long uniform runs. A high floor keeps every cell
    # dense enough to read as a solid surface.
    _FLOOR = 0.55
    _D0 = 6.0                                   # distance that reaches full density
    dist = distance_field(grid)

    def shade_char(x: int, y: int) -> str:
        t = min(1.0, dist[y][x] / _D0)
        b = _FLOOR + (1.0 - _FLOOR) * t
        idx = min(len(_SHADE_RAMP) - 1, int(b * len(_SHADE_RAMP)))
        return _SHADE_RAMP[idx]

    def _region_runs(a: int, b: int) -> list[tuple[int, int]]:
        """Runs (pos-index ranges) contained inside [a, b)."""
        out: list[tuple[int, int]] = []
        i = a
        while i < b:
            re = min(_run_end(i), b)
            out.append((i, re))
            i = re
        return out

    def _fill_region(a: int, b: int) -> None:
        """Fill unoccupied cells [a, b) with ONE comment spanning any holes.

        The opening and closing markers each need a run with >= 2 cells; the
        comment body between them can cross holes (the holes are whitespace).
        Short runs that cannot hold a marker at the ends are left blank.
        """
        eligible = [(s, e) for (s, e) in _region_runs(a, b) if e - s >= 2]
        if not eligible:
            return
        os_, oe = eligible[0]
        _cs, ce = eligible[-1]
        if os_ == _cs and oe - os_ < 4:
            return
        _write_marker(os_, "/*")
        _write_marker(ce - 2, "*/")
        for k in range(os_, ce):
            x, y, _ = pos[k]
            if canvas[y][x] == " ":
                canvas[y][x] = shade_char(x, y)

    def fill_all_remaining() -> None:
        """Fill blank foreground cells, one row at a time (comments stay in-row)."""
        p = 0
        while p < len(pos):
            x, y, _ = pos[p]
            if canvas[y][x] != " ":
                p += 1
                continue
            q = p
            while q < len(pos):
                qx, qy, _ = pos[q]
                if qy != y or canvas[qy][qx] != " ":
                    break
                q += 1
            _fill_region(p, q)
            p = q

    # Derive run boundaries (pos-index) from the run ids.
    run_bounds: list[tuple[int, int]] = []
    _rs = 0
    for _idx in range(1, len(pos) + 1):
        if _idx == len(pos) or pos[_idx][2] != pos[_rs][2]:
            run_bounds.append((_rs, _idx))
            _rs = _idx

    # Force-show key features: rows that contain a meaningful internal hole (eyes,
    # ...) are "feature rows". Real code and explanatory comments never land there,
    # so only shade surrounds the hole and it stays a clear blank shape. This is
    # purely geometric and generalizes to any image with enclosed features.
    feature_rows: set[int] = set()
    for _hole in internal_holes(grid):
        if len(_hole) >= 10:
            feature_rows.update(_y for (_x, _y) in _hole)

    # Outer-contour foreground cells (adjacent to the OUTER background, not to an
    # internal hole). A required lexical gap that lands here is replaced by a
    # non-space comment so the silhouette never gets a notch.
    _internal_bg = {p for _hole in internal_holes(grid) for p in _hole}

    def _on_outer_contour(x: int, y: int) -> bool:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < grid.width and 0 <= ny < grid.height):
                return True
            if not grid.at(nx, ny).fg and (nx, ny) not in _internal_bg:
                return True
        return False

    # Group items into statements: each block comment starts a new group and the
    # following code tokens belong to it, so a statement stays in one block.
    groups: list[list] = []
    _cur = None
    for _it in items:
        if _it[0] == "m":
            _cur = []
            groups.append(_cur)
        _cur.append(_it)

    def place_code_item(pi: int, item: tuple, last_code):
        _, text, kind = item
        gap = 1 if (last_code is not None
                    and _needs_space((last_code[1], last_code[2]),
                                     (item[1], item[2]))) else 0
        while True:
            run_end = _run_end(pi)
            if pi >= len(pos):
                raise LayoutLimitError("v2 tokens exceed the available foreground runs")
            if pos[pi][1] in feature_rows:
                pi = run_end                          # keep feature rows code-free
                gap = 0
                continue
            if pi + gap + len(text) <= run_end:
                tail = run_end - (pi + gap + len(text))
                if 0 < tail < 4:
                    # A 1-3 cell tail cannot hold a comment and would notch the
                    # contour; move the token to a later run that fits cleanly.
                    nxt = run_end
                    while nxt < len(pos):
                        nre = _run_end(nxt)
                        if (pos[nxt][1] not in feature_rows
                                and nxt + len(text) <= nre):
                            pi, gap = nxt, 0
                            break
                        nxt = nre
                    else:
                        break
                    continue
                break
            pi = run_end                          # no inline fill; global pass later
            gap = 0
        if gap:
            gx, gy, _ = pos[pi]
            if _on_outer_contour(gx, gy) and pi + 4 <= _run_end(pi):
                # A non-space comment keeps the lexical separation and the
                # silhouette closed where a bare space would notch the contour.
                for m in "/**/":
                    x, y, _ = pos[pi]
                    canvas[y][x] = m
                    pi += 1
            else:
                pi += 1                             # minimal lexical space
        for ch in text:
            x, y, _ = pos[pi]
            canvas[y][x] = ch
            pi += 1
        return pi, item

    # Place statements in order, spread by CELL fraction rather than run count.
    # Run widths vary wildly (a solid shape has wide runs; a ring's runs are
    # split by the hole), so scheduling by run count would overfill wide shapes
    # and starve the last statement. Each group starts at the run nearest to its
    # proportional cell index; every other cell is filled with shaded comments.
    n_groups = len(groups)
    run_starts = [rs for (rs, _re) in run_bounds]

    pi = 0
    last_code = None
    for g, group in enumerate(groups):
        ideal = int(g * len(pos) / n_groups)
        cur_run = pos[pi][2]
        target_rs = pi
        for k, rs in enumerate(run_starts):
            if k < cur_run:
                continue
            if rs <= ideal:
                target_rs = rs
            else:
                break
        if pi < target_rs:
            pi = target_rs                        # skip ahead; global pass fills it
        for it in group:
            if it[0] == "m":
                pi = place_comment(pi, it[1][2:-2])
                last_code = None
            else:
                pi, last_code = place_code_item(pi, it, last_code)

    fill_all_remaining()                          # cover every blank foreground cell

    top = [_HEADER] + list(pre_lines)
    shape_lines = ["".join(row).rstrip() for row in canvas]
    start_line = len(top) + 1
    return top + shape_lines, start_line, 1
