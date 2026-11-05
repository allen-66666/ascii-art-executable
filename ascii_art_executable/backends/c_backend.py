"""c_backend —— CBackend 完整实现（C 角色的主交付物）。

对外契约（启动方案 §六·三）：``CBackend(Backend) + fill(grid, skeleton, plan)``
消费 B 的 ``PixelGrid``，产出可编译、能运行、输出正确、且被 F 的 ``check_shape``
判定保形的 C 源文件。

档位（C 预研 §七，自动选择）：
- ``mode="auto"``（默认）：先试 v1b（语句嵌进图案），缝不够宽自动降级 v1a。
- ``mode="v1a"``：图案在块注释、语句在其后，100% 保形（核心安全线）。
- ``mode="v1b"``：强制语句嵌入（失败则降级 v1a）。
- ``mode="v0"``：图案放进字符串逐行 printf（兜底）。

编译器策略（启动方案 §三·三）：优先探测 gcc / clang；缺失时 ``verify`` 自动降级为
"只做保形与结构校验并明确提示"，不假装编译通过。本机（Windows）通常无 gcc，
端到端编译运行在有编译器的机器上执行。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from shared.types import CanvasPlan, CodeSkeleton, CompilerInfo, PixelGrid, ShapeReport

from ascii_art_executable.backends.base import Backend
from ascii_art_executable.backends.c_fill import (
    build_pattern_rows,
    render_v0,
    render_v1a,
    render_v1b,
    split_skeleton,
)
from ascii_art_executable.backends.c_tokenfill import render_v2
from ascii_art_executable.backends.c_widthsafe import C_SAFE_CHARSET
from ascii_art_executable.shapecheck import check_shape


class CBackend(Backend):
    lang = "c"
    name = "CBackend"

    def __init__(self, safe_charset: str = C_SAFE_CHARSET):
        self.safe_charset = safe_charset

    # -- 编译器探测 ----------------------------------------------------------
    # Known fallback locations even when the compiler is not on PATH (e.g. Dev-C++).
    _KNOWN_GCC = (
        r"C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\gcc.exe",
        r"C:\Program Files\Dev-Cpp\MinGW64\bin\gcc.exe",
        r"C:\Dev-Cpp\MinGW64\bin\gcc.exe",
    )

    @classmethod
    def detect_compiler(cls) -> CompilerInfo:
        # 1) gcc / clang on PATH
        for kind, exe in (("gcc", "gcc"), ("clang", "clang")):
            p = shutil.which(exe)
            if p:
                return cls._info(kind, p)
        # 2) bundled MinGW gcc from Dev-C++ (and similar fixed locations)
        for p in cls._KNOWN_GCC:
            if Path(p).is_file():
                return cls._info("gcc", p)
        return CompilerInfo(kind="", path="", needs_degrade=True)

    @staticmethod
    def _info(kind: str, path: str) -> CompilerInfo:
        try:
            import subprocess
            ver = subprocess.run([path, "--version"], capture_output=True,
                                 text=True, timeout=10).stdout.splitlines()[0]
        except Exception:
            ver = ""
        return CompilerInfo(kind=kind, path=path, version=ver, needs_degrade=False)

    # -- Backend 四方法 ------------------------------------------------------
    def available_canvas(self, grid: PixelGrid, skeleton: CodeSkeleton) -> CanvasPlan:
        return CanvasPlan(lang="c",
                          block_comments=[(2, 2 + grid.height + 1, 1, grid.width)],
                          safe_charset=self.safe_charset)

    def render_fragment(self, grid: PixelGrid, skeleton: CodeSkeleton,
                        canvas: CanvasPlan) -> str:
        # render_fragment 实现 v1a 语义（确定性、保形）；fill() 负责档位选择。
        rows = build_pattern_rows(grid, self.safe_charset)
        pre, body = split_skeleton(skeleton)
        body_lines = [st.text for st in body]
        lines, _start, _col, _ = render_v1a(pre, rows, body_lines)
        return "\n".join(lines) + "\n"

    def compile_cmd(self) -> Optional[list]:
        ci = self.detect_compiler()
        if ci.needs_degrade:
            return None
        return [ci.path, "-fsyntax-only", "-std=c11"]

    def run_cmd(self, program: str) -> Optional[list]:
        ci = self.detect_compiler()
        if ci.needs_degrade:
            return None
        return [program]

    # -- C 角色主入口 --------------------------------------------------------
    def fill(self, grid: PixelGrid, skeleton: CodeSkeleton,
             plan: Optional[CanvasPlan] = None, *,
             mode: str = "auto") -> CodeSkeleton:
        """生成 C 源文件，回填 skeleton 的输出路径与图案区域位置。"""
        plan = plan if plan is not None else self.available_canvas(grid, skeleton)
        rows = build_pattern_rows(grid, self.safe_charset)
        pre, body = split_skeleton(skeleton)
        body_lines = [st.text for st in body]

        if mode == "v2":
            lines, start_line, start_col = render_v2(pre, body, grid)
            used = "v2"
        elif mode == "v0":
            lines, start_line, start_col = render_v0(pre, rows, body_lines)
            used = "v0"
        elif mode == "v1a":
            lines, start_line, start_col = render_v1a(pre, rows, body_lines)
            used = "v1a"
        elif mode in ("v1b", "auto"):
            res = render_v1b(pre, rows, body)
            if res is not None:
                lines, start_line, start_col, used = res
            else:
                lines, start_line, start_col = render_v1a(pre, rows, body_lines)
                used = "v1a"
        else:
            raise ValueError(f"unknown mode: {mode}")

        if not skeleton.output_path:
            skeleton.output_path = str(
                Path(skeleton.source_path).with_suffix(".c"))
        Path(skeleton.output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        skeleton.start_line = start_line
        skeleton.start_column = start_col
        skeleton.canvas_width = grid.width
        skeleton.canvas_height = grid.height
        skeleton.used_mode = used
        skeleton.lang = "c"
        return skeleton

    # -- 端到端校验（编译 + 运行 + 保形），无编译器自动降级 --------------------
    def verify(self, source: str, grid: PixelGrid, *,
               start_line: int, start_column: int = 1,
               expected_stdout: Optional[str] = None,
               min_precision: float = 0.0) -> dict:
        import subprocess

        ci = self.detect_compiler()
        shape = check_shape(source, grid, start_line=start_line,
                            start_column=start_column, min_precision=min_precision)
        result = {"compiler": ci, "shape": shape, "compile_ok": None,
                  "run_ok": None, "output_match": None, "actual_stdout": None,
                  "note": ""}

        if ci.needs_degrade:
            result["note"] = ("未找到 gcc/clang：跳过编译与运行比对，仅做保形校验。"
                              "在有编译器的机器上运行 scripts/demo_c.py 会补齐该步。")
            return result

        src_path = Path(source)
        exe = src_path.with_suffix(".exe" if os_name() == "nt" else "")
        build = [ci.path, "-std=c11", "-o", str(exe), str(src_path)]
        try:
            comp = subprocess.run(build, capture_output=True, text=True,
                                  errors="replace", timeout=60)
            result["compile_ok"] = comp.returncode == 0
            if not result["compile_ok"]:
                result["note"] = "gcc 编译失败：" + comp.stderr.strip()[:300]
                return result
            run = subprocess.run([str(exe)], capture_output=True, text=True,
                                 errors="replace", timeout=30)
            result["run_ok"] = run.returncode == 0
            result["actual_stdout"] = run.stdout
            if expected_stdout is not None:
                result["output_match"] = (run.stdout == expected_stdout)
        except Exception as exc:                       # 编译/运行环境异常
            result["compile_ok"] = None
            result["note"] = f"compile/run interrupted: {exc}"
        return result


def os_name() -> str:
    import sys
    return "nt" if sys.platform == "win32" else "posix"


def make_hello_skeleton(source_path: str = "hello_skeleton",
                        text: str = "hello") -> CodeSkeleton:
    """构造一个最简单的 C 骨架：输出一句话（demo 与测试用）。"""
    s = CodeSkeleton(source_path=source_path, lang="c")
    s.statements.append(StatementFactory.preprocessor(f"#include <stdio.h>", 1))
    s.statements.append(StatementFactory.code(f'    puts("{text}");', 2))
    return s


class StatementFactory:
    @staticmethod
    def preprocessor(text: str, line: int):
        from shared.types import Statement
        return Statement(text=text, start_line=line, end_line=line,
                         kind="preprocessor")

    @staticmethod
    def code(text: str, line: int):
        from shared.types import Statement
        return Statement(text=text, start_line=line, end_line=line, kind="code")
