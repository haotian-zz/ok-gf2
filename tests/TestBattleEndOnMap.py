"""
实录 2026-10-20：改成真实鼠标输入后，skip_dialogs 在等结算时的角落点击把「任务完成」结算页点过去了，
等到的直接是选关页面；而选关页面右上角是货币「+」，再点就弹「物品详情」。
战斗结束的判定要认选关页面，选关页面上不做角落点击，「物品详情」按弹窗 ESC 关掉。
"""

import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

source = Path(__file__).resolve().parents[1] / "src/core/BaseGfTask.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BaseGfTask")
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "skip_dialogs"]
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("battle_over_on_map", "describe_screen")]
consts = [
    n
    for n in tree.body
    if isinstance(n, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id in ("pop_ups", "map_re", "stamina_popup_re", "battle_ui_re", "challenge_button_re") for t in n.targets)
]
ns = {"re": re, "time": __import__("time")}
exec(compile(ast.Module(body=consts + funcs + methods, type_ignores=[]), str(source), "exec"), ns)
battle_over_on_map, skip_dialogs, pop_ups, map_re = ns["battle_over_on_map"], ns["skip_dialogs"], ns["pop_ups"], ns["map_re"]


def box(name):
    return SimpleNamespace(name=name)


def find_boxes(boxes, match=None, boundary=None):
    pats = match if isinstance(match, list) else [match]
    out = []
    for b in boxes:
        for p in pats:
            if (p.search(b.name) if hasattr(p, "search") else p == b.name):
                out.append(b)
                break
    return out


class BattleOverTest(unittest.TestCase):
    def test_map_cards_mean_battle_is_over(self):
        self.assertTrue(battle_over_on_map([box("9-7"), box("BH-9-1")]))
        self.assertTrue(battle_over_on_map([box("确认"), box("SL-9-2")]))

    def test_result_pages_are_not_over(self):
        self.assertFalse(battle_over_on_map([box("任务完成")]))
        self.assertFalse(battle_over_on_map([box("继续前进")]))
        self.assertFalse(battle_over_on_map([]))
        self.assertFalse(battle_over_on_map(None))

    def test_item_detail_dialog_is_a_pop_up(self):
        self.assertIn("物品详情", pop_ups)


class SkipDialogsOnMapTest(unittest.TestCase):
    def make_task(self, boxes):
        task = Mock()
        task.ocr.return_value = boxes
        task.find_boxes.side_effect = find_boxes
        task._is_loading_frame.return_value = False
        task._is_battle_frame.return_value = False
        task._dismiss_notice.return_value = False
        return task

    def test_no_corner_clicks_on_stage_select_page(self):
        task = self.make_task([box("9-7"), box("BH-9-1"), box("普通")])
        self.assertIsNone(skip_dialogs(task, end_match=["任务完成"], time_out=0.01, has_dialog=True, raise_if_not_found=False))
        task.click_relative.assert_not_called()
        task.click.assert_not_called()

    def test_unknown_page_still_gets_corner_clicks(self):
        task = self.make_task([box("……")])
        skip_dialogs(task, end_match=["任务完成"], time_out=0.01, has_dialog=True, raise_if_not_found=False)
        task.click_relative.assert_called()

    def test_map_in_end_match_returns_map_boxes(self):
        task = self.make_task([box("9-7"), box("普通")])
        result = skip_dialogs(task, end_match=["任务完成", map_re], time_out=1, has_dialog=True, raise_if_not_found=False)
        self.assertEqual([b.name for b in result], ["9-7"])
        task.click_relative.assert_not_called()


if __name__ == "__main__":
    unittest.main()
