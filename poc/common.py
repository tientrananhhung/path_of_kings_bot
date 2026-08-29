"""Tiện ích dùng chung cho các script POC."""
import os
import subprocess
import sys

import Quartz

# iPhone Mirroring có tên localized theo ngôn ngữ hệ thống ("Phản chiếu iPhone"
# trên máy tiếng Việt), nên KHÔNG dò theo tên. Dò theo bundle identifier.
BUNDLE_ID = os.environ.get("POC_BUNDLE", "com.apple.ScreenContinuity")
OWNER_HINT = os.environ.get("POC_OWNER")  # tuỳ chọn: ép dò theo tên app, để smoke-test


def _pid_for_bundle(bundle_id):
    from AppKit import NSWorkspace
    for a in NSWorkspace.sharedWorkspace().runningApplications():
        if (a.bundleIdentifier() or "") == bundle_id:
            return int(a.processIdentifier()), str(a.localizedName())
    return None, None


def find_window():
    """Trả về dict thông tin cửa sổ iPhone Mirroring, hoặc None nếu không thấy.

    Dùng CGWindowListCopyWindowInfo thay vì nhận diện viền bằng OpenCV như
    plan_bot.md đề xuất: chính xác tuyệt đối, tức thời, không cần train gì.
    """
    if OWNER_HINT:
        want_pid, app_name = None, OWNER_HINT
    else:
        want_pid, app_name = _pid_for_bundle(BUNDLE_ID)
        if want_pid is None:
            return None

    opts = (Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements)
    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        if OWNER_HINT:
            if w.get("kCGWindowOwnerName") != OWNER_HINT:
                continue
        elif int(w.get("kCGWindowOwnerPID", -1)) != want_pid:
            continue

        b = w.get("kCGWindowBounds") or {}
        # Bỏ cửa sổ phụ nhỏ (shadow layer, tooltip); giữ cửa sổ to nhất.
        if b.get("Width", 0) < 150 or b.get("Height", 0) < 250:
            continue
        cand = {
            "id": int(w["kCGWindowNumber"]),
            "pid": int(w.get("kCGWindowOwnerPID", 0)),
            "name": w.get("kCGWindowOwnerName") or app_name,
            "x": int(b["X"]), "y": int(b["Y"]),
            "w": int(b["Width"]), "h": int(b["Height"]),
        }
        if best is None or cand["w"] * cand["h"] > best["w"] * best["h"]:
            best = cand
    return best


def require_window():
    win = find_window()
    if not win:
        print("[X] Không tìm thấy cửa sổ iPhone Mirroring "
              f"(bundle {BUNDLE_ID}).")
        print("    Hãy mở iPhone Mirroring, kết nối xong iPhone, rồi chạy lại.")
        sys.exit(2)
    print(f"[OK] Cửa sổ '{win['name']}': id={win['id']} pid={win['pid']} "
          f"bounds=({win['x']},{win['y']},{win['w']},{win['h']}) [đơn vị: point]")
    return win


def check_permissions():
    """In trạng thái 2 quyền bắt buộc. Trả về (screen_ok, ax_ok)."""
    screen_ok = bool(Quartz.CGPreflightScreenCaptureAccess())
    try:
        from ApplicationServices import AXIsProcessTrusted
        ax_ok = bool(AXIsProcessTrusted())
    except Exception:
        ax_ok = None

    print(f"[{'OK' if screen_ok else 'X '}] Screen Recording  : {screen_ok}")
    print(f"[{'OK' if ax_ok else 'X '}] Accessibility     : {ax_ok}")
    if not screen_ok or not ax_ok:
        print("    Cấp quyền cho ứng dụng Terminal đang chạy script này tại:")
        print("    System Settings > Privacy & Security > Screen & System Audio Recording")
        print("    System Settings > Privacy & Security > Accessibility")
        print("    (Sau khi cấp quyền, phải QUIT hẳn Terminal rồi mở lại.)")
    return screen_ok, ax_ok


def activate(pid):
    """Đưa cửa sổ của pid lên foreground (iPhone Mirroring cần được focus)."""
    from AppKit import NSRunningApplication
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None:
        app.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps
        return
    subprocess.run(
        ["osascript", "-e",
         f'tell application "System Events" to set frontmost of '
         f'(first process whose unix id is {pid}) to true'],
        capture_output=True,
    )
