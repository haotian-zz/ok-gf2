"""
全局「阵容与助战」配置：所有会进部署界面的任务共用一套（推图、以后可能的活动/日常）。
任务里只留「借好友助战」开关，具体借谁、最低几椎、用哪个编队都在这里改。
"""

from ok.util.config import ConfigOption

LINEUP_OPTION_NAME = "阵容与助战"
KEY_PRESET = "编队名"
KEY_PRESET_ARENA = "竞技场编队"
KEY_PRESET_STAMINA = "体力本编队"
KEY_PRESET_GUILD = "班组编队"
KEY_PRESET_ACTIVITY = "活动编队"
# 关卡类型 -> 用哪个编队设置；没列出来的类型（推图等）和留空的都用「编队名」
PRESET_KEY_BY_KIND = {
    "竞技场": KEY_PRESET_ARENA,
    "体力本": KEY_PRESET_STAMINA,
    "班组": KEY_PRESET_GUILD,
    "活动": KEY_PRESET_ACTIVITY,
}
KEY_ROLE = "助战角色"
KEY_MIN_BADGE = "助战最低椎数"
KEY_FALLBACK = "找不到就借战力最高"

lineup_option = ConfigOption(
    LINEUP_OPTION_NAME,
    {
        KEY_PRESET: "编队1",
        KEY_PRESET_ARENA: "",
        KEY_PRESET_STAMINA: "",
        KEY_PRESET_GUILD: "",
        KEY_PRESET_ACTIVITY: "",
        KEY_ROLE: "威玛西娜",
        KEY_MIN_BADGE: 6,
        KEY_FALLBACK: True,
    },
    description="所有会进部署界面的任务共用：先切到对应关卡类型的整备室编队并补满，推图还会按下面的规则借好友助战",
    config_description={
        KEY_PRESET: "默认编队：推图以及下面没单独填的关卡类型都用它（游戏里可自定义名字，默认 编队1）。留空就不切编队，只补满空位",
        KEY_PRESET_ARENA: "一键日常「竞技场」（实兵演习）用的编队，留空用默认编队",
        KEY_PRESET_STAMINA: "一键日常「自动刷体力」手动挑战时用的编队，留空用默认编队",
        KEY_PRESET_GUILD: "一键日常「班组」要务用的编队，留空用默认编队",
        KEY_PRESET_ACTIVITY: "一键日常「活动自律」用的编队，留空用默认编队",
        KEY_ROLE: "要借的助战角色名，须与游戏内显示一致，如 威玛西娜",
        KEY_MIN_BADGE: "卡片左上角蓝圈里的椎数至少要多少，默认 6",
        KEY_FALLBACK: "没有椎数达标的指定角色时，切到「全部」按战力从高到低借第一个",
    },
    config_type={
        KEY_PRESET: {"type": "line_edit"},
        KEY_PRESET_ARENA: {"type": "line_edit"},
        KEY_PRESET_STAMINA: {"type": "line_edit"},
        KEY_PRESET_GUILD: {"type": "line_edit"},
        KEY_PRESET_ACTIVITY: {"type": "line_edit"},
        KEY_ROLE: {"type": "line_edit"},
        KEY_MIN_BADGE: {"min": 0, "max": 6},
    },
)


def preset_name_for_kind(cfg, kind):
    """kind（竞技场/体力本/班组/活动/None）对应的编队名；该类型没填就退回「编队名」。"""
    key = PRESET_KEY_BY_KIND.get(kind)
    name = (cfg.get(key) or "").strip() if key else ""
    return name or (cfg.get(KEY_PRESET) or "").strip()
