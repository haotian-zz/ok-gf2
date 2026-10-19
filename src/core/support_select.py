"""
部署界面的纯逻辑：卡片定位、椎数角标识别、已上场勾选判断、空地格查找。
坐标按 1280x768 实测，偏移统一用画面宽高的比例表达，换分辨率后仍成立。
"""

import os
import re

import cv2
import numpy as np

power_re = re.compile(r"^\d{3,6}$")  # 卡片下方的作战效能
digit_re = re.compile(r"^\d$")  # 地图上已上场单位头顶的编号

# 右侧面板的位置（画面比例）
PANEL_BOX = (0.75, 0.15, 0.995, 0.86)  # 卡片区域
NAME_BOX = (0.05, 0.80, 0.24, 0.90)  # 点中卡片后左下角的人形名字
BUTTON_BOX = (0.74, 0.88, 0.99, 0.995)  # 右下角「部署人形 / 撤回人形」
TAB_BOX = (0.74, 0.0, 0.95, 0.09)  # 「我的人形 / 好友助战」页签
COUNT_BOX = (0.35, 0.0, 0.65, 0.09)  # 顶部「部署人形 3/4」
MAP_BOX = (0.0, 0.08, 0.72, 0.86)  # 地图区域（排除右侧面板和底部按钮）
# 属性筛选图标：页签中心往下 0.052 画面高，x 按顺序 全部/物理/燃烧/电导/冷凝
FILTER_DY = 0.052
FILTER_X = {"全部": 0.791, "物理": 0.828, "燃烧": 0.867, "电导": 0.906, "冷凝": 0.945}
# 卡片中心相对战力数字中心：往上 0.065 画面高
CARD_DY = -0.065
# 已上场的橙色勾相对战力数字中心：右 0.023 画面宽、上 0.105 画面高
CHECK_DX, CHECK_DY = 0.023, -0.105
# 椎数角标（蓝色小圆）中心相对战力数字中心
BADGE_DX, BADGE_DY = -0.0242, -0.0814
BADGE_WIN = 13  # 角标搜索窗半径，1280x768 下的像素
BADGE_DIGIT_R = 5.5  # 只看圆内这个半径里的白色像素
BADGE_SIZE = 13  # 模板尺寸
BADGE_MIN_IOU = 0.6
BADGE_DIR = os.path.join("assets", "support_badges")

_badge_templates = None


def _center(box):
    return box.x + box.width / 2, box.y + box.height / 2


def find_cards(boxes, width, height, badge_of=None):
    """
    由 OCR 结果找出卡片：每个战力数字代表一张卡片。
    :param badge_of: 可选，输入战力 box 返回椎数（int / None）
    :return: [{"power": int, "badge": int | None, "center": (x, y), "power_box": box}, ...] 按战力从高到低
    """
    cards = []
    for p in boxes:
        if not power_re.match(p.name):
            continue
        px, py = _center(p)
        badge = badge_of(p) if badge_of else None
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


# ------------------------------------------------------------------ 椎数角标
def load_badge_templates(folder=BADGE_DIR):
    """读取 assets/support_badges/*.png（13x13 二值图），文件名 dash 代表没椎（0）。"""
    global _badge_templates
    if _badge_templates is None:
        templates = {}
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                stem, ext = os.path.splitext(name)
                if ext.lower() != ".png":
                    continue
                img = cv2.imread(os.path.join(folder, name), cv2.IMREAD_GRAYSCALE)
                if img is None or img.shape != (BADGE_SIZE, BADGE_SIZE):
                    continue
                templates[0 if stem == "dash" else int(stem)] = img > 127
        _badge_templates = templates
    return _badge_templates


def find_badge_disk(frame, x, y, scale=1.0):
    """在 (x, y) 附近找蓝色小圆，返回圆心 (cx, cy)；找不到返回 None。"""
    r = int(round(BADGE_WIN * scale))
    h, w = frame.shape[:2]
    x0, y0 = max(0, int(x) - r), max(0, int(y) - r)
    win = frame[y0 : min(h, int(y) + r), x0 : min(w, int(x) + r)]
    if win.size == 0:
        return None
    hsv = cv2.cvtColor(win, cv2.COLOR_BGR2HSV)
    blue = ((hsv[..., 0] > 85) & (hsv[..., 0] < 110) & (hsv[..., 1] > 25) & (hsv[..., 2] > 170)).astype(np.uint8)
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(blue)
    lo, hi = 9 * scale, 18 * scale
    best = None
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if not (60 * scale * scale <= area <= 260 * scale * scale and lo <= bw <= hi and lo <= bh <= hi):
            continue
        cx, cy = cents[i]
        d = (x0 + cx - x) ** 2 + (y0 + cy - y) ** 2
        if best is None or d < best[0]:
            best = (d, x0 + cx, y0 + cy)
    return None if best is None else (best[1], best[2])


