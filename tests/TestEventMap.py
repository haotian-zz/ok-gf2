"""
往期活动推图（2026-10-22 用户需求）：活动列表的纯函数，OCR 文本用实机记录（2560x1440）。
纯函数从 EventMapTask 源码抠出来跑，不依赖 ok 框架。
"""

import ast
import re
import unittest
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).resolve().parents[1] / "src/tasks/EventMapTask.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
nodes = [
    n
    for n in tree.body
    if (isinstance(n, ast.FunctionDef))
    or (isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) and (t.id.isupper() or t.id.endswith("_re")) for t in n.targets))
]
ns = {"re": re, "SequenceMatcher": SequenceMatcher}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)
event_cards, pick_event, same_event, event_title_on_map = (
    ns["event_cards"],
    ns["pick_event"],
    ns["same_event"],
    ns["event_title_on_map"],
)
W, H = 2560, 1440


def boxes(rows):
    return [SimpleNamespace(name=n, x=x, y=y, width=150, height=40) for n, x, y in rows]


# 实录 2026-10-22 01:50：往期活动 → 活动剧情 列表最左边
LIST = [
    ("剧情战役", 1389, 45),
    ("往期活动", 1680, 45),
    ("Supply Missions", 1968, 42),
    ("模拟作战", 2261, 45),
    ("活动剧情", 69, 193),
    ("悖论操演", 67, 323),
    ("03", 1605, 304),
    ("模拟习练", 67, 458),
    ("狂想四重奏", 667, 1083),
    ("拂晓的回响", 1205, 1081),
    ("密米尔的返演·上篇", 1691, 1085),
    ("密米尔的返演·下篇", 2235, 1088),
    ("完成度0%", 691, 1141),
    ("完成度0%", 1235, 1141),
    ("完成度0%", 1779, 1141),
    ("完成度0%", 2323, 1141),
]


class EventListTest(unittest.TestCase):
    def test_pairs_title_with_percent(self):
        cards = event_cards(boxes(LIST), W, H)
        self.assertEqual(
            [(t.name, p) for t, p in cards],
            [("狂想四重奏", 0), ("拂晓的回响", 0), ("密米尔的返演·上篇", 0), ("密米尔的返演·下篇", 0)],
        )

    def test_left_menu_and_tabs_are_not_cards(self):
        names = [t.name for t, _ in event_cards(boxes(LIST), W, H)]
        self.assertNotIn("活动剧情", names)
        self.assertNotIn("往期活动", names)

    def test_pick_first_unfinished_skipping_done(self):
        rows = [("完成度100%", 691, 1141) if r == ("完成度0%", 691, 1141) else r for r in LIST]
        cards = event_cards(boxes(rows), W, H)
        self.assertEqual(pick_event(cards, [])[0].name, "拂晓的回响")
        self.assertEqual(pick_event(cards, ["拂晓的回晌"])[0].name, "密米尔的返演·上篇")
        self.assertIsNone(pick_event([(c[0], 100) for c in cards], []))

    def test_percent_with_spaces(self):
        cards = event_cards(boxes([("狂想四重奏", 667, 1083), ("完成度 57 %", 691, 1141)]), W, H)
        self.assertEqual(cards[0][1], 57)

    def test_same_event_tolerates_ocr_typo(self):
        self.assertTrue(same_event("狂想四重秦", "狂想四重奏"))  # 实录：地图顶上的活动名
        self.assertFalse(same_event("密米尔的返演·上篇", "狂想四重奏"))
        self.assertFalse(same_event("", "狂想四重奏"))

    def test_upper_and_lower_part_are_different_events(self):
        # 上篇 / 下篇只差一个字，相似度很高；必须挑没推过的那个
        cards = event_cards(boxes(LIST), W, H)
        hit = pick_event(cards, ["狂想四重奏", "拂晓的回响", "密米尔的返演·上篇"])
        self.assertEqual(hit[0].name, "密米尔的返演·下篇")

    def test_title_on_map(self):
        # 实录 01:51：活动地图顶上「狂想四重秦」（OCR 错字）+「活动剧情」
        rows = [("狂想四重秦", 1213, 42), ("活动剧情", 1192, 79), ("MA-1-1", 968, 683)]
        self.assertEqual(event_title_on_map(boxes(rows), W, H), "狂想四重秦")

    def test_title_split_into_two_boxes(self):
        # 实录 2026-10-22：「密米尔的返演·上篇」只读出前半截，上篇被拆到另一个框
        rows = [("·上篇", 1330, 45), ("密米尔的返演", 1170, 42), ("活动剧情", 1192, 79)]
        title = event_title_on_map(boxes(rows), W, H)
        self.assertEqual(title, "密米尔的返演·上篇")
        self.assertFalse(same_event(title, "密米尔的返演·下篇"))


