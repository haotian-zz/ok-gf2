"""
往期活动推图：主页「战役推进」→ 右上「往期活动」→ 左边「活动剧情」，活动卡片从左到右排，卡片下面写「完成度 xx%」。
找第一个完成度不到 100% 的活动点进去，进去后的关卡地图、关卡面板和主线一样（MA-1-1 / MS-1-1 …，「挑战 / 观看」），
所以每关怎么推、阵容怎么整理都直接沿用 ClearMapTask，这里只换「章节」层的导航：
- 主线的「章节选择页 + 章节进度」换成「活动列表 + 卡片上的完成度」；
- 「进下一章」换成「回列表找下一个完成度不到 100% 的活动」。
"""

import re
from difflib import SequenceMatcher

from src.core.BaseGfTask import map_re, nav_tabs_re
from src.tasks.ClearMapTask import ClearMapTask, campaign_re

event_percent_re = re.compile(r"完\s*成\s*度\s*(\d{1,3})\s*%")
event_tab_re = re.compile(r"^往期活动$")
event_story_re = re.compile(r"^活动剧情$")
EVENT_TITLE_DX = 0.08  # 活动名在「完成度」正上方：中心 x 相差不超过画面宽的这个比例
EVENT_TITLE_DY = (0.02, 0.07)  # 活动名中心在「完成度」中心上方多远（画面高的比例）
EVENT_LIST_DRAG = (0.75, 0.35)  # 拖活动列表时按住的起止 x（相对宽），一次挪两张多卡片，不会跳过
EVENT_LIST_Y = 0.45  # 拖列表的高度：卡片立绘中间
EVENT_LIST_MAX_DRAGS = 12
EVENT_MAX = 40  # 一次最多推多少个活动（防止死循环）
EVENT_TABS = ("剧情", "物资")  # 活动地图右下的两个页签，各是一张关卡地图


def _center(b):
    return b.x + b.width / 2, b.y + b.height / 2


def event_cards(boxes, width, height):
    """
    活动列表上的卡片：每个「完成度 xx%」配上它正上方的活动名，返回 [(活动名框, 完成度)]，按 x 从左到右。
    实录 2026-10-22（2560x1440）：「狂想四重奏」(667,1083)，「完成度0%」(691,1141)。
    """
    titles = [
        b
        for b in boxes
        if not event_percent_re.search(b.name or "") and re.search(r"[一-鿿]{2,}", b.name or "")
    ]
    out = []
    for p in boxes:
        m = event_percent_re.search(p.name or "")
        if not m:
            continue
        px, py = _center(p)
        above = [
            t
            for t in titles
            if abs(_center(t)[0] - px) < EVENT_TITLE_DX * width
            and EVENT_TITLE_DY[0] * height < py - _center(t)[1] < EVENT_TITLE_DY[1] * height
        ]
        if above:
            title = min(above, key=lambda t: py - _center(t)[1])
            out.append((title, min(int(m.group(1)), 100)))
    return sorted(out, key=lambda c: c[0].x)


def same_event(a, b):
    """活动名 OCR 常错一两个字（实录「狂想四重奏」读成「狂想四重秦」），按相似度比；上 / 中 / 下篇不同算两个。"""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    pa, pb = re.search(r"[上中下]篇", a), re.search(r"[上中下]篇", b)
    if pa and pb and pa.group(0) != pb.group(0):
        return False  # 「密米尔的返演·上篇 / 下篇」只差一个字，是两个活动
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.6


def pick_event(cards, skip):
    """第一个完成度不到 100%、这次还没放弃过的活动。"""
    for title, percent in cards:
        if percent < 100 and not any(same_event(title.name, s) for s in skip):
            return title, percent
    return None


def event_title_on_map(boxes, width, height):
    """活动地图顶部正中：小字活动名在「活动剧情」上面一行。"""
    cands = [
        b
        for b in boxes
        if b.y < 0.06 * height
        and 0.35 * width < _center(b)[0] < 0.65 * width
        and re.search(r"[一-鿿]{2,}", b.name or "")
        and not event_story_re.search(b.name or "")
    ]
    return min(cands, key=lambda b: b.y).name.strip() if cands else None


