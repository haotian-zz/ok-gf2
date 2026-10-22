"""
补读卡片空档（实录 2026-10-22 驻足之地）：「当前」剧情关 DS-1-1 是浅绿底深色字的卡片，整屏 OCR 检测不到，
扫图一直当它不存在，后面的 DA-1-7～1-9 卡在「需要完成前置关卡」。坐标用实机 2560x1440 的识别结果。
"""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).resolve().parents[1] / "src/tasks/ClearMapTask.py"
nodes = [
    n
    for n in ast.parse(source.read_text(encoding="utf-8")).body
    if (isinstance(n, ast.FunctionDef) and n.name in ("card_gaps", "gap_tiles"))
    or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith("GAP_") for t in n.targets))
]
ns = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)
card_gaps, gap_tiles = ns["card_gaps"], ns["gap_tiles"]
W, H = 2560, 1440


def box(name, x, y=684, width=150, height=38):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)


class CardGapTest(unittest.TestCase):
    def test_missing_story_card_falls_in_a_gap(self):
        maps = [box("-1-6", 3, width=101), box("DA-1-7", 1179), box("DA-1-8", 1795), box("DA-1-9", 2405)]
        gaps = card_gaps(maps, W, H)
        hit = [g for g in gaps if g[0] <= 571 and 571 + 120 <= g[1]]
        self.assertEqual(len(hit), 1)  # DS-1-1 的文字（x≈571）在某个空档里
        x0, x1, y0, y1 = hit[0]
        self.assertLess(y0, 684)
        self.assertGreater(y1, 684 + 38)
        tile = int(ns["GAP_TILE"][0] * W)
        self.assertTrue(any(x <= 571 and 571 + 120 <= x + tile for x in gap_tiles(x0, x1, W)))

    def test_rows_are_separate(self):
        """上下两排的卡片各算各的空档，下排的卡不会把上排的空档切掉。"""
        maps = [box("LA-1-1", 600), box("LA-1-2", 1800), box("LZ-1-1", 1200, y=930)]
        top = [g for g in card_gaps(maps, W, H) if g[2] < 700]
        self.assertIn((750, 1800), [(g[0], g[1]) for g in top])

    def test_narrow_gap_ignored(self):
        maps = [box("A", 1000), box("B", 1200)]
        self.assertFalse([g for g in card_gaps(maps, W, H) if g[0] == 1150])

    def test_tiles_stay_on_screen_and_cover_gap(self):
        tile = int(ns["GAP_TILE"][0] * W)
        for x0, x1 in [(0, 696), (2248, 2560), (1000, 1100), (104, 1179)]:
            tiles = gap_tiles(x0, x1, W)
            self.assertTrue(all(0 <= x and x + tile <= W for x in tiles))
            self.assertLessEqual(tiles[0], max(0, x0))
            self.assertGreaterEqual(tiles[-1] + tile, min(x1, W))


if __name__ == "__main__":
    unittest.main()
