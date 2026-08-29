#!/usr/bin/env python
"""POC #1d — CHỐT BLOCKER #1: iPhone Mirroring có chuyển tiếp synthetic input
xuống iPhone thật không?

Chỉ chạy được khi mirroring ĐANG KẾT NỐI (chạy poc/state.py để kiểm tra).

Test đúng 2 thao tác mà bot cần: SWIPE ngang và TAP.
Sau mỗi bước tự khôi phục trạng thái (swipe ngược lại / về Home Screen).

Backend chụp là CGWindowListCreateImage — chụp riêng cửa sổ, KHÔNG vẽ con trỏ,
nên diff before/after không bị dương tính giả bởi việc con trỏ dịch chuyển.
"""
import os
import subprocess
import sys
import time

import numpy as np
import Quartz
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import activate, check_permissions, require_window  # noqa: E402
from poc2_capture import bk_cgwindowlist  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
SETTLE = 1.5
HOLD = 0.10


# ------------------------------------------------------------- primitives
def post(t, x, y, tap):
    Quartz.CGEventPost(tap, Quartz.CGEventCreateMouseEvent(
        None, t, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft))


def post_pid(t, x, y, pid):
    Quartz.CGEventPostToPid(pid, Quartz.CGEventCreateMouseEvent(
        None, t, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft))


