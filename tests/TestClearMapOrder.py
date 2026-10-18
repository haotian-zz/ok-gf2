"""推图关卡排序与调试截图的纯逻辑测试，不依赖设备与 ok-script 运行时。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ok import Box

from src.core.debug_shot import save_debug_shot
from src.data.FeatureList import FeatureList as fL
from src.tasks.ClearMapTask import is_branch_group, merge_maps, order_maps, pick_candidate


class TestOrderMaps(unittest.TestCase):
    def test_branch_detection(self):
        self.assertTrue(is_branch_group({"SL-2-1"}))
        self.assertTrue(is_branch_group({"BH-2-2"}))
        self.assertFalse(is_branch_group({"2-5"}))
        self.assertFalse(is_branch_group({"2-", "SL-2-2"}))
        self.assertFalse(is_branch_group({fL.now_icon}))

    def test_order_feature_then_main_then_branch(self):
        maps = [
            Box(300, 10, 10, 10, name="SL-2-1"),
            Box(500, 10, 10, 10, name="2-6"),
            Box(100, 10, 10, 10, name="2-4"),
            Box(900, 10, 10, 10, name=fL.not_clear_one),
        ]
        groups = [{"SL-2-1"}, {"2-6"}, {"2-4"}, {fL.not_clear_one}]
        ordered = order_maps(maps, groups, main_first=True)
        self.assertEqual([m.name for m, _ in ordered], [fL.not_clear_one, "2-4", "2-6", "SL-2-1"])
        # 名字组跟着关卡一起排序
        self.assertEqual([g for _, g in ordered], [{fL.not_clear_one}, {"2-4"}, {"2-6"}, {"SL-2-1"}])

    def test_order_left_to_right_when_main_first_disabled(self):
        maps = [Box(500, 0, 1, 1, name="2-6"), Box(300, 0, 1, 1, name="SL-2-1"), Box(100, 0, 1, 1, name="2-4")]
        groups = [{"2-6"}, {"SL-2-1"}, {"2-4"}]
        ordered = order_maps(maps, groups, main_first=False)
        self.assertEqual([m.name for m, _ in ordered], ["2-4", "SL-2-1", "2-6"])

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
    def test_skips_done_and_locked(self):
        ordered = [
            (Box(100, 0, 1, 1, name="SL-3-1"), {"SL-3-1"}),
            (Box(400, 0, 1, 1, name="3-1"), {"3-1"}),
            (Box(700, 0, 1, 1, name="SL-3-2"), {"SL-3-2"}),
        ]
        self.assertEqual(pick_candidate(ordered, set(), set())[0].name, "SL-3-1")
        self.assertEqual(pick_candidate(ordered, {"SL-3-1"}, set())[0].name, "3-1")
        self.assertEqual(pick_candidate(ordered, {"SL-3-1"}, {"3-1"})[0].name, "SL-3-2")
        self.assertIsNone(pick_candidate(ordered, {"SL-3-1", "SL-3-2"}, {"3-1"}))

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
