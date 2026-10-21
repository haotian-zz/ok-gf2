import re
import time

from ok import Logger

from src.core.BaseGfTask import pop_ups, BaseGfTask, map_re, chapter_select_re
from src.image.hsv_config import HSVRange as hR

logger = Logger.get_logger(__name__)



PANEL_WORDS = ["特殊奖励", "观看", "挑战", "完成前置关卡解锁"]
# 面板底部按钮：实机上 OCR 常把「观看」只框出一个「观」（0.81），所以第二个字可有可无
BUTTON_RE = [re.compile(r"^观\s*看?$"), re.compile(r"^挑\s*战?$")]
BUTTON_MIN_Y = 0.85  # 按钮在面板最底下，只认 y 在这以下的框，避免描述文字里的字混进来

# ------------------------------------------------------------------ 章节选择页（持续推进用，实录 2026-10-20）
# 从章节地图按 ESC 回到章节选择页：左边一列章节标题，当前章前面有「9.0」这样的高亮角标，后面的章节往下排，
# 未解锁的带锁、点了没有任何反应；右下是「章节进度 57% / 27/48 / 一句简介」和「确认」。
CHAPTER_LIST_MAX_X = 0.2  # 章节标题都在画面左边 20% 以内
CHAPTER_LIST_MAX_Y = 0.85  # 再往下是「猎人评定 / 同调演练」入口
CHAPTER_BADGE_MAX_X = 0.015  # 当前章的「9.0」角标贴着左边（x≈13/2560）；其他章前面的「C-11.0」小字在 x≈69
chapter_badge_re = re.compile(r"\d+\s*\.\s*\d\s*$")
chapter_title_re = re.compile(r"[\u4e00-\u9fff]{2,}")
chapter_noise_re = re.compile(r"^C\s*-|猎人评定|同调演练|剧情战役|往期活动|模拟作战|补给作战")
chapter_select_words = ["章节进度"]


class ChapterLocked(Exception):
    """本章剩下的关卡都未解锁。"""


def chapter_titles(boxes, width, height):
    """章节选择页左列的章节标题框，从上到下。"""
    out = []
    for b in boxes:
        name = (b.name or "").strip()
        if b.x > CHAPTER_LIST_MAX_X * width or b.y > CHAPTER_LIST_MAX_Y * height or b.y < 0.08 * height:
            continue
        if chapter_noise_re.search(name) or not chapter_title_re.search(name):
            continue
        out.append(b)
    return sorted(out, key=lambda b: b.y)


def current_and_next_chapter(boxes, width, height):
    """(当前章标题框, 下一章标题框)。当前章按「9.0」角标所在行认，角标没读到就当最上面那个是当前章。"""
    titles = chapter_titles(boxes, width, height)
    if not titles:
        return None, None
    badges = [
        b
        for b in boxes
        if b.x <= CHAPTER_BADGE_MAX_X * width and chapter_badge_re.search(b.name or "") and not (b.name or "").strip().startswith("C")
    ]
    if badges:
        by = badges[0].y + badges[0].height / 2
        current = min(titles, key=lambda t: abs(t.y + t.height / 2 - by))
    else:
        current = titles[0]
    later = [t for t in titles if t.y > current.y + current.height / 2]
    return current, (later[0] if later else None)


chapter_progress_re = re.compile(r"^\s*\d{1,3}\s*%\s*$|^\s*\d{1,3}\s*/\s*\d{1,3}\s*$")


def chapter_display_name(text):
    """「010.0远日点·下篇Q」→「远日点·下篇」：去掉粘进来的角标数字和尾巴上的杂字，只用于日志。"""
    m = re.search(r"[\u4e00-\u9fff][\u4e00-\u9fff·・\s]*[\u4e00-\u9fff]", text or "")
    return m.group(0) if m else (text or "").strip()


