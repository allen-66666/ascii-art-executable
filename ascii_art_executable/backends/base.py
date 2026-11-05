"""Backend 抽象基类（A 契约的草稿，C 依据预研落地）。

每个语言后端实现四个方法，公共管线据此无差别调用：
- ``available_canvas(grid, skeleton) -> CanvasPlan``：向目标后端询问可用"自由画布"落点
- ``render_fragment(grid, skeleton, canvas) -> str``：把图案写入落点，产出源码文本
- ``compile_cmd() -> list[str]``：编译命令（如 ["gcc","-fsyntax-only"]）
- ``run_cmd(program) -> list[str]``：运行命令
``fill()`` 是 C/D 共用的公共入口：available_canvas -> render_fragment -> 写盘 -> 回填
``CodeSkeleton`` 的输出信息（output_path/start_line/start_column）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from shared.types import CanvasPlan, CodeSkeleton, PixelGrid


class Backend(ABC):
    """Base class all language backends must inherit (freeze in days 1-3)."""

    lang: str = "c"          # c | cpp | python
    name: str = "backend"

    # -- the four required methods -------------------------------------------
    @abstractmethod
    def available_canvas(self, grid: PixelGrid, skeleton: CodeSkeleton) -> CanvasPlan:
        """Return where the pattern can be written in this language's source."""

    @abstractmethod
    def render_fragment(self, grid: PixelGrid, skeleton: CodeSkeleton,
                        canvas: CanvasPlan) -> str:
        """Return the full generated source text."""

    @abstractmethod
    def compile_cmd(self) -> list:
        """Compiler command (syntax-only check or full build)."""

    @abstractmethod
    def run_cmd(self, program: str) -> list:
        """Command to run the compiled program."""

    # -- shared public entry ------------------------------------------------
    def fill(self, grid: PixelGrid, skeleton: CodeSkeleton,
             plan: Optional[CanvasPlan] = None) -> CodeSkeleton:
        """Default pipeline: plan -> render -> write -> return skeleton with output info.

        Subclasses override to add mode selection (v0/v1a/v1b) or cleaning.
        """
        plan = plan if plan is not None else self.available_canvas(grid, skeleton)
        text = self.render_fragment(grid, skeleton, plan)
        if not skeleton.output_path:
            skeleton.output_path = str(
                Path(skeleton.source_path).with_suffix("." + self.lang))
        Path(skeleton.output_path).write_text(text, encoding="utf-8")
        return skeleton
