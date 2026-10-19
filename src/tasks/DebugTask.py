"""
调试工具：给 okctl 远程调试用的小动作，点一个 OCR 文字、按几次 ESC、或抓一张带 OCR 框的截图。
不做任何游戏逻辑判断，只按配置执行一次。
"""

import re

from src.core.BaseGfTask import BaseGfTask


class DebugTask(BaseGfTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "调试工具"
        self.description = "按配置点一个文字 / 按 ESC / 截图，供远程调试用"
        self.default_config.update(
            {
                "点击文字": "",
                "按ESC次数": 0,
                "截图并OCR": False,
                "调试截图": True,
            }
        )
        self.config_description.update(
            {
                "点击文字": "非空时用 OCR 找到这个文字并点击（支持正则），找不到就报错",
                "按ESC次数": "点击之后再按几次 ESC",
                "截图并OCR": "把当前画面全部 OCR 一遍，文字写进日志，截图存到 screenshots/调试工具/",
            }
        )

    def run(self):
        text = (self.config.get("点击文字") or "").strip()
        if text:
            box = self.wait_ocr(match=re.compile(text), time_out=5, raise_if_not_found=False)
            if not box:
                raise Exception(f"没找到文字: {text}")
            self.log_info(f"点击 {box[0].name} at {box[0].center()}", notify=True)
            self.click(box, after_sleep=1.5)
        for _ in range(int(self.config.get("按ESC次数") or 0)):
            self.back(after_sleep=1.5)
        if self.config.get("截图并OCR"):
            self.next_frame()
            boxes = self.ocr()
            self.log_info(f"OCR: {[(b.name, int(b.x), int(b.y)) for b in boxes]}", notify=False)
            self.debug_shot("ocr", boxes)
