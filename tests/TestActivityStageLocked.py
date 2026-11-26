import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

PATH = "src/tasks/daily/daily_activity_mixin.py"
locked_re = re.compile("需要完成前置关卡")
map_re = re.compile(r"^[A-Z]{1,3}-\d+-\d+$")


def method(name, **extra):
    """从源码里只取出一个方法，配上它用到的模块常量。"""
    tree = ast.parse(Path(PATH).read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {"re": re, "activity_stage_locked_re": locked_re, **extra}
    exec(compile(ast.Module(body=[node], type_ignores=[]), PATH, "exec"), ns)
    return ns[name]


def box(name):
    return SimpleNamespace(name=name)


class ActivityStageLockedTest(unittest.TestCase):
    def setUp(self):
        self.check = method("_activity_stage_locked")

    def test_locked_panel_is_skipped_with_screenshot(self):
        """实录 2026-11-25：面板只有「需要完成前置关卡」→ 跳过、截图、标待核查。"""
        task = Mock()
        task.wait_ocr.return_value = [box("需要完成前置关卡")]
        self.assertTrue(self.check(task, box("KF-1-3")))
        task.screenshot.assert_called_once()
        task.info_set.assert_called_once()
        self.assertIn("待核查", task.info_set.call_args.args[1])
        self.assertIn("KF-1-3", task.log_info.call_args.args[0])

    def test_zilv_present_is_not_locked(self):
        task = Mock()
        task.wait_ocr.return_value = [box("自律")]
        self.assertFalse(self.check(task, box("KF-1-3")))
        task.screenshot.assert_not_called()

    def test_zilv_wins_over_locked_text(self):
        task = Mock()
        task.wait_ocr.return_value = [box("需要完成前置关卡"), box("自律")]
        self.assertFalse(self.check(task, box("KF-1-3")))

    def test_nothing_recognized_falls_back_to_fast_combat(self):
        """两个都没认出：不吞掉，交给 fast_combat 照旧报错。"""
        task = Mock()
        task.wait_ocr.return_value = None
        self.assertFalse(self.check(task, box("KF-1-3")))
        task.info_set.assert_not_called()


class ActivityFlowTest(unittest.TestCase):
    def make_task(self, locked):
        task = Mock()
        task.config = {"当前物资关卡名称": "某活动"}
        task.wait_click_ocr.return_value = box("限时开启")
        task.wait_ocr_until_count.return_value = []
        task.ocr.return_value = []

        def wait_ocr(*args, match=None, **kwargs):
            if match == ["开启中"]:
                return [box("开启中")]
            if match is map_re:
                return [box("KF-1-2"), box("KF-1-3")]
            if isinstance(match, list) and "活动战役" in match:
                return [box("物资模式")]
            return None

        task.wait_ocr.side_effect = wait_ocr
        task._activity_stage_locked.return_value = locked
        return task

    def run_activity(self, task):
        run = method(
            "activity",
            map_re=map_re,
            chapter_suffix_re="[上下中]篇",
            up_chapter_re=re.compile("上篇"),
            middle_chapter_re=re.compile("中篇"),
            down_chapter_re=re.compile("下篇"),
        )
        return run(task)

    def test_locked_stage_returns_uncertain_without_fast_combat(self):
        task = self.make_task(locked=True)
        self.assertEqual("待核查", self.run_activity(task))
        task.fast_combat.assert_not_called()
        task._activity_stage_locked.assert_called_once()
        self.assertEqual("KF-1-3", task._activity_stage_locked.call_args.args[0].name)

    def test_unlocked_stage_runs_fast_combat(self):
        task = self.make_task(locked=False)
        self.assertIsNone(self.run_activity(task))
        task.fast_combat.assert_called_once_with(set_cost=1, battle_max=6, activity=True)


if __name__ == "__main__":
    unittest.main()