def cg_swipe(x0, y0, x1, y1, tap, steps=18, poster=None, arg=None):
    p = poster or (lambda t, x, y: post(t, x, y, tap))
    p(Quartz.kCGEventMouseMoved, x0, y0)
    time.sleep(0.10)
    p(Quartz.kCGEventLeftMouseDown, x0, y0)
    time.sleep(0.12)
    for i in range(1, steps + 1):
        p(Quartz.kCGEventLeftMouseDragged,
          x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        time.sleep(0.012)
    time.sleep(0.10)
    p(Quartz.kCGEventLeftMouseUp, x1, y1)


def cg_click(x, y, tap):
    post(Quartz.kCGEventMouseMoved, x, y, tap)
    time.sleep(0.08)
    post(Quartz.kCGEventLeftMouseDown, x, y, tap)
    time.sleep(HOLD)
    post(Quartz.kCGEventLeftMouseUp, x, y, tap)


# ------------------------------------------------------------------ utils
def diff_pct(a, b):
    ga = np.asarray(Image.fromarray(a[:, :, :3]).convert("L").resize((180, 380)), float)
    gb = np.asarray(Image.fromarray(b[:, :, :3]).convert("L").resize((180, 380)), float)
    return float((np.abs(ga - gb) > 22).mean() * 100)


def go_home(win, tap):
    """Swipe từ mép dưới lên = gesture Home của iOS."""
    cx = win["x"] + win["w"] // 2
    cg_swipe(cx, win["y"] + win["h"] - 4, cx, win["y"] + win["h"] - 260, tap, 20)
    time.sleep(1.2)


def main():
    print("=" * 78)
    print("POC #1d — CHỐT: synthetic input có xuống được iPhone thật không?")
    print("=" * 78)
    screen_ok, ax_ok = check_permissions()
    if not (screen_ok and ax_ok):
        print("!! DỪNG: cần cả Screen Recording và Accessibility.")
        sys.exit(1)
    print()
    win = require_window()
    os.makedirs(OUT, exist_ok=True)
    cap = lambda: bk_cgwindowlist(win)

    activate(win["pid"])
    time.sleep(1.0)

    # toạ độ tuyệt đối (point)
    mid_y = win["y"] + 450
    x_right = win["x"] + win["w"] - 60
    x_left = win["x"] + 60
    search = (win["x"] + 206, win["y"] + 735)   # nút "Tìm kiếm" do OCR tìm ra

    # Cảnh báo: giữ chuột lâu trên Home Screen có thể làm iOS vào chế độ chỉnh
    # sửa icon (jiggle mode). Đã gặp thật. poc/restore_home.py trả về trạng thái
    # bình thường bằng cách OCR tìm nút "Xong" rồi tap.
    print("Đo nhiễu nền (không input)...", end=" ", flush=True)
    a = cap(); time.sleep(SETTLE); noise = diff_pct(a, cap())
    # Sàn 5%: swipe/tap thật đo được 7-33% (tap mở Spotlight tới 74%). Sàn 1.5%
    # ban đầu quá lỏng — nó cho CGEventPostToPid 1.60% đậu oan, mà ảnh
    # before/after thực ra là CÙNG một trang Home Screen.
    thresh = max(noise * 3, 5.0)
    print(f"{noise:.2f}%  ->  ngưỡng = {thresh:.2f}%")

    HID, SESS = Quartz.kCGHIDEventTap, Quartz.kCGSessionEventTap
    results = []

    def record(name, kind, fn, restore):
        activate(win["pid"]); time.sleep(0.5)
        before = cap()
        try:
            fn()
        except Exception as e:
            print(f"  {name:<34}{kind:<8}{'LỖI':>9}  {type(e).__name__}: {str(e)[:40]}")
            results.append((name, kind, None)); return
        time.sleep(SETTLE)
        after = cap()
        d = diff_pct(before, after)
        ok = d > thresh
        tag = (f"{kind}_" + name.replace(" ", "_").replace(".", "_")
               .replace(">", "").replace("-", ""))
        Image.fromarray(before[:, :, :3]).save(os.path.join(OUT, f"live_{tag}_before.png"))
        Image.fromarray(after[:, :, :3]).save(os.path.join(OUT, f"live_{tag}_after.png"))
        print(f"  {name:<34}{kind:<8}{d:>8.2f}%  {'ĂN' if ok else 'không ăn'}")
        results.append((name, kind, d))
        if restore:
            try:
                restore()
            except Exception:
                pass
        time.sleep(1.0)

    hdr = f"  {'METHOD':<34}{'THAO TÁC':<8}{'ĐỔI MÀN':>9}  KẾT LUẬN"
    print("\n" + hdr)
    print("  " + "-" * (len(hdr) - 2))

    # --- SWIPE ---
    record("CGEventPost -> HID tap", "swipe",
           lambda: cg_swipe(x_right, mid_y, x_left, mid_y, HID),
           lambda: cg_swipe(x_left, mid_y, x_right, mid_y, HID))

    record("CGEventPost -> Session tap", "swipe",
           lambda: cg_swipe(x_right, mid_y, x_left, mid_y, SESS),
           lambda: cg_swipe(x_left, mid_y, x_right, mid_y, SESS))

    record("CGEventPostToPid", "swipe",
           lambda: cg_swipe(x_right, mid_y, x_left, mid_y, None,
                            poster=lambda t, x, y: post_pid(t, x, y, win["pid"])),
           lambda: cg_swipe(x_left, mid_y, x_right, mid_y, HID))

    def pag_swipe(a, b):
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.moveTo(a, mid_y); time.sleep(0.1)
        pyautogui.mouseDown(); time.sleep(0.12)
        pyautogui.moveTo(b, mid_y, duration=0.35); time.sleep(0.1)
        pyautogui.mouseUp()

    record("pyautogui drag", "swipe",
           lambda: pag_swipe(x_right, x_left),
           lambda: pag_swipe(x_left, x_right))

    # --- TAP --- (đích: nút Tìm kiếm -> mở Spotlight; khôi phục bằng gesture Home)
    record("pyautogui.click", "tap",
           lambda: __import__("pyautogui").click(*search),
           lambda: go_home(win, HID))

    record("CGEventPost -> HID tap", "tap",
           lambda: cg_click(*search, HID),
           lambda: go_home(win, HID))

    def as_click():
        r = subprocess.run(["osascript", "-e",
                            f'tell application "System Events" to click at '
                            f'{{{search[0]}, {search[1]}}}'],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip().split("\n")[0][:60])

    record("AppleScript System Events", "tap", as_click, lambda: go_home(win, HID))

    go_home(win, HID)

    # --- tổng kết ---
    print("\n" + "=" * 78)
    winners = sorted({f"{n} ({k})" for n, k, d in results if d and d > thresh})
    if winners:
        print("BLOCKER #1 THÔNG. iPhone Mirroring CHUYỂN TIẾP synthetic input:")
        for w in winners:
            print(f"  - {w}")
        fails = sorted({f"{n} ({k})" for n, k, d in results
                        if d is not None and d <= thresh})
        if fails:
            print("Không ăn:")
            for f in fails:
                print(f"  - {f}")
    else:
        print("BLOCKER #1 CHẶN. Không thao tác nào xuống được iPhone.")
    print(f"\nẢnh before/after: {OUT}/live_*.png")
    print("=" * 78)


if __name__ == "__main__":
    main()
