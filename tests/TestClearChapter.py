"""
推一章的算法（ClearMapTask.clear_chapter）跑在一张模拟的章节地图上：
屏幕只能看到一段（点卡片会把镜头滚到它那里）、上下两排、关卡之间有解锁依赖、打完镜头会跳、
看完最后的剧情会停在没有关卡卡片的画面、对勾识别偶尔漏看。
不依赖 ok 框架：把相关方法从源码里抠出来绑到模拟器上。
"""

import ast
import re
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).resolve().parents[1] / "src/tasks/ClearMapTask.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ClearMapTask")
wanted = ("clear_chapter", "chapter_pass", "ensure_map", "go_to_chapter_start")
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "canonical_name"]
consts = [
    n
    for n in tree.body
    if isinstance(n, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id in ("CHAPTER_MAX_PASSES", "STAGE_MAX_ATTEMPTS", "ENSURE_MAP_TRIES", "PASS_MAX_STEPS", "STATUS_TEXT") for t in n.targets)
]
ns = {"re": re, "Counter": Counter, "map_re": re.compile("x"), "chapter_select_re": re.compile("^章节进度$")}
ns["has_clear_badge"] = lambda frame, card, w, h: frame.badge(card)
exec(compile(ast.Module(body=consts + funcs + methods, type_ignores=[]), str(source), "exec"), ns)

SCREEN = 2000  # 屏幕能看到的地图宽度（真实章节里相邻卡片相距不到一屏，造数据时也别超过 500）


class FakeChapter:
    width, height = 2560, 1440

    def __init__(self, stages):
        # name -> {"x": 地图横坐标, "y": 行, "done": bool, "needs": [...], "story": bool}
        self.stages = stages
        self.view_left = 0
        self.played = []
        self.blank_after = {}  # 打完/看完某关后有几次扫描看不到卡片（停在剧情尾巴、结算等）
        self.camera_after = {}  # 打完某关后镜头跳到哪
        self.badge_misses = Counter()  # 某关的对勾前几次漏看
        self.broken_badge = set()  # 打完也永远看不出对勾的关
        self.blank = 0
        self.config = {}
        self.frame = self
        self.log = []
        self._pending = None
        for name in wanted:
            setattr(self, name, ns[name].__get__(self))

    # ---- 画面
    def scan_maps(self):
        if self.blank:
            self.blank -= 1
            return []
        vis = [
            (SimpleNamespace(x=st["x"] - self.view_left, y=st.get("y", 600), name=n), {n})
            for n, st in self.stages.items()
            if self.view_left <= st["x"] < self.view_left + SCREEN
        ]
        return sorted(vis, key=lambda v: v[0].x)

    def badge(self, card):
        st = self.stages[card.name]
        if self.badge_misses[card.name]:
            self.badge_misses[card.name] -= 1
            return False
        return st["done"] and card.name not in self.broken_badge

    def status(self, name):
        st = self.stages[name]
        if st["done"]:
            return "cleared"
        if all(self.stages[n]["done"] for n in st.get("needs", [])):
            return "watch" if st.get("story") else "challenge"
        return "locked"

    # ---- 操作
    def click(self, target, after_sleep=0):
        if isinstance(target, SimpleNamespace) and target.name in self.stages:
            # 点卡片：游戏把它滚到屏幕左边约 1/4 处（左边还能看到 500 左右）
            self.view_left = max(0, self.stages[target.name]["x"] - 500)
            self._pending = target.name

    def inspect_card(self, card, name):
        self.click(card)
        st = self.status(name)
        return st, ([SimpleNamespace(name="挑战")] if st in ("challenge", "watch") else None)

    def _finish(self, **kw):
        name = self._pending
        self.stages[name]["done"] = True
        self.played.append(name)
        self.view_left = self.camera_after.get(name, self.view_left)
        self.blank = self.blank_after.get(name, 0)

    auto_battle = _finish

    def skip_dialogs(self, **kw):
        self._finish()

    def resume_battle(self, time_out=0):
        self.blank = 0
        return True

    def reenter_from_chapter_select(self):
        return False

    def back(self, after_sleep=0):
        pass

    def chapter_medals(self):
        return None

    def close_map_panel(self):
        pass

    def debug_shot(self, *a, **k):
        pass

    def sleep(self, *a):
        pass

    def info_set(self, *a):
        pass

    def log_info(self, msg, notify=False):
        self.log.append(msg)


def chapter_11():
    """第 11 章上篇的形状：上排主线 LA + 剧情 LS，下排支线 LZ；LZ-1-4/LZ-1-6 要主线推到后面才解锁。"""
    st = {}
    prev = None
    for i in range(1, 18):
        name = f"LA-1-{i}"
        st[name] = {"x": 300 * i, "y": 600, "done": False, "needs": [prev] if prev else []}
        prev = name
    st["LS-1-7"] = {"x": 300 * 18, "y": 600, "done": False, "needs": ["LA-1-17"], "story": True}
    st["LZ-1-1"] = {"x": 900, "y": 400, "done": False, "needs": ["LA-1-3"]}
    st["LZ-1-4"] = {"x": 2400, "y": 900, "done": False, "needs": ["LA-1-12"]}  # 在 LA-1-8 下面，LA-1-12 打完才开
    st["LZ-1-6"] = {"x": 300 * 18 + 200, "y": 900, "done": False, "needs": ["LS-1-7"]}
    return st


