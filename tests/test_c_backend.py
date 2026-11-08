"""C 后端测试：填充结构、等宽清洗、保列接缝、保形校验、端到端(gcc 可选)。

pytest-compatible；也可独立运行（无 pytest 时自动用内置 runner）：
    python tests/test_c_backend.py
其中真实调用 gcc 的端到端用例在找不到编译器时会自动 skip 并注明（启动方案降级策略）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ascii_art_executable.backends import CBackend, make_hello_skeleton  # noqa: E402
from ascii_art_executable.backends.c_widthsafe import (  # noqa: E402
    C_SAFE_CHARSET, clean_comment_row, assert_width_preserved,
)
from ascii_art_executable.backends.c_seam import (  # noqa: E402
    build_seam_row, find_blank_runs, needed_width, select_seams,
)
from ascii_art_executable.backends.c_fill import render_v1a, render_v1b  # noqa: E402
from ascii_art_executable.backends.c_tokenfill import (  # noqa: E402
    _SHADE_RAMP, recommend_width, LayoutLimitError, distance_field,
    internal_holes, recommend_feature_width, recommend_width_for,
    feature_report, LAYOUT_MAX_WIDTH, LAYOUT_MAX_ATTEMPTS,
    repair_outer_silhouette,
)
from ascii_art_executable.backends.shaper import shape_code  # noqa: E402
from ascii_art_executable.backends.c_parser import (  # noqa: E402
    validate_c_source, SourceInputError, read_c_source,
)
from ascii_art_executable.grid import build_grid  # noqa: E402
from ascii_art_executable.shapecheck import check_shape  # noqa: E402
from shared.types import Statement  # noqa: E402

import pytest  # noqa: E402


# ---------------------------------------------------------------- helpers --

def _cat_grid(max_w: int = 72):
    from PIL import Image, ImageDraw
    tmp = Path(tempfile.mkdtemp(prefix="c-test-"))
    p = tmp / "cat.png"
    im = Image.new("L", (400, 400), 0)
    d = ImageDraw.Draw(im)
    d.ellipse([80, 80, 320, 320], fill=255)
    im.save(p)
    return build_grid(p, max_w=max_w)


def _ring_png(folder=None) -> Path:
    """Write an elliptical annulus PNG and return its path."""
    from PIL import Image, ImageDraw
    if folder is None:
        folder = Path(tempfile.mkdtemp(prefix="c-ring-"))
    p = Path(folder) / "ring.png"
    S = 480
    im = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(im)
    rx, ry = int(S * 0.46), int(S * 0.46 * 0.72)
    d.ellipse([S//2-rx, S//2-ry, S//2+rx, S//2+ry], fill=255)
    ix, iy = int(rx*0.45), int(ry*0.45)
    d.ellipse([S//2-ix, S//2-iy, S//2+ix, S//2+iy], fill=0)
    im.save(p)
    return p


def _ring_grid(max_w: int = 60):
    """An elliptical annulus (donut) so most runs are filled by the shade ramp."""
    return build_grid(_ring_png(), max_w=max_w)


# --------------------------------------------------------------- widthsafe --

class TestWidthSafe:
    def test_danger_sequences_removed(self):
        assert clean_comment_row("a*/b") == "a*|b"
        assert clean_comment_row("x??y") == "x?~y"
        assert clean_comment_row("a\\b") == "a/b"
        assert clean_comment_row("a#b") == "a+b"

    def test_width_preserved(self):
        for s in ["a*/b", "a\\b", "a#b", "x??y", "*/", "####", "\\\\"]:
            c = clean_comment_row(s)
            assert assert_width_preserved(s, c) and len(c) == len(s)

    def test_safe_charset_has_no_danger(self):
        assert "#" not in C_SAFE_CHARSET and "*" not in C_SAFE_CHARSET
        assert "\\" not in C_SAFE_CHARSET and "?" not in C_SAFE_CHARSET


# ------------------------------------------------------------------- seam --

class TestSeam:
    def test_find_blank_runs(self):
        runs = find_blank_runs(["ab  cd", "      ", "ab"])
        assert runs[0] == [(2, 4)]
        assert runs[1] == [(0, 6)]
        assert runs[2] == []

    def test_build_seam_preserves_width_and_align(self):
        # 缝 [2,10)，语句 len=4，需 12 -> 这里 run_w=8 不够 -> 用更宽的
        row = "ab      cd"        # 8 格背景，len(row)=10
        # 语句 "int i;" len=6 -> need 14；改用 run 足够的情况
        row2 = "ab            cd"  # 背景宽 12, row2 长 16
        s, e = 2, 14
        stmt = "int i;"
        out = build_seam_row(row2, s, e, stmt)
        assert len(out) == len(row2)          # 行长不变
        assert out[:2] == "ab" and out[-2:] == "cd"   # 左右图案保留
        # 右段仍从原列号开始：cd 在 out 的位置 == e == 14
        assert out.index("cd") == 14

    def test_needed_width(self):
        assert needed_width("int i;") == len("int i;") + 8

    def test_select_seams_ascending_order(self):
        rows = [" " * 20, "  abc            ", " " * 20]   # 每行都有一条 >=18 的空缝
        stmts = [Statement("puts(\"A\");", 1), Statement("puts(\"B\");", 2)]
        seams = select_seams(rows, stmts)
        assert seams is not None
        # 行号严格升序 -> 语句顺序与源顺序一致
        rows_idx = [se[0] for se in seams]
        assert rows_idx == sorted(rows_idx)
        assert [se[3] for se in seams] == [0, 1]            # 语句按原始顺序填入

    def test_select_seams_returns_none_when_no_room(self):
        rows = ["abc", "abc", "abc"]          # 无空缝
        stmts = [Statement("puts(\"A\");", 1)]
        assert select_seams(rows, stmts) is None


# ------------------------------------------------------------------ fill --

class TestFill:
    def test_v1a_structure(self):
        pre = ["#include <stdio.h>"]
        rows = ["ab", "cd"]
        lines, sl, sc = render_v1a(pre, rows, ['puts("hello");'])
        # sl points at the first pattern row
        assert lines[sl - 1] == rows[0]
        assert sc == 1
        # 预处理单独占行且在 main 之前
        assert lines[0] == "#include <stdio.h>"
        assert lines[1].startswith("int main")
        # 真实语句带英文解释注释
        assert any("standard output" in ln for ln in lines)

    def test_fill_v1a_passes_shape(self, tmp_path):
        grid = _cat_grid(48)
        sk = make_hello_skeleton(str(tmp_path / "s"), text="hi")
        sk.output_path = str(tmp_path / "out.c")
        sk = CBackend().fill(grid, sk, mode="v1a")
        # 读生成文件，用 F 校验保形
        rep = check_shape(sk.output_path, grid, start_line=sk.start_line,
                          start_column=sk.start_column)
        assert rep.passed, rep.message

    def test_fill_v1a_strict_background(self, tmp_path):
        # v1a 背景应干净 -> min_precision=1.0 也能过
        grid = _cat_grid(48)
        sk = make_hello_skeleton(str(tmp_path / "s"))
        sk.output_path = str(tmp_path / "out.c")
        sk = CBackend().fill(grid, sk, mode="v1a")
        rep = check_shape(sk.output_path, grid, start_line=sk.start_line,
                          start_column=sk.start_column, min_precision=1.0)
        assert rep.passed, rep.message

    def test_fill_auto_uses_v1b_when_possible(self, tmp_path):
        # 猫图有很多空缝 -> auto 应落到 v1b（或至少生成合法文件）
        grid = _cat_grid(72)
        sk = make_hello_skeleton(str(tmp_path / "s"))
        sk.output_path = str(tmp_path / "out.c")
        sk = CBackend().fill(grid, sk, mode="auto")
        src = Path(sk.output_path).read_text(encoding="utf-8")
        assert sk.used_mode in ("v1a", "v1b")
        # 保形仍通过
        rep = check_shape(sk.output_path, grid, start_line=sk.start_line,
                          start_column=sk.start_column)
        assert rep.passed, rep.message

    def test_fill_degrade_when_no_seam(self, tmp_path):
        # 全实心 -> 无空缝 -> v1b 降级 v1a，仍可保形
        from PIL import Image
        tmp = Path(tempfile.mkdtemp(prefix="c-test-"))
        p = tmp / "solid.png"
        Image.new("L", (60, 30), 255).save(p)
        grid = build_grid(p, max_w=60)
        sk = make_hello_skeleton(str(tmp_path / "s"))
        sk.output_path = str(tmp_path / "out.c")
        sk = CBackend().fill(grid, sk, mode="auto")
        assert sk.used_mode == "v1a"
        rep = check_shape(sk.output_path, grid, start_line=sk.start_line,
                          start_column=sk.start_column)
        assert rep.passed, rep.message

    def test_interface_statement_carries_start_line(self):
        # C 预研：语句必须带 start_line（顺序反转 bug 的接口需求）
        st = Statement("puts(\"x\");", start_line=3)
        assert st.start_line == 3


# --------------------------------------------------------- token v2 --------

HAS_CC = not CBackend.detect_compiler().needs_degrade


class TestTokenV2:
    def test_v2_packs_real_tokens_with_clean_background(self, tmp_path):
        grid = _cat_grid(48)
        sk = make_hello_skeleton(str(tmp_path / "s"), text="hello")
        sk.output_path = str(tmp_path / "out.c")
        sk = CBackend().fill(grid, sk, mode="v2")
        assert sk.used_mode == "v2"
        rep = check_shape(sk.output_path, grid, start_line=sk.start_line,
                          start_column=sk.start_column)
        # Real tokens carry the shape; no background pollution (precision 100%),
        # and the only blank foreground cells are required inter-token spaces.
        assert rep.precision == 1.0
        assert rep.recall >= 0.95

    def test_v2_exports_canvas_geometry(self, tmp_path):
        grid = _cat_grid(48)
        sk = make_hello_skeleton(str(tmp_path / "s"))
        sk.output_path = str(tmp_path / "out.c")
        sk = CBackend().fill(grid, sk, mode="v2")
        # Review report action item: canvas start (1-based) + width/height exported.
        assert sk.start_line >= 1 and sk.start_column >= 1
        assert sk.canvas_width == grid.width
        assert sk.canvas_height == grid.height

    def test_v2_shade_ramp_is_safe_and_used(self, tmp_path):
        # The ramp must never contain a character that could break a comment.
        for bad in ("*", "/", "?", "\\"):
            assert bad not in _SHADE_RAMP
        grid = _ring_grid(60)
        sk = make_hello_skeleton(str(tmp_path / "s"))
        sk.output_path = str(tmp_path / "out.c")
        CBackend().fill(grid, sk, mode="v2")
        text = Path(sk.output_path).read_text(encoding="utf-8")
        used = {ch for ch in text if ch in _SHADE_RAMP}
        # Several distinct ramp levels appear, confirming a gradient is drawn.
        assert len(used) >= 4

    def test_v2_solid_shape_with_wide_runs_does_not_overflow(self, tmp_path):
        # Regression: a solid (non-ring) shape has wide runs; scheduling by run
        # count used to fill the whole canvas and raise LayoutLimitError.
        grid = _cat_grid(60)
        sk = make_hello_skeleton(str(tmp_path / "s"))
        sk.output_path = str(tmp_path / "out.c")
        CBackend().fill(grid, sk, mode="v2")
        text = Path(sk.output_path).read_text(encoding="utf-8")
        # Every block comment stays balanced and no stray markers appear.
        assert text.count("/*") == text.count("*/")
        assert "/*/" not in text

    @pytest.mark.skipif(not HAS_CC, reason="本机无 gcc/clang，跳过真实编译运行")
    def test_v2_compiles_runs_and_keeps_behavior(self, tmp_path):
        grid = _cat_grid(48)
        sk = make_hello_skeleton(str(tmp_path / "s"), text="hello")
        sk.output_path = str(tmp_path / "out.c")
        backend = CBackend()
        sk = backend.fill(grid, sk, mode="v2")
        v = backend.verify(sk.output_path, grid, start_line=sk.start_line,
                           start_column=sk.start_column, expected_stdout="hello\n")
        assert v["compile_ok"] is True, v.get("note")
        assert v["run_ok"] is True
        assert v["output_match"] is True


# --------------------------------------------------------- e2e (gcc) ------


class TestE2E:
    @pytest.mark.skipif(not HAS_CC, reason="本机无 gcc/clang，跳过真实编译运行")
    def test_compile_run_output_shape(self, tmp_path):
        grid = _cat_grid(72)
        sk = make_hello_skeleton(str(tmp_path / "s"), text="hello")
        sk.output_path = str(tmp_path / "out.c")
        backend = CBackend()
        sk = backend.fill(grid, sk, mode="auto")
        v = backend.verify(sk.output_path, grid, start_line=sk.start_line,
                           start_column=sk.start_column, expected_stdout="hello\n")
        assert v["compile_ok"] is True, v.get("note")
        assert v["run_ok"] is True
        assert v["output_match"] is True
        assert v["shape"].passed, v["shape"].message


class TestV13Features:
    def test_recommend_width_is_deterministic_and_fits_token(self):
        code = '#include <stdio.h>\nint main(void){printf("a 16-char string");}\n'
        w1 = recommend_width(code)
        w2 = recommend_width(code)
        assert w1 == w2                                   # deterministic
        assert 40 <= w1 <= LAYOUT_MAX_WIDTH
        # The width must leave a run wide enough for the longest token.
        longest = max(len('"a 16-char string"'), 1)
        assert w1 * 0.28 >= longest

    def test_layout_limits_and_exception(self):
        assert issubclass(LayoutLimitError, RuntimeError)
        assert LAYOUT_MAX_WIDTH > 0 and LAYOUT_MAX_ATTEMPTS > 0

    def test_layout_error_carries_structured_diagnostic(self):
        # Backward-compatible single-arg form keeps a default code and empty details.
        plain = LayoutLimitError("boom")
        assert str(plain) == "boom"
        assert plain.code == "LAYOUT_LIMIT" and plain.details == {}
        # The full form carries a code, stage and a details dict (v1.4 Diagnostic).
        rich = LayoutLimitError("nope", code="LAYOUT_TIMEOUT", stage="layout",
                                details={"attempt_history": [{"width": 40}]})
        assert rich.code == "LAYOUT_TIMEOUT" and rich.stage == "layout"
        assert rich.details["attempt_history"][0]["width"] == 40
        assert isinstance(rich, RuntimeError)

    def test_distance_field_is_general_and_oriented(self):
        # Background cells are distance sources (0); foreground grows positive.
        grid = _ring_grid(60)
        field = distance_field(grid)
        for y in range(grid.height):
            for x in range(grid.width):
                if grid.at(x, y).fg:
                    assert field[y][x] > 0.0          # foreground has a real distance
                else:
                    assert field[y][x] == 0.0         # background is the zero source

    def test_internal_holes_are_geometric_and_general(self):
        # A ring has exactly one enclosed hole; a solid disk has none.
        ring_holes = internal_holes(_ring_grid(60))
        assert len(ring_holes) == 1
        assert all(0 <= x < 60 and 0 <= y < 60 for (x, y) in ring_holes[0])
        assert internal_holes(_cat_grid(60)) == []      # solid disk: no enclosed hole

    def test_feature_width_and_combined_recommendation(self, tmp_path):
        img = _ring_png(tmp_path)
        fw = recommend_feature_width(str(img))
        assert 40 <= fw <= LAYOUT_MAX_WIDTH
        code = '#include <stdio.h>\nint main(void){puts("hi");}\n'
        combined = recommend_width_for(code, str(img))
        assert combined >= recommend_width(code)
        assert combined >= fw

    def test_feature_report_structure(self):
        rep = feature_report(_ring_grid(60))
        assert rep["holes"] >= 1
        assert set(rep) == {"holes", "sizes", "undersized", "ok"}

    def test_outer_contour_is_closed_around_internal_holes(self, tmp_path):
        # A solid rectangle with two enclosed "eye" holes; every outer-contour
        # foreground cell must be occupied after the v2 fill.
        from shared.types import GridCell, PixelGrid
        W, H = 44, 20
        mask = [[True] * W for _ in range(H)]
        for (hx, hy) in ((12, 7), (28, 7)):
            for dy in range(4):
                for dx in range(5):
                    mask[hy + dy][hx + dx] = False
        cells = tuple(GridCell(x, y, mask[y][x], 0, "#" if mask[y][x] else " ")
                      for y in range(H) for x in range(W))
        grid = PixelGrid(width=W, height=H, cells=cells, charset=" .:-=+%oO",
                         source="test-eyes")
        assert len(internal_holes(grid)) == 2

        sk = make_hello_skeleton(str(tmp_path / "s"))
        sk.output_path = str(tmp_path / "out.c")
        CBackend().fill(grid, sk, mode="v2")
        lines = Path(sk.output_path).read_text(encoding="utf-8").splitlines()
        rows = [ln.ljust(W) for ln in lines[sk.start_line - 1:]]
        internal_bg = {p for h in internal_holes(grid) for p in h}
        for y in range(H):
            for x in range(W):
                if not grid.at(x, y).fg:
                    continue
                on_outer = any(
                    (not (0 <= nx < W and 0 <= ny < H))
                    or (not grid.at(nx, ny).fg and (nx, ny) not in internal_bg)
                    for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)))
                if on_outer:
                    assert not rows[y][x].isspace(), f"gap at ({x},{y})"

    def test_repair_bounds_deep_outer_notches_and_keeps_holes(self):
        # A solid block whose middle rows have a deep side notch (whisker-like
        # gap), plus an enclosed hole. The repair must bound the notch and leave
        # the internal hole exactly as it was.
        from shared.types import GridCell, PixelGrid
        W, H = 30, 12
        mask = [[True] * W for _ in range(H)]
        for y in range(4, 8):                    # deep left notch
            for x in range(0, 18):
                mask[y][x] = False
        for dy in range(2):                      # enclosed hole
            for dx in range(3):
                mask[2 + dy][22 + dx] = False
        cells = tuple(GridCell(x, y, mask[y][x], 0, "#" if mask[y][x] else " ")
                      for y in range(H) for x in range(W))
        grid = PixelGrid(width=W, height=H, cells=cells, charset=" .:-=+%oO",
                         source="test-notch")
        before = sorted(len(h) for h in internal_holes(grid))
        repaired = repair_outer_silhouette(grid, max_notch=4)
        after = sorted(len(h) for h in internal_holes(repaired))
        assert before == after                  # internal hole untouched
        # The notch edge can recede at most 2*max_notch (envelope slope) vs
        # the solid rows above/below; it was 18 before repair.
        for y in range(4, 8):
            xs = [x for x in range(W) if repaired.at(x, y).fg]
            assert min(xs) <= 8
        assert repaired.at(4, 4).fg and repaired.at(4, 7).fg   # first/last bounded
        assert repaired.fg_count > grid.fg_count

    def test_shape_code_uses_injected_builder_and_backend(self, tmp_path):
        class _FakeGrid:
            width, height = 40, 20
        class _FakeBackend:
            def __init__(self):
                self.seen = None
            def fill(self, grid, sk, mode="auto"):
                self.seen = (grid, mode)
                sk.used_mode = "fake"
                return sk
        sentinel = _FakeGrid()
        fake_backend = _FakeBackend()
        sk, grid = shape_code(
            'int main(void){puts("hi");}',
            str(tmp_path / "img.png"), str(tmp_path / "out.c"),
            grid_builder=lambda image_path, charset=None, max_w=None: sentinel,
            backend=fake_backend, mode="v2")
        assert grid is sentinel
        assert fake_backend.seen == (sentinel, "v2")
        assert sk.used_mode == "fake"

    def test_shape_code_retries_grows_width_and_records_attempt(self, tmp_path):
        class _FakeGrid:
            def __init__(self, w):
                self.width, self.height = w, max(1, w // 2)
        seen_widths = []

        def _builder(image_path, charset=None, max_w=None):
            seen_widths.append(max_w)
            return _FakeGrid(max_w)

        class _FlakyBackend:
            def __init__(self):
                self.calls = 0
            def fill(self, grid, sk, mode="auto"):
                self.calls += 1
                if self.calls == 1:
                    raise LayoutLimitError("does not fit yet")
                sk.used_mode = "v2"
                return sk

        backend = _FlakyBackend()
        sk, grid = shape_code(
            'int main(void){puts("x");}',
            str(tmp_path / "img.png"), str(tmp_path / "out.c"),
            grid_builder=_builder, backend=backend, mode="v2", max_w=40)
        assert backend.calls == 2                       # first failure, then success
        assert seen_widths[0] == 40 and seen_widths[1] > 40
        assert len(sk.attempt_history) == 1
        record = sk.attempt_history[0]
        assert record["reason"] == "does not fit yet"
        assert record["width"] == 40 and record["height"] == 20
        assert record["elapsed_s"] >= 0.0

    def test_shape_code_failure_keeps_attempt_history_in_details(self, tmp_path):
        class _FakeGrid:
            def __init__(self, w):
                self.width, self.height = w, 10

        def _builder(image_path, charset=None, max_w=None):
            return _FakeGrid(max_w)

        class _AlwaysFailing:
            def fill(self, grid, sk, mode="auto"):
                raise LayoutLimitError("never fits")

        with pytest.raises(LayoutLimitError) as caught:
            shape_code(
                'int main(void){puts("x");}',
                str(tmp_path / "img.png"), str(tmp_path / "out.c"),
                grid_builder=_builder, backend=_AlwaysFailing(),
                mode="v2", max_w=40)
        err = caught.value
        assert err.code == "LAYOUT_LIMIT"
        history = err.details["attempt_history"]
        assert len(history) >= 2                        # bounded but retried
        assert all({"width", "height", "reason", "elapsed_s"} <= set(r)
                   for r in history)
        assert all(r["reason"] == "never fits" for r in history)


class TestInputValidation:
    def test_valid_c_program_passes(self):
        code = '#include <stdio.h>\nint main(void){puts("ok"); return 0;}\n'
        validate_c_source(code)                       # no exception

    def test_empty_source_rejected(self):
        with pytest.raises(SourceInputError) as caught:
            validate_c_source("   \n")
        assert caught.value.code == "INVALID_SOURCE"

    def test_non_ascii_rejected_with_position(self):
        # The Chinese in a Python comment is the exact garbled-comment failure.
        code = '# 以下为测试部分\nint main(void){return 0;}\n'
        with pytest.raises(SourceInputError) as caught:
            validate_c_source(code)
        err = caught.value
        assert err.code == "UNSUPPORTED_SOURCE"
        assert err.line == 1 and err.column is not None

    def test_python_syntax_rejected(self):
        py = 'def f(n):\n    return n + 1\n'
        with pytest.raises(SourceInputError) as caught:
            validate_c_source(py)
        assert caught.value.code == "UNSUPPORTED_SOURCE"

    def test_python_colon_block_rejected(self):
        py = 'while True:\n    break\n'
        with pytest.raises(SourceInputError) as caught:
            validate_c_source(py)
        assert caught.value.code == "UNSUPPORTED_SOURCE"

    def test_missing_main_rejected(self):
        code = '#include <stdio.h>\nint helper(void){return 1;}\n'
        with pytest.raises(SourceInputError) as caught:
            validate_c_source(code)
        assert caught.value.code == "INVALID_SOURCE"

    def test_shape_code_rejects_python_instead_of_bad_file(self, tmp_path):
        with pytest.raises(SourceInputError):
            shape_code('def f(x):\n    return x\n',
                       str(tmp_path / "img.png"), str(tmp_path / "out.c"),
                       mode="v2")
        # No output file is written when the input is rejected.
        assert not Path(tmp_path / "out.c").exists()

    def test_read_gbk_file_does_not_crash_and_then_validates(self, tmp_path):
        # A legacy ANSI/GBK file (the exact UnicodeDecodeError report) must be
        # decoded to text rather than crashing the frozen entry point.
        source = '// 中文注释\nint main(void){return 0;}\n'
        gbk_path = tmp_path / "legacy.c"
        gbk_path.write_bytes(source.encode("gbk"))

        decoded = read_c_source(gbk_path)
        assert "int main" in decoded
        with pytest.raises(SourceInputError) as caught:
            validate_c_source(decoded)
        assert caught.value.code == "UNSUPPORTED_SOURCE"

    def test_read_utf8_bom_strips_bom(self, tmp_path):
        bom_path = tmp_path / "bom.c"
        bom_path.write_bytes(b'\xef\xbb\xbfint main(void){return 0;}\n')
        decoded = read_c_source(bom_path)
        assert decoded.startswith("int main")
        validate_c_source(decoded)

    def test_read_plain_utf8(self, tmp_path):
        plain_path = tmp_path / "plain.c"
        plain_path.write_bytes(b'int main(void){return 0;}\n')
        decoded = read_c_source(plain_path)
        assert decoded == "int main(void){return 0;}\n"


if __name__ == "__main__":
    import inspect
    import tempfile as _tf
    import traceback

    tmp = Path(_tf.mkdtemp(prefix="c-run-"))
    total = fail = skip = 0
    collected = []
    for name, obj in sorted(globals().items()):
        if isinstance(obj, type) and name.startswith("Test"):
            try:
                inst = obj()
            except Exception:
                continue
            for m in dir(obj):
                if m.startswith("test_"):
                    collected.append((name + "." + m, getattr(inst, m)))
        elif name.startswith("test_") and callable(obj):
            collected.append((name, obj))

    def _call(fn, label):
        params = inspect.signature(fn).parameters
        if "tmp_path" in params:
            fn(tmp)
        else:
            fn()

    for label, fn in collected:
        total += 1
        if "TestE2E" in label and not HAS_CC:
            skip += 1
            print(f"SKIP  {label} (no compiler)")
            continue
        try:
            _call(fn, label)
            print(f"PASS  {label}")
        except Exception:
            fail += 1
            print(f"FAIL  {label}")
            traceback.print_exc()
    print(f"\n{total - fail - skip}/{total} passed ({skip} skipped)")
    raise SystemExit(1 if fail else 0)
