import re
import time

from ok import Logger

from src.core.BaseGfTask import pop_ups, BaseGfTask, map_re
from src.image.hsv_config import HSVRange as hR

logger = Logger.get_logger(__name__)



PANEL_WORDS = ["特殊奖励", "观看", "挑战", "完成前置关卡解锁"]
# 面板底部按钮：实机上 OCR 常把「观看」只框出一个「观」（0.81），所以第二个字可有可无
BUTTON_RE = [re.compile(r"^观\s*看?$"), re.compile(r"^挑\s*战?$")]
BUTTON_MIN_Y = 0.85  # 按钮在面板最底下，只认 y 在这以下的框，避免描述文字里的字混进来


def button_kind(text):
    """按钮文字 -> watch / challenge / None，容忍只读到第一个字。"""
    text = (text or "").strip().replace(" ", "")
    if text in ("观", "观看"):
        return "watch"
    if text in ("挑", "挑战"):
        return "challenge"
    return None


def classify_panel(has_boxes, locked_hint, special_reward, challenge, watch):
    """
    关卡面板文字 -> (状态, 动作按钮)。
    - 没识别到任何面板文字：nopanel
    - 有「完成前置关卡解锁」：locked
    - 没有「特殊奖励」（首通奖励已领）：cleared
    - 有奖励且有「挑战」/「观看」：challenge / watch
    - 有奖励但按钮还没识别到：unknown，交给调用方重读，绝不能当未解锁跳过
    """
    if not has_boxes:
        return "nopanel", None
    if locked_hint:
        return "locked", None
    if not special_reward:
        return "cleared", None
    if challenge:
        return "challenge", challenge
    if watch:
        return "watch", watch
    return "unknown", None


def canonical_name(name_group):
    """一组 OCR 名字里取一个稳定的关卡名：优先不带 * 的、最短的。"""
    names = sorted((n for n in name_group if isinstance(n, str)), key=lambda n: (n.endswith("*"), len(n), n))
    return names[0] if names else None


def order_maps(maps, name_groups):
    """把关卡和对应的名字组配对后按 x 从左到右排序，返回 [(map, name_group), ...]。"""
    return sorted(zip(maps, name_groups, strict=True), key=lambda item: item[0].x)


def pick_candidate(ordered, skip, cursor=None):
    """
    从排序后的 (map, name_group) 列表里挑下一个要点的关卡。

    - skip 里的名字（本地记录已通关 / 本次已处理 / 本轮未解锁）跳过
    - cursor 是进度游标：最近一次处理过的关卡名；只在它右边找。游标不在屏幕上时退回最左边
    - 返回 None 表示屏幕上没有可点的关卡
    """
    usable = [(m, g) for m, g in ordered if not (g & skip)]
    if cursor:
        cursor_box = next((m for m, g in ordered if cursor in g), None)
        if cursor_box is not None:
            usable = [(m, g) for m, g in usable if m.x > cursor_box.x]
    return usable[0] if usable else None


