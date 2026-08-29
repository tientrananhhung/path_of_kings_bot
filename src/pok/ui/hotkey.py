"""Global hotkey qua CGEventTap (listen-only).

Cần thiết vì bot CHIẾM CHUỘT VẬT LÝ — không thể bấm nút trên UI cùng máy trong
lúc bot chạy. Bàn phím vẫn dùng được bình thường.
  ⌃⌥⌘S  start/pause    ⌃⌥⌘K  KILL
  ⌃⌥⌘C  chụp frame     ⌃⌥⌘P  probe
"""
from __future__ import annotations

import threading
from typing import Callable

import Quartz

KEYCODES = {"s": 1, "k": 40, "c": 8, "p": 35}
NEED = (Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
        | Quartz.kCGEventFlagMaskCommand)


class HotkeyListener:
    def __init__(self, handlers: dict[str, Callable[[], None]]):
        self.handlers = handlers
        self._thread: threading.Thread | None = None
        self._loop = None
        self.error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()

    def _cb(self, proxy, etype, event, refcon):  # noqa: ANN001
        try:
            if etype == Quartz.kCGEventKeyDown:
                flags = Quartz.CGEventGetFlags(event)
                if (flags & NEED) == NEED:
                    code = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode)
                    for name, kc in KEYCODES.items():
                        if code == kc and name in self.handlers:
                            threading.Thread(target=self.handlers[name],
                                             daemon=True).start()
                            return None       # chặn không cho lọt xuống app
        except Exception:
            pass
        return event

    def _run(self) -> None:
        try:
            tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionDefault,
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
                self._cb, None)
            if not tap:
                self.error = "CGEventTapCreate thất bại (thiếu quyền Accessibility?)"
                return
            src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            self._loop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(self._loop, src,
                                      Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(tap, True)
            Quartz.CFRunLoopRun()
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
