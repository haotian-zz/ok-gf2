import re

import cv2
from ok import Logger

from src.core.BaseGfTask import BaseGfTask, stamina_re
from src.image.hsv_config import HSVRange as hR

logger = Logger.get_logger(__name__)
pattern_kt = re.compile(r"^(?!(?=.*开拓之王)(?=.*区域开拓))(?:开拓之王|区域开拓(?:I|II|III|IV|V|VI|VII))$")


class WeeklyTask(BaseGfTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "周常"
        self.description = ""
        self.support_schedule_task = True
        self.default_config.update(
            {
                "首领挑战": True,
                "峰值推定": True,
                "扩编实练": True,
            }
        )

    def run(self):
        self.reset_lineup(None)
        self.ensure_main(recheck_time=2, time_out=90)
        tasks = [("首领挑战", self.boss_fast), ("峰值推定", self.peak_estimate_tion), ("扩编实练", self.deep_battle)]
        for key, func in tasks:
            if self.config.get(key):
                if func:
                    func()
        self.log_info("周常完成!", notify=True)

    def boss_fast(self):
        self.info_set("current_task", "boss_fast")
        self.wait_click_ocr(match=re.compile("战役推进"), box="top_right", after_sleep=0.5, raise_if_not_found=True)
        self.wait_click_ocr(match=re.compile("模拟作战"), box="top_right", raise_if_not_found=True)
        self.wait_click_ocr(match=re.compile("首领挑战"), raise_if_not_found=True, after_sleep=2)
        # 页面会记住上次的标签，停在「歧路挑战」（50 级解锁）时没有自律按钮，先切回「常规挑战」
        self.wait_click_ocr(match=re.compile("常规挑战"), box="top_right", time_out=3, after_sleep=1)
        self.fast_combat(set_cost=1, click_all=True)
        self.ensure_main()

    def peak_estimate_tion(self):
        self.info_set("current_task", "peak_estimate_tion")
        self.wait_click_ocr(match=re.compile("战役推进"), box="top_right", after_sleep=0.5, raise_if_not_found=True)
        self.wait_click_ocr(match=re.compile("模拟作战"), box="top_right", raise_if_not_found=True, after_sleep=2)
        self.wait_click_ocr(match=re.compile("峰值推定"), raise_if_not_found=True, after_sleep=2)
        self.wait_pop_up(count=1)
        self.wait_click_ocr(match=re.compile("常规峰值"), box="bottom_right", time_out=2, after_sleep=2)
        max_retry = 3
        for attempt in range(max_retry):
            temp = self.wait_ocr(match=re.compile("周期报酬"), box="bottom_left", time_out=2)
            if temp:
                self.click(temp[0], after_sleep=2)
                if self.wait_click_ocr(match=re.compile("一键领取"), time_out=2, after_sleep=2):
                    self.wait_pop_up(count=1)
                    self.back()
                break
            self.back()
        for attempt in range(max_retry):
            temp = self.wait_ocr(match=re.compile("极限峰值"), box="bottom_right", time_out=2)
            if temp:
                self.click(temp[0], after_sleep=2)
                self.click(temp[0], after_sleep=2)
                if not self._tab_selected(re.compile("极限峰值")):
                    self.log_info("极限峰值未解锁，跳过")
                    break
                if attempt == 0:
                    self.wait_pop_up(count=1)
                for i in range(max_retry):
                    if self.wait_click_ocr(match=re.compile("0" + str(i + 1)), after_sleep=2):
                        temp = self.wait_ocr(match=["开始作战"], box="bottom_right", raise_if_not_found=True, log=True)
                        if temp[0].name == "开始作战":
                            self.click(temp)
                            if not self.wait_ocr(match=re.compile("激化等级不足"), time_out=2):
                                self.auto_battle(has_dialog=True)
                            else:
                                self.back(after_sleep=2)
                            if self.wait_ocr(match=re.compile("激化阶群"), box="top_right", time_out=3):
                                self.back(after_sleep=2)
                break
            self.back()
        self.ensure_main()

    def deep_battle(self):
        self.info_set("current_task", "deep_battle")
        self.wait_click_ocr(match=re.compile("战役推进"), box="top_right", after_sleep=0.5, raise_if_not_found=True)
        self.wait_click_ocr(match=re.compile("模拟作战"), box="top_right", raise_if_not_found=True, after_sleep=2)
        self.wait_click_ocr(match=re.compile("扩编实练"), raise_if_not_found=True, after_sleep=2)
        self.wait_pop_up(count=1)
        results = None
        if result := self.wait_ocr(match=stamina_re, box="bottom_right", time_out=2):
            result = result[0].name.split("/")
            if len(result) == 2 and result[0] == result[1]:
                pass
            else:
                results = self.wait_ocr(match="特殊增强", settle_time=2, log=True)
        # results = self.wait_ocr(match="特殊增强", settle_time=2, log=True)
        if results:
            # 扩编实练是部署关：进部署界面后按「扩编实练编队」切整备室编队并补满
            self.set_lineup_kind("扩编实练")
            one_bool = False
            for result in results:
                self.click(result, after_sleep=2)
                self.wait_click_ocr(match="开始作战", box="bottom_right", after_sleep=2, log=True)
                self.auto_battle(has_dialog=True, need_click_auto=True, has_dialog_behind_start=True)
                self.wait_ocr(match="扩编实练", box="left", time_out=15, log=True)
                if not one_bool:
                    if self.wait_ocr(match="实练奖励", box="top", time_out=5, log=True):
                        self.back(after_sleep=2)
                    one_bool = True
                if result == results[-1]:
                    self.wait_pop_up(count=1)
                    if self.wait_click_ocr(match="当期实练奖励", box="bottom_right", after_sleep=2):
                        if result := self.ocr(match="一键领取", frame_processor=self.make_hsv_isolator(hR.WHITE)):
                            self.click(result[0], after_sleep=2)
        self.set_lineup_kind(None)
        self.ensure_main()

    def _tab_selected(self, match):
        """右下角标签：选中是蓝绿底（饱和度高），未选中/未解锁是浅灰底；找不到标签按选中处理，走原流程。"""
        self.next_frame()
        boxes = self.ocr(box="bottom_right", match=match)
        if not boxes or self.frame is None:
            return True
        b = boxes[0]
        region = self.frame[int(b.y):int(b.y + b.height), int(b.x):int(b.x + b.width)]
        if region.size == 0:
            return True
        sat = float(cv2.cvtColor(region, cv2.COLOR_BGR2HSV)[..., 1].mean())
        self.log_info(f"{b.name} 标签饱和度 {round(sat)}", notify=False)
        return sat > 50
