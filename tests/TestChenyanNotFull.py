"""尘烟攻坚战编队没坐满时弹「仍有可上阵的位置，是否依然开始作战」，要先确认再开战。"""

import unittest

from tests.TestChenyanAssist import AssistDevice

NOT_FULL = "仍有可上阵的位置，是否依然开始作战"


class NotFullDevice(AssistDevice):
    """点「确定」后弹没坐满的确认框；点框里的「确认」才进战斗。"""

    def __init__(self, popup=True, **kwargs):
        super().__init__(**kwargs)
        self.popup = popup

    def visible(self):
        if self.page == "not_full":
            return [NOT_FULL, "取消", "确认"]
        return super().visible()

    def click(self, target, **kwargs):
        name = (target[0] if isinstance(target, list) else target).name
        if name == "确定" and self.popup:
            self.clicked.append(name)
            self.page = "not_full"
            return
        if name == "确认" and self.page == "not_full":
            self.clicked.append(name)
            self.page = "battle"
            return
        super().click(target, **kwargs)

    click_box = click

    def auto_battle(self, *args):
        """开战时还挡着确认框就说明没处理弹窗。"""
        if self.page == "not_full":
            raise RuntimeError("确认框还挡着就开战了")
        self.battles += 1


class ChenyanNotFullTest(unittest.TestCase):
    def test_not_full_popup_is_confirmed_before_battle(self):
        """实录 2026-11-25：第二场有人休息中，只上 2 人 + 助战，弹框挡住开战。"""
        task = NotFullDevice(candidates=["OTs-14"])
        self.assertTrue(task.choose_chenyan(1))
        self.assertEqual(["确定", "确认"], task.clicked[-2:])
        self.assertEqual(1, task.battles)

    def test_full_lineup_goes_straight_to_battle(self):
        task = NotFullDevice(popup=False, candidates=["OTs-14"])
        self.assertTrue(task.choose_chenyan(2))
        self.assertNotIn("确认", task.clicked)
        self.assertEqual(1, task.battles)


if __name__ == "__main__":
    unittest.main()
