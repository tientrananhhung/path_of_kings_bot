"""Actuator — bắn input vào iPhone Mirroring.

Đã kiểm chứng bằng poc/poc1d_live_test.py trên mirroring ĐANG kết nối:
  CGEventPost -> kCGHIDEventTap : swipe 7.87%, tap 74.26% đổi màn  -> ĂN
  CGEventPost -> kCGSessionEventTap: swipe 22.09%                  -> ăn
  CGEventPostToPid              : 1.60% = nhiễu                    -> KHÔNG ăn
  AppleScript System Events     : 0.00%                            -> KHÔNG ăn
=> chỉ dùng kCGHIDEventTap. PostToPid bỏ qua window server nên vô dụng.

Mọi hành động phát ActionEvent lên EventBus (kể cả khi bị chặn) để web overlay
vẽ được — kể cả vẽ hành động bị SafetyGuard loại.
"""
from __future__ import annotations

import time

import Quartz

from ..store.events import EventBus
from .coords import rel_to_screen
from .safety import SafetyGuard
from .window import WindowInfo, activate, is_frontmost

HID = Quartz.kCGHIDEventTap


def _post(ev_type, x: float, y: float) -> None:
    Quartz.CGEventPost(HID, Quartz.CGEventCreateMouseEvent(
        None, ev_type, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft))


class Actuator:
    def __init__(self, guard: SafetyGuard, bus: EventBus):
        self.guard = guard
        self.bus = bus
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def ensure_focus(self, win: WindowInfo) -> bool:
        """Đưa cửa sổ iPhone Mirroring lên trước. Trả True nếu đã phải activate.

        ĐO THẬT (phiên data/sessions/20260830-052421, 16/16 hành động): mỗi
        hành động tốn thêm **1.27-1.37 giây** trước khi chuột chạm màn, HẰNG SỐ
        như nhau cho tap (sleep lý thuyết 0.13s) lẫn swipe (0.72s) -> không phải
        do độ dài cú vuốt mà là phần mở màn cố định này.

        Trong 1.3 giây đó mới giải thích được 0.26s: `activate()` đo được 8ms,
        cộng `sleep(0.25)` dưới đây. Phần ~1.0s còn lại CHƯA rõ — trường `ms`
        trong event `action` sinh ra để đo nốt, đừng bỏ nó đi.

        Lý do phải gọi từ đầu tick chứ không để nằm giữa "quyết định" và "chạm
        màn": 1.3 giây đủ để game sang màn khác, cú swipe trái rơi vào màn đang
        chạy. Gọi lại ở đây vẫn giữ làm lưới an toàn — đã frontmost thì
        `is_frontmost` tốn 0.4ms.
        """
        if is_frontmost(win.pid):
            return False
        activate(win.pid)
        time.sleep(0.25)
        return True

    def _emit(self, kind: str, points_rel: list[tuple[float, float]],
              duration_ms: int, source: str, label: str,
              blocked: bool, reason: str | None, frame_id: int | None,
              t0: float | None = None) -> None:
        self.bus.publish({
            "type": "action",
            "id": self._next_id(),
            "frame_id": frame_id,
            "kind": kind,
            "points": [[round(p[0], 4), round(p[1], 4)] for p in points_rel],
            "duration_ms": duration_ms,
            # ms THẬT từ lúc bắt đầu tới lúc nhả chuột — khác xa duration_ms khi
            # phải activate cửa sổ. Không có số này thì không cách nào biết hành
            # động rơi vào màn nào; đã phải suy ngược từ khoảng cách giữa các
            # event classify để tìm ra bug 1.3 giây.
            "ms": round((time.perf_counter() - t0) * 1000) if t0 else None,
            "source": source,
            "label": label,
            "blocked": blocked,
            "block_reason": reason,
        })

    # ------------------------------------------------------------------ tap
    def tap(self, rel: tuple[float, float], win: WindowInfo, *,
            source: str = "rule", label: str = "", hold_ms: int = 80,
            frame_id: int | None = None) -> bool:
        t0 = time.perf_counter()
        pt = rel_to_screen(rel, win)
        v = self.guard.check_action(pt, win)
        if not v.allowed:
            self._emit("tap", [rel], hold_ms, source, label, True, v.reason,
                       frame_id, t0)
            return False
        hold_ms = self.guard.clamp_hold_ms(hold_ms)
        self.ensure_focus(win)
        _post(Quartz.kCGEventMouseMoved, *pt)
        time.sleep(0.05)
        _post(Quartz.kCGEventLeftMouseDown, *pt)
        time.sleep(hold_ms / 1000.0)
        _post(Quartz.kCGEventLeftMouseUp, *pt)
        self.guard.note_action()
        self._emit("tap", [rel], hold_ms, source, label, False, None, frame_id, t0)
        return True

    # ---------------------------------------------------------------- swipe
    def swipe(self, rel_from: tuple[float, float], rel_to: tuple[float, float],
              win: WindowInfo, *, duration_ms: int = 220, steps: int = 18,
              hold_end_ms: int = 80, source: str = "rule", label: str = "",
              frame_id: int | None = None) -> bool:
        """hold_end_ms: giữ chuột ở điểm cuối trước khi nhả.

        Đo thật trên màn quyết định PVP RAID của Path of Kings: swipe 260ms và
        400ms KHÔNG commit lựa chọn (animation trả về), 600ms thì commit. Game
        cần drag chậm hơn / có thời gian dừng ở cuối.
        """
        t0 = time.perf_counter()
        p0 = rel_to_screen(rel_from, win)
        p1 = rel_to_screen(rel_to, win)
        for pt in (p0, p1):
            v = self.guard.check_action(pt, win)
            if not v.allowed:
                self._emit("swipe", [rel_from, rel_to], duration_ms, source,
                           label, True, v.reason, frame_id, t0)
                return False
        self.ensure_focus(win)

        # điểm nội suy THẬT — web overlay vẽ đúng những điểm này, không phải
        # đường thẳng giả định
        pts_rel: list[tuple[float, float]] = []
        _post(Quartz.kCGEventMouseMoved, *p0)
        time.sleep(0.08)
        _post(Quartz.kCGEventLeftMouseDown, *p0)
        time.sleep(0.10)
        per = max(0.004, (duration_ms / 1000.0) / steps)
        for i in range(1, steps + 1):
            t = i / steps
            x = p0[0] + (p1[0] - p0[0]) * t
            y = p0[1] + (p1[1] - p0[1]) * t
            _post(Quartz.kCGEventLeftMouseDragged, x, y)
            pts_rel.append(((x - win.x) / win.w, (y - win.y) / win.h))
            time.sleep(per)
        time.sleep(max(0.0, hold_end_ms / 1000.0))
        _post(Quartz.kCGEventLeftMouseUp, *p1)
        self.guard.note_action()
        self._emit("swipe", [rel_from] + pts_rel, duration_ms, source, label,
                   False, None, frame_id, t0)
        return True

    # ----------------------------------------------------------------- hold
    def hold(self, rel: tuple[float, float], win: WindowInfo, *,
             ms: int = 200, source: str = "rule", label: str = "",
             frame_id: int | None = None) -> bool:
        return self.tap(rel, win, source=source, label=label,
                        hold_ms=ms, frame_id=frame_id)

    # -------------------------------------------------------------- gesture
    def home_gesture(self, win: WindowInfo, *, source: str = "watchdog",
                     label: str = "gesture Home") -> bool:
        """Swipe từ mép dưới lên = về Home Screen của iOS."""
        return self.swipe((0.5, 0.995), (0.5, 0.70), win,
                          duration_ms=260, steps=20, source=source, label=label)
