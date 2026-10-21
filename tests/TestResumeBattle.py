"""
推图接管（ClearMapTask.resume_battle）：重启后可能停在部署界面、战斗中、结算页或剧情里。
实录 2026-10-21：停在剧情→「任务完成」结算页，resume_battle 没认「任务完成」，和 skip_dialogs 互相踢皮球卡了 15 分钟。
"""

import ast
import re
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

source = Path(__file__).resolve().parents[1] / "src/tasks/ClearMapTask.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ClearMapTask")
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "resume_battle"]
ns = {
    "re": re,
    "time": time,
    "map_re": re.compile(r"^[^\d\s]{0,4}\s*\d{1,2}\s*-\s*\d{1,2}\s*\*?$"),
    "BACK_TO_MAP": ["back"],
    "pop_ups": ["点击空白处关闭"],
}
exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), ns)
resume_battle = ns["resume_battle"]


def box(name):
    return SimpleNamespace(name=name)


def find_boxes(boxes, match=None, boundary=None):
    pats = match if isinstance(match, list) else [match]
    return [b for b in boxes if any((p.search(b.name) if hasattr(p, "search") else p == b.name) for p in pats)]


def make_task(screens):
    task = Mock()
    task.config = {}
    frames = iter(screens)
    current = {"boxes": []}

    def ocr(*a, **k):
        current["boxes"] = next(frames, current["boxes"])
        return current["boxes"]

    task.ocr.side_effect = ocr
    task.find_boxes.side_effect = find_boxes
    task.fix_match_regex.side_effect = lambda words: words
    task._is_battle_frame.return_value = False
    task.skip_dialogs.return_value = [box("任务完成")]
    return task


class ResumeBattleTest(unittest.TestCase):
    def test_result_page_is_finished_by_auto_battle(self):
        task = make_task([[box("任务完成"), box("HA-1-2 往日名讳")]])
        self.assertTrue(resume_battle(task, time_out=5))
        task.auto_battle.assert_called_once()
        task.skip_dialogs.assert_not_called()

    def test_story_then_result_page(self):
        task = make_task([[box("自动跳过"), box("全部跳过")], [box("任务完成")]])
        self.assertTrue(resume_battle(task, time_out=5))
        task.auto_battle.assert_called_once()

    def test_unhandled_page_does_not_spin_until_timeout(self):
        task = make_task([[box("？？？")]])
        task.skip_dialogs.return_value = [box("某个按钮")]
        start = time.time()
        self.assertFalse(resume_battle(task, time_out=30))
        self.assertLess(time.time() - start, 5)
        task.auto_battle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
