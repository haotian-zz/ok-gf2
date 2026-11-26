import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

PATH = "src/tasks/daily/daily_battle_mixin.py"


def method(name):
    """从源码里只取出一个方法；它不依赖模块常量。"""
    tree = ast.parse(Path(PATH).read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {"re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), PATH, "exec"), ns)
    return ns[name]


def box(name):
    return SimpleNamespace(name=name)


class ChenyanOnSelectPageTest(unittest.TestCase):
    def setUp(self):
        self.check = method("_chenyan_on_select_page")

    def test_both_tabs_mean_select_page(self):
        task = Mock()
        task.ocr.return_value = [box("前哨战"), box("攻坚战")]
        self.assertTrue(self.check(task))

    def test_one_tab_or_nothing_is_not_select_page(self):
        task = Mock()
        for found in ([box("攻坚战")], [], None):
            with self.subTest(found=found):
                task.ocr.return_value = found
                self.assertFalse(self.check(task))


class ChenyanStartAssaultTest(unittest.TestCase):
    def make_task(self, still_on_page):
        """still_on_page：每次点完「开始作战」后，是否还停在尘烟选战役页。"""
        task = Mock()
        pages = iter(still_on_page)
        task._chenyan_on_select_page.side_effect = lambda: next(pages)
        task.wait_until.side_effect = lambda predicate, **kw: predicate()
        return task

    def test_first_click_opens_lineup(self):
        task = self.make_task([False])
        self.assertTrue(method("_chenyan_start_assault")(task))
        self.assertEqual(1, task.wait_click_ocr.call_count)
        task.screenshot.assert_not_called()

    def test_swallowed_click_is_retried(self):
        """实录 2026-11-25：第一次点击被吞，还在尘烟页 → 再点一次进了编队。"""
        task = self.make_task([True, False])
        self.assertTrue(method("_chenyan_start_assault")(task))
        self.assertEqual(2, task.wait_click_ocr.call_count)
        self.assertIn("再点一次", task.log_info.call_args.args[0])

    def test_gives_up_after_three_clicks(self):
        task = self.make_task([True, True, True])
        self.assertFalse(method("_chenyan_start_assault")(task))
        self.assertEqual(3, task.wait_click_ocr.call_count)
        task.screenshot.assert_called_once()

    def test_clicks_only_start_button_in_bottom_right(self):
        task = self.make_task([False])
        method("_chenyan_start_assault")(task)
        kwargs = task.wait_click_ocr.call_args.kwargs
        self.assertEqual("开始作战", kwargs["match"])
        self.assertIs(task.box.bottom_right, kwargs["box"])


if __name__ == "__main__":
    unittest.main()
