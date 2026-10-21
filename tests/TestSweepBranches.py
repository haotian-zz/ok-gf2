"""
实录 2026-10-20 第 10 章：支线 BH-10-3 在主线 10-8 打完后才解锁，但它在地图上位于 10-10 左边；
推图的进度游标停在 10-10，只往右找，BH-10-3 被漏掉。现在往右推到头时只要这一遍推过关卡，就回章节起点再扫一遍。
sweep_right 从源码抠出来跑在一张假地图上（所有关卡都在一屏里）。
"""

import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).resolve().parents[1] / "src/tasks/ClearMapTask.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ClearMapTask")
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "sweep_right"]
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("pick_candidate", "canonical_name")]
locked_cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ChapterLocked"]
ns = {"re": re, "map_re": re.compile("x"), "chapter_select_re": re.compile("^章节进度$")}
exec(compile(ast.Module(body=locked_cls + funcs + methods, type_ignores=[]), str(source), "exec"), ns)
ChapterLocked = ns["ChapterLocked"]


class FakeChapter:
    width, height = 2560, 1440

    def __init__(self, stages):
        # stages: name -> {"x": 横坐标, "done": bool, "needs": [前置关卡]}
        self.stages = stages
        self.played = []
        self.view_left = 0  # 屏幕上能看到 x 在 [view_left, view_left + 1000) 的关卡
        self.camera_after = {}  # 打完某关后镜头停在哪（继续前进连打会把镜头带到右边）
        self.config = {}
        self.sweep_right = ns["sweep_right"].__get__(self)

    def status(self, name):
        st = self.stages[name]
        if st["done"]:
            return "cleared"
        if all(self.stages[n]["done"] for n in st.get("needs", [])):
            return "challenge"
        return "locked"

    def scan_maps(self):
        return [
            (SimpleNamespace(x=st["x"] - self.view_left, name=n), {n})
            for n, st in sorted(self.stages.items(), key=lambda kv: kv[1]["x"])
            if self.view_left <= st["x"] < self.view_left + 1000
        ]

    def inspect_card(self, card, name):
        status = self.status(name)
        return status, ([SimpleNamespace(name="挑战")] if status == "challenge" else None)

    def click(self, target, after_sleep=0):
        pass

    def auto_battle(self, **kw):
        name = self._pending
        self.stages[name]["done"] = True
        self.played.append(name)
        self.view_left = self.camera_after.get(name, self.view_left)

    def close_map_panel(self):
        pass

    def reenter_from_chapter_select(self):
        return False

    def go_to_chapter_start(self):
        self.view_left = 0

    def skip_dialogs(self, **kw):
        pass

    def sleep(self, *a):
        pass

    def info_set(self, *a):
        pass

    def log_info(self, *a, **k):
        pass


def track(game):
    orig = game.inspect_card

    def inspect(card, name):
        game._pending = name
        return orig(card, name)

    game.inspect_card = inspect
    return game


class SweepBranchesTest(unittest.TestCase):
    def test_branch_unlocked_left_of_cursor_is_played(self):
        game = track(
            FakeChapter(
                {
                    "10-7": {"x": 100, "done": False},
                    "BH-10-3": {"x": 300, "done": False, "needs": ["10-8"]},
                    "10-8": {"x": 500, "done": False, "needs": ["10-7"]},
                    "10-10": {"x": 900, "done": True},
                    "10-11": {"x": 1200, "done": True},
                }
            )
        )
        game.camera_after = {"10-8": 650}  # 10-8 打完镜头到了 10-10 附近，BH-10-3 在屏幕外
        self.assertEqual(game.sweep_right(), 3)
        self.assertEqual(game.played, ["10-7", "10-8", "BH-10-3"])

    def test_all_done_returns_zero_after_single_pass(self):
        game = track(FakeChapter({"9-1": {"x": 100, "done": True}, "9-2": {"x": 300, "done": True}}))
        self.assertEqual(game.sweep_right(), 0)

    def test_truly_locked_stages_raise_after_rescan(self):
        game = track(
            FakeChapter(
                {
                    "9-1": {"x": 100, "done": False},
                    "SL-9-3": {"x": 300, "done": False, "needs": ["9-9"]},
                    "9-9": {"x": 900, "done": False, "needs": ["时间锁"]},
                    "时间锁": {"x": 2000, "done": False, "needs": ["永远"]},
                    "永远": {"x": 2100, "done": False, "needs": ["永远"]},
                }
            )
        )
        with self.assertRaises(ChapterLocked) as ctx:
            game.sweep_right()
        self.assertEqual(game.played, ["9-1"])
        self.assertEqual(ctx.exception.count, 1)


if __name__ == "__main__":
    unittest.main()
