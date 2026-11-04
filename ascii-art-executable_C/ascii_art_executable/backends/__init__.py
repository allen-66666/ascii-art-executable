"""C 语言后端包（owner C）。

- base        : Backend 抽象基类（A 契约草稿）
- c_widthsafe : 等宽清洗（保形前置依赖）
- c_seam      : 保列接缝（v1b：语句嵌入图案）
- c_doc       : 解释代码作用的英文注释
- c_parser    : 把真实 C 源码解析成 CodeSkeleton
- c_fill      : 块注释填充 + 源码组装（v0/v1a/v1b）
- c_backend   : CBackend 完整实现（fill / verify / 编译器探测）
- shaper      : 高层入口（代码 + 图片 -> 保形代码）
"""

from ascii_art_executable.backends.base import Backend
from ascii_art_executable.backends.c_backend import CBackend, make_hello_skeleton
from ascii_art_executable.backends.shaper import shape_code

__all__ = ["Backend", "CBackend", "make_hello_skeleton", "shape_code"]
