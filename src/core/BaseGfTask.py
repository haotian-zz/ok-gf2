import re
import threading
import time
from difflib import SequenceMatcher

from ok import BaseTask, Box, Logger, find_boxes_by_name

from src.core.base_mixin.runtime_mixin import RuntimeMixin
from src.core.debug_shot import save_debug_shot
from src.core.support_select import (
    AvatarBook,
    BUTTON_BOX,
    COUNT_BOX,
    MAP_BOX,
    NAME_BOX,
    PANEL_BOX,
    TAB_BOX,
    check_point,
    empty_tiles,
    far_point,
    filter_point,
    find_deploy_tiles,
    find_unit_tags,
    unit_tiles_from_tags,
    find_cards,
    find_tiles,
    identify_cards,
    is_orange_check,
    merge_tiles,
    order_tiles,
    pick_candidates,
    read_badge,
)
from src.data.FeatureList import FeatureList as fL
from src.image.frame_processs import isolate_by_hsv_ranges
from src.image.hsv_config import HSVRange as hR
from src.interaction.ScreenPosition import ScreenPosition

logger = Logger.get_logger(__name__)
pop_ups = ["点击空白处关闭", "点击屏幕任意位置继续", "点击任意位置继续", "新周期开启", "周期已重置"]
number_re = re.compile(r"^\d+$")
stamina_re = re.compile(r"^\d+/\d+")
# 关卡名：可选的字母前缀（SL-/BH-/今后其他组合）+ 章-关，如 3-1、SL-3-2、BH-3-4
map_re = re.compile(r"^[^\d\s]{0,4}\s*\d{1,2}\s*-\s*\d{1,2}\s*\*?$")
# 战斗中界面的标志：右下角「行动结束」或左上角「01/12 回合」计数
battle_ui_re = re.compile(r"行动结束|\d{1,2}\s*/\s*\d{1,2}\s*回合")
# 体力不足弹窗「情报拼图补充」：三个页签从左到右是 调度室储存、情报拼图道具、坍塌晶条
stamina_popup_re = re.compile(r"情报拼图补充|情报.{0,3}补充|体力不足|体力补充")
# 弹窗说明里出现这些字样，说明当前页签会消耗抽卡资源，绝不能点确认
# 第三页签是坍塌晶条（抽卡资源），绝不能用；第二页签「消耗接入密钥兑换」是正常的体力道具，
# 所以禁用词里不能有「兑换」
forbidden_restore_re = re.compile(r"晶条|晶体|钻石|购买|充值|付费")
STAMINA_TAB_DY = 0.14  # 页签行相对弹窗标题中心的垂直偏移，单位：画面高度
STAMINA_TAB_DX = 0.161  # 相邻页签中心的水平间距，单位：画面高度
STAMINA_SAFE_TABS = (0, 1)  # 只允许点前两个页签（储存、道具），第三个是坍塌晶条
PRESET_BOX = (0.75, 0.06, 0.995, 0.86)  # 「使用整备室配置」下拉框及其展开的编队列表
PRESET_HEADER_Y = 0.12  # 下拉框标题在这条线以上，展开后的「整备室配置」选项在以下
MAX_CONTINUE_STREAK = 8  # 连续点「继续前进」却没进入战斗的次数上限


def box_center(box):
    return box.x + box.width / 2, box.y + box.height / 2


def stamina_tab_points(title_box, height):
    """由弹窗标题位置推算三个页签的中心点，顺序与游戏内一致：储存、道具、晶条。"""
    cx, cy = box_center(title_box)
    y = cy + STAMINA_TAB_DY * height
    return [(cx + (i - 1) * STAMINA_TAB_DX * height, y) for i in range(3)]


def has_forbidden_restore_text(names):
    """说明文字里提到晶条/购买等字样时返回 True。"""
    return any(forbidden_restore_re.search(n) for n in names)


def popup_texts(boxes, title_box, height):
    """只取弹窗范围内（标题下方约半屏高、左右各 0.42 画面高）的文字。"""
    cx, cy = box_center(title_box)
    out = []
    for b in boxes:
        bx, by = box_center(b)
        if cy < by < cy + 0.5 * height and abs(bx - cx) < 0.42 * height:
            out.append(b.name)
    return out


def tab_count(boxes, tab_x, tab_y, height):
    """读页签图标下方的数量数字；识别不到返回 None。"""
    for b in boxes:
        bx, by = box_center(b)
        if abs(bx - tab_x) < 0.06 * height and tab_y < by < tab_y + 0.1 * height and number_re.match(b.name):
            return int(b.name)
    return None


def parse_time_option(option: str) -> list[float]:
    """
    将配置中的时间字符串解析为浮点数列表
    例如 "1.087-1.4-0.5" -> [1.087, 1.4, 0.5]
    """
    return [float(x) for x in option.split("-")]


def parse_deploy_count(text):
    """「3/4」→ (3, 4)。斜杠常被 OCR 读成 1/l/I（如 '414'、'3l4'），单独一个三字符的也接受。"""
    m = re.search(r"(\d)\s*[/|\\]\s*(\d)", text) or re.fullmatch(r"(\d)[1lI](\d)", text.strip())
    if not m:
        return None
    n, total = int(m.group(1)), int(m.group(2))
    # 「4/4」偶尔被读成 412：总数比已上场还小肯定是读错了，当没读到
    return (n, total) if total >= n else None


