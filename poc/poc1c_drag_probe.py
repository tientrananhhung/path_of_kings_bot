#!/usr/bin/env python
"""POC #1c — synthetic mouse-down/drag/up có tới được cửa sổ iPhone Mirroring không?

Ưu điểm so với poc1_click.py: KHÔNG so ảnh. Đo trực tiếp bounds cửa sổ qua
CGWindowListCopyWindowInfo -> không thể bị nhiễu bởi con trỏ chuột, animation,
hay việc nút đích đang vô hiệu. Nếu cửa sổ dịch chuyển đúng delta yêu cầu thì
chuỗi event mouseDown -> mouseDragged -> mouseUp đã được xử lý thật.

Tự trả cửa sổ về đúng vị trí cũ khi xong (kể cả khi lỗi).

Hạn chế cần biết: kéo cửa sổ do AppKit/window server xử lý. Test này chứng minh
event tới được CỬA SỔ của app, chưa chứng minh iPhone Mirroring chuyển tiếp tap
xuống iPhone — muốn chốt điều đó phải test khi mirroring đang kết nối thật.

Chạy:  ./.venv/bin/python poc/poc1c_drag_probe.py
"""
import os
import sys
import time

import Quartz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import activate, check_permissions, find_window, require_window  # noqa: E402

DELTA = (60, 40)   # dịch bao nhiêu point để thử
STEPS = 12


def post(ev_type, x, y, tap=Quartz.kCGHIDEventTap):
    ev = Quartz.CGEventCreateMouseEvent(
        None, ev_type, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(tap, ev)


def drag(x0, y0, x1, y1, tap):
    post(Quartz.kCGEventMouseMoved, x0, y0, tap)
    time.sleep(0.12)
    post(Quartz.kCGEventLeftMouseDown, x0, y0, tap)
    time.sleep(0.18)
    for i in range(1, STEPS + 1):
        post(Quartz.kCGEventLeftMouseDragged,
             x0 + (x1 - x0) * i / STEPS, y0 + (y1 - y0) * i / STEPS, tap)
        time.sleep(0.02)
    time.sleep(0.15)
    post(Quartz.kCGEventLeftMouseUp, x1, y1, tap)
    time.sleep(0.45)


def try_grab(win, gx, gy, tap, label):
    """Thử kéo từ điểm (gx,gy) offset trong cửa sổ. Trả về delta thực tế."""
    x0, y0 = win["x"] + gx, win["y"] + gy
    before = (win["x"], win["y"])
    drag(x0, y0, x0 + DELTA[0], y0 + DELTA[1], tap)
    now = find_window()
    if not now:
        return None, None
    moved = (now["x"] - before[0], now["y"] - before[1])
    print(f"    {label:<34} delta = {moved}")
    return moved, now


def restore_via_ax(pid, x, y):
    """Đặt lại vị trí cửa sổ chính xác bằng Accessibility API.

    Kéo chuột thường lệch 1-2 point vì làm tròn, nên dùng AX để trả về đúng.
    """
    try:
        import ApplicationServices as AS
        app = AS.AXUIElementCreateApplication(pid)
        err, wins = AS.AXUIElementCopyAttributeValue(app, "AXWindows", None)
        if err != 0 or not wins:
            return False
        pos = AS.AXValueCreate(AS.kAXValueCGPointType, Quartz.CGPointMake(x, y))
        return AS.AXUIElementSetAttributeValue(wins[0], "AXPosition", pos) == 0
    except Exception:
        return False


def restore(target_x, target_y, tap, pid=None):
    """Kéo cửa sổ về đúng vị trí ban đầu; chốt lại bằng AX cho khớp tuyệt đối."""
    for _ in range(3):
        now = find_window()
        if not now or (now["x"] == target_x and now["y"] == target_y):
            return True
        dx, dy = target_x - now["x"], target_y - now["y"]
        gx, gy = now["x"] + now["w"] // 2, now["y"] + 8
        drag(gx, gy, gx + dx, gy + dy, tap)
    now = find_window()
    if now and (now["x"] != target_x or now["y"] != target_y) and pid:
        restore_via_ax(pid, target_x, target_y)
        time.sleep(0.3)
        now = find_window()
    return bool(now and abs(now["x"] - target_x) <= 1 and abs(now["y"] - target_y) <= 1)


def main():
    print("=" * 74)
    print("POC #1c — SYNTHETIC DRAG: đo bounds cửa sổ, không so ảnh")
    print("=" * 74)
    screen_ok, ax_ok = check_permissions()
    if not ax_ok:
        print("!! DỪNG: thiếu Accessibility -> event bị chặn ngay từ đầu.")
        sys.exit(1)
    print()
    win = require_window()
    home = (win["x"], win["y"])
    activate(win["pid"])
    time.sleep(0.8)

    # Không biết chắc chỗ nào kéo được (cửa sổ iPhone Mirroring không có title
    # bar thường), nên thử vài điểm bám: sát mép trên, mép trên-trái, mép dưới.
    grabs = [("mép trên, giữa", win["w"] // 2, 6),
             ("mép trên, lệch trái", 40, 6),
             ("mép trái, giữa", 4, win["h"] // 2),
             ("mép dưới, giữa", win["w"] // 2, win["h"] - 6)]
    taps = [("HID tap", Quartz.kCGHIDEventTap),
            ("Session tap", Quartz.kCGSessionEventTap)]

    ok_any = False
    try:
        for tap_name, tap in taps:
            print(f"\n  [{tap_name}]")
            for label, gx, gy in grabs:
                cur = find_window()
                if not cur:
                    print("    cửa sổ biến mất, dừng.")
                    break
                moved, _ = try_grab(cur, gx, gy, tap, label)
                if moved and (abs(moved[0]) > 3 or abs(moved[1]) > 3):
                    print(f"    -> KÉO ĐƯỢC. Event tới được cửa sổ qua {tap_name}.")
                    ok_any = True
                    restore(*home, tap, win["pid"])
                    break
            if ok_any:
                break
    finally:
        back = restore(*home, Quartz.kCGHIDEventTap, win["pid"])
        now = find_window()
        print(f"\n  trả cửa sổ về {home}: {'OK' if back else 'THẤT BẠI'} "
              f"(hiện tại {(now['x'], now['y']) if now else None})")

    print("\n" + "=" * 74)
    if ok_any:
        print("KẾT LUẬN: synthetic mouse down/drag/up ĐƯỢC XỬ LÝ.")
        print("  Chuỗi event CGEventPost tới được cửa sổ iPhone Mirroring.")
        print("  CHƯA chốt được việc app chuyển tiếp tap xuống iPhone — muốn chốt")
        print("  phải test lúc mirroring đang kết nối (khoá iPhone, đừng chạm vào).")
    else:
        print("KẾT LUẬN: không kéo được cửa sổ bằng synthetic event.")
        print("  Có thể do không tìm ra điểm bám đúng, chưa hẳn là bị chặn.")
        print("  Chạy lại poc1_click.py khi mirroring kết nối thật để chốt.")
    print("=" * 74)


if __name__ == "__main__":
    main()
