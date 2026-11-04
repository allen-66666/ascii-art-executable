"""c_parser —— 把一段真实 C 源码解析成 CodeSkeleton（"代码 + 图片"入口的前半段）。

启动方案里 C 的输入是"解析好的 CodeSkeleton"。本模块提供一个轻量的行级解析器，
让用户直接给一段 C 代码文本即可，不必手工构造骨架：逐行分类（预处理 / 代码），
保留原始行号（start_line，1 起始），空行跳过。不追求完整 C 语法，只覆盖课程项目
中"逐行语句"的简单程序；复杂多行结构按其首行归类，仍可被后续填充使用。
"""

from __future__ import annotations

from shared.types import CodeSkeleton, Statement


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
