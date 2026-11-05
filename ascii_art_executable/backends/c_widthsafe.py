"""c_widthsafe —— C 后端的等宽清洗（保形校验的前置依赖）。

F 的 ``check_shape`` 会按目标宽度重新渲染生成文件、比对关键字符列位置。如果清洗
过程改变某行长度，列位置必然偏移，保形校验必失败。因此所有危险字符替换都必须
保持 1:1 宽度（一个字符换一个字符）。

本模块覆盖 C 画布里的危险模式（C 预研 §四）：
- ``*/``  -> ``*|``   （块注释提前闭合，编译报 stray；替换后宽度不变）
- ``??``  -> ``?~``   （三字符组/trigraph 触发，等价于反斜杠行拼接；防 C23 之前标准）
- ``\\``  -> ``/``    （行注释末尾反斜杠会把下一行吞进注释，静默改变行为）
- ``#``   -> ``+``    （画布内裸 # 落在会被解释的位置时，使预处理指令失效）

说明：对纯 ``/* */`` 块注释画布，真正必须防的只有 ``*/`` 序列（``#``/``\\`` 在块注释
内其实无害）；本模块按预研的保守策略统一清洗，同时提供 ``safe_charset`` 让 B 在源头
避免危险字符，从而让清洗成为空操作、不损失图案密度（见 C 预研 §九问题3）。

用法：``from ascii_art_executable.backends.c_widthsafe import clean_comment_row``
"""

from __future__ import annotations


def clean_comment_row(row: str) -> str:
    """等宽清洗一行图案文本：逐字符替换，行长不变（1 个字符换 1 个字符）。

    返回的新行与原行等长。顺序处理：
    1. ``*/`` -> ``*|``（两字符 -> 两字符）
    2. ``??`` -> ``?~``（两字符 -> 两字符）
    3. ``\\`` -> ``/``、``#`` -> ``+``（单字符 -> 单字符）
    """
    out: list[str] = []
    i, n = 0, len(row)
    while i < n:
        pair = row[i:i + 2]
        if pair == "*/":
            out.append("*|")
            i += 2
            continue
        if pair == "??":
            out.append("?~")
            i += 2
            continue
        ch = row[i]
        if ch == "\\":
            out.append("/")
        elif ch == "#":
            out.append("+")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def assert_width_preserved(original: str, cleaned: str) -> bool:
    """校验清洗前后行长一致（保形前提）。"""
    return len(original) == len(cleaned)


# 建议给 B 的安全字符集：避开 C 画布中的危险字符（* ? \\ # / " ' 等）
# 疏 -> 密。用它在源头出图可让 c_widthsafe 变为空操作，且不损失密度。
C_SAFE_CHARSET = " .:-=+%oO"


def clean_block(lines: list[str]) -> list[str]:
    """批量等宽清洗多行图案。"""
    return [clean_comment_row(line) for line in lines]