class ClearMapTask(BaseGfTask):
    LINEUP_TASK = True  # 每关开战前都整理阵容（切编队、补满；借助战看开关）

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "推图"
        self.description = "停在任意关卡页面启动即可，会先回到章节起点再从左到右推完所有未通关的关卡"
        self.default_config.update(
            {
                "普通OCR": True,
                "除杂色OCR1": True,
                "除杂色OCR2": True,
                "战斗内点击自动": False,
                "借好友助战": False,
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
                "借好友助战": (
                    "开战前按设置页「阵容与助战」里的规则借助战：先切到指定编队，再选椎数达标的指定角色\n"
                    "（没有就借战力最高），撤掉旧助战/同名人形/战力最低的一人后把助战部署上场，最后补满空位"
                ),
            }
        )
        self.processors = []

    # ------------------------------------------------------------------ 扫描
    def scan_maps(self):
        """识别当前屏幕上的关卡卡片，返回按 x 排序的 [(box, name_group), ...]。"""
        self.next_frame()
        maps = []
        for p in self.processors:
            maps.extend(self.ocr(match=map_re, log=True, frame_processor=p))
        maps, groups = merge_maps(maps, x_threshold=40 / 1920 * self.width, y_threshold=40 / 1080 * self.height)
        ordered = order_maps(maps, groups)
        self.log_debug(f"maps: {[m for m, _ in ordered]}")
        self.debug_shot("scan", [m for m, _ in ordered])
        return ordered

    # ------------------------------------------------------------------ 面板
    def inspect_card(self, card, name):
        """
        点开卡片读右侧面板，返回 (状态, 动作按钮)。
        状态：cleared / locked / challenge / watch / nopanel / unknown
        面板是带动画弹出来的，「特殊奖励」往往比底部按钮先出现，所以看到奖励却没看到按钮时多读几帧再下结论。
        """
        self.click(card, after_sleep=1)
        boxes = (
            self.wait_ocr(box="right", match=PANEL_WORDS, time_out=3, log=True)
            or []
        )
        status, action = self.panel_status(boxes)
        for _ in range(3):
            if status != "unknown":
                break
            # 有「特殊奖励」却没按钮：单独在右下角找按钮，容忍 OCR 只读到「观」/「挑」
            btn_boxes = self.ocr(box="bottom_right", match=BUTTON_RE, log=True) or []
            for b in btn_boxes:
                kind = button_kind(b.name)
                if kind and b.y >= self.height * BUTTON_MIN_Y:
                    self.log_info(f"右下角按钮读到 '{b.name}'，按 {kind} 处理", notify=False)
                    status, action = kind, [b]
                    break
            if status != "unknown":
                break
            self.sleep(0.6)
            self.next_frame()
            boxes = self.ocr(box="right", match=PANEL_WORDS, log=True) or []
            status, action = self.panel_status(boxes)
        self.debug_shot(f"panel_{name}", boxes)
        return status, action

    def panel_status(self, boxes):
        """按面板上识别到的文字判断关卡状态；只看到「特殊奖励」没看到按钮算 unknown，不能当作未解锁。"""
        # wait_ocr 的 match 会经过 OCR 纠错表展开（現看/観看 → 观看），
        # 但 find_boxes 是精确比较，这里要用同样展开过的匹配列表
        locked_hint = self.find_boxes(boxes, match=self.fix_match_regex(["完成前置关卡解锁"]))
        special_reward = self.find_boxes(boxes, match=self.fix_match_regex(["特殊奖励"]))
        challenge = self.find_boxes(boxes, match=self.fix_match_regex(["挑战"]))
        watch = self.find_boxes(boxes, match=self.fix_match_regex(["观看"]))
        return classify_panel(bool(boxes), bool(locked_hint), bool(special_reward), challenge, watch)

    def close_map_panel(self):
        """关卡面板打开时才按返回；选关页面没有面板时按返回会直接退出到章节页面。"""
        self.sleep(0.5)
        if self.ocr(box="right", match=[re.compile("推荐等级"), "挑战目标", "特殊奖励", "敌方单位"]):
            self.back(after_sleep=1.5)

    # ------------------------------------------------------------------ 主流程
    def run(self):
        processors = []
        if self.config.get("普通OCR", True):
            processors.append(None)  # None 表示不做预处理，直接识别
        if self.config.get("除杂色OCR1", True):
            processors.append(self.make_hsv_isolator(hR.WHITE))  # 标准白色过滤
        if self.config.get("除杂色OCR2", True):
            processors.append(self.make_hsv_isolator(hR.WHITE_GRAY))  # 宽松白灰色过滤
        if not processors:
            processors = [None, self.make_hsv_isolator(hR.WHITE), self.make_hsv_isolator(hR.WHITE_GRAY)]
        self.processors = processors

        self.log_info("推图开始", notify=False)
        self._lineup_verified = False  # 每次启动任务只在第一场整理阵容，之后沿用
        self.start_watchdog()
        try:
            self._run_sweep()
        finally:
            self.stop_watchdog()

    def _run_sweep(self):
        ordered = self.scan_maps()
        if not ordered:
            # 不在选关页面：可能停在部署界面、战斗中或结算页（比如上次手动停止），先把这一关收尾再继续
            if not self.resume_battle():
                raise Exception("未找到要推的图! 请停在关卡选择页面再启动")
            ordered = self.scan_maps()
            if not ordered:
                raise Exception("收尾后仍未回到选关页面, 请检查游戏画面")

        self.go_to_chapter_start()
        count = self.sweep_right()
        self.log_info(f"推图完成, 本次推进 {count} 关", notify=True)

    def resume_battle(self, time_out=1200):
        """
        从非选关页面接管：部署界面 / 战斗中 / 继续前进 → 走 auto_battle；结算页点确认；任务失败则报错。
        回到选关页面返回 True，认不出当前页面返回 False。
        """
        self.info_set("current_task", "接管当前战斗")
        start = time.time()
        unknown = 0
        while time.time() - start < time_out:
            self.next_frame()
            boxes = self.ocr()
            if self.find_boxes(boxes, match=map_re):
                return True
            if (
                self.find_boxes(boxes, match="作战开始")
                or self._is_battle_frame(boxes)
                or self.find_boxes(boxes, match="继续前进")
            ):
                self.log_info("当前在部署界面或战斗中，先打完这一关再继续推图", notify=True)
                self.auto_battle(end_match=map_re, has_dialog=True, need_click_auto=self.config.get("战斗内点击自动", False))
                self.close_map_panel()
                return True
            if self.find_boxes(boxes, match="任务失败"):
                self.debug_shot("resume_failed", boxes)
                raise Exception("任务失败, 没打过!")
            if confirm := self.find_boxes(boxes, match=self.fix_match_regex(["确认", "确认结算"])):
                self.click(confirm, after_sleep=2)
                continue
            if self.find_boxes(boxes, match=pop_ups):
                self.back(after_sleep=1)
                continue
            # 认不出的页面多半是剧情对话（没有可识别文字），按 skip_dialogs 的方式点右上角跳过
            unknown += 1
            self.log_info("当前页面没有可识别的按钮，按剧情处理尝试跳过", notify=False)
            found = self.skip_dialogs(
                end_match=[map_re, "作战开始", "继续前进", "任务完成", "任务失败", "确认", "确认结算"],
                time_out=90,
                has_dialog=True,
                raise_if_not_found=False,
            )
            if not found and unknown >= 2:
                self.debug_shot("resume_unknown", boxes)
                return False
        return False

    def go_to_chapter_start(self):
        """
        点屏幕最左边的卡片把视野往左挪，直到最左的卡片不再变化（到达章节起点）。
        地图拖动对 PostMessage 无效，但点任意卡片后游戏会把它滚到屏幕左中位置。
        路过的卡片顺便核实一下状态。
        """
        self.info_set("current_task", "回到章节起点")
        prev = None
        for _ in range(30):
            ordered = self.scan_maps()
            if not ordered:
                return
            leftmost, group = ordered[0]
            name = canonical_name(group)
            if name == prev or leftmost.x >= self.width * 0.45:
                return
            prev = name
            self.inspect_card(leftmost, name)
            self.close_map_panel()

    def sweep_right(self):
        """从当前视野开始一路往右，核实并推进每一关，直到右边没有可处理的关卡。返回本次推进的关数。"""
        self.info_set("current_task", "从左到右推图")
        count = 0
        session_done = set()  # 本次已处理过的关卡名
        locked = set()  # 本轮判定未解锁，推完任意一关后清空重判
        cursor = None  # 进度游标：最近一次处理过的关卡名，只往它右边推
        last_scroll = None  # 上次为了往右看而点击的最右卡片名
        rewound = False  # 本轮是否已经回到章节起点重查过未解锁的关卡
        unknown_tries = {}  # 面板读不出按钮的关卡 -> 已重试次数

        while True:
            self.sleep(1)
            ordered = self.scan_maps()
            if not ordered:
                raise Exception("选关页面上没有识别到关卡, 请检查游戏画面")

            skip = session_done | locked
            candidate = pick_candidate(ordered, skip, cursor)
            if candidate is None:
                # 屏幕右边没有可处理的了：点最右边的卡片把视野往右挪，看看还有没有更多关卡
                rightmost, group = ordered[-1]
                name = canonical_name(group)
                if name != last_scroll and rightmost.x > self.width * 0.55:
                    last_scroll = name
                    self.log_info(f"向右查看更多关卡 (点击 {name})", notify=False)
                    self.click(rightmost, after_sleep=1.5)
                    self.close_map_panel()
                    continue
                if locked and not rewound:
                    # 未解锁的关卡可能在游标左边、甚至已经滚出屏幕（比如 SL-5-3 在 BH-5-1 左边），
                    # 回到章节起点不带游标重新核实一遍
                    self.log_info(f"右边没有可推的关卡，回章节起点重查未解锁的 {sorted(locked)}", notify=False)
                    rewound = True
                    locked.clear()
                    cursor = None
                    last_scroll = None
                    self.go_to_chapter_start()
                    continue
                if locked:
                    raise Exception(f"剩余关卡都未解锁({sorted(locked)}), 请检查前置关卡后再启动")
                return count

            card, group = candidate
            name = canonical_name(group) or "unknown"
            status, action = self.inspect_card(card, name)
            if status == "nopanel":
                self.log_info(f"{name} 未识别到关卡面板, 跳过", notify=False)
                session_done.update(group)
                self.close_map_panel()
                continue
            if status == "unknown":
                tries = unknown_tries.get(name, 0) + 1
                unknown_tries[name] = tries
                if tries <= 2:
                    self.log_info(f"{name} 面板上没读到挑战/观看按钮，关掉面板重试第 {tries} 次", notify=False)
                else:
                    self.log_info(f"{name} 面板反复读不到按钮, 跳过", notify=True)
                    session_done.update(group)
                self.close_map_panel()
                continue
            if status == "locked":
                self.log_info(f"{name} 未解锁, 先推其他关卡", notify=False)
                locked.update(group)
                self.close_map_panel()
                continue
            if status == "cleared":
                self.log_info(f"{name} 已通关, 跳过", notify=False)
                session_done.update(group)
                cursor = name
                self.close_map_panel()
                continue

            # challenge / watch
            self.click(action, after_sleep=2)
            if status == "challenge":
                self.auto_battle(
                    end_match=map_re,
                    has_dialog=True,
                    need_click_auto=self.config.get("战斗内点击自动", False),
                )
            else:
                self.skip_dialogs(end_match=map_re)
            count += 1
            session_done.update(group)
            cursor = name
            if locked:
                # 推过一关后，之前未解锁的关卡可能已经解锁；它们可能在游标左边，所以不带游标重新找
                locked.clear()
                cursor = None
            last_scroll = None
            rewound = False
            self.close_map_panel()


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
