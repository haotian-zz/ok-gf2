import re

from ok import Logger

from src.core.BaseGfTask import BaseGfTask, map_re
from src.data.FeatureList import FeatureList as fL
from src.image.hsv_config import HSVRange as hR

logger = Logger.get_logger(__name__)

# 主线关卡名以数字开头（如 2-5），支线带字母前缀（如 SL-2-1、BH-2-2）
main_map_re = re.compile(r"^\s*-?\s*\d")


def is_branch_group(name_group):
    """名字组里没有任何以数字开头的关卡名时视为支线。"""
    names = [n for n in name_group if isinstance(n, str) and n not in (fL.not_clear_one, fL.now_icon)]
    if not names:
        return False
    return not any(main_map_re.match(n) for n in names)


def order_maps(maps, name_groups, main_first=True):
    """
    把关卡和对应的名字组配对后按优先级排序：
    1. 带未通关标记 / 当前位置标记的关卡
    2. 主线关卡（main_first 为 True 时）
    3. 支线关卡
    同一优先级按 x 从左到右。
    返回 [(map, name_group), ...]
    """

    def rank(item):
        current_map, group = item
        if fL.not_clear_one in group or fL.now_icon in group:
            return (0, current_map.x)
        if main_first and is_branch_group(group):
            return (2, current_map.x)
        return (1, current_map.x)

    return sorted(zip(maps, name_groups, strict=True), key=rank)


