"""ASCII Art Executable — public pipeline package.

Module owners per 启动方案 §五:
- B: grid (image/slogan -> PixelGrid)   -> 图案输入与字符画
- C: backends.c (C 后端与主力填充引擎)   -> this phase
- D: backends.{cpp,python}  (可选后端)
- E: verify + cli  (校验循环与命令行)
- F: shapecheck  (检测器 + 图案保形)
"""

from shared.types import GridCell, PixelGrid
from ascii_art_executable.grid import DEFAULT_CHARSET, build_grid

__all__ = ["DEFAULT_CHARSET", "GridCell", "PixelGrid", "build_grid"]
