"""推图本地通关记录：关卡一次性通关后写入 configs/clear_map_progress.json，后续直接跳过。

结构：
{
  "3.0缺位拟合|普通": {"cleared": ["SL-3-1", "3-1"], "updated": "2026-10-18 17:00:00"}
}
键 = 章节标题 + 难度；关卡名在同一章同一难度内唯一。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime

DEFAULT_PATH = os.path.join("configs", "clear_map_progress.json")


class ProgressStore:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def cleared(self, key: str) -> set[str]:
        return set(self._data.get(key, {}).get("cleared", []))

    def is_cleared(self, key: str, name: str) -> bool:
        return name in self.cleared(key)

    def mark(self, key: str, name: str) -> bool:
        """记录通关，返回是否为新增。"""
        with self._lock:
            entry = self._data.setdefault(key, {"cleared": []})
            if name in entry["cleared"]:
                return False
            entry["cleared"].append(name)
            entry["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save()
            return True