class BaseGfTask(RuntimeMixin, BaseTask):
    """任务基类：RuntimeMixin 提供模板匹配入口重写，BaseTask 提供框架能力。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.roles_dict = {
            "物理": [
                "夏安",
                "莱妮",
                "威玛西娜",
                "巴希达",
                "幼熙",
                "绯",
                "波波沙",
                "乌尔丽德",
                "莉塔拉",
                "黛烟",
                "维普蕾",
                "闪电",
            ],
            "燃烧": [
                "罗蕾莱",
                "樱花",
                "刘易斯",
                "秋桦",
                "佩莉",
                "维克托",
                "桑朵莱希",
                "科谢尼娅",
                "琼玖",
                "奇塔",
                "夏克里",
                "克罗丽科",
            ],
            "电导": ["莱娅", "安朵丝", "比悠卡", "绛雨", "莱娜", "莫辛纳甘"],
            "冷凝": ["海伦", "埃芙", "洛贝拉", "杜莎妮", "索米", "洛塔", "玛绮朵"],
            "浊刻": ["芙洛伦", "妮基塔", "春田", "朝晖", "塞布丽娜", "托洛洛", "寇尔芙"],
            "酸蚀": ["翡图萨", "哈卜茜", "琳德", "米什缇", "可露凯", "纳甘", "佩里缇亚", "纳美西丝"],
        }
        self.box = ScreenPosition(self)
        self.default_config_group = {}

        # 多账户：是否允许按账号覆盖本任务的配置（「账号配置」页据此列出任务）。
        # 用 getattr 读类属性，这样子类可以直接在类体里声明而不会被 __init__ 覆盖掉。
        self.support_multi_account = bool(getattr(self, "support_multi_account", False))
        self.account_config_blacklist = set(getattr(self, "account_config_blacklist", ()))
        self.account_config_whitelist = set(getattr(self, "account_config_whitelist", ()))
        self.account_config_defaults = dict(getattr(self, "account_config_defaults", {}))

    def debug_shot(self, tag, boxes=None):
        """
        保存调试截图到 screenshots/<任务名>/<日期>/，仅在任务配置「调试截图」开启时生效。
        :param tag: 文件名标签，说明当前阶段
        :param boxes: 需要画框标注的 Box 列表，可选
        """
        if not self.config.get("调试截图", False):
            return None
        try:
            return save_debug_shot(self.frame, self.name, tag, boxes)
        except Exception as e:
            self.log_debug(f"调试截图失败: {e}")
            return None

    def isolate_by_hsv_ranges(self, frame, ranges, invert=True, kernel_size=2):
        """
        :param frame: 输入图像（BGR）
        :param ranges: HSV 区间列表
        :param invert: 是否反转结果
        :param kernel_size: 形态学核大小

        作用：按 HSV 范围提取颜色区域。
        """
        return isolate_by_hsv_ranges(frame, ranges, invert, kernel_size)

    def make_hsv_isolator(self, ranges, invert=True, kernel_size=2):
        """返回一个可直接调用的 HSV 过滤函数"""
        return lambda frame: isolate_by_hsv_ranges(
            frame,
            ranges,
            invert=invert,
            kernel_size=kernel_size,
        )

    def get_role_by_name(self, name):
        return next((k for k, v in self.roles_dict.items() if name in v), None)

    def ensure_main(self, recheck_time=1, time_out=30, esc=True):
        self.info_set("current_task", "go_to_main")
        if not self.wait_until(lambda: self.is_main(recheck_time=recheck_time, esc=esc), time_out=time_out):
            raise Exception("请从游戏主页进入")

    def skip_dialogs(self, end_match, end_box=None, time_out=120, has_dialog=True, raise_if_not_found=True):
        self.info_set("current_task", "skip_dialogs")
        start = time.time()
        attempts = 0
        next_debug_shot = 30
        while time.time() - start < time_out:
            if time.time() - start > next_debug_shot:
                # 长时间没匹配到结束条件，留一张图方便排查卡在什么页面
                self.debug_shot("skip_dialogs_waiting")
                next_debug_shot += 30
            try:
                boxes = self.ocr()
            except AttributeError:
                self.log_info("WGC 抓帧返回空帧，等待 3s 后重试", notify=False)
                self.sleep(3)
                self.next_frame()
                continue
            if skip := self.find_boxes(boxes, match=["跳过"]):
                self.click(skip, after_sleep=2)
            elif no_alert := self.find_boxes(boxes, match="今日不再提示"):
                self.click(no_alert)
                self.sleep(0.2)
                self.click(self.find_boxes(boxes, match="确认"), after_sleep=2)
            elif stamina_popup := self.find_boxes(boxes, match=stamina_popup_re):
                # 体力不足弹窗挡在「继续前进」前面时，OCR 仍能读到后面的按钮，必须先处理弹窗
                self._handle_stamina_popup(stamina_popup[0])
            elif result := self.find_boxes(boxes, match=end_match, boundary=end_box):
                # 优先返回"继续前进"
                for r in result:
                    if r.name == "继续前进":
                        self.sleep(1)
                        return [r]
                self.sleep(1)
                return result
            elif self.find_boxes(boxes, match=pop_ups):
                self.back()
                self.sleep(1)
            else:
                # 战斗中界面右上角是加速/跳过回合图标，不是剧情跳过，不能点
                if has_dialog and not self._is_loading_frame(boxes) and not self._is_battle_frame(boxes):
                    # 剧情跳过标签在 (0.95, 0.04)，教学弹窗的关闭 X 在 (0.967, 0.042)，交替点两处
                    if attempts % 2 == 0:
                        self.click_relative(0.95, 0.04)
                    else:
                        self.click_relative(0.967, 0.042)
                    attempts += 1
                self.sleep(2)
            self.next_frame()
        self.debug_shot("skip_dialogs_timeout")
        if raise_if_not_found:
            raise Exception("跳过剧情超时!")

    # ------------------------------------------------------------------ 好友助战
    def _ocr_panel(self, box, **kw):
        x, y, to_x, to_y = box
        return self.ocr(x, y, to_x, to_y, **kw)

    _avatar_book = AvatarBook()

    def _scan_cards(self):
        """
        识别右侧面板的卡片：战力数字定位卡片，蓝圈椎数用模板比对（OCR 认不出那么小的数字），
        立绘和 assets/card_avatars 里的模板比对直接认出是谁（认不出的 name 为 None，点一下后会自动学会）。
        """
        if self._fix_panel_state():
            self.next_frame()
        boxes = self._ocr_panel(PANEL_BOX, match=re.compile(r"^\d{3,6}$"))
        cards = find_cards(boxes, self.width, self.height, badge_of=lambda b: read_badge(self.frame, b, self.width, self.height))
        identify_cards(self.frame, cards, self.width, self.height, self._avatar_book)
        return cards

    @staticmethod
    def _name_like(a, b):
        """OCR 认名字偶尔错一个字（克莱妲/克兼妲），立绘模板按名字预筛时用模糊比较，宁可多点一下也别漏掉目标。"""
        if not a or not b:
            return False
        if a in b or b in a:
            return True
        return SequenceMatcher(None, a, b).ratio() >= 0.5

    def _learn_card(self, card, name):
        """点过卡片、OCR 到名字后，把它的立绘存成模板，下次扫描就不用再点。"""
        if self._avatar_book.learn(name, card.get("avatar")):
            self.log_info(f"记住了 {name} 的卡片立绘（assets/card_avatars/{name}.png）", notify=False)

    def _click_card(self, card):
        """点中一张卡片，返回左下角名字，并顺手学习立绘。"""
        x, y = card["center"]
        self.click_relative(x / self.width, y / self.height, after_sleep=0.8)
        self.next_frame()
        name = self._selected_role_name()
        self._learn_card(card, name)
        return name

    def _ensure_panel(self):
        """右侧卡片面板可能被点地图关掉了（页签消失），点「作战开始」左边的按钮把它打开。"""
        if self._ocr_panel(TAB_BOX, match=self.fix_match_regex(["我的人形", "好友助战"])):
            return True
        self.log_info("部署面板没打开，点左下按钮打开", notify=False)
        self.click_relative(0.37, 0.915, after_sleep=1)
        self.next_frame()
        ok = bool(self._ocr_panel(TAB_BOX, match=self.fix_match_regex(["我的人形", "好友助战"])))
        self.debug_shot("panel_open" if ok else "panel_open_fail")
        return ok

    def _fix_panel_state(self):
        """
        「我的人形」页签顶上有个「使用整备室配置」下拉框。误点它会展开「编队1…编队7」列表，
        选中某个编队后面板只显示该编队的人形（空编队就是「暂无可选人形」，还会把场上阵容清掉）。
        这里检查：面板里出现「编队n」就把它恢复成默认的「整备室配置」。返回是否做了修正。
        """
        boxes = self._ocr_panel(PRESET_BOX, match=[re.compile(r"编队\s*\d"), re.compile(r"整备室配置")])
        presets = [b for b in boxes if re.search(r"编队\s*\d", b.name)]
        if not presets:
            return False
        self.debug_shot("preset_fix", boxes)
        for _ in range(2):
            entries = [b for b in boxes if "整备室配置" in b.name and b.y > self.height * PRESET_HEADER_Y]
            if entries:
                self.log_info(f"面板上出现编队列表 {[b.name for b in presets]}，选回「整备室配置」", notify=True)
                self.click(entries[0], after_sleep=1)
                self.next_frame()
                return True
            # 列表没展开（标题就是「编队n」）：点标题展开下拉框
            self.log_info(f"面板当前选中了 {presets[0].name}，展开下拉框选回整备室配置", notify=True)
            self.click(presets[0], after_sleep=1)
            self.next_frame()
            boxes = self._ocr_panel(PRESET_BOX, match=[re.compile(r"编队\s*\d"), re.compile(r"整备室配置")])
        self.log_info("没能把编队下拉框恢复成整备室配置", notify=True)
        return True

    def _lineup_full(self):
        """阵容是否已满：优先看顶部计数；读不到就看地图上还有没有空地格。"""
        count = self._deploy_count()
        if count is not None:
            return count[0] >= count[1]
        _, empty = self._occupied_and_empty()
        return not empty

    _own_deployed = ()

    def _withdraw_old_support(self, role):
        """
        场上同时只能有一个助战：上一关借的助战还在场上时，必须先撤回才能借别的。
        逐个点地图上有人的地格，名字不在我方已上场名单里的就是助战：
        是目标角色就保留（返回 "keep"），不是就点「撤回人形」（返回 "withdrawn"）；场上没有助战返回 None。
        """
        own_names = [c["name"] for c in self._own_deployed if c.get("name")]
        for tile, desc in self._unit_tiles():
            self.click_relative(tile[0] / self.width, tile[1] / self.height, after_sleep=0.8)
            self.next_frame()
            name = self._selected_role_name()
            kind, button = self._deploy_button()
            if kind != "withdraw" or not name or any(self._name_like(n, name) for n in own_names):
                self._clear_selection()
                continue
            if role in name:
                self.log_info(f"场上已有助战 {name}，保留不换", notify=True)
                self._clear_selection()
                return "keep"
            self.log_info(f"场上已有上一关借的助战 {name}，先撤回再换", notify=True)
            self.click(button, after_sleep=1)
            self.next_frame()
            self.debug_shot("old_support_withdrawn")
            return "withdrawn"
        return None

    def _make_room(self):
        """
        阵容满时给助战腾一个位置：逐个点地图上有人的地格（点中后右下角是「撤回人形」、左下角是名字），
        优先撤回不在我方已上场名单里的那个（上一关借的助战），否则撤回我方战力最低的。返回是否腾出了位置。
        """
        if not self._lineup_full():
            return True
        own = {c["name"]: c["power"] for c in self._own_deployed if c.get("name")}
        found = []
        for tile, desc in self._unit_tiles():
            self.click_relative(tile[0] / self.width, tile[1] / self.height, after_sleep=0.8)
            self.next_frame()
            name = self._selected_role_name()
            kind, _ = self._deploy_button()
            if kind == "withdraw" and name:
                found.append((tile, name))
            self._clear_selection()
        if not found:
            self.debug_shot("make_room_fail")
            self.log_info("阵容已满，但在地图上没点中任何可撤回的单位，助战只能试着顶替", notify=True)
            return False

        def order(item):
            powers = [p for n, p in own.items() if self._name_like(n, item[1])]
            return (1, min(powers)) if powers else (0, 0)

        found.sort(key=order)
        tile, name = found[0]
        self.click_relative(tile[0] / self.width, tile[1] / self.height, after_sleep=0.8)
        self.next_frame()
        kind, button = self._deploy_button()
        if kind != "withdraw":
            self._clear_selection()
            self.log_info(f"阵容已满，重新点中 {name} 失败，助战只能试着顶替", notify=True)
            return False
        why = "上一关借的助战" if order((tile, name))[0] == 0 else "我方战力最低"
        self.log_info(f"阵容已满，撤回{why}的 {name} 给助战腾位", notify=True)
        self.click(button, after_sleep=1)
        self.next_frame()
        self.debug_shot("room_made")
        return True

    def _deploy_count(self):
        """顶部「部署人形 3/4」，返回 (3, 4)；读不到就换一帧再试一次，还读不到返回 None。"""
        for attempt in range(2):
            boxes = self._ocr_panel(COUNT_BOX)
            self.log_info(f"顶部计数区文字: {[b.name for b in boxes]}", notify=False)
            for b in boxes:
                if m := parse_deploy_count(b.name):
                    return m
            self.sleep(0.3)
            self.next_frame()
        return None

    def _click_tab(self, name):
        tab = self._ocr_panel(TAB_BOX, match=self.fix_match_regex([name]))
        if not tab:
            raise Exception(f"部署界面没找到「{name}」页签")
        self.click(tab[0], after_sleep=1)
        self.next_frame()
        return tab[0]

    def _selected_role_name(self):
        """左下角当前选中人形的名字，去掉等级后缀，如 '莱娅Lv.60格' -> '莱娅'。"""
        boxes = self._ocr_panel(NAME_BOX)
        raw = "".join(b.name for b in boxes)
        name = re.split(r"L[vV]", raw)[0].strip()
        self.log_info(f"左下角人形名: {raw!r} -> {name!r}", notify=False)
        return name

    def _unit_tiles(self):
        """地图上已上场单位所在的格子：编号标签下方的格子优先，再用填充率低（被立绘挡住）的地格兜底。"""
        occupied, _ = self._occupied_and_empty()
        out = [(c, f"标签下的地格({int(c[0])},{int(c[1])})") for c in occupied]
        for t in reversed(find_deploy_tiles(self.frame, self.width, self.height)):
            if all((t["center"][0] - x) ** 2 + (t["center"][1] - y) ** 2 >= 45**2 for (x, y), _ in out):
                out.append((t["center"], f"地格({int(t['center'][0])},{int(t['center'][1])}, 填充 {t['fill']})"))
        return out[:6]

    def _select_unit_on_map(self, want):
        """点地图上的单位格子，直到左下角名字是 want。点中单位后右侧面板会切回「我的人形」。"""
        for tile, desc in self._unit_tiles():
            self.click_relative(tile[0] / self.width, tile[1] / self.height, after_sleep=0.8)
            self.next_frame()
            if want in self._selected_role_name() and self._deploy_button()[0] == "withdraw":
                self.log_info(f"在地图上选中了 {want}（{desc}）", notify=False)
                return True
            self._clear_selection()
        return False

    def _deploy_button(self):
        """右下角按钮：("deploy", box) 部署人形 / ("withdraw", box) 撤回人形 / ("hint", box) 请点击地格 /
        ("swap", box) 编入队伍（顶替地图上选中的单位）/ ("blocked", box) 无法部署 / (None, None)。"""
        boxes = self._ocr_panel(BUTTON_BOX)
        self.log_info(f"右下角按钮: {[b.name for b in boxes]}", notify=False)
        for b in boxes:
            if re.fullmatch(r"\s*部署人形\s*", b.name):
                return "deploy", b
            if re.fullmatch(r"\s*编入队伍\s*", b.name):
                # 地图上还选中着一个单位时点卡片，按钮变成「编入队伍」= 用这张卡顶替选中的单位
                # （实录：刚部署完的助战还处于选中状态，补人时把助战顶掉了），要先取消选中
                return "swap", b
            if re.fullmatch(r"\s*撤回人形\s*", b.name):
                return "withdraw", b
        for b in boxes:
            if "地格" in b.name or "拖拽" in b.name:
                return "hint", b
            if "无法" in b.name:
                # 「无法在该点位部署」「该人形无法撤回」：地图上还挂着上一次点的格子/单位，要先取消选中
                return "blocked", b
        return None, None

    def _clear_selection(self):
        """点一下地图上离地格很远的空地，取消地图上挂着的格子/单位选中（否则后面点卡片会变成「无法在该点位部署」）。"""
        tiles = find_deploy_tiles(self.frame, self.width, self.height)
        x, y = far_point(tiles, self.width, self.height)
        self.click_relative(x, y, after_sleep=0.8)
        self.next_frame()
        kind, _ = self._deploy_button()
        self.log_info(f"取消地图选中（点 {x:.2f},{y:.2f}），按钮状态 {kind}", notify=False)
        return kind not in ("withdraw", "blocked")

    def _occupied_and_empty(self):
        """(有人的地格列表, 空地格列表)：有人的按编号标签定位，空的用菱形模板找并排除标签附近的。"""
        tags = find_unit_tags(self.frame, self.width, self.height)
        occupied = unit_tiles_from_tags(tags, self.height)
        tiles = find_deploy_tiles(self.frame, self.width, self.height)
        near = lambda t: any((t["center"][0] - x) ** 2 + (t["center"][1] - y) ** 2 < 45**2 for x, y in occupied)
        empty = [t for t in tiles if not near(t)]
        self.log_info(f"单位标签 {[(x, y, sc) for x, y, sc in tags]}，空地格 {[(t['center'], t['fill']) for t in empty]}", notify=False)
        return occupied, empty

    def _candidate_tiles(self):
        """
        选中卡片后可以试着点的地格：阵容没满就点空地格（填充率高的在前）；满了（顶替）就点有人的格子。
        """
        count = self._deploy_count()
        occupied, empty = self._occupied_and_empty()
        self.debug_shot("tiles")
        full = count is not None and count[0] >= count[1]
        if full:
            out = [(c, f"有人的地格({int(c[0])},{int(c[1])})") for c in occupied]
        else:
            out = [(t["center"], f"空地格({int(t['center'][0])},{int(t['center'][1])}, 填充 {t['fill']})") for t in empty]
        self.log_info(f"阵容 {count}，候选地格 {len(out)} 个", notify=False)
        return out[:4]

    def _placed(self, card_name, before):
        """核对是否上场：按钮是「撤回人形」且左下角名字就是这张卡，或者计数涨了。"""
        kind, _ = self._deploy_button()
        if kind == "withdraw" and card_name and card_name in self._selected_role_name():
            return True
        after = self._deploy_count()
        return before is not None and after is not None and after[0] > before[0]

    def _place_selected(self, label, card_name, before=None, reselect=None):
        """
        当前已选中一张卡片（我的人形或好友助战），把它放到场上：
        - 按钮已是「撤回人形」且左下角名字就是它：已在场上；
        - 「请点击地格」：逐个试点地格。点到空格会出现「部署人形」再点一下；
          阵容满时点有人的格子会直接顶替（按钮变「撤回人形」且名字变成它）；
          点到别的单位只是选中了那个单位，面板会切回「我的人形」，所以试下一个格子前要用 reselect 重新选卡。
        :param card_name: 这张卡的名字，用来核对是否真的上场
        :param before: 部署前的 (n, m) 计数
        :param reselect: 重新选中这张卡片的函数（含切回对应页签）
        """
        kind, button = self._deploy_button()
        if kind == "withdraw" and card_name in self._selected_role_name():
            self.log_info(f"{label} 已在场上", notify=True)
            return True
        if kind in ("withdraw", "blocked", "swap") and reselect:
            # 地图上还挂着别的格子/单位，先取消再重选这张卡
            self._clear_selection()
            reselect()
            self.next_frame()
            kind, button = self._deploy_button()
        if kind == "swap":
            self.log_info(f"{label} 按钮是「编入队伍」（会顶替地图上选中的单位），不点，跳过", notify=False)
            self._clear_selection()
            return False
        if kind == "hint":
            candidates = self._candidate_tiles()
            if not candidates:
                self.log_info(f"{label} 需要先点地格，但没找到可点的地格", notify=False)
                return False
            for i, (tile, desc) in enumerate(candidates):
                if i > 0:
                    self._clear_selection()
                    if reselect:
                        reselect()
                        self.next_frame()
                self.log_info(f"{label} 试点{desc}", notify=False)
                self.click_relative(tile[0] / self.width, tile[1] / self.height, after_sleep=1)
                self.next_frame()
                kind, button = self._deploy_button()
                if kind == "deploy":
                    break
                if kind == "withdraw" and card_name in self._selected_role_name():
                    self.log_info(f"已顶替上场 {label}，阵容 {self._deploy_count()}", notify=True)
                    return True
            else:
                # 所有地格都试完了还没出现「部署人形」，把挂着的选中清掉再返回
                self._clear_selection()
        if kind != "deploy":
            self.log_info(f"{label} 没出现部署按钮，跳过", notify=False)
            return False
        for attempt in range(2):
            # 偶尔第一下「部署人形」点了没反应（按钮还是部署人形），等一下再点一次
            self.click(button, after_sleep=1.5)
            self.next_frame()
            if confirm := self.ocr(match=self.fix_match_regex(["确认"]), box=self.box.bottom):
                self.click(confirm, after_sleep=1.5)
                self.next_frame()
            kind, button = self._deploy_button()
            if kind != "deploy":
                break
            self.log_info(f"{label} 点了部署人形没反应，再点一次", notify=False)
        if self._placed(card_name, before):
            self.log_info(f"已部署 {label}，阵容 {self._deploy_count()}", notify=True)
            return True
        self.log_info(f"{label} 点了部署但没确认上场", notify=False)
        return False

    def borrow_support(self):
        """
        在部署界面借好友助战：目标角色由「助战角色」「助战最低椎数」决定。
        1. 我的人形里若已上场同名角色，先选中并「撤回人形」；
        2. 好友助战按属性筛选，按战力从高到低找椎数达标的卡片，点中后核对左下角名字，再「部署人形」；
        3. 没有达标的就不借，直接返回 False。
        """
        role = self.config.get("助战角色", "威玛西娜").strip()
        min_badge = int(self.config.get("助战最低椎数", 6))
        self.info_set("current_task", "borrow_support")
        self._borrowed_support = None
        self.next_frame()
        if not self.ocr(match="作战开始", box=self.box.bottom):
            self.log_info("不在部署界面，跳过借助战", notify=False)
            return False
        if not self._ensure_panel():
            self.log_info("打不开部署面板，跳过借助战", notify=True)
            return False
        try:
            self._withdraw_own(role)
            if self._withdraw_old_support(role) == "keep":
                return True
            return self._pick_friend_support(role, min_badge)
        finally:
            self.next_frame()
            self.debug_shot("support_done")

    def _withdraw_own(self, role):
        self._click_tab("我的人形")
        self.sleep(0.5)
        self.next_frame()
        cards = self._scan_cards()
        deployed = [c for c in cards if is_orange_check(self.frame, *check_point(c, self.width, self.height))]
        self.debug_shot("support_my_tab", [c["power_box"] for c in deployed])
        for c in deployed:
            if c["name"] is None:
                # 立绘没认出来的，点一下读名字（顺便学会），保证我方已上场名单完整，后面才能分辨谁是助战
                c["name"] = self._click_card(c) or None
        self.log_info(f"我的人形已上场 {len(deployed)} 张卡片 {[(c['name'], c['power']) for c in deployed]}", notify=False)
        self._own_deployed = tuple(deployed)
        if not any(c["name"] is None or self._name_like(c["name"], role) for c in deployed):
            return False
        for c in deployed:
            if c["name"] and not self._name_like(c["name"], role):
                continue
            name = self._click_card(c)
            if role not in name:
                continue
            kind, button = self._deploy_button()
            if kind != "withdraw":
                # 点卡片只是选中卡片，撤回要先在地图上点中这个单位
                if not self._select_unit_on_map(role):
                    self.log_info(f"我方已上场 {role}，但在地图上没点中它，无法撤回", notify=True)
                    return False
                kind, button = self._deploy_button()
            if kind == "withdraw":
                self.log_info(f"我方已上场 {role}，先撤回再借助战", notify=True)
                self.click(button, after_sleep=1)
                self.next_frame()
                self.debug_shot("support_withdrawn")
                return True
            return False
        return False

    def _pick_friend_support(self, role, min_badge):
        tab = self._click_tab("好友助战")
        attr = self.get_role_by_name(role)
        fx, fy = filter_point(tab, attr, self.width, self.height)
        self.click_relative(fx / self.width, fy / self.height, after_sleep=1)
        self.next_frame()
        cards = self._scan_cards()
        self.debug_shot("support_scan", [c["power_box"] for c in cards])
        if not cards and self.ocr(match=self.fix_match_regex(["暂无可选择人形"])):
            self.log_info("好友助战列表为空（暂无可选择人形），通常是我方已上场同名角色没撤回", notify=True)
        candidates = pick_candidates(cards, min_badge)
        # 立绘认出来是别人的直接跳过；认出来就是目标的优先，认不出的再点一下确认
        candidates = [c for c in candidates if c["name"] is None or self._name_like(c["name"], role)]
        candidates.sort(key=lambda c: (c["name"] != role, c["name"] is None, -c["power"]))
        self.log_info(
            f"好友助战({attr or '全部'}) 识别 {len(cards)} 张 {[(c['name'], c['badge'], c['power']) for c in cards]}，"
            f"椎数>={min_badge} 且可能是 {role} 的 {len(candidates)} 张",
            notify=False,
        )
        room_checked = False
        for c in candidates:
            x, y = c["center"]
            name = self._click_card(c)
            if role not in name:
                self.log_info(f"{c['badge']}椎 战力{c['power']} 是 {name}，不是 {role}，跳过", notify=False)
                continue
            if not room_checked:
                room_checked = True
                self._make_room()
                self._reselect_card("好友助战", x, y)()
                self.next_frame()
            if self._deploy_selected_support(
                f"{c['badge']}椎 {role}（战力 {c['power']}）", role, self._reselect_card("好友助战", x, y)
            ):
                return True
        self.log_info(f"没有 {min_badge} 椎及以上的 {role} 助战", notify=True)
        if self.config.get("找不到就借战力最高", False):
            return self._pick_strongest_support(tab)
        self.log_info("不借，直接开战", notify=True)
        return False

    _borrowed_support = None

    def _deploy_selected_support(self, label, card_name, reselect):
        ok = self._place_selected(f"助战 {label}", card_name, reselect=reselect)
        if ok:
            self._borrowed_support = card_name
        return ok

    def _reselect_card(self, tab, x, y):
        """切回页签再点卡片（点过地图单位后面板会跳回「我的人形」）。"""

        def _do():
            self._click_tab(tab)
            self.click_relative(x / self.width, y / self.height, after_sleep=0.8)

        return _do

    def _pick_strongest_support(self, tab):
        """兜底：切到「全部」筛选，按战力从高到低借第一个能部署的助战。"""
        # 前面试点地格可能点中了己方单位，面板会跳回「我的人形」——那一页同样位置是「使用整备室配置」，
        # 点下去会展开编队列表甚至清空阵容，所以先确保在好友助战页签
        tab = self._click_tab("好友助战")
        fx, fy = filter_point(tab, "全部", self.width, self.height)
        self.click_relative(fx / self.width, fy / self.height, after_sleep=1)
        self.next_frame()
        cards = self._scan_cards()
        self.debug_shot("support_scan_all", [c["power_box"] for c in cards])
        self.log_info(f"兜底借战力最高：全部列表 {[(c['name'], c['badge'], c['power']) for c in cards]}", notify=False)
        deployed = [c for c in cards if is_orange_check(self.frame, *check_point(c, self.width, self.height))]
        if deployed:
            # 列表里有打了勾的卡片 = 上一关借的助战还在场上，不用再借
            self.log_info(f"已有助战在场上 {[(c['name'], c['power']) for c in deployed]}，不再换", notify=True)
            return True
        room_checked = False
        for c in cards[:3]:
            x, y = c["center"]
            name = self._click_card(c)
            if not name:
                self.log_info(f"战力 {c['power']} 的卡片点了没读到名字，跳过", notify=False)
                continue
            if not room_checked:
                room_checked = True
                self._make_room()
                self._reselect_card("好友助战", x, y)()
                self.next_frame()
            if self._deploy_selected_support(
                f"战力最高 {name}（{c['badge']}椎 战力 {c['power']}）", name, self._reselect_card("好友助战", x, y)
            ):
                return True
        self.log_info("兜底也没借到助战，直接开战", notify=True)
        return False

    def fill_lineup(self, max_rounds=4):
        """
        把阵容补满：顶部「部署人形 n/m」不满时，到我的人形里按战力从高到低挑没上场的卡片，
        选中卡片 → 点一个空地格 → 点「部署人形」，直到 n == m 或没有可用的卡片/地格。
        """
        self.info_set("current_task", "fill_lineup")
        self.next_frame()
        count = self._deploy_count()
        if count is None:
            self.log_info("没读到部署人形计数，跳过补满阵容", notify=False)
            return False
        if count[0] >= count[1]:
            return True
        self.log_info(f"阵容 {count[0]}/{count[1]}，开始补满", notify=True)
        if not self._ensure_panel():
            self.log_info("打不开部署面板，跳过补满阵容", notify=True)
            return False
        tab = self._click_tab("我的人形")
        # 属性筛选和好友助战页签是共用的，借完助战后这里可能还停在某个属性上，先点「全部」
        fx, fy = filter_point(tab, "全部", self.width, self.height, my_tab=True)
        self.click_relative(fx / self.width, fy / self.height, after_sleep=0.8)
        self.sleep(0.5)
        tried = set()
        for _ in range(max_rounds):
            self.next_frame()
            cards = self._scan_cards()
            spare = [
                c
                for c in cards
                if c["power"] not in tried and not is_orange_check(self.frame, *check_point(c, self.width, self.height))
            ]
            if self._borrowed_support:
                # 和场上助战同名的自己人形不能再上（点它按钮会变成撤回助战）
                spare = [c for c in spare if not (c["name"] and self._name_like(c["name"], self._borrowed_support))]
            if not spare:
                self.log_info("我的人形里没有可补的卡片了", notify=False)
                break
            card = spare[0]
            tried.add(card["power"])
            x, y = card["center"]
            name = self._click_card(card)
            placed = self._place_selected(
                f"我的人形 {name}（战力 {card['power']}）", name, before=count, reselect=self._reselect_card("我的人形", x, y)
            )
            if placed:
                count = self._deploy_count() or (count[0] + 1, count[1])
            else:
                self.log_info(f"战力 {card['power']} 没能部署，换下一张", notify=False)
            if count[0] >= count[1]:
                break
        self.debug_shot("lineup_done")
        return count[0] >= count[1]

    def _handle_stamina_popup(self, title):
        """
        体力不足弹窗：开了「自动使用体力药」就只用调度室储存/情报拼图道具恢复，
        没开、或两种都用不了，就取消弹窗并抛异常停止任务，绝不消耗坍塌晶条。
        """
        self.debug_shot("stamina_popup", [title])
        if not self.config.get("自动使用体力药", False):
            self._cancel_stamina_popup()
            raise Exception("体力不足，已停止；要自动用体力药请打开「自动使用体力药」选项")
        if self.restore_stamina(title):
            return
        raise Exception("体力不足，调度室储存和情报拼图道具都用不了，已停止（不会使用坍塌晶条）")

    def _cancel_stamina_popup(self):
        self.next_frame()
        if cancel := self.ocr(match=self.fix_match_regex(["取消"])):
            self.click(cancel, after_sleep=1)
        else:
            self.back()
            self.sleep(1)

    def restore_stamina(self, title):
        """
        在「情报拼图补充」弹窗上依次试前两个页签（调度室储存、情报拼图道具），每次只用 1 份。
        :return: True 弹窗已消失（恢复成功）；False 两个页签都没用上，弹窗已取消
        """
        points = stamina_tab_points(title, self.height)
        for idx in STAMINA_SAFE_TABS:
            x, y = points[idx]
            self.click_relative(x / self.width, y / self.height, after_sleep=1)
            self.next_frame()
            boxes = self.ocr()
            if not self.find_boxes(boxes, match=stamina_popup_re):
                self.log_info("体力弹窗已消失", notify=False)
                return True
            texts = popup_texts(boxes, title, self.height)
            self.debug_shot(f"stamina_tab{idx + 1}", boxes)
            if has_forbidden_restore_text(texts):
                self.log_info(f"体力弹窗页签{idx + 1} 会消耗抽卡资源，跳过: {texts}", notify=False)
                continue
            count = tab_count(boxes, x, y, self.height)
            if count == 0:
                self.log_info(f"体力弹窗页签{idx + 1} 数量为 0，跳过", notify=False)
                continue
            confirm = [c for c in self.find_boxes(boxes, match=self.fix_match_regex(["确认"])) if c.y > y]
            if not confirm:
                self.log_info(f"体力弹窗页签{idx + 1} 没找到确认按钮，跳过", notify=False)
                continue
            self.click(confirm[0], after_sleep=2)
            # 确认后弹窗要过一会儿才关（实录：接入密钥已经扣了，2 秒后标题还在，误判成失败又点了取消）
            for _ in range(4):
                self.next_frame()
                boxes = self.ocr()
                if not self.find_boxes(boxes, match=stamina_popup_re):
                    self.log_info(f"已用体力弹窗页签{idx + 1} 恢复体力（数量 {count}）", notify=True)
                    self.debug_shot("stamina_restored", boxes)
                    return True
                self.sleep(1)
            self.log_info(f"体力弹窗页签{idx + 1} 确认后弹窗仍在，换下一个页签", notify=False)
            self.debug_shot(f"stamina_tab{idx + 1}_after_confirm", boxes)
        self._cancel_stamina_popup()
        return False

    def _click_continue(self, box):
        """点「继续前进」，连续点太多次都没进入战斗就停，避免体力不足时无限循环。"""
        self._continue_streak = getattr(self, "_continue_streak", 0) + 1
        if self._continue_streak > MAX_CONTINUE_STREAK:
            self.debug_shot("continue_no_progress", box)
            raise Exception(f"连续点击继续前进 {MAX_CONTINUE_STREAK} 次都没进入战斗，已停止")
        self.click_box(box, after_sleep=2)

    def _is_battle_frame(self, boxes):
        """
        判断当前帧是否为战斗中界面（存在「行动结束」或回合计数）。
        :param boxes: OCR 识别结果
        :return: True 如果处于战斗中，否则 False
        """
        return bool(self.find_boxes(boxes, match=battle_ui_re))

    def _is_loading_frame(self, boxes):
        """
        判断当前帧是否为加载界面。
        :param boxes: OCR 识别结果
        :return: True 如果是加载界面，否则 False
        """
        if not boxes:
            return True
        names = [box.name for box in boxes if box.name]
        if any("资源加载中" in name for name in names):
            return True
        # 只有一个进度百分比、几乎没有别的文字时才算加载页；
        # 教学弹窗里的「60% 25% 60% 20%」这类伤害数值不能当成加载页，否则会一直不点关闭
        has_progress = any(re.fullmatch(r"\s*\d{1,3}%\s*", name) for name in names)
        return has_progress and len(names) <= 3

    def auto_battle(
        self, end_match=None, end_box=None, has_dialog=False, need_click_auto=False, has_dialog_behind_start=False
    ):
        self.info_set("current_task", "auto battle")
        result = self.skip_dialogs(
            end_match=["作战开始", "行动结束", "继续前进"],
            end_box=self.box.bottom,
            time_out=120,
            has_dialog=has_dialog,
            raise_if_not_found=False,
        )
        self.debug_shot("battle_entry", result)
        if result and result[0].name != "继续前进":
            self._continue_streak = 0
        if result and result[0].name == "继续前进":
            self.log_info("开局检测到继续前进，点击后开启新一轮自动战斗", notify=True)
            self._click_continue(result)
            self.auto_battle(
                end_match=end_match,
                end_box=end_box,
                has_dialog=has_dialog,
                need_click_auto=need_click_auto,
                has_dialog_behind_start=has_dialog_behind_start,
            )
            return
        if result[0].name == "作战开始":
            self.sleep(2)
            if self.config.get("借好友助战", False):
                self.borrow_support()
            if self.config.get("自动补满阵容", False):
                self.fill_lineup()
            if self.config.get("借好友助战", False) or self.config.get("自动补满阵容", False):
                if self._deploy_button()[0] in ("withdraw", "blocked"):
                    self._clear_selection()
                result = self.wait_ocr(match="作战开始", box=self.box.bottom, time_out=10, raise_if_not_found=True)
            self.click_box(result, after_sleep=1)
            for _ in range(2):
                # 地图上挂着选中时点「作战开始」只会把面板弹出来，战斗不会开始；清掉选中再点一次
                self.sleep(2)
                self.next_frame()
                still = self.ocr(match="作战开始", box=self.box.bottom)
                if not still:
                    break
                self.log_info("点了作战开始但还在部署界面，清掉选中后再点", notify=True)
                self.debug_shot("battle_start_retry")
                self._clear_selection()
                self.click_box(still, after_sleep=1)
            start_result = self.skip_dialogs(
                end_match=[
                    re.compile("行动完成"),
                    re.compile("行动结束"),
                    re.compile("还有可部署"),
                    re.compile("任务完成"),
                    re.compile("继续前进"),
                ],
                has_dialog=True,
                time_out=45,
                raise_if_not_found=False,
            )
            self.debug_shot("after_battle_start", start_result)
            if start_result and "继续前进" in start_result[0].name:
                self.log_info("开局后检测到继续前进，点击后开启新一轮自动战斗", notify=True)
                self._click_continue(start_result)
                self.auto_battle(
                    end_match=end_match,
                    end_box=end_box,
                    has_dialog=has_dialog,
                    need_click_auto=need_click_auto,
                    has_dialog_behind_start=has_dialog_behind_start,
                )
                return
            ok_bool = bool(start_result) and (
                not ("还有可部署" in start_result[0].name or "行动结束" in start_result[0].name)
            )
            if not ok_bool:
                if start_result and ("还有可部署" in start_result[0].name):
                    self.log_info("阵容没上满!", notify=True)

                    self.wait_click_ocr(match=["确认"], box=self.box.bottom, time_out=5, raise_if_not_found=True)
                    self.wait_ocr(match=["行动结束"], box=self.box.bottom_right, raise_if_not_found=False, time_out=15)
                    # start_result = self.wait_ocr(match=['行动结束'], box=self.box.bottom_right,
                    #                              raise_if_not_found=False, time_out=15)
                if not start_result and has_dialog_behind_start:
                    start_result = self.skip_dialogs(
                        end_match=["作战开始", "行动结束", "继续前进"],
                        end_box=self.box.bottom,
                        time_out=120,
                        has_dialog=has_dialog,
                        raise_if_not_found=False,
                    )
                    if start_result and start_result[0].name == "继续前进":
                        self.log_info("开局二次检测到继续前进，点击后开启新一轮自动战斗", notify=True)
                        self._click_continue(start_result)
                        self.auto_battle(
                            end_match=end_match,
                            end_box=end_box,
                            has_dialog=has_dialog,
                            need_click_auto=need_click_auto,
                            has_dialog_behind_start=has_dialog_behind_start,
                        )
                        return
                    if self.wait_ocr(match="注意", box=self.box.top):
                        self.wait_click_ocr(match="取消", after_sleep=2)
                if start_result and need_click_auto:
                    self.sleep(0.5)
                    # 最多尝试 5 次，避免自动按钮被反复切换
                    for _ in range(5):
                        if not self.ocr(match="行动结束", box=self.box.bottom_right):
                            break
                        self.log_info("检测到行动结束，点击右上角自动战斗按钮", notify=False)
                        if self.is_adb():
                            self.click_relative(0.85, 0.05, after_sleep=1)
                        else:
                            self.click_relative(0.88, 0.04, after_sleep=1)
                        self.debug_shot("after_click_auto")

        clicked_continue = False
        while results := self.skip_dialogs(
            end_match=["任务完成", "任务失败", "战斗失败", "对战胜利", "对战失败", "确认", "确认结算", "继续前进"],
            time_out=900,
            has_dialog=has_dialog,
        ):
            # 优先遍历所有结果找"继续前进"
            clicked = False
            if any(r.name != "继续前进" for r in results):
                self._continue_streak = 0
            for result in results:
                if result.name == "继续前进":
                    self._click_continue(result)
                    clicked = True
                    clicked_continue = True
                    break
            if not clicked:
                for result in results:
                    if result.name in ("确认", "确认结算"):
                        self.click_box(result, after_sleep=2)
                        clicked = True
                        break
            self.sleep(2)
            self.click_box(results, after_sleep=2)
            if results[0].name not in pop_ups:
                break
        self.debug_shot("battle_result", results)
        if not results:
            raise Exception("自动战斗异常")
        if results[0].name == "任务失败":
            raise Exception("任务失败, 没打过!")
        if clicked_continue:
            self.log_info("检测到继续前进，点击后开启新一轮自动战斗", notify=True)
            self.auto_battle(
                end_match=end_match,
                end_box=end_box,
                has_dialog=has_dialog,
                need_click_auto=need_click_auto,
                has_dialog_behind_start=has_dialog_behind_start,
            )
            return
        if cont := self.wait_ocr(match="继续前进", box=self.box.bottom_right, raise_if_not_found=False, time_out=3):
            self.log_info("结算后检测到继续前进，点击后开启新一轮自动战斗", notify=True)
            self._click_continue(cont)
            self.auto_battle(
                end_match=end_match,
                end_box=end_box,
                has_dialog=has_dialog,
                need_click_auto=need_click_auto,
                has_dialog_behind_start=has_dialog_behind_start,
            )
            return
        while self.wait_click_ocr(match="确认", box=self.box.bottom_right, raise_if_not_found=False, time_out=3):
            pass
        if end_match:
            if isinstance(end_match, list):
                end_match = end_match + pop_ups
            else:
                end_match = [end_match] + pop_ups
            end_match.append("确认")
            end_match.append("确认结算")
            end_match.append("继续前进")
            while True:
                match = self.skip_dialogs(
                    end_match=end_match, end_box=end_box, time_out=30, has_dialog=has_dialog, raise_if_not_found=True
                )
                if match[0].name in pop_ups:
                    self.back(after_sleep=2)
                    continue
                if match[0].name == "继续前进":
                    self.log_info("最后阶段检测到继续前进，点击后开启新一轮自动战斗", notify=True)
                    self.click_box(match, after_sleep=2)
                    self.auto_battle(
                        end_match=end_match,
                        end_box=end_box,
                        has_dialog=has_dialog,
                        need_click_auto=need_click_auto,
                        has_dialog_behind_start=has_dialog_behind_start,
                    )
                    return
                if match[0].name in ("确认", "确认结算"):
                    self.click_box(match, after_sleep=8)
                break
        self.sleep(2)

    def is_main(self, recheck_time=0.0, esc=True):
        boxes = self.ocr(match=["整备室", "公共区", "活动层", re.compile("招募")], box="right", log=True)
        feature_boxes = []
        for feature in [fL.dog_icon, fL.message_icon]:
            if result := self.find_one(feature, vertical_variance=0.002, horizontal_variance=0.002):
                feature_boxes.append(result)
        total = len(boxes) + len(feature_boxes)
        self.log_info(f"is main ocr={len(boxes)} features={len(feature_boxes)} total={total}")
        if total >= 2:
            return True
        # if not self.do_handle_alert()[0]:
        if self.ocr(match=re.compile("^是否离开活动层"), box=self.box.center, log=True):
            self.wait_click_ocr(match="确认", after_sleep=2, box=self.box.bottom_right)
            return False
        if box := self.ocr(box=self.box.bottom, match=["点击开始", "点击空白处关闭", "取消"], log=True):
            self.click(box, after_sleep=2)
            return False
        if esc:
            if result := self.find_feature(
                feature=[fL.back_home, fL.back_home_light], horizontal_variance=0.02, vertical_variance=0.002
            ):
                self.click(result, after_sleep=2)
                return False
            self.back(after_sleep=2)
        self.next_frame()
        return False

    def click(
        self,
        x: float | Box | list[Box] = 0.0,
        y: float | int = 0.0,
        move_back=False,
        name=None,
        interval=-1,
        move=True,
        down_time=0.01,
        after_sleep=0,
        key="left",
        alt=False,
    ):
        """
        点击。

        ``alt=True`` 时按住 alt 再点击（等价于 ``click_with_alt``），用于只有 alt 组合键才能命中的界面。
        x 支持 Box、Box 列表、屏幕比例（0~1）与绝对坐标，分派逻辑沿用父类。
        """
        if alt:
            return self.click_with_alt(
                x,
                y,
                move_back=move_back,
                name=name,
                interval=interval,
                move=move,
                down_time=down_time,
                after_sleep=after_sleep,
                key=key,
            )
        frame = self.frame
        super().click(
            x,
            y,
            move_back=move_back,
            name=name,
            move=move,
            down_time=0.04,
            after_sleep=after_sleep,
            interval=interval,
            key=key,
        )
        if self.debug:
            self.screenshot("click", frame=frame)

    def click_with_alt(
        self,
        x: float | Box | list[Box] = 0.0,
        y: float | int = 0.0,
        move_back=False,
        name=None,
        interval=-1,
        move=True,
        down_time=0.01,
        after_sleep=0,
        key="left",
        alt_hold_delay=0.5,
        debug_name="click_with_alt",
    ):
        """
        按住 alt 键点击。

        用于只有 alt 组合键才能生效的目标（例如自由层内的点击）。
        先 ``send_key_down('alt')``，等待 ``alt_hold_delay`` 让游戏识别到修饰键，再点击，最后 ``send_key_up('alt')``。

        Args:
            alt_hold_delay: 按下 alt 后到点击之间的等待秒数；传 0 可保持不加额外等待的时序。
            debug_name: debug 模式下的截图名。
        """
        frame = self.frame
        self.send_key_down("alt")
        try:
            if alt_hold_delay > 0:
                self.sleep(alt_hold_delay)
            self.click(
                x,
                y,
                move_back=move_back,
                name=name,
                interval=interval,
                move=move,
                down_time=down_time,
                after_sleep=after_sleep,
                key=key,
            )
        finally:
            # 必须保证松开 alt：点击抛异常时若卡住 alt，后续所有按键都会被污染
            self.send_key_up("alt")
        if self.debug:
            self.screenshot(debug_name, frame=frame)

    def back(self, after_sleep=0):
        frame = self.frame
        self.send_key("esc", down_time=0.04, after_sleep=after_sleep)
        if self.debug:
            self.screenshot("back", frame=frame)

    def free_layer_click(
        self, x=0, y=0, move_back=False, name=None, interval=-1, move=True, down_time=0.01, after_sleep=0, key="left"
    ):
        # alt_hold_delay=0：保持改造前的时序（按下 alt 后立即点击，不加额外等待）
        self.click_with_alt(
            x,
            y,
            move_back=move_back,
            name=name,
            interval=interval,
            move=move,
            down_time=down_time,
            after_sleep=after_sleep,
            key=key,
            alt_hold_delay=0,
            debug_name="free_layer_click",
        )

    def click_with_key(self, hold_key, result, delay1=1, delay2=0.5, after_sleep=0):
        def start_task1():
            self.send_key(key=hold_key, down_time=delay1)

        def start_task2():
            time.sleep(delay2)  # 控制任务2启动延迟
            self.click(result)

        t1 = threading.Thread(target=start_task1)
        t2 = threading.Thread(target=start_task2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.sleep(after_sleep)

    def wait_click_ocr(
        self,
        x=0,
        y=0,
        to_x=1,
        to_y=1,
        width=0,
        height=0,
        box=None,
        name=None,
        match=None,
        threshold=0,
        frame=None,
        target_height=0,
        time_out=0,
        raise_if_not_found=False,
        recheck_time=0,
        after_sleep=0,
        post_action=None,
        log=False,
        screenshot=False,
        settle_time=-1,
        lib="default",
        alt=False,
    ):
        """
        等待 OCR 命中并点击，``alt=True`` 时改用 alt 组合键点击。

        参数与父类一致；``alt=False`` 直接走父类实现，不做任何改动。
        """
        if not alt:
            return super().wait_click_ocr(
                x=x,
                y=y,
                to_x=to_x,
                to_y=to_y,
                width=width,
                height=height,
                box=box,
                name=name,
                match=match,
                threshold=threshold,
                frame=frame,
                target_height=target_height,
                time_out=time_out,
                raise_if_not_found=raise_if_not_found,
                recheck_time=recheck_time,
                after_sleep=after_sleep,
                post_action=post_action,
                log=log,
                screenshot=screenshot,
                settle_time=settle_time,
                lib=lib,
            )

        result = self.wait_ocr(
            x,
            y,
            width=width,
            height=height,
            to_x=to_x,
            to_y=to_y,
            box=box,
            name=name,
            match=match,
            threshold=threshold,
            frame=frame,
            target_height=target_height,
            time_out=time_out,
            raise_if_not_found=raise_if_not_found,
            post_action=post_action,
            log=log,
            screenshot=screenshot,
            settle_time=settle_time,
            lib=lib,
        )
        if recheck_time > 0:
            self.sleep(1)
            result = self.ocr(
                x,
                y,
                width=width,
                height=height,
                to_x=to_x,
                to_y=to_y,
                box=box,
                name=name,
                match=match,
                threshold=threshold,
                frame=frame,
                target_height=target_height,
                log=log,
                screenshot=screenshot,
                lib=lib,
            )
        if result is not None:
            self.click_with_alt(result, after_sleep=after_sleep)
            return result
        logger.warning(f"wait ocr no box {x} {y} {width} {height} {to_x} {to_y} {match}")

    def wait_click_feature(
        self,
        feature,
        horizontal_variance=0,
        vertical_variance=0,
        threshold=0,
        relative_x=0.5,
        relative_y=0.5,
        time_out=0,
        pre_action=None,
        post_action=None,
        box=None,
        raise_if_not_found=True,
        use_gray_scale=False,
        canny_lower=0,
        canny_higher=0,
        click_after_delay=0,
        settle_time=-1,
        after_sleep=0,
        target_height=0,
        alt=False,
    ):
        """
        等待特征命中并点击，``alt=True`` 时改用 alt 组合键点击。

        参数与父类一致；``alt=False`` 直接走父类实现，不做任何改动。
        """
        if not alt:
            return super().wait_click_feature(
                feature,
                horizontal_variance,
                vertical_variance,
                threshold,
                relative_x=relative_x,
                relative_y=relative_y,
                time_out=time_out,
                pre_action=pre_action,
                post_action=post_action,
                box=box,
                raise_if_not_found=raise_if_not_found,
                use_gray_scale=use_gray_scale,
                canny_lower=canny_lower,
                canny_higher=canny_higher,
                click_after_delay=click_after_delay,
                settle_time=settle_time,
                after_sleep=after_sleep,
                target_height=target_height,
            )

        found = self.wait_until(
            lambda: self.find_one(
                feature,
                horizontal_variance,
                vertical_variance,
                threshold,
                box=box,
                use_gray_scale=use_gray_scale,
                canny_lower=canny_lower,
                canny_higher=canny_higher,
                target_height=target_height,
            ),
            time_out=time_out,
            pre_action=pre_action,
            post_action=post_action,
            raise_if_not_found=raise_if_not_found,
            settle_time=settle_time,
        )
        if found is not None:
            if click_after_delay > 0:
                self.sleep(click_after_delay)
            x, y = found.relative_with_variance(relative_x, relative_y)
            self.click_with_alt(x, y, name=found.name, after_sleep=after_sleep)
            return True
        return False

    def find_top_right_count(self):
        result = self.ocr(0.89, 0.01, 0.99, 0.1, match=re.compile(r"^\d+/\d+$"), box="top_right")
        if not result:
            raise Exception("找不到当前体力或票")
        return int(result[0].name.split("/")[0])

    def find_cost(self, boxes=None, default=30):
        boundary = self.box_of_screen(0.48, 0.56, 0.57, 0.7)
        if not boxes:
            boxes = self.ocr(box=boundary)

        if costs := self.find_boxes(boxes, match=number_re, boundary=boundary):
            cost = int(costs[0].name)
        else:
            cost = default
        return cost

    def out_free_layer(self):
        self.info_set("current_task", "out_free_layer")
        while not self.wait_click_ocr(match=["确认"], time_out=2):
            self.back()
            self.sleep(2)

    def is_free_layer(self, time_out=20, every_time=1):
        # wait_ocr(time_out=0) 使用框架默认超时，不能用于单次探测。
        """按限定超时识别活动层 HUD，避免嵌套默认等待。"""
        def detected():
            """仅用当前帧检查活动层快捷键标识是否齐全。"""
            result = self.ocr(match=["Esc", "P", "M", "F1", "F2", "F3", "F4"], box=self.box.top)
            return bool(result and len(result) >= 5)

        return bool(self.wait_until(detected, time_out=max(time_out, 0.01), settle_time=0))

    def break_if_not_enough(self):
        if self.wait_ocr(match=re.compile("坍塌晶条"), time_out=2, log=True):
            self.wait_click_ocr(match=["取消"], after_sleep=2, time_out=2, raise_if_not_found=True)
            return True
        return False

    def back_if_not_ocr_match(self, match, box=None, max_back_count=1, raise_if_not_found=False):
        for count in range(max_back_count + 1):
            temp_raise_if_not_found = False
            if count == max_back_count:
                temp_raise_if_not_found = True
            if self.wait_ocr(match=match, box=box, raise_if_not_found=temp_raise_if_not_found):
                return
            else:
                self.back(after_sleep=2)
        return

    def fast_combat(self, *, set_cost, battle_max=10, plus_x=0.616, plus_y=0.52, click_all=False, activity=False):
        if activity:
            click_all = True
        if click_all:
            plus_x = 0.65
            plus_y = 0.52
            self.wait_click_ocr(match=["自律"], box=self.box.bottom_right, after_sleep=2, raise_if_not_found=True)
            if self.break_if_not_enough():
                self.wait_ocr(match=["自律"], box=self.box.bottom_right, raise_if_not_found=True)
                return 0
            self.click(plus_x, plus_y)
            self.wait_click_ocr(match=["确认"], after_sleep=1, raise_if_not_found=False)
            if not self.wait_click_ocr(match=["取消"], time_out=2, raise_if_not_found=False):
                self.wait_pop_up(count=1)
            self.back_if_not_ocr_match(match=["自律"], box=self.box.bottom_right, raise_if_not_found=True)
            return 0

        self.wait_click_ocr(match=["自律"], box=self.box.bottom_right, after_sleep=2, raise_if_not_found=True)
        if self.break_if_not_enough():
            self.wait_ocr(match=["自律"], box=self.box.bottom_right, raise_if_not_found=True)
            return 0
        boxes = self.ocr(log=True, threshold=0.8, frame_processor=self.make_hsv_isolator(hR.WHITE))
        if next_step := self.find_boxes(boxes, "下一步", self.box.bottom_right):
            self.click(next_step, after_sleep=1)
            boxes = self.ocr(log=True, threshold=0.8, frame_processor=self.make_hsv_isolator(hR.WHITE))
            # default_cost = 30
        current = self.ocr(match=[stamina_re, number_re], box=self.box_of_screen(0.84, 0, 0.99, 0.10))
        if current:
            current = int(current[0].name.split("/")[0])
        else:
            current = 1
        self.sleep(1)
        if (
            len(find_boxes_by_name(boxes, ["确认", "取消", "上一步"])) != 2
            and len(find_boxes_by_name(boxes, ["确认", "取消", "上", "一步"])) != 3
        ):
            if self.debug:
                self.screenshot("fast_no_zilv")
            self.log_info("自律没有弹窗, 可能是调度权限不足")
            return current
        cost = set_cost
        # if set_cost:
        #     cost = set_cost
        # else:
        #     cost = self.find_cost(boxes, default=default_cost)

        self.info_set("current_stamina", current)
        self.info_set("battle_cost", cost)
        self.info_set("battle_max", battle_max)
        can_fast_count = min(int(current / cost), battle_max)
        self.info_set("can_fast_count", can_fast_count)
        self.info_set("click_battle_plus", 0)
        self.log_info(f"battle cost: {cost} current_stamina: {current} can_fast_count: {can_fast_count}")

        for _ in range(can_fast_count - 1):
            self.click(plus_x, plus_y)
            self.info_incr("click_battle_plus")
            self.sleep(0.2)
        self.sleep(1)
        remaining = current - can_fast_count * cost
        self.info_set("remaining_stamina", remaining)
        if can_fast_count <= 0:
            self.click(find_boxes_by_name(boxes, "取消"))
            return remaining

        self.click(find_boxes_by_name(boxes, "确认"), after_sleep=2)

        if self.click(find_boxes_by_name(boxes, "前往"), after_sleep=2):
            if self.enter_fast_disassemble():
                self.fast_disassemble_loop(stamina_re)

            self.click(find_boxes_by_name(boxes, "确认"), after_sleep=2)

        self.wait_pop_up(count=1)
        self.wait_ocr(match=["自律"], box=self.box.bottom_right, raise_if_not_found=True)

        return remaining

    def click_box_by_match_position(self, box: Box | list[Box], match: str | re.Pattern, after_sleep=None):
        if isinstance(box, list):
            box = box[0]
        text = box.name

        # 找匹配位置
        if isinstance(match, str):
            start = text.find(match)
            if start == -1:
                return self.click_box(box)
            end = start + len(match)

        else:  # regex
            m = match.search(text)
            if not m:
                return self.click_box(box)
            start = m.start()
            end = m.end()

        mid = (start + end) / 2
        ratio = mid / len(text)

        x = box.x
        y = box.y
        w = box.width
        h = min(box.height, int(30 / 1080 * self.height))  # 限制高度，避免匹配到下方的按钮

        click_y = y + h // 2

        if ratio < 0.33:
            click_x = x + h
        elif ratio > 0.66:
            click_x = x + w - h
        else:
            click_x = x + w // 2

        self.click(click_x, click_y, after_sleep=after_sleep)

    def fast_disassemble_loop(self, model_re):
        while self.wait_click_ocr(match=["快捷选择"], after_sleep=2):
            ocr_select_num = self.wait_ocr(match=re.compile(model_re), box=self.box.bottom_right)

            if not ocr_select_num:
                self.back(after_sleep=2)
                break

            self.wait_click_ocr(match=["拆解"], box=self.box.bottom_right, after_sleep=2)
            self.wait_pop_up(count=1)

    def enter_fast_disassemble(self):
        # 拆解入口是硬条件
        if not self.wait_click_ocr(match=["拆解"], box=self.box.top_right, after_sleep=2):
            return False

        # 以下是“尽力而为”的筛选条件
        self.wait_click_ocr(match=["工业级及以下未培养"], after_sleep=2)
        self.wait_click_ocr(match=["精密级及以下未培养"], after_sleep=2)

        return True

    def loop_click_ocr(self, match_list, box=None, pop_up_count=1, sleep_after_click=0.5):
        """
        循环点击 OCR 匹配元素，直到找不到为止。
        处理弹窗 pop_up_count。
        """
        if box is None:
            box = self.box.bottom_right
        while self.wait_click_ocr(match=match_list, box=box, raise_if_not_found=False, after_sleep=sleep_after_click):
            if pop_up_count:
                self.wait_pop_up(count=pop_up_count)

    def wait_pop_up(self, time_out=15, other=None, box=None, count=100):
        if box is None:
            box = self.box.bottom
        start = time.time()
        check = pop_ups.copy()
        if other:
            if isinstance(other, list):
                check += other
            else:
                check.append(other)
        found_count = 0
        while (
            self.wait_ocr(
                match=pop_ups,
                box=box,
                settle_time=2,
                time_out=int(time_out - (time.time() - start)),
                raise_if_not_found=False,
            )
            and found_count < count
        ):
            found_count += 1
            self.back(after_sleep=3)

    def press_keys_sequence(self, keys, times, sleep_between=0.5, sleep_after_last=False):
        """
        按顺序按下按键，每次按键后等待 sleep_between 秒，可选择最后一个按键后不等待。
        当按键持续时间为 0 时，不传 down_time 参数给 send_key。
        """
        for i, (key, t) in enumerate(zip(keys, times)):
            if t:  # t != 0
                self.send_key(key, down_time=t)
            else:  # t == 0
                self.send_key(key)
            if i < len(keys) - 1 or sleep_after_last:
                self.sleep(sleep_between)

    def run_steps_with_retry_and_rollback(self, steps):
        """
        执行带重试与回退机制的步骤序列。

        参数:
            steps: List[List[Callable, bool, bool]]
                每个元素为 [func, retry_on_fail, rollback_on_fail]
                - func: 无参可调用对象，成功返回 True，失败返回 False
                - retry_on_fail: 是否允许重试（最多尝试 2 次）
                - rollback_on_fail: 失败且未达重试上限时，是否回退到上一步

        返回:
            bool: 全部成功返回 True，中途失败返回 False
        """
        if not steps:
            return True

        retries = [0] * len(steps)
        i = 0

        while 0 <= i < len(steps):
            func, retry_on_fail, rollback_on_fail = steps[i]

            # 执行当前步骤
            try:
                success = func()
            except Exception:
                success = False

            if success:
                retries[i] = 0
                i += 1
                continue

            # === 处理失败 ===
            if retry_on_fail:
                retries[i] += 1
                if retries[i] >= 2:
                    return False
            else:
                return False

            # 决定是否回退
            if rollback_on_fail and i > 0:
                i -= 1
            # 否则：留在当前步，下一轮重试（因 i 未变）

        return True

    def kill_all_related_processes(self):
        """尝试杀死游戏进程和本软件自身进程（除当前进程外）"""
        import os

        import psutil
        import win32api
        import win32con
        import win32process

        # 1. 杀死游戏进程
        try:
            hwnd = getattr(self, "hwnd", None)
            if hwnd is not None:
                hwnd_val = getattr(hwnd, "hwnd", None)
                if hwnd_val:
                    tid, pid = win32process.GetWindowThreadProcessId(hwnd_val)
                    handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
                    win32api.TerminateProcess(handle, 0)
                    win32api.CloseHandle(handle)
                    self.log_info(f"已终止游戏进程 pid={pid}", notify=True)
                else:
                    self.log_info("未获取到 hwnd，无法终止游戏进程", notify=True)
            else:
                self.log_info("未获取到 hwnd 属性，无法终止游戏进程", notify=True)
        except Exception as e:
            self.log_info(f"终止游戏进程失败: {e}", notify=True)
        # 2. 杀死本软件所有同名进程（除当前进程）
        try:
            current_pid = os.getpid()
            exe_name = psutil.Process(current_pid).name()
            for proc in psutil.process_iter(["pid", "name"]):
                if proc.info["name"] == exe_name and proc.info["pid"] != current_pid:
                    try:
                        proc.kill()
                        self.log_info(f"已终止本软件进程 pid={proc.info['pid']}", notify=True)
                    except Exception as e2:
                        self.log_info(f"终止本软件进程失败: {e2}", notify=True)
        except Exception as e:
            self.log_info(f"查找/终止本软件进程失败: {e}", notify=True)
