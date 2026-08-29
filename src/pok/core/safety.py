"""SafetyGuard — chặn cứng. Mọi hành động phải qua đây trước khi tới Actuator."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from .coords import inside
from .window import WindowInfo


@dataclass
class Verdict:
    allowed: bool
    reason: str | None = None


class SafetyGuard:
    def __init__(self, cfg: dict):
        s = cfg.get("safety", {})
        self.max_taps_per_min = int(s.get("max_taps_per_min", 90))
        self.max_hold_ms = int(s.get("max_hold_ms", 250))
        self.max_session_minutes = int(s.get("max_session_minutes", 240))
        self.max_consecutive_stuck = int(s.get("max_consecutive_stuck", 5))
        self.forbidden_zones = [tuple(z) for z in s.get("forbidden_zones", [])]
        self._taps: deque[float] = deque()
        self.session_started = time.time()
        self.consecutive_stuck = 0
        self.killed = False

    # --- kill switch ---
    def kill(self) -> None:
        self.killed = True

    def reset(self) -> None:
        self.killed = False
        self._taps.clear()
        self.session_started = time.time()
        self.consecutive_stuck = 0

    # --- kiểm tra ---
    def check_action(self, screen_pt: tuple[float, float],
                     win: WindowInfo) -> Verdict:
        if self.killed:
            return Verdict(False, "killed")
        if not inside(screen_pt, win):
            return Verdict(False, "out_of_bounds")
        rx = (screen_pt[0] - win.x) / win.w
        ry = (screen_pt[1] - win.y) / win.h
        for (x0, y0, x1, y1) in self.forbidden_zones:
            if x0 <= rx <= x1 and y0 <= ry <= y1:
                return Verdict(False, "forbidden_zone")
        self._prune()
        if len(self._taps) >= self.max_taps_per_min:
            return Verdict(False, "rate_limit")
        return Verdict(True)

    def note_action(self) -> None:
        self._taps.append(time.time())

    def clamp_hold_ms(self, ms: int) -> int:
        """Giới hạn thời gian giữ chuột — vượt ngưỡng iOS vào jiggle mode."""
        return min(int(ms), self.max_hold_ms)

    def session_expired(self) -> bool:
        return (time.time() - self.session_started) > self.max_session_minutes * 60

    def note_stuck(self) -> bool:
        self.consecutive_stuck += 1
        return self.consecutive_stuck >= self.max_consecutive_stuck

    def clear_stuck(self) -> None:
        self.consecutive_stuck = 0

    def taps_per_min(self) -> int:
        self._prune()
        return len(self._taps)

    def _prune(self) -> None:
        cutoff = time.time() - 60.0
        while self._taps and self._taps[0] < cutoff:
            self._taps.popleft()
