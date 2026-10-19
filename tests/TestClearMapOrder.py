"""推图关卡排序、候选选择与调试截图的纯逻辑测试，不依赖设备与 ok-script 运行时。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ok import Box

from src.core.BaseGfTask import map_re
from src.core.debug_shot import save_debug_shot
from src.data.FeatureList import FeatureList as fL
from src.tasks.ClearMapTask import merge_maps, order_maps, pick_candidate


class TestMapRe(unittest.TestCase):
    def test_names(self):
        for name in ["3-1", "SL-3-2", "BH-3-4", "ABC-12-3", "2-5*", "SL-2-1"]:
            self.assertIsNotNone(map_re.search(name), name)
        for name in ["420/240", "300/240", "01/12 回合", "2-", "推荐等级13", "3020"]:
            self.assertIsNone(map_re.search(name), name)


class TestOrderMaps(unittest.TestCase):
    def test_feature_first_then_left_to_right(self):
        maps = [
            Box(300, 10, 10, 10, name="SL-2-1"),
            Box(500, 10, 10, 10, name="2-6"),
            Box(100, 10, 10, 10, name="2-4"),
            Box(900, 10, 10, 10, name=fL.not_clear_one),
        ]
        groups = [{"SL-2-1"}, {"2-6"}, {"2-4"}, {fL.not_clear_one}]
        ordered = order_maps(maps, groups)
        self.assertEqual([m.name for m, _ in ordered], [fL.not_clear_one, "2-4", "SL-2-1", "2-6"])
        # 名字组跟着关卡一起排序
        self.assertEqual([g for _, g in ordered], [{fL.not_clear_one}, {"2-4"}, {"SL-2-1"}, {"2-6"}])

    def test_merge_then_order_keeps_groups_aligned(self):
        maps = [
            Box(800, 100, 10, 10, name="2-5"),
            Box(805, 103, 10, 10, name="2-5*"),
            Box(100, 100, 10, 10, name="2-3"),
        ]
        merged, groups = merge_maps(maps, x_threshold=40, y_threshold=40)
        ordered = order_maps(merged, groups)
        self.assertEqual([m.name for m, _ in ordered], ["2-3", "2-5"])
        self.assertEqual(ordered[1][1], {"2-5", "2-5*"})


class TestPickCandidate(unittest.TestCase):
    def setUp(self):
        self.ordered = [
            (Box(100, 0, 1, 1, name="SL-3-1"), {"SL-3-1"}),
            (Box(400, 0, 1, 1, name="3-1"), {"3-1"}),
            (Box(700, 0, 1, 1, name="SL-3-2"), {"SL-3-2"}),
            (Box(1000, 0, 1, 1, name="3-2"), {"3-2"}),
        ]

    def test_left_to_right_skipping_done_and_locked(self):
        self.assertEqual(pick_candidate(self.ordered, set(), set())[0].name, "SL-3-1")
        self.assertEqual(pick_candidate(self.ordered, {"SL-3-1"}, set())[0].name, "3-1")
        self.assertEqual(pick_candidate(self.ordered, {"SL-3-1"}, {"3-1"})[0].name, "SL-3-2")
        self.assertIsNone(pick_candidate(self.ordered, {"SL-3-1", "SL-3-2", "3-2"}, {"3-1"}))

    def test_cursor_only_moves_right(self):
        # 3-1 已通关作为游标 -> 它左边的 SL-3-1 不再考虑，下一张是右边的 SL-3-2
        self.assertEqual(pick_candidate(self.ordered, {"3-1"}, set(), cursor="3-1")[0].name, "SL-3-2")
        # SL-3-2 未解锁 -> 跳过它继续往右
        self.assertEqual(pick_candidate(self.ordered, {"3-1"}, {"SL-3-2"}, cursor="3-1")[0].name, "3-2")
        # 右边都处理完 -> None
        self.assertIsNone(pick_candidate(self.ordered, {"3-1", "3-2"}, {"SL-3-2"}, cursor="3-1"))

    def test_cursor_not_visible_falls_back_to_leftmost(self):
        self.assertEqual(pick_candidate(self.ordered, set(), set(), cursor="3-9")[0].name, "SL-3-1")

    def test_group_partial_overlap_counts(self):
        ordered = [(Box(100, 0, 1, 1, name="2-5"), {"2-5", "2-5*"})]
        self.assertIsNone(pick_candidate(ordered, {"2-5*"}, set()))


class TestDebugShot(unittest.TestCase):
    def test_save_and_rotate(self):
        frame = np.zeros((72, 128, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as root:
            paths = [
                save_debug_shot(frame, "推图", f"tag{i}", [Box(1, 1, 5, 5, name="n")], root=root, max_files=3)
                for i in range(5)
            ]
            self.assertTrue(all(p.endswith(".jpg") for p in paths))
            self.assertTrue(os.path.exists(paths[-1]))
            remaining = [f for _, _, files in os.walk(os.path.join(root, "推图")) for f in files]
            self.assertEqual(len(remaining), 3)
            self.assertFalse(os.path.exists(paths[0]))

    def test_none_frame(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(save_debug_shot(None, "推图", "x", root=root))


if __name__ == "__main__":
    unittest.main()
