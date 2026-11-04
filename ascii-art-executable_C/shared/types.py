"""Shared data structures for the ASCII Art Executable project.

Contract rules (from 启动方案 §六):
- Every cross-module object lives here; all members import from here, no private copies.
- Interfaces freeze in days 1-3. After the freeze, only backward-compatible
  additions are allowed; changing existing signatures is forbidden.

Ownership (per 启动方案 §五):
- ``PixelGrid``            — drafted by B (图案输入与字符画), ready for the day 1-3 freeze.
- ``GridCell``             — drafted by B.
- ``CodeSkeleton``         — owner C (this file now fills the placeholder).
- ``CanvasPlan``           — owner A (base) + C/D (per backend); C fills the C case.
- ``VerifyReport``         — owner E. NOTE: the original placeholder had a
                             ``shape_ok: bool = Optional[bool]`` bug; fixed here to
                             ``Optional[bool] = None`` so an unchecked state is not
                             truthy. (F's review also flagged this.)
- ``CompilerInfo``         — owner E.
- ``ShapeReport``          — added by F (检测器 + 图案保形), backward-compatible.
- ``DetectionReport``      — added by F, backward-compatible.
- ``Statement``            — added by C: one real statement in the skeleton, must
                             carry its original ``start_line`` (see C 预研: 顺序反转 bug).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# B's deliverable: the downsampled character grid
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GridCell:
    """One cell of the character grid — one character position in the source."""

    x: int          # column, 0-based
    y: int          # row, 0-based
    fg: bool        # True = 前景（需占用）, False = 背景（可留空）
    level: int      # density index, 0 <= level < len(charset)
    ch: str         # final glyph: charset[level] for fg, ' ' for background


@dataclass
class PixelGrid:
    """Downsampled target pattern, row-major cells, size bounded by max_w.

    Producers : B's ``build_grid(src, charset, max_w)``
    Consumers : C / D backends (fill foreground cells), F's shape check.
    """

    width: int
    height: int
    cells: tuple[GridCell, ...]   # index = y * width + x
    charset: str                  # density chars, sparse -> dense, first char ~ blank
    source: str                   # image path or slogan text, for reporting
    threshold: float = 128.0      # gray level (0-255) separating fg from bg

    def at(self, x: int, y: int) -> GridCell:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"({x}, {y}) out of {self.width}x{self.height}")
        return self.cells[y * self.width + x]

    def row(self, y: int) -> str:
        return "".join(self.cells[y * self.width + x].ch for x in range(self.width))

    def render(self) -> str:
        return "\n".join(self.row(y) for y in range(self.height))

    @property
    def fg_count(self) -> int:
        return sum(1 for c in self.cells if c.fg)

    @property
    def density(self) -> float:
        """Foreground ratio 0.0-1.0, used by F's 图案密度 report."""
        return self.fg_count / len(self.cells) if self.cells else 0.0


# ---------------------------------------------------------------------------
# C's deliverable: the parsed functional code skeleton
# ---------------------------------------------------------------------------

@dataclass
class Statement:
    """One real statement/declaration from the functional code skeleton.

    ``start_line`` (1-based, in the original skeleton) MUST be present and usable:
    the C 预研 showed a greedy seam-filler reordered statements because it lacked
    this line number. The filler assigns statements to seams in ascending row
    order to preserve execution order.
    """

    text: str
    start_line: int = 0       # 1-based original line, required (0 means "not placed")
    end_line: int = 0
    kind: str = "code"        # code | preprocessor | decl | comment


@dataclass
class CodeSkeleton:
    """Parsed functional code skeleton: real statements + original positions. (owner: C)

    ``output_path`` / ``start_line`` / ``start_column`` are set by C's ``fill()``:
    they describe where the generated source lives and where the pattern region
    begins (1-based), which F's ``check_shape`` needs.
    """

    source_path: str
    lang: str = "c"                                    # c | cpp | python
    statements: list = field(default_factory=list)     # list[Statement]
    fixed_regions: list = field(default_factory=list)  # regions only statements may occupy
    output_path: str = ""                              # filled by C backend
    start_line: int = 1                                # pattern region 1-based start line
    start_column: int = 1                              # pattern region 1-based start column
    canvas_width: int = 0                              # pattern region width in columns
    canvas_height: int = 0                             # pattern region height in rows
    used_mode: str = ""                                # "v1a" | "v1b" | "v0", for reporting
    attempt_history: list = field(default_factory=list)  # v1.4: one AttemptRecord per retry


# ---------------------------------------------------------------------------
# A's base / C·D per backend: free-canvas landing points
# ---------------------------------------------------------------------------

@dataclass
class CanvasPlan:
    """Backend's free-canvas landing points. (owner: A for the base, C/D per backend)

    C uses ``block_comments``: a list of (start_line, end_line, start_col, end_col)
    giving where the pattern can be written as block-comment content (1-based).
    ``safe_charset`` lets the backend suggest a charset that avoids characters
    dangerous in that language's canvas (see C 预研 §九问题3).
    """

    lang: str = "c"
    block_comments: list = field(default_factory=list)   # (start_line, end_line, start_col, end_col)
    string_lands: list = field(default_factory=list)     # string-literal landing points
    raw_strings: list = field(default_factory=list)      # C++ R"( )" intervals
    paren_regions: list = field(default_factory=list)    # Python implicit-line-join spans
    safe_charset: str = ""                               # suggested backend-safe charset


# ---------------------------------------------------------------------------
# E's placeholder (bug fixed) / structures
# ---------------------------------------------------------------------------

@dataclass
class VerifyReport:
    """Aggregate of the three checks: compile / run-stdout / shape. (owner: E)"""

    path: str
    compile_ok: bool = False
    run_ok: bool = False
    output_match: bool = False
    shape_ok: Optional[bool] = None   # FIXED: was ``bool = Optional[bool]`` (truthy bug)
    failed_items: list = field(default_factory=list)
    note: str = ""                    # e.g. degraded mode when no compiler found


@dataclass
class CompilerInfo:
    """Detected compiler: path, version, whether verify must degrade. (owner: E)"""

    kind: str = ""                    # gcc | g++ | clang | clang++ | cl
    path: str = ""
    version: str = ""
    needs_degrade: bool = False


# ---------------------------------------------------------------------------
# F's reports (additive; B's PixelGrid and E's VerifyReport are unchanged)
# ---------------------------------------------------------------------------

@dataclass
class ShapeReport:
    passed: bool
    expected_pixels: int
    matched_pixels: int
    missing_pixels: int
    extra_pixels: int
    recall: float
    precision: float
    mismatches: list[dict]
    message: str
    width: int = 0
    height: int = 0
    target_density: float = 0.0
    actual_density: float = 0.0


@dataclass
class DetectionReport:
    language: str
    lines: int
    width: int
    occupied_cells: int
    total_cells: int
    density: float
    comment_characters: int
    whitespace_characters: int
    suspicious_lines: list[dict]
    limitations: str
