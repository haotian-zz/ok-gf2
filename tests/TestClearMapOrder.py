"""推图关卡排序、候选选择、本地通关记录与调试截图的纯逻辑测试，不依赖设备与 ok-script 运行时。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ok import Box

from src.core.BaseGfTask import (
    has_forbidden_restore_text,
    map_re,
    popup_texts,
    stamina_popup_re,
    stamina_tab_points,
    tab_count,
)
from src.core.debug_shot import save_debug_shot
from src.tasks.clear_map_progress import ProgressStore
from src.tasks.ClearMapTask import canonical_name, merge_maps, order_maps, pick_candidate


class TestMapRe(unittest.TestCase):
    def test_names(self):
        for name in ["3-1", "SL-3-2", "BH-3-4", "ABC-12-3", "2-5*", "SL-2-1"]:
            self.assertIsNotNone(map_re.search(name), name)
        for name in ["420/240", "300/240", "01/12 回合", "2-", "推荐等级13", "3020"]:
            self.assertIsNone(map_re.search(name), name)


class TestOrderMaps(unittest.TestCase):
    def test_left_to_right_keeps_groups_aligned(self):
        maps = [Box(300, 10, 10, 10, name="SL-2-1"), Box(500, 10, 10, 10, name="2-6"), Box(100, 10, 10, 10, name="2-4")]
        groups = [{"SL-2-1"}, {"2-6"}, {"2-4"}]
        ordered = order_maps(maps, groups)
        self.assertEqual([m.name for m, _ in ordered], ["2-4", "SL-2-1", "2-6"])
        self.assertEqual([g for _, g in ordered], [{"2-4"}, {"SL-2-1"}, {"2-6"}])

    def test_merge_then_order(self):
        maps = [
            Box(800, 100, 10, 10, name="2-5"),
            Box(805, 103, 10, 10, name="2-5*"),
            Box(100, 100, 10, 10, name="2-3"),
        ]
        merged, groups = merge_maps(maps, x_threshold=40, y_threshold=40)
        ordered = order_maps(merged, groups)
        self.assertEqual([m.name for m, _ in ordered], ["2-3", "2-5"])
        self.assertEqual(ordered[1][1], {"2-5", "2-5*"})
        self.assertEqual(canonical_name(ordered[1][1]), "2-5")

    def test_canonical_name(self):
        self.assertEqual(canonical_name({"SL-3-2", "SL-3-2*"}), "SL-3-2")
        self.assertIsNone(canonical_name(set()))


class TestPickCandidate(unittest.TestCase):
    def setUp(self):
        self.ordered = [
            (Box(100, 0, 1, 1, name="SL-3-1"), {"SL-3-1"}),
            (Box(400, 0, 1, 1, name="3-1"), {"3-1"}),
            (Box(700, 0, 1, 1, name="SL-3-2"), {"SL-3-2"}),
            (Box(1000, 0, 1, 1, name="3-2"), {"3-2"}),
        ]

    def test_left_to_right_skipping(self):
        self.assertEqual(pick_candidate(self.ordered, set())[0].name, "SL-3-1")
        self.assertEqual(pick_candidate(self.ordered, {"SL-3-1"})[0].name, "3-1")
        self.assertEqual(pick_candidate(self.ordered, {"SL-3-1", "3-1"})[0].name, "SL-3-2")
        self.assertIsNone(pick_candidate(self.ordered, {"SL-3-1", "3-1", "SL-3-2", "3-2"}))

    def test_cursor_only_moves_right(self):
        # 3-1 作为游标 -> 它左边的 SL-3-1 不再考虑，下一张是右边的 SL-3-2
        self.assertEqual(pick_candidate(self.ordered, {"3-1"}, cursor="3-1")[0].name, "SL-3-2")
        self.assertEqual(pick_candidate(self.ordered, {"3-1", "SL-3-2"}, cursor="3-1")[0].name, "3-2")
        self.assertIsNone(pick_candidate(self.ordered, {"3-1", "3-2", "SL-3-2"}, cursor="3-1"))

    def test_cursor_not_visible_falls_back_to_leftmost(self):
        self.assertEqual(pick_candidate(self.ordered, set(), cursor="3-9")[0].name, "SL-3-1")

    def test_group_partial_overlap_counts(self):
        ordered = [(Box(100, 0, 1, 1, name="2-5"), {"2-5", "2-5*"})]
        self.assertIsNone(pick_candidate(ordered, {"2-5*"}))


class TestProgressStore(unittest.TestCase):
    def test_mark_persist_reload(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "configs", "clear_map_progress.json")
            store = ProgressStore(path)
            self.assertFalse(store.is_cleared("3.0缺位拟合|普通", "3-1"))
            self.assertTrue(store.mark("3.0缺位拟合|普通", "3-1"))
            self.assertFalse(store.mark("3.0缺位拟合|普通", "3-1"))  # 重复不再新增
            store.mark("3.0缺位拟合|普通", "SL-3-1")
            reloaded = ProgressStore(path)
            self.assertEqual(reloaded.cleared("3.0缺位拟合|普通"), {"3-1", "SL-3-1"})
            self.assertEqual(reloaded.cleared("3.0缺位拟合|困难"), set())

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "p.json")
            Path(path).write_text("not json", encoding="utf-8")
            store = ProgressStore(path)
            self.assertEqual(store.cleared("x"), set())
            self.assertTrue(store.mark("x", "1-1"))


class TestLoadingFrame(unittest.TestCase):
    """_is_loading_frame 只依赖 OCR 结果，直接用未绑定方法测。"""

    def setUp(self):
        from src.core.BaseGfTask import BaseGfTask

        self.is_loading = BaseGfTask._is_loading_frame

    def boxes(self, *names):
        return [Box(0, 0, 1, 1, name=n) for n in names]

    def test_loading_screens(self):
        self.assertTrue(self.is_loading(None, []))
        self.assertTrue(
            self.is_loading(None, self.boxes("18%", "资源加载中", "//.008625", "罗联污染区勘测维护及环境分析情报组"))
        )
        self.assertTrue(self.is_loading(None, self.boxes("42%")))

    def test_tutorial_popup_is_not_loading(self):
        self.assertFalse(
            self.is_loading(
                None,
                self.boxes(
                    "60%", "25%", "60%", "20%", "显示此次伤害的具体信息，包括稳态减伤、掩体减伤、降防率以及暴击率。"
                ),
            )
        )

    def test_battle_ui_is_not_loading(self):
        self.assertFalse(self.is_loading(None, self.boxes("01/12 回合", "击杀所有敌方单位 5/8", "行动结束", "115%")))


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


class TestStaminaPopup(unittest.TestCase):
    """按 1280x768 窗口实测的「情报拼图补充」弹窗布局：标题中心 (614, 215)，页签中心 y=323，x=488/612/738。"""

    def setUp(self):
        self.h = 768
        self.title = Box(548, 203, 132, 24, name="情报拼图补充")

    def test_title_regex(self):
        for name in ["情报拼图补充", "情报拼圖补充", "体力不足"]:
            self.assertIsNotNone(stamina_popup_re.search(name), name)
        for name in ["继续前进", "情报", "补充"]:
            self.assertIsNone(stamina_popup_re.search(name), name)

    def test_tab_points(self):
        pts = stamina_tab_points(self.title, self.h)
        self.assertEqual(len(pts), 3)
        for (x, y), (ex, ey) in zip(pts, [(488, 323), (612, 323), (738, 323)], strict=True):
            self.assertAlmostEqual(x, ex, delta=6)
            self.assertAlmostEqual(y, ey, delta=6)

    def test_forbidden_text(self):
        self.assertTrue(has_forbidden_restore_text(["使用坍塌晶条恢复情报拼图"]))
        self.assertTrue(has_forbidden_restore_text(["购买", "确认"]))
        self.assertFalse(has_forbidden_restore_text(["快速取出调度室储存情报拼图", "取出数量 0", "确认", "取消"]))

    def test_popup_texts_excludes_background(self):
        boxes = [
            Box(500, 450, 220, 20, name="快速取出调度室储存情报拼图"),
            Box(1030, 70, 60, 20, name="81/240"),  # 右上角体力
            Box(40, 360, 40, 20, name="4-3"),  # 弹窗外的关卡卡片
            Box(730, 530, 40, 20, name="确认"),
        ]
        self.assertEqual(popup_texts(boxes, self.title, self.h), ["快速取出调度室储存情报拼图", "确认"])

    def test_tab_count(self):
        boxes = [Box(600, 345, 28, 16, name="121"), Box(720, 345, 36, 16, name="6140"), Box(1140, 70, 50, 20, name="6140")]
        self.assertEqual(tab_count(boxes, 612, 323, self.h), 121)
        self.assertEqual(tab_count(boxes, 738, 323, self.h), 6140)
        self.assertIsNone(tab_count(boxes, 488, 323, self.h))