def chapter_signature(boxes, width, height):
    """
    选中了哪一章的指纹：右侧「57%」「27/48」两个数字 + 左边角标所在行。
    点锁着的章节什么都不变；简介那句话 OCR 时有时无句号，不拿来比。
    """
    nums = tuple(sorted((b.name or "").replace(" ", "") for b in boxes if b.x > 0.6 * width and chapter_progress_re.match(b.name or "")))
    current, _ = current_and_next_chapter(boxes, width, height)
    return nums, (current.name if current else None)



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
        self.description = "停在任意关卡页面或章节选择页启动即可，先回章节起点从左到右推完未通关的关卡，推完自动进下一章"
        self.default_config.update(
            {
                "普通OCR": True,
                "除杂色OCR1": True,
                "除杂色OCR2": True,
                "战斗内点击自动": False,
                "推完继续下一章": True,
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
                "推完继续下一章": (
                    "本章能推的都推完（或剩下的都没解锁）后，回章节选择页进入下一章继续推\n"
                    "下一章没解锁（带锁、点了没反应）就正常结束"
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
        self.reset_lineup("推图")  # 每次启动任务只在第一场整理阵容，之后沿用
        self.start_watchdog()
        try:
            self._run_sweep()
        finally:
            self.stop_watchdog()

    def _run_sweep(self):
        ordered = self.scan_maps()
        if not ordered and self.reenter_from_chapter_select():
            # 停在章节选择页（或作战的其他页签）：进当前选中的章节
            ordered = self.scan_maps()
        if not ordered:
            # 不在选关页面：可能停在部署界面、战斗中或结算页（比如上次手动停止），先把这一关收尾再继续
            if not self.resume_battle():
                raise Exception("未找到要推的图! 请停在关卡选择页面再启动")
            ordered = self.scan_maps()
            if not ordered:
                raise Exception("收尾后仍未回到选关页面, 请检查游戏画面")

        total = 0
        for _ in range(30):
            self.go_to_chapter_start()
            try:
                count, locked = self.sweep_right(), None
            except ChapterLocked as e:
                count, locked = getattr(e, "count", 0), e
            total += count
            if not self.config.get("推完继续下一章", True):
                if locked:
                    raise locked
                break
            nxt = self.enter_next_chapter()
            if not nxt:
                if locked:
                    self.log_info(f"{locked}；下一章也没解锁，推图结束", notify=True)
                break
            self.log_info(f"进入下一章「{nxt}」继续推图", notify=True)
            if not self.scan_maps():
                raise Exception(f"进入「{nxt}」后没看到关卡, 请检查游戏画面")
        self.log_info(f"推图完成, 本次推进 {total} 关", notify=True)

    # ------------------------------------------------------------------ 持续推进
    def open_chapter_select(self):
        """从章节地图按 ESC 回到章节选择页。"""
        for _ in range(3):
            if self.wait_ocr(match=chapter_select_words, box="bottom_right", time_out=3, raise_if_not_found=False):
                return True
            self.back(after_sleep=2)
        return bool(self.ocr(match=chapter_select_words, box="bottom_right"))

    def reenter_from_chapter_select(self):
        """
        打完 / 看完一关后游戏退回了章节选择页：点「确认」进回选中的章节。返回是否进去了。
        停在「模拟作战 / 往期活动 / 补给作战」页签时先点「剧情战役」页签回到章节选择页。
        """
        if not self.ocr(match=chapter_select_words, box="bottom_right"):
            tab = self.ocr(box="top", match=re.compile(r"^剧情战役$"))
            if not tab:
                return False
            self.log_info("停在作战的其他页签上，切回「剧情战役」", notify=True)
            self.click(tab, after_sleep=2)
            if not self.wait_ocr(match=chapter_select_words, box="bottom_right", time_out=5, raise_if_not_found=False):
                return False
        self.log_info("回到了章节选择页，点确认进回章节继续推", notify=True)
        self.debug_shot("back_on_chapter_select")
        if not self.wait_click_ocr(match=self.fix_match_regex(["确认"]), box="bottom_right", time_out=5, after_sleep=3, raise_if_not_found=False):
            return False
        self.skip_dialogs(end_match=map_re, time_out=120, has_dialog=True, raise_if_not_found=False)
        return True

    def enter_next_chapter(self):
        """
        回章节选择页，点当前章下面那一章：右侧章节信息变了说明已选中（解锁了），点「确认」进去并跳过开场剧情；
        信息没变（锁着，点了没反应）或已经是最后一章就返回 None，停在章节选择页。返回新章节名。
        """
        self.info_set("current_task", "进入下一章")
        self.close_map_panel()
        if not self.open_chapter_select():
            self.log_info("没回到章节选择页，不继续下一章", notify=True)
            return None
        self.sleep(1)
        boxes = self.ocr(log=True)
        self.debug_shot("chapter_select", boxes)
        current, nxt = current_and_next_chapter(boxes, self.width, self.height)
        if nxt is None:
            self.log_info(f"「{current.name if current else '?'}」后面没有下一章了", notify=True)
            return None
        before = chapter_signature(boxes, self.width, self.height)
        self.click(nxt, after_sleep=1.5)
        self.next_frame()
        after_boxes = self.ocr(log=True)
        if chapter_signature(after_boxes, self.width, self.height) == before:
            self.log_info(f"下一章「{chapter_display_name(nxt.name)}」还没解锁（点了没反应）", notify=True)
            self.debug_shot("next_chapter_locked", after_boxes)
            return None
        confirm = self.find_boxes(after_boxes, match=self.fix_match_regex(["确认"]))
        if not confirm:
            self.log_info(f"选中了「{nxt.name}」但没找到「确认」", notify=True)
            return None
        self.click(confirm, after_sleep=3)
        # 新章节开头常有剧情 / 动画，跳过直到看到关卡卡片
        self.skip_dialogs(end_match=map_re, time_out=180, has_dialog=True, raise_if_not_found=False)
        return chapter_display_name(nxt.name)

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
                self.auto_battle(end_match=[map_re, chapter_select_re], has_dialog=True, need_click_auto=self.config.get("战斗内点击自动", False))
                self.reenter_from_chapter_select()
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
        pushed_since_rewind = False  # 上次从章节起点开扫以来推过关卡（可能解锁了游标左边的支线）
        unknown_tries = {}  # 面板读不出按钮的关卡 -> 已重试次数

        while True:
            self.sleep(1)
            ordered = self.scan_maps()
            if not ordered and self.reenter_from_chapter_select():
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
                if pushed_since_rewind or (locked and not rewound):
                    # 未解锁的关卡可能在游标左边、甚至已经滚出屏幕（比如 SL-5-3 在 BH-5-1 左边）；
                    # 推过的关卡也可能解锁了游标左边的支线（实录 2026-10-20：10-8 打完后 BH-10-3 解锁，
                    # 但它在 10-10 左边，游标停在 10-10 时被跳过）。回章节起点不带游标重新扫一遍，
                    # 直到某一遍从头扫到尾一关都没推。
                    why = "推过关卡，可能解锁了左边的支线" if pushed_since_rewind else f"重查未解锁的 {sorted(locked)}"
                    self.log_info(f"右边没有可推的关卡，回章节起点再扫一遍（{why}）", notify=False)
                    rewound = True
                    pushed_since_rewind = False
                    locked.clear()
                    cursor = None
                    last_scroll = None
                    self.go_to_chapter_start()
                    continue
                if locked:
                    err = ChapterLocked(f"剩余关卡都未解锁({sorted(locked)}), 请检查前置关卡后再启动")
                    err.count = count
                    raise err
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
            # 实录 2026-10-20：看完 SL-10-6 剧情游戏退回了章节选择页，所以章节选择页也算结束，下一轮扫描前再点确认进回来
            if status == "challenge":
                self.auto_battle(
                    end_match=[map_re, chapter_select_re],
                    has_dialog=True,
                    need_click_auto=self.config.get("战斗内点击自动", False),
                )
            else:
                self.skip_dialogs(end_match=[map_re, chapter_select_re])
            count += 1
            session_done.update(group)
            cursor = name
            if locked:
                # 推过一关后，之前未解锁的关卡可能已经解锁；它们可能在游标左边，所以不带游标重新找
                locked.clear()
                cursor = None
            last_scroll = None
            pushed_since_rewind = True
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
