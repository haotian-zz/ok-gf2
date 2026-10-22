"""
实录 2026-10-22：尘烟前线两期之间卡片显示「12天22小时后开启」，点了进不去；原来照样按返回退出了班组页，
紧接着的「补给」找不到，班组补给（带红点）没领。
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.tasks.daily.daily_battle_mixin import DailyBattleMixin, chenyan_not_open_re


def card(name):
    return SimpleNamespace(name=name)


def fake_task(bottom_right_texts):
    task = Mock()
    task.config = {"尘烟": True}
    task.box = SimpleNamespace(bottom_right="bottom_right", top_right="top_right")

    def ocr(*args, match=None, box=None, **kw):
        if args:  # 右上角次数：没进尘烟页就读不到
            return []
        names = bottom_right_texts if box == "bottom_right" else []
        if isinstance(match, list):
            return [card(n) for n in names if n in match]
        return [card(n) for n in names if match.search(n)]

    task.ocr.side_effect = ocr
    return task


class ChenyanEntryTest(unittest.TestCase):
    def test_not_open_card_is_not_clicked(self):
        task = fake_task(["补给", "要务", "尘烟前线", "12天22小时后开启"])
        DailyBattleMixin.chenyan(task)
        task.click.assert_not_called()
        task.back.assert_not_called()

    def test_click_that_stays_on_guild_page_does_not_back_out(self):
        task = fake_task(["补给", "要务", "尘烟前线"])
        DailyBattleMixin.chenyan(task)
        task.click.assert_called_once()
        task.back.assert_not_called()

    def test_entered_page_backs_out(self):
        """进了尘烟页（班组页的按钮不在了）、次数读不到时照旧按返回。"""
        task = fake_task(["尘烟前线"])
        state = {"clicked": False}
        base_ocr = task.ocr.side_effect

        def ocr(*args, match=None, box=None, **kw):
            if state["clicked"] and box == "bottom_right":
                return []
            return base_ocr(*args, match=match, box=box, **kw)

        task.ocr.side_effect = ocr
        task.click.side_effect = lambda *a, **kw: state.update(clicked=True)
        DailyBattleMixin.chenyan(task)
        task.back.assert_called_once()

    def test_not_open_texts(self):
        for text in ("12天22小时后开启", "未开启", "暂未开放"):
            self.assertTrue(chenyan_not_open_re.search(text), text)
        self.assertFalse(chenyan_not_open_re.search("尘烟前线"))


if __name__ == "__main__":
    unittest.main()
