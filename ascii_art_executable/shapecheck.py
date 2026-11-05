"""F: shape checking with B's PixelGrid and heuristic layout detection."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import io
import json
from pathlib import Path
import re
import tokenize
from typing import Sequence

from shared.types import DetectionReport, PixelGrid, ShapeReport


def _target(grid: PixelGrid | Sequence[str]) -> tuple[list[str], list[list[bool]]]:
    if isinstance(grid, PixelGrid):
        if grid.width <= 0 or grid.height <= 0:
            raise ValueError("PixelGrid dimensions must be positive")
        if len(grid.cells) != grid.width * grid.height:
            raise ValueError("PixelGrid cell count does not match dimensions")
        rows, mask = [], []
        for y in range(grid.height):
            chars, flags = [], []
            for x in range(grid.width):
                cell = grid.at(x, y)
                if (cell.x, cell.y) != (x, y):
                    raise ValueError("PixelGrid cells must be in row-major coordinate order")
                if len(cell.ch) != 1:
                    raise ValueError("each PixelGrid cell must contain one character")
                chars.append(cell.ch)
                flags.append(cell.fg)
            rows.append("".join(chars))
            mask.append(flags)
    else:
        if isinstance(grid, (str, bytes)):
            raise ValueError("grid must be PixelGrid or a sequence of string rows")
        rows = list(grid)
        if not rows or not all(isinstance(row, str) for row in rows):
            raise ValueError("grid must contain at least one string row")
        width = max(map(len, rows))
        if width == 0:
            raise ValueError("grid must have nonzero width")
        rows = [row.ljust(width) for row in rows]
        mask = [[not ch.isspace() for ch in row] for row in rows]
    if any(any(ord(ch) < 32 or ord(ch) > 126 for ch in row) for row in rows):
        raise ValueError("shape grid must use printable single-column ASCII")
    return rows, mask


def check_shape(
    path: str | Path,
    grid: PixelGrid | Sequence[str],
    *,
    start_line: int = 1,
    start_column: int = 1,
    mode: str = "occupancy",
    max_mismatches: int = 50,
    min_precision: float = 0.0,
) -> ShapeReport:
    """Compare a rectangular target grid with source positions (1-based origin).

    PixelGrid.fg is authoritative; string-row input uses non-space foreground.
    In occupancy mode any
    non-space source character matches; in exact mode the character must match.
    Extra source characters are reported but do not fail the check: syntax
    delimiters and program tokens may need to occupy background cells. Set
    min_precision to reject excessive background occupancy (e.g. 1.0 for none).
    """
    if start_line < 1 or start_column < 1 or max_mismatches < 0:
        raise ValueError("origin must be 1-based and max_mismatches non-negative")
    if mode not in ("occupancy", "exact"):
        raise ValueError("mode must be 'occupancy' or 'exact'")
    if not 0.0 <= min_precision <= 1.0:
        raise ValueError("min_precision must be between 0 and 1")
    rows, mask = _target(grid)
    width = len(rows[0])
    if mode == "exact" and any(
        mask[y][x] and ch.isspace()
        for y, row in enumerate(rows) for x, ch in enumerate(row)
    ):
        raise ValueError("exact mode cannot check an invisible foreground glyph")
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    expected = matched = extra = occupied = 0
    mismatches: list[dict] = []
    for y, row in enumerate(rows):
        index = start_line - 1 + y
        source = lines[index] if index < len(lines) else ""
        # Tabs have no fixed visual width, so callers must resolve them first.
        # Validate the prefix as well: it determines the target region's columns.
        if any(ord(ch) < 32 or ord(ch) > 126
               for ch in source[:start_column - 1 + width]):
            raise ValueError(f"non-ASCII or tab in target source line {index + 1}")
        for x, target in enumerate(row):
            pos = start_column - 1 + x
            actual = source[pos] if pos < len(source) else " "
            occupied += not actual.isspace()
            if mask[y][x]:
                expected += 1
                ok = not actual.isspace() and (mode == "occupancy" or actual == target)
                if ok:
                    matched += 1
                elif len(mismatches) < max_mismatches:
                    mismatches.append({"line": index + 1, "column": pos + 1,
                                       "expected": target, "actual": actual})
            elif not actual.isspace():
                extra += 1
    missing = expected - matched
    # An empty target is not meaningful evidence of shape preservation.
    precision = matched / occupied if occupied else 0.0
    passed = expected > 0 and missing == 0 and precision >= min_precision
    return ShapeReport(
        passed, expected, matched, missing, extra,
        matched / expected if expected else 0.0,
        precision,
        mismatches,
        "No foreground pixels in target" if not expected else
        ("All target positions matched" if passed else
         ("Target positions missing or changed" if missing else "Background occupancy exceeds threshold")),
        width, len(rows), expected / (width * len(rows)), occupied / (width * len(rows)),
    )


def _c_comments(text: str) -> list[tuple[int, str]]:
    """Extract C-family comments while skipping quoted literals."""
    result: list[tuple[int, str]] = []
    i, line, n = 0, 1, len(text)
    while i < n:
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            result.append((line, text[i:end]))
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            comment = text[i:end]
            result.append((line, comment))
            line += comment.count("\n")
            i = end
        elif text[i] in "'\"":
            quote = text[i]
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    line += text[i + 1] == "\n"
                    i += 2
                elif text[i] == quote:
                    i += 1
                    break
                else:
                    line += text[i] == "\n"
                    i += 1
        else:
            line += text[i] == "\n"
            i += 1
    return result


def _python_comments(text: str) -> list[tuple[int, str]]:
    result = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                result.append((token.start[0], token.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Keep the comments found before the lexical error; detect is not a parser.
        pass
    return result


def detect(path: str | Path, *, language: str | None = None) -> DetectionReport:
    """Describe file density and flag comment lines with art-like punctuation.

    This is an explainable heuristic, not proof that a comment is redundant.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if language is None:
        language = {".py": "python", ".c": "c", ".h": "c", ".cpp": "cpp",
                    ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp"}.get(path.suffix.lower())
    if language not in ("c", "cpp", "python"):
        raise ValueError("language must be c, cpp, or python")
    lines = text.splitlines()
    # Tab expansion is fixed at 8 columns for density; shape checking rejects tabs.
    visual = [line.expandtabs(8) for line in lines]
    width = max(map(len, visual), default=0)
    occupied = sum(sum(not ch.isspace() for ch in line) for line in visual)
    total = width * len(visual)
    comments = _python_comments(text) if language == "python" else _c_comments(text)
    flagged = []
    for first_line, comment in comments:
        for offset, row in enumerate(comment.splitlines()):
            body = re.sub(r"^\s*(?://|/\*|#|\*)|\*/\s*$", "", row).strip()
            if len(body) >= 4:
                symbols = sum(not ch.isalnum() and not ch.isspace() for ch in body)
                if symbols >= 4 and symbols / len(body) >= 0.5:
                    flagged.append({"line": first_line + offset, "text": row.strip(),
                                    "reason": "high proportion of punctuation in comment"})
    return DetectionReport(
        language, len(lines), width, occupied, total,
        occupied / total if total else 0.0,
        sum(len(comment) for _, comment in comments),
        sum(ch.isspace() for ch in text),
        flagged,
        "Heuristic only; comments may be meaningful. C++ raw strings, line splicing "
        "and complex preprocessing are not fully parsed. Density covers the whole file.",
    )


def render_report(report: ShapeReport | DetectionReport) -> str:
    """Render a concise, plain-text report suitable for CLI and log output."""
    if isinstance(report, ShapeReport):
        state = "PASS" if report.passed else "FAIL"
        return (f"Shape: {state}\n"
                f"Matched: {report.matched_pixels}/{report.expected_pixels} "
                f"({report.recall:.1%}); extra cells: {report.extra_pixels}\n"
                f"Precision: {report.precision:.1%}\n{report.message}")
    flagged = "\n".join(
        f"  line {item['line']}: {item['text']}" for item in report.suspicious_lines
    ) or "  none"
    return (f"Detection: {report.language}\n"
            f"Density: {report.occupied_cells}/{report.total_cells} ({report.density:.1%})\n"
            f"Comment characters: {report.comment_characters}; "
            f"whitespace characters: {report.whitespace_characters}\n"
            f"Art-like comment lines: {len(report.suspicious_lines)}\n{flagged}\n"
            f"Note: {report.limitations}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Shape and heuristic detection tools")
    sub = parser.add_subparsers(dest="command", required=True)
    shape = sub.add_parser("shape")
    shape.add_argument("source")
    shape.add_argument("grid", help="UTF-8 text file containing the target grid")
    shape.add_argument("--line", type=int, default=1)
    shape.add_argument("--column", type=int, default=1)
    shape.add_argument("--mode", choices=["occupancy", "exact"], default="occupancy")
    shape.add_argument("--min-precision", type=float, default=0.0)
    detection = sub.add_parser("detect")
    detection.add_argument("source")
    detection.add_argument("--language", choices=["c", "cpp", "python"])
    for command in (shape, detection):
        command.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "shape":
            grid = Path(args.grid).read_text(encoding="utf-8").splitlines()
            result = check_shape(args.source, grid, start_line=args.line,
                                 start_column=args.column, mode=args.mode,
                                 min_precision=args.min_precision)
        else:
            result = detect(args.source, language=args.language)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2) if args.json
          else render_report(result))
    return 1 if isinstance(result, ShapeReport) and not result.passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