class ClearChapterTest(unittest.TestCase):
    def test_chapter_11_with_blank_screen_after_last_story(self):
        """实录 2026-10-20：看完 LS-1-7 后画面上没有卡片，旧逻辑报错停下，LZ-1-4 / LZ-1-6 没推。"""
        game = FakeChapter(chapter_11())
        game.blank_after = {"LS-1-7": 2}
        game.camera_after = {f"LA-1-{i}": 300 * i + 300 for i in range(1, 17)}  # 继续前进把镜头带着走
        played, locked = game.clear_chapter()
        self.assertTrue(all(st["done"] for st in game.stages.values()), [n for n, s in game.stages.items() if not s["done"]])
        self.assertEqual(locked, [])
        self.assertEqual(played, len(game.stages))
        self.assertEqual(len(game.played), len(set(game.played)))  # 每关只打一次

    def test_branch_unlocked_left_of_frontier(self):
        """实录 2026-10-20 第 10 章：BH-10-3 在 10-8 打完才解锁，但在 10-10 左边。"""
        game = FakeChapter(
            {
                "10-7": {"x": 100, "done": False},
                "BH-10-3": {"x": 300, "done": False, "needs": ["10-8"]},
                "10-8": {"x": 500, "done": False, "needs": ["10-7"]},
                "10-9": {"x": 900, "done": True},
                "10-10": {"x": 1400, "done": True},
                "10-11": {"x": 1900, "done": True},
                "10-12": {"x": 2400, "done": True},
            }
        )
        game.camera_after = {"10-8": 1000}  # 打完 10-8 镜头停在 10-10 附近，BH-10-3 在屏幕左边外面
        played, locked = game.clear_chapter()
        self.assertEqual(game.played, ["10-7", "10-8", "BH-10-3"])
        self.assertEqual((played, locked), (3, []))

    def test_truly_locked_reported_not_looped(self):
        game = FakeChapter(
            {
                "9-1": {"x": 100, "done": False},
                "SL-9-3": {"x": 300, "done": False, "needs": ["9-9"]},
                "9-9": {"x": 800, "done": False, "needs": ["时间锁"]},
                "时间锁": {"x": 1300, "done": False, "needs": ["永远"]},
                "永远": {"x": 1800, "done": False, "needs": ["永远"]},
                "9-10": {"x": 2300, "done": False, "needs": ["永远"]},
            }
        )
        played, locked = game.clear_chapter()
        self.assertEqual(game.played, ["9-1"])
        self.assertEqual(played, 1)
        self.assertEqual(locked, ["9-10", "9-9", "SL-9-3", "时间锁", "永远"])

    def test_missed_badge_falls_back_to_panel(self):
        game = FakeChapter({"1-1": {"x": 100, "done": True}, "1-2": {"x": 500, "done": False}})
        game.badge_misses = Counter({"1-1": 5})
        game.clear_chapter()
        self.assertEqual(game.played, ["1-2"])  # 1-1 对勾漏看了也只是点开面板，面板说已通关就不打

    def test_stage_that_never_shows_cleared_is_capped(self):
        game = FakeChapter({"1-1": {"x": 100, "done": False}, "1-2": {"x": 500, "done": False, "needs": ["1-1"]}})
        game.broken_badge = {"1-1"}
        original = game.status
        game.status = lambda name: "challenge" if name == "1-1" else original(name)  # 面板也一直说能挑战
        game.clear_chapter()
        self.assertEqual(game.played.count("1-1"), 2)
        self.assertIn("1-2", game.played)

    def test_all_done_single_pass_no_clicks_on_panels(self):
        game = FakeChapter({f"1-{i}": {"x": 400 * i, "done": True} for i in range(1, 12)})
        opened = []
        game.inspect_card = lambda card, name: opened.append(name) or ("cleared", None)
        played, locked = game.clear_chapter()
        self.assertEqual((played, locked, opened), (0, [], []))


class StageCardTest(unittest.TestCase):
    """实录 2026-10-20 第 11 章 2560x1440：通关的卡片右上有橙色对勾，没通关的没有。"""

    def check(self, fixture, expected):
        import sys

        import cv2

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from src.core.stage_card import has_clear_badge

        frame = cv2.imread(str(Path(__file__).resolve().parent / "fixtures" / fixture))
        self.assertIsNotNone(frame)
        for name, (x, y, w, h, done) in expected.items():
            box = SimpleNamespace(x=x, y=y, width=w, height=h)
            self.assertEqual(has_clear_badge(frame, box, 2560, 1440), done, name)

    def test_badges_on_map(self):
        # 关卡名文字框（OCR 框的大致位置）
        self.check(
            "map_cleared_badges_2560x1440.jpg",
            {
                "LA-1-3": (102, 672, 128, 36, True),
                "LA-1-4": (822, 672, 132, 36, True),
                "LZ-1-1": (468, 432, 124, 36, True),
                "LS-1-3（剧情点，上方有橙色进度▼）": (1546, 672, 130, 36, False),
            },
        )
        self.check(
            "map_chapter_end_2560x1440.jpg",
            {"LA-1-17": (488, 672, 154, 36, True), "LS-1-7": (1234, 672, 128, 36, True), "LZ-1-6": (1594, 912, 128, 36, False)},
        )

    def test_parse_medals(self):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from src.core.stage_card import parse_medals

        self.assertEqual(parse_medals(["63/69"]), (63, 69))
        self.assertEqual(parse_medals(["再收集6可领取", "15 / 69"]), (15, 69))
        self.assertIsNone(parse_medals(["可领取"]))
        self.assertIsNone(parse_medals(["70/69"]))


if __name__ == "__main__":
    unittest.main()