class EventMapTask(ClearMapTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "往期活动推图"
        self.description = (
            "从主页、作战页或活动列表启动：进第一个完成度不到 100% 的往期活动推图，推完回列表找下一个；"
            "停在活动地图上启动就先推当前这个"
        )
        for key in ("推完继续下一章", "难度", "英雄难度"):
            self.default_config.pop(key, None)
            self.config_description.pop(key, None)
        self.config_type.pop("难度", None)
        self.default_config["推完继续下一个活动"] = True
        self.config_description["推完继续下一个活动"] = (
            "当前活动推完（或剩下的关都推不动）后，回往期活动列表进下一个完成度不到 100% 的活动继续推"
        )
        self.event_name = None
        self.skipped_events = []  # 这次推过 / 推不动的活动，不再回头选

    # ------------------------------------------------------------------ 主流程
    def _run_sweep(self):
        self.event_name = None
        self.skipped_events = []
        if self.scan_maps():
            self.event_name = event_title_on_map(self.ocr(box="top") or [], self.width, self.height)
            self.log_info(f"停在活动「{self.event_name or '?'}」的地图上，先推这个", notify=True)
        elif not self.enter_next_event():
            self.log_info("往期活动都推到 100% 了", notify=True)
            return
        total = 0
        for _ in range(EVENT_MAX):
            self.ensure_map()
            self.prepare_chapter()
            count, locked = self.finish_chapter()
            total += count
            self.log_info(f"活动「{self.event_name or '?'}」本次推进 {count} 关，未解锁 {locked or '无'}", notify=True)
            if self.event_name:
                self.skipped_events.append(self.event_name)
            if not self.config.get("推完继续下一个活动", True):
                break
            if not self.enter_next_event():
                self.log_info("没有完成度不到 100% 的往期活动了", notify=True)
                break
        self.log_info(f"往期活动推图完成, 本次推进 {total} 关", notify=True)

    def prepare_chapter(self):
        """活动地图没有普通 / 困难、英雄难度。"""
        self.close_map_panel()
        self.hero_mode = False

    def clear_chapter(self):
        """
        活动地图右下有「剧情 / 物资」两个页签，各是一张关卡地图，两边的关卡都算进完成度：先推「剧情」再推「物资」。
        实录 2026-10-22 狂想四重奏：剧情全推完完成度才 75%，剩下的是物资页签的 MF-1-1～（推荐等级 30）；
        拂晓的回响刚进去时「物资」点了没反应（剧情没推到解锁），这种就跳过，下一轮再试。
        """
        total, locked = 0, []
        for tab in EVENT_TABS:
            if not self.switch_event_tab(tab):
                continue
            count, tab_locked = super().clear_chapter()
            total += count
            locked += tab_locked
        return total, locked

    def switch_event_tab(self, tab):
        """切到右下的「剧情 / 物资」页签，返回切没切过去（地图上的关卡名变了才算）。"""
        self.close_map_panel()
        before = {b.name for b, _ in self.ensure_map()}
        button = self.ocr(box="bottom_right", match=re.compile(rf"^{tab[0]}\s*{tab[1]}$"))
        if not button:
            self.log_info(f"活动地图右下没找到「{tab}」页签", notify=False)
            return tab == EVENT_TABS[0]  # 没有页签的活动只有一张图，当作「剧情」
        self.click(button, after_sleep=2)
        after = {b.name for b, _ in self.ensure_map()}
        if tab != EVENT_TABS[0] and after == before:
            self.log_info(f"「{tab}」页签点了没反应（还没解锁），先不推", notify=True)
            return False
        self.log_info(f"推活动「{self.event_name or '?'}」的「{tab}」页签", notify=False)
        return True

    def chapter_medals(self):
        # 活动地图左下角的「0/45」是活动代币收集进度，不是勋章
        return None

    # ------------------------------------------------------------------ 活动列表
    def on_event_list(self):
        if not self.ocr(box="top", match=nav_tabs_re):
            return False
        return bool(event_cards(self.ocr(log=True) or [], self.width, self.height))

    def open_event_list(self):
        """从活动地图 / 作战的其他页签 / 主页回到往期活动列表。"""
        for _ in range(4):
            if self.on_event_list():
                return True
            self.close_map_panel()
            if self.ocr(box="top", match=nav_tabs_re):
                tab = self.ocr(box="top", match=event_tab_re)
                if tab:
                    self.click(tab, after_sleep=2)
                story = self.ocr(box="left", match=event_story_re)
                if story:
                    self.click(story, after_sleep=2)
                continue
            if entry := self.ocr(box="top_right", match=campaign_re):
                self.log_info("停在游戏主页，点「战役推进」", notify=False)
                self.click(entry, after_sleep=3)
                continue
            if self.scan_maps():
                self.back(after_sleep=2)  # 活动地图按 ESC 回列表
                continue
            if not self.resume_battle(time_out=300):
                self.back(after_sleep=2)
        return self.on_event_list()

    def read_event_cards(self):
        self.next_frame()
        boxes = self.ocr(log=True) or []
        cards = event_cards(boxes, self.width, self.height)
        self.debug_shot("event_list", [t for t, _ in cards])
        return cards

    def drag_event_list(self, direction):
        """往右（1）/ 往左（-1）挪活动列表，返回挪完的卡片；没挪动（到头了）返回 None。"""
        before = [t.name for t, _ in self.read_event_cards()]
        a, b = EVENT_LIST_DRAG if direction > 0 else EVENT_LIST_DRAG[::-1]
        self.swipe_relative(a, EVENT_LIST_Y, b, EVENT_LIST_Y, duration=0.6)
        self.sleep(1.5)
        after = self.read_event_cards()
        return None if [t.name for t, _ in after] == before else after

    def find_event(self, want=None):
        """
        从列表最左边往右找：want 为空找第一个完成度不到 100% 且没放弃过的活动，否则找名字是 want 的那个。
        返回 (活动名框, 完成度) 或 None。
        """
        if want and (hit := next((c for c in self.read_event_cards() if same_event(c[0].name, want)), None)):
            return hit  # 从活动里退出来列表一般还停在原处，先看当前屏
        for _ in range(EVENT_LIST_MAX_DRAGS):
            if self.drag_event_list(-1) is None:
                break
        cards = self.read_event_cards()
        for _ in range(EVENT_LIST_MAX_DRAGS):
            if want:
                hit = next((c for c in cards if same_event(c[0].name, want)), None)
            else:
                hit = pick_event(cards, self.skipped_events)
            if hit:
                return hit
            cards = self.drag_event_list(1)
            if cards is None:
                return None
        return None

    def click_event(self, title):
        """点活动卡片进地图，跳过开场剧情直到看到关卡卡片。"""
        self.event_name = title.name.strip()
        self.info_set("current_task", f"活动 {self.event_name}")
        self.click(title, after_sleep=3)
        self.skip_dialogs(end_match=map_re, time_out=180, has_dialog=True, raise_if_not_found=False)

    def enter_next_event(self):
        """回列表进下一个完成度不到 100% 的活动，返回是否进去了。"""
        self.info_set("current_task", "找下一个往期活动")
        if not self.open_event_list():
            raise Exception("回不到往期活动列表, 请检查游戏画面")
        hit = self.find_event()
        if not hit:
            return False
        title, percent = hit
        self.log_info(f"进往期活动「{title.name}」（完成度 {percent}%）推图", notify=True)
        self.click_event(title)
        return True

    # ------------------------------------------------------------------ 覆盖主线的章节导航
    def chapter_percent(self):
        """回列表读当前活动卡片上的完成度（停在列表上）。"""
        if not self.open_event_list():
            return None
        if not self.event_name:
            return None
        hit = self.find_event(self.event_name)
        if not hit:
            self.log_info(f"列表上没找到活动「{self.event_name}」", notify=True)
            return None
        self.log_info(f"活动「{hit[0].name}」完成度 {hit[1]}%", notify=False)
        return hit[1]

    def reenter_from_chapter_select(self):
        """停在活动列表上：点回当前活动；没记住是哪个活动就进第一个没推完的。"""
        if not self.on_event_list():
            return False
        hit = self.find_event(self.event_name) if self.event_name else self.find_event()
        if not hit:
            return False
        self.click_event(hit[0])
        return True

    def open_campaign_from_main(self):
        """停在主页 / 作战其他页签：回到往期活动列表再进当前活动。"""
        if not (self.ocr(box="top_right", match=campaign_re) or self.ocr(box="top", match=nav_tabs_re)):
            return False
        return self.open_event_list() and self.reenter_from_chapter_select()