def badge_digit_mask(frame, cx, cy, scale=1.0, dx=0.0, dy=0.0, white=215):
    """圆内的白色像素，重采样成 13x13 二值图。"""
    r = BADGE_SIZE // 2
    out = np.zeros((BADGE_SIZE, BADGE_SIZE), bool)
    h, w = frame.shape[:2]
    for oy in range(BADGE_SIZE):
        for ox in range(BADGE_SIZE):
            if (ox - r) ** 2 + (oy - r) ** 2 > BADGE_DIGIT_R**2:
                continue
            px = int(round(cx + (dx + ox - r) * scale))
            py = int(round(cy + (dy + oy - r) * scale))
            if 0 <= py < h and 0 <= px < w and frame[py, px].min() > white:
                out[oy, ox] = True
    return out


def _iou(a, b):
    return float((a & b).sum() / max(1, (a | b).sum()))


def read_badge(frame, power_box, width, height, templates=None):
    """
    读战力数字左上方蓝圈里的椎数：0 表示「—」，None 表示没找到蓝圈或没匹配上任何模板。
    """
    if frame is None:
        return None
    templates = templates if templates is not None else load_badge_templates()
    if not templates:
        return None
    scale = height / 768
    px, py = _center(power_box)
    disk = find_badge_disk(frame, px + BADGE_DX * width, py + BADGE_DY * height, scale)
    if disk is None:
        return None
    cx, cy = disk
    best, best_score = None, 0.0
    for digit, tpl in templates.items():
        score = max(_iou(badge_digit_mask(frame, cx, cy, scale, dx, dy), tpl) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        if score > best_score:
            best, best_score = digit, score
    return best if best_score >= BADGE_MIN_IOU else None


# ------------------------------------------------------------------ 地格
TILE_LOOSE = ((85, 30, 120), (125, 255, 255))  # 泛蓝的地格（含已站人的、颜色淡的）
TILE_STRICT = ((90, 90, 200), (125, 255, 255))  # 高亮的亮蓝地格，通常是选中卡片后可部署的空格


def find_tiles(frame, width, height, strict=False):
    """
    地图上的蓝色地格，返回 [{"center": (x, y), "bbox": (x, y, w, h), "sat": 平均饱和度}, ...]，先上后下、先左后右。
    strict=True 只取高亮的亮蓝地格。
    """
    if frame is None:
        return []
    lo, hi = TILE_STRICT if strict else TILE_LOOSE
    x0, y0, x1, y1 = (int(MAP_BOX[0] * width), int(MAP_BOX[1] * height), int(MAP_BOX[2] * width), int(MAP_BOX[3] * height))
    region = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    # 地格之间是白色细边（饱和度很低），不做闭运算，否则相邻地格会连成一块
    mask = cv2.inRange(hsv, lo, hi)
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    s = height / 768
    tiles = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        bx, by, bw, bh = stats[i, :4]
        if area < 800 * s * s or not (60 * s <= bw <= 260 * s) or not (40 * s <= bh <= 200 * s):
            continue
        cx, cy = x0 + bx + bw / 2, y0 + by + bh / 2
        comp = mask[by : by + bh, bx : bx + bw] > 0
        sat = float(hsv[by : by + bh, bx : bx + bw, 1][comp].mean()) if comp.any() else 0.0
        tiles.append({"center": (cx, cy), "bbox": (x0 + bx, y0 + by, int(bw), int(bh)), "sat": sat})
    tiles.sort(key=lambda t: (t["center"][1], t["center"][0]))
    return tiles


def merge_tiles(primary, secondary, min_dist=40):
    """primary 在前，secondary 里离 primary 任一中心不足 min_dist 的去重。"""
    out = list(primary)
    for t in secondary:
        if all((t["center"][0] - o["center"][0]) ** 2 + (t["center"][1] - o["center"][1]) ** 2 >= min_dist**2 for o in out):
            out.append(t)
    return out


def order_tiles(tiles, digit_boxes, height):
    """
    试点地格的顺序：没有单位编号压着的优先，其中颜色更饱和（蓝得更明显，通常是可部署的高亮格）的靠前。
    """
    free = empty_tiles(tiles, digit_boxes, height)
    free_ids = {id(t) for t in free}
    taken = [t for t in tiles if id(t) not in free_ids]
    key = lambda t: -t.get("sat", 0)
    return sorted(free, key=key) + sorted(taken, key=key)


def empty_tiles(tiles, digit_boxes, height):
    """去掉头顶有单位编号（1~4 的小白框）的地格；编号在地格上方约 0.5~1.3 个地格高处。"""
    out = []
    for t in tiles:
        bx, by, bw, bh = t["bbox"]
        occupied = False
        for d in digit_boxes:
            if not digit_re.match(d.name):
                continue
            dx, dy = _center(d)
            if bx - 0.1 * bw <= dx <= bx + 1.1 * bw and by - 1.3 * bh <= dy <= by + 0.6 * bh:
                occupied = True
                break
        if not occupied:
            out.append(t)
    return out


def make_check_frame(width, height, checks):
    """测试用：生成一张黑图并在给定点画橙色方块。"""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for x, y in checks:
        frame[max(0, y - 6) : y + 7, max(0, x - 6) : x + 7] = (0, 160, 255)
    return frame


# ---------------- 卡片头像识别（免点击认人） ----------------
# 卡片立绘区域相对战力数字中心：左右各 0.02 画面宽，上方 0.10h ~ 0.03h（避开左上角椎数圆标和右上角橙勾）
AVATAR_DX = 0.02
AVATAR_Y0, AVATAR_Y1 = -0.10, -0.03
AVATAR_REF = (52, 54)  # 统一缩放到的 (宽, 高)，1280x768 下正好是原尺寸
AVATAR_DIR = os.path.join("assets", "card_avatars")
AVATAR_THRESHOLD = 0.75
_name_ok = re.compile(r"^[一-鿿A-Za-z0-9\-·]{2,12}$")


def avatar_crop(frame, power_box, width, height, margin=0):
    """
    截取卡片立绘中间一块并缩放到固定尺寸，用来和模板比对。
    :param margin: 四周多截的像素（按 1280 宽的尺度），比对时用它容忍几个像素的定位偏差
    """
    px = power_box.x + power_box.width / 2
    py = power_box.y + power_box.height / 2
    scale = width / 1280
    m = margin * scale
    x0, x1 = int(px - AVATAR_DX * width - m), int(px + AVATAR_DX * width + m)
    y0, y1 = int(py + AVATAR_Y0 * height - m), int(py + AVATAR_Y1 * height + m)
    x0, y0 = max(x0, 0), max(y0, 0)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
        return None
    return cv2.resize(crop, (AVATAR_REF[0] + 2 * margin, AVATAR_REF[1] + 2 * margin), interpolation=cv2.INTER_AREA)


AVATAR_MARGIN = 8


def _imread_any(path):
    data = np.fromfile(path, dtype=np.uint8)  # cv2.imread 在 Windows 上读不了中文路径
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def _imwrite_any(path, img):
    ok, buf = cv2.imencode(".png", img)
    if ok:
        buf.tofile(path)
    return ok


class AvatarBook:
    """
    assets/card_avatars/<人形名>.png：每个人形一张卡片立绘模板。
    第一次见到某张卡片时点一下、OCR 左下角名字并自动存模板；以后扫描卡片直接比对立绘就知道是谁，不用再点。
    """

    def __init__(self, folder=AVATAR_DIR, threshold=AVATAR_THRESHOLD):
        self.folder = folder
        self.threshold = threshold
        self.templates = None

    def load(self):
        if self.templates is None:
            self.templates = {}
            if os.path.isdir(self.folder):
                for fn in os.listdir(self.folder):
                    stem, ext = os.path.splitext(fn)
                    if ext.lower() != ".png":
                        continue
                    img = _imread_any(os.path.join(self.folder, fn))
                    if img is not None and img.shape[:2] == (AVATAR_REF[1], AVATAR_REF[0]):
                        self.templates[stem] = img
        return self.templates

    def match(self, crop):
        """返回 (名字, 相似度)；没有模板或都不像时名字为 None。"""
        best, best_score = None, -1.0
        if crop is None:
            return None, 0.0
        for name, tpl in self.load().items():
            score = float(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best, best_score = name, score
        if best_score < self.threshold:
            return None, best_score
        return best, best_score

    def learn(self, name, crop):
        """名字合法且还没有模板时存一张；返回是否新存。"""
        if crop is None or not name or not _name_ok.match(name):
            return False
        if name in self.load():
            return False
        os.makedirs(self.folder, exist_ok=True)
        if _imwrite_any(os.path.join(self.folder, f"{name}.png"), crop):
            self.templates[name] = crop.copy()
            return True
        return False


def identify_cards(frame, cards, width, height, book):
    """给每张卡片填上 name / name_score（认不出为 None）。"""
    for c in cards:
        c["avatar"] = avatar_crop(frame, c["power_box"], width, height)
        crop = avatar_crop(frame, c["power_box"], width, height, margin=AVATAR_MARGIN)
        c["name"], c["name_score"] = book.match(crop)
    return cards