try:
    import cv2
    import numpy as np
except ImportError:  # mac 开发机没装 cv2，这组只在 Windows 上跑
    cv2 = None


@unittest.skipIf(cv2 is None, "需要 cv2")
class EventTabTest(unittest.TestCase):
    """实录 2026-10-22 密米尔的返演·上篇：物资还锁着，点了不切；不能看关卡名变没变，要看哪个按钮是实心的。"""

    def setUp(self):
        clear = ast.parse((Path(__file__).resolve().parents[1] / "src/tasks/ClearMapTask.py").read_text(encoding="utf-8"))
        extra = [
            n
            for n in clear.body
            if (isinstance(n, ast.FunctionDef) and n.name == "difficulty_fill")
            or (
                isinstance(n, ast.Assign)
                and any(isinstance(x, ast.Name) and x.id in ("DIFFICULTY_FILL", "DIFFICULTY_MIN_FILL") for x in n.targets)
            )
        ]
        ns["cv2"] = cv2
        exec(compile(ast.Module(body=extra, type_ignores=[]), "ClearMapTask", "exec"), ns)

    def frame(self, filled, color=(0, 110, 240)):
        img = np.full((H, W, 3), 30, np.uint8)  # 暗底
        for x in (2128, 2379):
            img[1320:1395, x - 40 : x + 160] = (79, 79, 79)  # 没选中的灰按钮（实测 V≈79）
        x = 2128 if filled == "剧情" else 2379
        img[1320:1395, x - 40 : x + 160] = color  # 默认橙色实心按钮（BGR）
        return img

    def test_filled_button_is_selected(self):
        tabs = boxes([("剧情", 2128, 1339), ("物资", 2379, 1339)])
        for want in ("剧情", "物资"):
            self.assertEqual(ns["selected_event_tab"](self.frame(want), tabs, H), want)

    def test_muted_green_button_is_selected(self):
        """实录 2026-10-22 纪念日礼赞：选中的「剧情」是灰绿色（HSV S≈70 V≈174），S>90 认不出，被当成切不过去先推了物资。"""
        tabs = boxes([("剧情", 2128, 1339), ("物资", 2379, 1339)])
        muted = cv2.cvtColor(np.uint8([[[60, 70, 174]]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()
        for want in ("剧情", "物资"):
            self.assertEqual(ns["selected_event_tab"](self.frame(want, muted), tabs, H), want)

    def test_bluish_gray_button_is_selected(self):
        """实录 2026-10-22 沉没夜潮：选中的「剧情」是蓝灰色（S≈26 V≈129），没颜色，只比没选中的（V≈79）亮。"""
        tabs = boxes([("剧情", 2128, 1339), ("物资", 2379, 1339)])
        for want in ("剧情", "物资"):
            self.assertEqual(ns["selected_event_tab"](self.frame(want, (129, 118, 110)), tabs, H), want)

    def test_single_tab_falls_back_to_fill(self):
        tab = boxes([("剧情", 2128, 1339)])
        self.assertEqual(ns["selected_event_tab"](self.frame("剧情"), tab, H), "剧情")
        self.assertIsNone(ns["selected_event_tab"](self.frame("物资"), tab, H))

    def test_no_filled_button(self):
        img = np.full((H, W, 3), 60, np.uint8)
        self.assertIsNone(ns["selected_event_tab"](img, boxes([("剧情", 2128, 1339), ("物资", 2379, 1339)]), H))


if __name__ == "__main__":
    unittest.main()
