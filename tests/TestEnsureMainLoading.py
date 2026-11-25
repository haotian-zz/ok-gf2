"""
ensure_main：加载页的时间不算进回主页的超时。
实录 2026-11-08：从极限峰值部署界面回主页，退出作战 14 秒、加载 15 秒，加载刚结束就满 30 秒；
原来只在超时那一刻看一眼画面，那时已经是峰值推定页（不是加载页），直接报「请从游戏主页进入」。
实录 2026-11-24：游戏更新当天启动，标题页前「下载资源 [x/2.95GB]」下了两分多钟，150 秒到点报「请从游戏主页进入」。
用假时钟按实录时间线跑，不依赖 ok 框架。
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
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("ensure_main", "_download_progress")]
consts = [
    n
    for n in tree.body
    if isinstance(n, ast.Assign)
    and any(
        isinstance(t, ast.Name) and t.id in ("download_re", "download_amount_re", "DOWNLOAD_STALL", "DOWNLOAD_MAX_WAIT")
        for t in n.targets
    )
]


class Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t


class Game:
    """按时间线切画面：battle（战斗菜单/退出确认）→ loading → peak（峰值推定页，按一次返回就到主页）→ main。"""

    IS_MAIN_COST = 4.5  # 实录里每轮 is_main 大约 4.5 秒

    def __init__(self, clock, loading_from, loading_until, download_until=0, download_rate=0.035):
        self.clock = clock
        self.loading_from = loading_from
        self.loading_until = loading_until
        self.download_until = download_until  # 这之前是游戏更新的下载页
        self.download_rate = download_rate  # GB/秒；0 = 进度卡住不动
        self.backed = False

    def page(self):
        t = self.clock.t
        if self.backed:
            return "main"
        if t < self.download_until:
            return "download"
        if t < self.loading_from:
            return "battle"
        if t < self.loading_until:
            return "loading"
        return "peak"

    def is_main(self, recheck_time=1, esc=True):
        page = self.page()
        self.clock.t += self.IS_MAIN_COST
        if page == "main":
            return True
        if page == "peak":
            self.backed = True  # is_main 在峰值推定页点了返回
        return False

    def ocr(self, *args, **kwargs):
        if self.page() == "download":
            done = min(self.clock.t * self.download_rate, 2.95)
            texts = (f"下载资源 [{done:.2f}GB/2.95GB]", "35MB/S", "Ver:4.0.5136.15157")
            return [SimpleNamespace(name=t) for t in texts]
        texts = {
            "battle": ["退出作战", "确认"],
            "loading": ["87%", "资源加载中", "2067年，由国安局主导的“人形角斗场取缔行动”顺利开展"],
            "peak": ["01", "激化阶群·子群1", "常规峰值", "极限峰值"],
            "main": ["整备室", "公共区"],
        }[self.page()]
        return [SimpleNamespace(name=t) for t in texts]


def make(loading_from, loading_until, **download):
    clock = Clock()
    ns = {"re": re, "time": clock}
    exec(compile(ast.Module(body=consts + methods, type_ignores=[]), str(source), "exec"), ns)
    game = Game(clock, loading_from, loading_until, **download)
    task = Mock()
    task._deadline_bump = 0
    task.is_main.side_effect = game.is_main
    task.ocr.side_effect = game.ocr
    task._is_loading_frame.side_effect = lambda boxes: any("资源加载中" in b.name for b in boxes)
    task._download_progress.side_effect = lambda boxes: ns["_download_progress"](task, boxes)
    task.sleep.side_effect = lambda s: setattr(clock, "t", clock.t + s)
    return ns["ensure_main"], task, clock


def download_progress(*names):
    ns = {"re": re}
    exec(compile(ast.Module(body=consts + methods, type_ignores=[]), str(source), "exec"), ns)
    return ns["_download_progress"](None, [SimpleNamespace(name=n) for n in names])


class EnsureMainLoadingTest(unittest.TestCase):
    def test_loading_right_before_deadline_does_not_time_out(self):
        ensure_main, task, clock = make(loading_from=14, loading_until=29.5)
        self.assertTrue(ensure_main(task))
        task.debug_shot.assert_not_called()
        self.assertLess(clock.t, 60)

    def test_stuck_page_without_loading_still_times_out(self):
        ensure_main, task, clock = make(loading_from=1000, loading_until=1000)
        task.is_main.side_effect = lambda **kw: setattr(clock, "t", clock.t + 4.5) or False
        with self.assertRaisesRegex(Exception, "请从游戏主页进入"):
            ensure_main(task)
        self.assertLess(clock.t, 40)
        task.debug_shot.assert_called_once_with("ensure_main_timeout")

    def test_endless_loading_is_capped_by_loading_grace(self):
        ensure_main, task, clock = make(loading_from=0, loading_until=10_000)
        with self.assertRaisesRegex(Exception, "请从游戏主页进入"):
            ensure_main(task, loading_grace=20)
        self.assertLess(clock.t, 30 + 20 + 10)

    def test_resource_download_does_not_count_toward_launch_timeout(self):
        # 拉起游戏后 2.95 GB 下 5 分多钟，下完加载 10 秒，再按一次返回进主页
        ensure_main, task, clock = make(loading_from=330, loading_until=340, download_until=330, download_rate=0.009)
        self.assertTrue(ensure_main(task, recheck_time=2, time_out=150))
        task.debug_shot.assert_not_called()
        self.assertGreater(clock.t, 330)

    def test_stalled_download_still_times_out(self):
        ensure_main, task, clock = make(
            loading_from=10_000, loading_until=10_000, download_until=10_000, download_rate=0
        )
        with self.assertRaisesRegex(Exception, "请从游戏主页进入"):
            ensure_main(task, recheck_time=2, time_out=150)
        self.assertLess(clock.t, 180 + 150 + 20)

    def test_endless_download_is_capped(self):
        ensure_main, task, clock = make(
            loading_from=100_000, loading_until=100_000, download_until=100_000, download_rate=0.00001
        )
        with self.assertRaisesRegex(Exception, "请从游戏主页进入"):
            ensure_main(task, recheck_time=2, time_out=150)
        self.assertLess(clock.t, 1800 + 150 + 120 + 20)


class DownloadProgressTest(unittest.TestCase):
    """实录 2026-11-24 的 OCR 结果：进度有时整段读出，有时被切成两段、单位读错。"""

    def test_reads_downloaded_amount(self):
        self.assertEqual(download_progress("下载资源 [1.53GB/2.95GB]", "40MB/S", "游戏著作权人"), "1.53G")
        self.assertEqual(download_progress("下载资源[196.22M", "/2.95GI", "6MB/S"), "196.22M")
        self.assertEqual(download_progress("下载资源", "84GB/2.95GB]", "32MB/S"), "84G")

    def test_download_page_without_numbers(self):
        self.assertEqual(download_progress("下载资源", "游戏著作权人：上海散爆信息技术有限公司"), "下载资源")

    def test_other_pages(self):
        self.assertIsNone(download_progress("整备室", "公共区", "活动层"))
        self.assertIsNone(download_progress("87%", "资源加载中"))
        self.assertIsNone(download_progress())


if __name__ == "__main__":
    unittest.main()
