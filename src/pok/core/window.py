"""Tìm cửa sổ iPhone Mirroring.

Tên app bị localized theo ngôn ngữ hệ thống ("Phản chiếu iPhone" trên máy tiếng
Việt) nên KHÔNG dò theo tên. Dò theo bundle identifier.
"""
from __future__ import annotations

from dataclasses import dataclass

import Quartz


@dataclass(frozen=True)
class WindowInfo:
    id: int
    pid: int
    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


def _pid_for_bundle(bundle_id: str) -> tuple[int | None, str | None]:
    from AppKit import NSWorkspace
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if (app.bundleIdentifier() or "") == bundle_id:
            return int(app.processIdentifier()), str(app.localizedName())
    return None, None


def find(bundle_id: str) -> WindowInfo | None:
    pid, app_name = _pid_for_bundle(bundle_id)
    if pid is None:
        return None
    opts = (Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements)
    best: WindowInfo | None = None
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        if int(w.get("kCGWindowOwnerPID", -1)) != pid:
            continue
        b = w.get("kCGWindowBounds") or {}
        # bỏ cửa sổ phụ nhỏ (shadow layer, tooltip)
        if b.get("Width", 0) < 150 or b.get("Height", 0) < 250:
            continue
        cand = WindowInfo(
            id=int(w["kCGWindowNumber"]), pid=pid,
            name=w.get("kCGWindowOwnerName") or app_name or "?",
            x=int(b["X"]), y=int(b["Y"]), w=int(b["Width"]), h=int(b["Height"]),
        )
        if best is None or cand.w * cand.h > best.w * best.h:
            best = cand
    return best


def activate(pid: int) -> None:
    """Đưa app lên foreground — iPhone Mirroring cần được focus để nhận input."""
    from AppKit import NSRunningApplication
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None:
        app.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps


def is_frontmost(pid: int) -> bool:
    """Hỏi THẲNG window server. KHÔNG dùng NSWorkspace.

    Bug đã gặp thật và đã đo: `NSWorkspace.frontmostApplication()` không bao giờ
    cập nhật trong tiến trình không bơm run loop (engine là thread thuần, không
    có NSApplication). Đo trực tiếp:

        activate(iPhone) -> True, 8ms
        +0.25s .. +1.50s: window server nói 'Phản chiếu iPhone'
                          NSWorkspace  vẫn nói 'Claude'  (mãi mãi)

    Hậu quả: `is_frontmost` luôn False -> mỗi hành động lại activate + sleep
    0.25s vô ích, và khi biến nó thành điều kiện chặn ở đầu tick thì bot đứng
    im hoàn toàn (tick nào cũng tưởng "vừa mới activate").

    Danh sách cửa sổ on-screen xếp từ TRƯỚC ra SAU; cửa sổ layer 0 đầu tiên là
    của app đang ở trên cùng. Dữ liệu mới mỗi lần gọi, ~4ms.
    """
    opts = (Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements)
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        if int(w.get("kCGWindowLayer", 0) or 0) != 0:
            continue          # menu bar, Control Center... không phải app
        return int(w.get("kCGWindowOwnerPID", -1) or -1) == pid
    return False
