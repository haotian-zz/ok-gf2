"""
全局「阵容与助战」配置：所有会进部署界面的任务共用一套（推图、以后可能的活动/日常）。
任务里只留「借好友助战」开关，具体借谁、最低几椎、用哪个编队都在这里改。
"""

from ok.util.config import ConfigOption

LINEUP_OPTION_NAME = "阵容与助战"
KEY_PRESET = "编队名"
KEY_ROLE = "助战角色"
KEY_MIN_BADGE = "助战最低椎数"
KEY_FALLBACK = "找不到就借战力最高"

lineup_option = ConfigOption(
    LINEUP_OPTION_NAME,
    {
        KEY_PRESET: "编队1",
        KEY_ROLE: "威玛西娜",
        KEY_MIN_BADGE: 6,
        KEY_FALLBACK: True,
    },
    description="进部署界面后先切到这个整备室编队，再按下面的规则借好友助战；留空编队名就不切编队",
    config_description={
        KEY_PRESET: "整备室编队的名字（游戏里可自定义，默认 编队1）。编队最多 6 人，关卡只能上 4 人时就用前 4 个",
        KEY_ROLE: "要借的助战角色名，须与游戏内显示一致，如 威玛西娜",
        KEY_MIN_BADGE: "卡片左上角蓝圈里的椎数至少要多少，默认 6",
        KEY_FALLBACK: "没有椎数达标的指定角色时，切到「全部」按战力从高到低借第一个",
    },
    config_type={
        KEY_PRESET: {"type": "line_edit"},
        KEY_ROLE: {"type": "line_edit"},
        KEY_MIN_BADGE: {"min": 0, "max": 6},
    },
)
