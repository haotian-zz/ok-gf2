"""推图关卡排序、候选选择、体力弹窗、助战选人与调试截图的纯逻辑测试，不依赖设备与 ok-script 运行时。"""

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
from src.core.support_select import (
    check_point,
    filter_point,
    find_cards,
    is_orange_check,
    make_check_frame,
    pick_candidates,
)
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


class TestSupportSelect(unittest.TestCase):
    """按 1280x768 好友助战面板实测：角标中心 (975,130)/(1068,130)，战力中心 (1005,198)/(1098,198)，第二行各下移 112。"""

    W, H = 1280, 768

    def boxes(self):
        return [
            Box(969, 122, 12, 16, name="6"),
            Box(999, 190, 36, 16, name="25871"),
            Box(1092, 190, 36, 16, name="17405"),  # 角标是「—」，识别不到数字
            Box(1155, 122, 12, 16, name="1"),
            Box(1185, 190, 36, 16, name="17342"),
            Box(969, 234, 12, 16, name="4"),
            Box(999, 302, 36, 16, name="16083"),
            Box(1030, 70, 50, 20, name="32757"),  # 顶部作战效能，不在面板里但也不该配到角标
        ]

    def test_find_cards_pairs_badges(self):
        cards = find_cards(self.boxes(), self.W, self.H)
        got = [(c["power"], c["badge"]) for c in cards]
        self.assertEqual(got, [(32757, None), (25871, 6), (17405, None), (17342, 1), (16083, 4)])
        c6 = cards[1]
        self.assertAlmostEqual(c6["center"][0], 1017, delta=3)
        self.assertAlmostEqual(c6["center"][1], 198 - 0.065 * self.H, delta=3)

    def test_pick_candidates(self):
        cards = find_cards(self.boxes(), self.W, self.H)
        self.assertEqual([c["power"] for c in pick_candidates(cards, 6)], [25871])
        self.assertEqual([c["power"] for c in pick_candidates(cards, 4)], [25871, 16083])
        self.assertEqual(pick_candidates(cards, 7), [])

    def test_orange_check(self):
        cards = find_cards(self.boxes(), self.W, self.H)
        c6 = next(c for c in cards if c["badge"] == 6)
        x, y = check_point(c6, self.W, self.H)
        self.assertAlmostEqual(x, 1046, delta=3)
        self.assertAlmostEqual(y, 117, delta=3)
        frame = make_check_frame(self.W, self.H, [(x, y)])
        self.assertTrue(is_orange_check(frame, x, y))
        other = next(c for c in cards if c["badge"] == 4)
        self.assertFalse(is_orange_check(frame, *check_point(other, self.W, self.H)))
        self.assertFalse(is_orange_check(None, x, y))

    def test_filter_point(self):
        tab = Box(1075, 22, 110, 16, name="好友助战")
        x, y = filter_point(tab, "物理", self.W, self.H)
        self.assertAlmostEqual(x, 1035, delta=4)
        self.assertAlmostEqual(y, 70, delta=4)
        x_all, _ = filter_point(tab, None, self.W, self.H)
        self.assertAlmostEqual(x_all, 988, delta=4)
