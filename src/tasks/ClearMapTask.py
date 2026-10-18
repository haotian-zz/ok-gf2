import re

from ok import Logger

from src.core.BaseGfTask import BaseGfTask, map_re
from src.data.FeatureList import FeatureList as fL
from src.image.hsv_config import HSVRange as hR

logger = Logger.get_logger(__name__)


def order_maps(maps, name_groups):
    """
    把关卡和对应的名字组配对后排序：带未通关标记 / 当前位置标记的关卡最先，其余按 x 从左到右。
    返回 [(map, name_group), ...]
    """

    def rank(item):
        current_map, group = item
        marked = fL.not_clear_one in group or fL.now_icon in group
        return (0 if marked else 1, current_map.x)

    return sorted(zip(maps, name_groups, strict=True), key=rank)


def pick_candidate(ordered, done, locked, anchor=None):
    """
    从排序后的 (map, name_group) 列表里挑下一个要点的关卡。

    - 跳过已处理(done)和已判定未解锁(locked)的关卡
    - anchor 为刚判定未解锁的关卡名：解锁它的前置只可能在它左边，所以只在它左边找，
      取最靠近它的那个；anchor 不在屏幕上时退回最左边的可用关卡
    - 返回 None 表示屏幕上没有可点的关卡
    """
    usable = [(m, g) for m, g in ordered if not (g & done) and not (g & locked)]
    if not usable:
        return None
    if anchor:
        anchor_box = next((m for m, g in ordered if anchor in g), None)
        if anchor_box is not None:
            left = [(m, g) for m, g in usable if m.x < anchor_box.x]
            return left[-1] if left else None
    return usable[0]


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
        done = set()  # 已通关 / 已看过剧情 / 确认无需再点的关卡名
        locked = set()  # 本轮判定为未解锁的关卡名，完成任意关卡后清空重判
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

        anchor = None  # 最近一次判定为未解锁的关卡名，下一步只往它左边找前置
        last_scroll_leftmost = None  # 上次为了往左看而点击的最左卡片名，用来判断视野有没有真的移动

        while True:
            self.sleep(1)
            self.next_frame()
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

            # 关卡与名字组必须一起排序，否则 done/locked 记录会对应到错误的关卡
            ordered = order_maps(maps, map_name_groups)
            self.log_debug(f"maps: {[m for m, _ in ordered]}")
            self.debug_shot("scan", [m for m, _ in ordered])

            if not ordered:
                if count == 0:
                    raise Exception("未找到要推的图! 请停在关卡选择页面再启动")
                self.log_info(f"推图完成, 共{count}个!", notify=True)
                return

            candidate = pick_candidate(ordered, done, locked, anchor)
            if candidate is None:
                if anchor:
                    # 前置关卡不在屏幕内。地图拖动对 PostMessage 无效，但点任意卡片后游戏会把它
                    # 滚到屏幕左中位置，所以点最左边那张卡就能把视野往左挪。
                    leftmost, leftmost_group = min(ordered, key=lambda item: item[0].x)
                    leftmost_name = next(iter(leftmost_group))
                    if leftmost_name != last_scroll_leftmost and leftmost.x < self.width * 0.45:
                        last_scroll_leftmost = leftmost_name
                        self.log_info(f"{anchor} 的前置关卡不在屏幕内, 点击 {leftmost_name} 把视野往左挪", notify=False)
                        self.click(leftmost, after_sleep=1.5)
                        self.close_map_panel()
                        continue
                    raise Exception(f"{anchor} 未解锁且屏幕左侧没有可推的前置关卡, 请手动把视野移到前置关卡再启动")
                if locked:
                    raise Exception(f"剩余关卡都未解锁({sorted(locked)}), 请手动把视野移到前置关卡再启动")
                self.log_info(f"推图完成, 共{count}个!", notify=True)
                return
            current_map, name_group = candidate
            self.click(current_map, after_sleep=1)

            boxes = (
                self.wait_ocr(box="right", match=["特殊奖励", "观看", "挑战", "完成前置关卡解锁"], time_out=3, log=True)
                or []
            )
            # wait_ocr 的 match 会经过 OCR 纠错表展开（現看/観看 → 观看），
            # 但 find_boxes 是精确比较，这里要用同样展开过的匹配列表
            locked_hint = self.find_boxes(boxes, match=self.fix_match_regex(["完成前置关卡解锁"]))
            special_reward = self.find_boxes(boxes, match=self.fix_match_regex(["特殊奖励"]))
            challenge = self.find_boxes(boxes, match=self.fix_match_regex(["挑战"]))
            watch = self.find_boxes(boxes, match=self.fix_match_regex(["观看"]))
            self.debug_shot(f"panel_{current_map.name}", boxes)
            if not boxes:
                # 面板没弹出或没识别到，跳过这张避免反复点
                self.log_info(f"{current_map.name} 未识别到关卡面板, 跳过", notify=False)
                done.update(name_group)
                self.close_map_panel()
                continue

            if locked_hint:
                self.log_info(f"{current_map.name} 未解锁, 往左找前置关卡", notify=False)
                locked.update(name_group)
                anchor = current_map.name
                self.close_map_panel()
                continue

            if not special_reward:
                # 没有首通特殊奖励 = 已通关
                self.log_info(f"{current_map.name} 已通关, 跳过", notify=False)
                done.update(name_group)
                self.close_map_panel()
                continue

            action = challenge or watch
            if not action:
                self.log_info(f"{current_map.name} 面板没有挑战/观看按钮, 视为未解锁", notify=False)
                locked.update(name_group)
                anchor = current_map.name
                self.close_map_panel()
                continue

            # 正常处理挑战或观看
            self.click(action, after_sleep=2)
            count += 1
            if challenge:
                self.auto_battle(
                    end_match=map_re,
                    has_dialog=True,
                    need_click_auto=self.config.get("战斗内点击自动", False),
                )
            else:
                self.skip_dialogs(end_match=map_re)
            done.update(name_group)
            # 推过一关后，之前未解锁的关卡可能已经解锁，重新从左往右判定
            locked.clear()
            anchor = None
            last_scroll_leftmost = None
            self.close_map_panel()

    def close_map_panel(self):
        """
        关卡面板打开时才按返回；选关页面没有面板时按返回会直接退出到章节页面。
        """
        self.sleep(0.5)
        if self.ocr(box="right", match=[re.compile("推荐等级"), "挑战目标", "特殊奖励", "敌方单位"]):
            self.back(after_sleep=1.5)


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