class ClearMapTask(BaseGfTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "推图"
        self.description = "从要推的图的最左边开始"
        self.default_config.update(
            {
                "普通OCR": True,
                "除杂色OCR1": True,
                "除杂色OCR2": True,
                "优先主线": True,
                "战斗内点击自动": False,
                "调试截图": True,
            }
        )
        self.config_description.update(
            {
                "普通OCR": (
                    "普通OCR：不做任何图像预处理，直接识别关卡名称\n"
                    "适用场景：背景和关卡卡片颜色与白色差异明显，文字清晰可辨"
                ),
                "除杂色OCR1": (
                    "除杂色OCR1（标准白色）：过滤掉非纯白色区域后再识别\n"
                    "适用场景：关卡卡片文字为标准白色，背景较复杂干扰识别"
                ),
                "除杂色OCR2": (
                    "除杂色OCR2（宽松白灰色）：同时保留白色与浅灰色区域后再识别\n"
                    "适用场景：关卡卡片文字为白色或浅灰色，或普通OCR/除杂色OCR1均无法识别时"
                ),
                "优先主线": (
                    "同一屏内先推数字开头的主线关卡（如 2-5），再清带字母前缀的支线（如 SL-2-1）\n"
                    "关闭后按从左到右的顺序推"
                ),
                "战斗内点击自动": (
                    "进入战斗后若检测到「行动结束」，自动点击右上角的自动战斗按钮\n"
                    "默认关闭，依赖游戏内全局自动（设置→其他→自动战斗设置）；未开全局自动时再打开"
                ),
                "调试截图": (
                    "把扫描、选关、战斗各阶段的截图保存到 screenshots/推图/日期/ 下\n"
                    "每个任务最多保留 400 张，方便排查问题"
                ),
            }
        )

    def run(self):
        count = 0
        clicked = []
        last_fallback_name = None
        last_failed_name = None  # 用来保存上次进入 if not text 分支的关卡名
        last_failed_flag = False  # 标记上次循环是否进入过 if not text 分支
        map_ocr_box = self.box_of_screen(x=0, y=100 / 1080, to_x=1.0, to_y=980 / 1080)

        # 根据用户配置动态组合要使用的帧处理器，保持顺序：普通OCR → 除杂色OCR1 → 除杂色OCR2
        # 至少保留一个，若全部关闭则回退到全部开启
        processors = []
        if self.config.get("普通OCR", True):
            processors.append(None)  # None 表示不做预处理，直接识别
        if self.config.get("除杂色OCR1", True):
            processors.append(self.make_hsv_isolator(hR.WHITE))  # 标准白色过滤
        if self.config.get("除杂色OCR2", True):
            processors.append(self.make_hsv_isolator(hR.WHITE_GRAY))  # 宽松白灰色过滤
        if not processors:
            processors = [None, self.make_hsv_isolator(hR.WHITE), self.make_hsv_isolator(hR.WHITE_GRAY)]

        while True:
            last_clicked = None
            self.sleep(2)
            # 根据上次是否失败，选择 OCR 匹配规则
            self.next_frame()
            map_name_groups = []
            if last_failed_flag and last_failed_name:
                maps = []
                pattern = re.compile(re.escape(last_failed_name))

                for p in processors:
                    maps = self.ocr(match=pattern, log=True, frame_processor=p)
                    if maps:
                        break

                if maps:
                    maps = [maps[0]]  # 只保留第一个，避免重复点击
                    maps[0].name = "before_one_" + maps[0].name
                    maps[0].x = int(maps[0].x - 80 / 256 * self.width)  # 往左扩展一些识别区域，增加找到的概率
                    map_name_groups = [{maps[0].name}]
                else:
                    map_name_groups = []
                last_failed_flag = False
            else:
                maps = []
                for p in processors:
                    maps.extend(self.ocr(match=map_re, log=True, frame_processor=p))
                maps.extend(self.find_feature(feature_name=fL.not_clear_one, box=map_ocr_box))
                now_icon_y_offset = 0.489 - 0.380
                # 当前帧直接匹配即可，不需要 wait_feature 的 1s 超时等待
                now_icon = self.find_feature(feature_name=fL.now_icon, box=map_ocr_box) or []
                for icon in now_icon:
                    icon.y = int(icon.y + now_icon_y_offset * self.height)

                maps.extend(now_icon)
                maps, map_name_groups = merge_maps(
                    maps, x_threshold=40 / 1920 * self.width, y_threshold=40 / 1080 * self.height
                )

            # 关卡与名字组必须一起排序，否则 clicked 记录会对应到错误的关卡
            ordered = order_maps(maps, map_name_groups, main_first=self.config.get("优先主线", True))
            maps = [m for m, _ in ordered]
            map_name_groups = [g for _, g in ordered]
            self.log_debug(f"maps: {maps}")
            self.debug_shot("scan", maps)

            if len(maps) == 0:
                if count == 0:
                    raise Exception("未找到要推的图!")
                else:
                    self.log_info(f"推图完成, 共{count}个!", notify=True)
                    return

            checked = False
            current_map = None
            name_group = set()
            for current_map, name_group in zip(maps, map_name_groups, strict=True):
                # 特殊特征永远允许点击
                if fL.not_clear_one in name_group or fL.now_icon in name_group:
                    checked = True
                    last_clicked = current_map
                    self.click(current_map, after_sleep=1)
                    break

                if not any(name in clicked for name in name_group):
                    clicked.extend(name_group)
                    checked = True
                    last_clicked = current_map
                    self.click(current_map, after_sleep=1)
                    break

            if not checked:
                # 当前兜底目标
                fallback = maps[-1]
                if last_fallback_name == fallback.name:
                    self.log_info(f"推图完成, 共{count}个!", notify=True)
                    return
                last_fallback_name = fallback.name
                self.click(fallback, after_sleep=2)
                self.back(after_sleep=2)
                continue

            self.sleep(0.5)
            boxes = self.wait_ocr(box="right", match=["特殊奖励", "观看", "挑战"], time_out=3, log=True)
            self.debug_shot(f"panel_{current_map.name}", boxes)
            if boxes:
                if self.find_boxes(boxes, match=["特殊奖励"]):
                    text = self.find_boxes(boxes, match=["观看", "挑战"])
                    if not text:
                        # 保存当前失败的关卡名，标记上次进入过该分支
                        last_failed_name = current_map.name
                        last_failed_flag = True
                        clicked = [name for name in clicked if name not in name_group]
                        self.back(after_sleep=2)
                        continue

                    # 正常处理挑战或观看
                    self.click(text, after_sleep=2)
                    count += 1
                    if text[0].name == "挑战":
                        self.auto_battle(
                            end_match=map_re,
                            has_dialog=True,
                            need_click_auto=self.config.get("战斗内点击自动", False),
                        )
                    else:
                        self.skip_dialogs(end_match=map_re)

                    if last_clicked:
                        self.log_debug(f"重新点击上一次关卡: {last_clicked.name}")
                        if self.wait_click_ocr(match=last_clicked.name, time_out=3, log=True, after_sleep=1):
                            self.back(after_sleep=2)
                else:
                    self.back(after_sleep=2)
            self.sleep(0.5)


def merge_maps(maps, x_threshold=40, y_threshold=40):
    merged = []  # 存最终的 map 对象
    merged_names = []  # 存每个合并组的所有 name

    for m in maps:
        for i, exist in enumerate(merged):
            if abs(m.x - exist.x) < x_threshold and abs(m.y - exist.y) < y_threshold:
                # 坐标取平均
                exist.x = int((exist.x + m.x) / 2)
                exist.y = int((exist.y + m.y) / 2)
                # 将当前 map 的名字加入该组
                merged_names[i].add(m.name)
                break
        else:
            merged.append(m)
            merged_names.append({m.name})  # 新组，名字放入 set

    return merged, merged_names
