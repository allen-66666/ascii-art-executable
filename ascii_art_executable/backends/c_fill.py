"""c_fill —— C 后端的块注释填充与源码组装（v0 / v1a / v1b），含英文说明注释。

把 B 的 PixelGrid 排成图案行；真实语句（来自 CodeSkeleton）按档位排布，并在每条
真实语句前用 c_doc 生成一句"解释这行作用"的英文注释：
- v0  : 图案由可执行的 printf 逐行打印（运行程序即输出图案），天然保形——形状来自
        真实执行的代码，而不是注释。
- v1a : 图案放进块注释（语句排在其后），100% 保形，核心安全线。
- v1b : 真实语句通过 c_seam 嵌进图案内部空白缝（列对齐零偏移），视觉最像；缝不够宽
        时自动降级回 v1a。

关键边界处理（启动方案 §三·三 / C 预研）：
- 图案行经 c_widthsafe 等宽清洗，杜绝 */ 提前闭合注释；
- # 预处理语句（如 #include）单独占行，且放在 main 之前。
"""

from __future__ import annotations

from typing import Optional

from shared.types import CodeSkeleton, PixelGrid

from ascii_art_executable.backends import c_doc
from ascii_art_executable.backends.c_widthsafe import clean_block, C_SAFE_CHARSET
from ascii_art_executable.backends.c_seam import select_seams, build_seam_row


def build_pattern_rows(grid: PixelGrid, charset: Optional[str] = None) -> list[str]:
    """取出网格的逐行文本；若给定 charset，把每个前景格映射到该字符集。

    确定性、保 fg：前景/背景判定完全沿用 B 的网格（shape 校验不变），只是把
    字形换成后端建议的安全字符集，从源头避免 # * ? \\ 等危险字符。背景格一律空格。
    返回的行已等宽清洗（等长、不含危险序列）。
    """
    rows: list[str] = []
    for y in range(grid.height):
        if charset and len(charset) > 1:
            n = len(charset)
            old_n = max(len(grid.charset), 1)
            rowchars = []
            for x in range(grid.width):
                c = grid.at(x, y)
                if c.fg:
                    idx = int(round(c.level / (old_n - 1) * (n - 1))) if old_n > 1 else n - 1
                    idx = min(n - 1, max(0, idx))
                    rowchars.append(charset[idx])
                else:
                    rowchars.append(" ")
            rows.append("".join(rowchars))
        else:
            rows.append(grid.row(y))
    return clean_block(rows)


def split_skeleton(skeleton: CodeSkeleton):
    """把骨架语句分成 前导预处理(#...) 与 主体(code/decl)。"""
    pre: list[str] = []
    body: list = []
    for st in skeleton.statements:
        text = st.text.strip()
        if st.kind == "preprocessor" or text.startswith("#"):
            pre.append(st.text.rstrip())
        else:
            body.append(st)
    return pre, body


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.splitlines())


def render_v1a(pre_lines: list[str], pattern_rows: list[str],
               body_lines: list[str], documented: bool = True
               ) -> tuple[list[str], int, int]:
    """v1a：预处理单独占行 -> main -> 英文标注的图案块 -> 带英文注释的主体语句 -> return。"""
    lines: list[str] = list(pre_lines)
    lines.append("int main(void) {")
    lines.append("/*")
    if documented:
        lines.append(c_doc.canvas_label())
    start_line = len(lines) + 1                    # 第一行图案所在行（1 起始）
    lines.extend(pattern_rows)
    lines.append("*/")
    for bl in body_lines:
        if documented:
            lines.append("    /* " + c_doc.explain(bl) + " */")
        lines.append(_indent(bl, 4))
    if documented:
        lines.append("    /* " + c_doc.explain("return 0;") + " */")
    lines.append("    return 0;")
    lines.append("}")
    return lines, start_line, 1


def render_v1b(pre_lines: list[str], pattern_rows: list[str],
               body: list, documented: bool = True
               ) -> tuple[list[str], int, int, str] | None:
    """v1b：把主体语句嵌进图案空白缝；返回四元组或 None（无法嵌入时降级）。"""
    single: list = []
    for st in body:
        t = st.text
        if "\n" in t or "*/" in t or "/*" in t:
            return None
        single.append(st)
    seams = select_seams(pattern_rows, single)
    if seams is None:
        return None
    rows = list(pattern_rows)
    for row, s, e, idx in seams:
        rows[row] = build_seam_row(rows[row], s, e, single[idx].text)

    lines: list[str] = list(pre_lines)
    lines.append("int main(void) {")
    lines.append("/*")
    if documented:
        lines.append(c_doc.canvas_label())
    start_line = len(lines) + 1
    lines.extend(rows)
    lines.append("*/")
    if documented:
        lines.append("    /* " + c_doc.explain("return 0;") + " */")
    lines.append("    return 0;")
    lines.append("}")
    return lines, start_line, 1, "v1b"


def render_v0(pre_lines: list[str], pattern_rows: list[str],
              body_lines: list[str], documented: bool = True
              ) -> tuple[list[str], int, int]:
    """v0：图案由可执行的 printf 逐行打印（运行即输出图案），真实代码承载形状。"""
    lines: list[str] = list(pre_lines)
    lines.append("int main(void) {")
    if documented:
        lines.append("    /* Executable pattern: each printf prints one row of the image. */")
    start_line = len(lines) + 1
    for row in pattern_rows:
        esc = row.replace("\\", "/")
        lines.append(f'    printf("{esc}");')
    for bl in body_lines:
        if documented:
            lines.append("    /* " + c_doc.explain(bl) + " */")
        lines.append(_indent(bl, 4))
    if documented:
        lines.append("    /* " + c_doc.explain("return 0;") + " */")
    lines.append("    return 0;")
    lines.append("}")
    return lines, start_line, 1
