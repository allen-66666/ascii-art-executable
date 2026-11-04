"""c_seam —— 保列接缝（v1b 核心：真实语句嵌入图案内部，且不破坏列对齐）。

启动方案 v1 最难的要求是"真实语句嵌在图案内部"。把一条语句插进图案的空白缝时，
行内结构为：``<左段图案>*/ 语句 /*<右段图案>``，其中 ``*/`` 关闭注释、``/*`` 重开。

宽度守恒的充要条件（C 预研 §五）：所选空白缝宽度 ≥ 语句长度 + 8。
- 脚手架开销："*/"(2) + 空格(1) + 语句 + 空格(1) + "/*"(2) = 语句长度 + 6；
  预留 2 个额外空格 => 需求 = 语句长度 + 8。
- 中段实际填充：``*/`` + 空格 + 语句 + 空格 + ``/*``，剩余宽度用空格补足，
  使右段图案仍从原列号起，零偏移。

顺序反转 bug 的修复（C 预研 §六）：两阶段选行。
- 第一阶段：按行号升序一次性选定全部接缝行（每条语句分配到"行号最小且缝够宽"的行）；
- 第二阶段：按语句原始顺序依次填入。
因为接缝行按行号升序、语句按原始顺序一一对应，执行顺序必然与骨架一致
（语句 0 在最上面的缝、语句 N 在最下面的缝）。

降级：找不到足够宽的缝时 ``select_seams`` 返回 None，由上层回退到 v1a
（语句排在图案注释之后）。
"""

from __future__ import annotations

from typing import Optional


def find_blank_runs(rows: list[str]) -> list[list[tuple[int, int]]]:
    """返回每行的"背景空白段"（0 起始列，end 开区间）。空白 = 空格字符。

    只有背景段（fg=False）才安全插入语句，插入不会吃掉前景格。
    """
    runs: list[list[tuple[int, int]]] = []
    for row in rows:
        r: list[tuple[int, int]] = []
        i, n = 0, len(row)
        while i < n:
            if row[i] == " ":
                j = i
                while j < n and row[j] == " ":
                    j += 1
                r.append((i, j))
                i = j
            else:
                i += 1
        runs.append(r)
    return runs


def needed_width(stmt_text: str) -> int:
    """一条语句在缝里需要的最小宽度：语句长度 + 8（脚手架 + 两边留白）。"""
    return len(stmt_text) + 8


def select_seams(rows: list[str], statements: list,
                 start_row: int = 0) -> Optional[list[tuple[int, int, int, int]]]:
    """两阶段选行：返回 ``[(row, start_col, end_col, stmt_index), ...]``，行号升序。

    - 每条语句（按原始顺序）落到"当前已用行之下、行号最小且缝够宽"的行；
    - 保证语句执行顺序与骨架一致；
    - 任一条放不下返回 None（上层降级到 v1a）。
    """
    runs = find_blank_runs(rows)
    seams: list[tuple[int, int, int, int]] = []
    used = start_row - 1
    for idx, st in enumerate(statements):
        need = needed_width(st.text)
        chosen = None
        for row in range(max(used + 1, start_row), len(rows)):
            for s, e in runs[row]:
                if e - s >= need:
                    chosen = (row, s, e)
                    break
            if chosen is not None:
                break
        if chosen is None:
            return None
        seams.append((chosen[0], chosen[1], chosen[2], idx))
        used = chosen[0]
    return seams


def build_seam_row(row: str, s: int, e: int, stmt_text: str) -> str:
    """把语句插入 ``[s, e)`` 空白缝，行长保持原长（右段零偏移）。

    ``row`` 必须是已经等宽清洗过的行（不含 ``*/``）。若语句文本含 ``*/`` / ``/*`` /
    换行，调用方应视为不可嵌入并降级（此处不校验，交给上层）。
    """
    left, right = row[:s], row[e:]
    run_w = e - s
    sp_total = run_w - len(stmt_text) - 4        # 4 = "*/"+"/*" 的 2+2
    sp1 = sp_total // 2
    sp2 = sp_total - sp1
    return left + "*/" + " " * sp1 + stmt_text + " " * sp2 + "/*" + right
