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


if __name__ == "__main__":
    unittest.main()
