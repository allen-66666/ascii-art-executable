"""F tests, including integration with B's actual build_grid."""

import tempfile
import unittest
from pathlib import Path

from ascii_art_executable.grid import build_grid
from ascii_art_executable.shapecheck import check_shape, detect, render_report
from shared.types import GridCell, PixelGrid, ShapeReport


class ShapeCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sample.c"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_offset(self):
        self.write("/*\n  ## \n  #x#\n*/\n")
        result = check_shape(self.path, ["## ", "# #"], start_line=2, start_column=3)
        self.assertIsInstance(result, ShapeReport)
        self.assertTrue(result.passed)
        self.assertEqual((result.expected_pixels, result.extra_pixels), (4, 1))
        self.assertIn("PASS", render_report(result))

    def test_background_threshold(self):
        self.write("###\n")
        self.assertTrue(check_shape(self.path, ["# #"]).passed)
        self.assertFalse(check_shape(self.path, ["# #"], min_precision=1).passed)

    def test_shift_is_caught(self):
        self.write(" ##\n")
        result = check_shape(self.path, ["##"])
        self.assertFalse(result.passed)
        self.assertEqual(result.mismatches[0]["column"], 1)

    def test_exact_mismatch_affects_precision(self):
        self.write("xy\n")
        result = check_shape(self.path, ["xx"], mode="exact")
        self.assertFalse(result.passed)
        self.assertEqual(result.precision, 0.5)

    def test_missing_line(self):
        self.write("#\n")
        self.assertEqual(check_shape(self.path, ["#", "#"]).missing_pixels, 1)

    def test_empty_foreground(self):
        self.write(" \n")
        self.assertFalse(check_shape(self.path, [" "]).passed)

    def test_invalid_inputs(self):
        self.write("#\n")
        for grid in ([], [""], "##", ["\t"], ["界"]):
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                check_shape(self.path, grid)
        with self.assertRaises(ValueError):
            check_shape(self.path, ["#"], start_line=0)
        with self.assertRaises(ValueError):
            check_shape(self.path, ["#"], min_precision=float("nan"))

    def test_tab_in_source_prefix(self):
        self.write("\t#\n")
        with self.assertRaises(ValueError):
            check_shape(self.path, ["#"], start_column=2)

    def test_mismatch_limit_preserves_counts(self):
        self.write("    \n")
        result = check_shape(self.path, ["####"], max_mismatches=1)
        self.assertEqual(result.missing_pixels, 4)
        self.assertEqual(len(result.mismatches), 1)

    def test_pixelgrid_uses_fg_even_when_glyph_is_space(self):
        grid = PixelGrid(2, 1, (
            GridCell(0, 0, True, 0, " "),
            GridCell(1, 0, False, 0, " "),
        ), " #", "mock")
        self.write("  \n")
        self.assertFalse(check_shape(self.path, grid).passed)
        self.write("# \n")
        self.assertTrue(check_shape(self.path, grid).passed)
        with self.assertRaises(ValueError):
            check_shape(self.path, grid, mode="exact")

    def test_malformed_pixelgrid(self):
        grid = PixelGrid(2, 1, (), " #", "mock")
        self.write("##\n")
        with self.assertRaises(ValueError):
            check_shape(self.path, grid)
        grid = PixelGrid(1, 1, (GridCell(1, 0, True, 1, "#"),), " #", "mock")
        with self.assertRaises(ValueError):
            check_shape(self.path, grid)

    def test_B_cat_grid_and_damaged_copy(self):
        cat = Path(__file__).resolve().parents[1] / "demo" / "cat.png"
        grid = build_grid(cat, max_w=48)
        # This is a layout fixture, not the C backend's generated output.
        rows = ["".join("#" if grid.at(x, y).fg else " "
                        for x in range(grid.width)) for y in range(grid.height)]
        self.write("/*\n" + "\n".join(rows) + "\n*/\nint main(void){return 0;}\n")
        result = check_shape(self.path, grid, start_line=2, min_precision=1)
        self.assertTrue(result.passed)
        self.assertEqual(result.expected_pixels, grid.fg_count)
        self.assertEqual(result.target_density, grid.density)
        cell = next(c for c in grid.cells if c.fg)
        rows[cell.y] = rows[cell.y][:cell.x] + " " + rows[cell.y][cell.x + 1:]
        self.write("/*\n" + "\n".join(rows) + "\n*/\n")
        self.assertEqual(check_shape(self.path, grid, start_line=2).missing_pixels, 1)

    def test_B_inverted_grid(self):
        cat = Path(__file__).resolve().parents[1] / "demo" / "cat.png"
        grid = build_grid(cat, max_w=24, invert=True)
        self.write("\n".join("".join("#" if grid.at(x, y).fg else " "
                                    for x in range(grid.width))
                             for y in range(grid.height)) + "\n")
        self.assertTrue(check_shape(self.path, grid).passed)

    def test_B_slogan_grid(self):
        grid = build_grid("F", max_w=32)
        self.write(grid.render() + "\n")
        self.assertTrue(check_shape(self.path, grid, mode="exact").passed)

    def test_comments_skip_literals(self):
        self.write('char *s = "/* #### */";\n/* #### */\n')
        result = detect(self.path)
        self.assertEqual([x["line"] for x in result.suspicious_lines], [2])

    def test_python_comments(self):
        self.path = self.path.with_suffix(".py")
        self.write('x = "# ####"\n# ####\n')
        self.assertEqual([x["line"] for x in detect(self.path).suspicious_lines], [2])

    def test_empty_detect(self):
        self.write("")
        self.assertEqual(detect(self.path).density, 0)


if __name__ == "__main__":
    unittest.main()
