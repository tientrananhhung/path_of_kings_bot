"""Watchdog — 4 ca khôi phục. Cả 4 đều ĐÃ XẢY RA THẬT khi làm POC.

  PAUSE     iPhone Mirroring tự ngắt khi chạm vào iPhone  -> tap nút "Kết nối"
  JIGGLE    giữ chuột lâu trên Home Screen                -> tap nút "Xong"
  SPOTLIGHT tap sai làm mở Spotlight                      -> gesture Home
  APPSTORE  quảng cáo đẩy sang App Store/Safari           -> gesture Home + mở lại game
"""
from __future__ import annotations

import time

from ..perception.ocr import find_any
from ..perception.types import ClassifyResult, ScreenKind

CONNECT_WORDS = ["kết nối", "connect"]
DONE_WORDS = ["xong", "done"]


class Watchdog:
    def __init__(self, actuator, bus, stats, game_app_label: str = "Path of Kings"):
        self.act = actuator
        self.bus = bus
        self.stats = stats
        self.game_app_label = game_app_label
        self.last_action = 0.0
        self.cooldown = 2.5

    def _cool(self) -> bool:
        if time.time() - self.last_action < self.cooldown:
            return False
        self.last_action = time.time()
        return True

    def handle(self, res: ClassifyResult, win, bgr) -> str | None:
        """Trả tên ca đã xử lý, hoặc None nếu không phải việc của watchdog."""
        h, w = bgr.shape[:2]

        if res.kind is ScreenKind.PAUSE:
            if not self._cool():
                return "pause"
            hits = find_any(res.texts, CONNECT_WORDS)
            if hits:
                t = hits[0]
                self.act.tap((t.cx / w, t.cy / h), win, source="watchdog",
                             label='tap "Kết nối"')
            else:
                self.bus.log("warn", "màn pause nhưng không tìm ra nút Kết nối")
            self.stats.note_watchdog("pause")
            return "pause"

        if res.kind is ScreenKind.JIGGLE:
            if not self._cool():
                return "jiggle"
            hits = find_any(res.texts, DONE_WORDS)
            if hits:
                t = hits[0]
                self.act.tap((t.cx / w, t.cy / h), win, source="watchdog",
                             label='tap "Xong" (thoát jiggle mode)')
            self.stats.note_watchdog("jiggle")
            return "jiggle"

        if res.kind is ScreenKind.SPOTLIGHT:
            if not self._cool():
                return "spotlight"
            self.act.home_gesture(win, label="thoát Spotlight")
            self.stats.note_watchdog("spotlight")
            return "spotlight"

        if res.kind is ScreenKind.APPSTORE:
            if not self._cool():
                return "appstore"
            self.act.home_gesture(win, label="thoát App Store")
            self.stats.note_watchdog("appstore")
            return "appstore"

        return None

    def open_game(self, res: ClassifyResult, win, bgr) -> bool:
        """Ở Home Screen: tìm nhãn icon game bằng OCR rồi tap."""
        h, w = bgr.shape[:2]
        hits = find_any(res.texts, [self.game_app_label])
        if not hits:
            self.bus.log("warn", f"không thấy icon '{self.game_app_label}' trên Home Screen")
            return False
        t = hits[0]
        # nhãn nằm DƯỚI icon -> tap lên trên nhãn ~34 point
        return self.act.tap(((t.cx) / w, max(0.0, (t.cy - 34) / h)), win,
                            source="watchdog", label=f"mở {self.game_app_label}")
