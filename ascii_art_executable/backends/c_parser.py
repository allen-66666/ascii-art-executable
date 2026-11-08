"""c_parser —— 把一段真实 C 源码解析成 CodeSkeleton（"代码 + 图片"入口的前半段）。

启动方案里 C 的输入是"解析好的 CodeSkeleton"。本模块提供一个轻量的行级解析器，
让用户直接给一段 C 代码文本即可，不必手工构造骨架：逐行分类（预处理 / 代码），
保留原始行号（start_line，1 起始），空行跳过。不追求完整 C 语法，只覆盖课程项目
中"逐行语句"的简单程序；复杂多行结构按其首行归类，仍可被后续填充使用。
"""

from __future__ import annotations

import codecs
import locale
import re
from pathlib import Path

from shared.types import CodeSkeleton, Statement


class SourceInputError(RuntimeError):
    """Raised when the supplied source is not supported C input.

    Mirrors the structured Diagnostic shape of ``LayoutLimitError``: a
    machine-readable ``code``, ``stage``, optional line/column and ``details``.
    """

    def __init__(self, message: str, *, code: str = "UNSUPPORTED_SOURCE",
                 stage: str = "input", line: int | None = None,
                 column: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.stage = stage
        self.line = line
        self.column = column
        self.details = dict(details) if details else {}


# Python (and other non-C) block headers that end a line with a colon. C never
# opens if/for/while/... blocks with a trailing colon.
_PY_BLOCK_RE = re.compile(
    r"^\s*(if|elif|else|for|while|def|try|except|finally|with|class)\b.*:\s*$")
# A C entry point: "main" optionally followed by whitespace then "(".
_MAIN_RE = re.compile(r"\bmain\s*\(")


def read_c_source(path) -> str:
    """Read a C source file, detecting its text encoding without crashing.

    On-disk files may be UTF-8 (with or without a BOM) or a legacy ANSI code
    page (for example GBK/cp936 on Chinese Windows).  The bytes are decoded in
    order: an explicit UTF-8 BOM, strict UTF-8, the system ANSI code page, then
    Latin-1 (which maps every byte), so a ``str`` is always returned.  The
    content is still validated separately by :func:`validate_c_source`, which
    rejects non-ASCII C with an actionable message instead of a raw
    ``UnicodeDecodeError``.
    """
    raw = Path(path).read_bytes()

    # 1) Explicit UTF-8 BOM.
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8):].decode("utf-8")

    # 2) Plain UTF-8, the documented and preferred encoding.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # 3) Legacy ANSI code page (cp936/GBK on Chinese Windows, cp1252 elsewhere).
    candidates = [locale.getpreferredencoding(False), "cp936", "latin-1"]
    for encoding in dict.fromkeys(c for c in candidates if c):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def validate_c_source(code_text: str, *, filename: str | None = None) -> None:
    """Validate that the input is supported, executable C source.

    Raises ``SourceInputError`` with an actionable message instead of letting a
    non-C language (e.g. Python) be silently rearranged into a wrong file. The
    checks are content based, so they also catch a Python file renamed to .c.

    - Non-ASCII characters are rejected (the C contract is printable ASCII);
    - clear Python syntax (def, colon block headers, triple-quoted strings);
    - a C ``main`` entry point must be present.
    """
    if not code_text or not code_text.strip():
        raise SourceInputError("the source is empty; please provide a C source file",
                               code="INVALID_SOURCE")

    lines = code_text.splitlines()
    for line_no, raw in enumerate(lines, start=1):
        # 1) Non-ASCII: report the first offending character precisely.
        for col, ch in enumerate(raw, start=1):
            if ord(ch) > 127:
                raise SourceInputError(
                    "non-ASCII character found. This tool only supports "
                    "printable-ASCII C source; save the file as ASCII/UTF-8 and "
                    "replace non-ASCII text (such as Chinese comments or string "
                    "literals) with ASCII characters, then retry.",
                    code="UNSUPPORTED_SOURCE", line=line_no, column=col,
                    details={"filename": filename or "", "character": ch})
        # 2) Unambiguous Python syntax.
        stripped = raw.strip()
        if stripped.startswith("def ") or '"""' in stripped or _PY_BLOCK_RE.match(raw):
            raise SourceInputError(
                "this looks like Python (or another language), not C. The engine "
                "rearranges existing C tokens and cannot translate Python to C; "
                "please provide a .c source file.",
                code="UNSUPPORTED_SOURCE", line=line_no,
                details={"filename": filename or "", "line_text": stripped})

    # 3) An executable C program needs a main entry point; otherwise the v2 path
    # would emit an empty main that just returns 0 and loses the real behavior.
    if not any(_MAIN_RE.search(raw) for raw in lines):
        raise SourceInputError(
            "no C 'main' entry point was found. This tool shapes an executable C "
            "program and cannot translate Python; please provide a .c file with main.",
            code="INVALID_SOURCE", details={"filename": filename or ""})


def parse_c_source(code_text: str, source_path: str = "parsed.c") -> CodeSkeleton:
    """Parse raw C source text into a CodeSkeleton with per-line Statements."""
    sk = CodeSkeleton(source_path=source_path, lang="c")
    for line_no, raw in enumerate(code_text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        kind = "preprocessor" if stripped.startswith("#") else "code"
        sk.statements.append(Statement(text=raw.rstrip(), start_line=line_no,
                                       end_line=line_no, kind=kind))
    return sk


def extract_main_parts(code_text: str) -> tuple[list[str], list[str]]:
    """Split a complete C program into (preprocessor lines, statements inside main).

    The high-level "code + image" entry uses this so the backend can rebuild the
    ``main`` wrapper itself without duplicating it. The opening/closing main line,
    braces and the trailing ``return`` are excluded; the executable statements that
    carry the program's real behavior are kept.
    """
    pre: list[str] = []
    body: list[str] = []
    depth = 0
    in_main = False
    for raw in code_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            pre.append(raw.rstrip())
            continue
        if not in_main:
            if "main(" in s:
                in_main = True
                depth += s.count("{") - s.count("}")
            continue
        opens, closes = s.count("{"), s.count("}")
        if closes and depth + opens - closes <= 0:       # this line closes main
            in_main = False
            depth = 0
            continue
        depth += opens - closes
        if s.startswith("return"):
            continue
        body.append(s)
    return pre, body
