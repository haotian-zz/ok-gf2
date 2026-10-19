"""
部署界面「好友助战」选人的纯逻辑：卡片定位、椎数配对、已上场勾选判断。
坐标按 1280x768 实测，偏移统一用画面宽高的比例表达，换分辨率后仍成立。
"""

import re

import numpy as np

badge_re = re.compile(r"^\d$")  # 卡片左上角蓝圈里的椎数
power_re = re.compile(r"^\d{3,6}$")  # 卡片下方的作战效能

# 右侧面板的位置（画面比例）
PANEL_BOX = (0.75, 0.15, 0.995, 0.86)  # 卡片区域，含椎数角标和战力
NAME_BOX = (0.05, 0.80, 0.24, 0.90)  # 点中卡片后左下角的人形名字
BUTTON_BOX = (0.74, 0.88, 0.99, 0.995)  # 右下角「部署人形 / 撤回人形」
TAB_BOX = (0.74, 0.0, 0.95, 0.09)  # 「我的人形 / 好友助战」页签
# 属性筛选图标：页签中心往下 0.052 画面高，x 按顺序 全部/物理/燃烧/电导/冷凝
FILTER_DY = 0.052
FILTER_X = {"全部": 0.772, "物理": 0.809, "燃烧": 0.848, "电导": 0.887, "冷凝": 0.926}
# 卡片中心相对战力数字中心：往上 0.065 画面高
CARD_DY = -0.065
# 已上场的橙色勾相对战力数字中心：右 0.023 画面宽、上 0.105 画面高
CHECK_DX, CHECK_DY = 0.023, -0.105


def _center(box):
    return box.x + box.width / 2, box.y + box.height / 2


def find_cards(boxes, width, height):
    """
    由 OCR 结果找出卡片：每个战力数字代表一张卡片，并配对它左上方的椎数角标。
    :return: [{"power": int, "badge": int | None, "center": (x, y), "power_box": box}, ...] 按战力从高到低
    """
    powers = [b for b in boxes if power_re.match(b.name)]
    badges = [b for b in boxes if badge_re.match(b.name)]
    cards = []
    for p in powers:
        px, py = _center(p)
        badge = None
        best = None
        for b in badges:
            bx, by = _center(b)
            dx, dy = px - bx, py - by
            if 0 < dx < 0.06 * width and 0.03 * height < dy < 0.14 * height:
                if best is None or dy < best:
                    best, badge = dy, int(b.name)
        cards.append({"power": int(p.name), "badge": badge, "center": (px, py + CARD_DY * height), "power_box": p})
    cards.sort(key=lambda c: -c["power"])
    return cards


def check_point(card, width, height):
    """卡片右上角橙色勾的采样点。"""
    px, py = _center(card["power_box"])
    return int(px + CHECK_DX * width), int(py + CHECK_DY * height)


def is_orange_check(frame, x, y, radius=5, ratio=0.4):
    """采样点周围是否主要是橙色（已上场的勾）。frame 为 BGR。"""
    if frame is None:
        return False
    h, w = frame.shape[:2]
    x0, x1 = max(0, x - radius), min(w, x + radius + 1)
    y0, y1 = max(0, y - radius), min(h, y + radius + 1)
    if x0 >= x1 or y0 >= y1:
        return False
    patch = frame[y0:y1, x0:x1].astype(int)
    b, g, r = patch[..., 0], patch[..., 1], patch[..., 2]
    orange = (r > 180) & (g > 90) & (g < 215) & (b < 110) & (r - b > 110)
    return float(orange.mean()) >= ratio


def filter_point(tab_box, attr, width, height):
    """属性筛选图标的点击位置；属性不在表里就点「全部」。"""
    _, ty = _center(tab_box)
    return FILTER_X.get(attr, FILTER_X["全部"]) * width, ty + FILTER_DY * height


def pick_candidates(cards, min_badge):
    """椎数达标的卡片，保持战力从高到低。"""
    return [c for c in cards if c["badge"] is not None and c["badge"] >= min_badge]


def make_check_frame(width, height, checks):
    """测试用：生成一张黑图并在给定点画橙色方块。"""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for x, y in checks:
        frame[max(0, y - 6) : y + 7, max(0, x - 6) : x + 7] = (0, 160, 255)
    return frame
