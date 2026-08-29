#!/usr/bin/env python
"""POC #1 — CÂU HỎI: iPhone Mirroring có nhận synthetic mouse event không?

Đây là blocker số 1 của plan_bot.md. Nếu KHÔNG method nào ăn, cả plan phải
đổi hướng (Appium/WebDriverAgent) chứ không phải sửa code.

Cách kiểm chứng: chụp màn hình TRƯỚC -> bắn event -> chụp SAU -> so ảnh.
Trước đó đo mức "nhiễu nền" (animation, đồng hồ) để không báo dương tính giả.

Thử 5 cách bắn event:
  1. pyautogui.click              (đúng cái plan_bot.md dùng)
  2. CGEventPost -> HID tap       (thấp nhất, giống chuột thật nhất)
  3. CGEventPost -> Session tap
  4. CGEventPostToPid             (bắn thẳng vào process)
  5. AppleScript System Events    (đi qua Accessibility API)

Chạy:  ./.venv/bin/python poc/poc1_click.py
       ./.venv/bin/python poc/poc1_click.py --point 512 700
       ./.venv/bin/python poc/poc1_click.py --only 2
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np
import Quartz
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import activate, check_permissions, require_window  # noqa: E402
from poc2_capture import (bk_cgwindowlist, bk_pyautogui,  # noqa: E402
                          bk_screencapture_window, bk_screencapturekit,
                          looks_like_mirror)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
SETTLE = 1.4          # giây chờ sau khi click để UI kịp phản ứng
CLICK_HOLD = 0.08     # giây giữ chuột giữa down và up


# --------------------------------------------------------------- capture
def pick_backend(win):
    # Thứ tự ưu tiên: các backend chụp RIÊNG cửa sổ (không có con trỏ chuột
    # trong ảnh) phải đứng trước. mss / screencapture -R / pyautogui chụp theo
    # vùng màn hình nên có vẽ con trỏ -> so ảnh before/after dương tính giả.
    order = [("CGWindowListCreateImage", bk_cgwindowlist),
             ("ScreenCaptureKit (no cursor)", bk_screencapturekit),
             ("screencapture -l", bk_screencapture_window),
             ("pyautogui.screenshot [CÓ CON TRỎ - kết quả không tin được]",
              bk_pyautogui)]
    fallback = None
    for name, fn in order:
        try:
            arr = fn(win)
        except Exception:
            continue
        ok, why = looks_like_mirror(arr)
        if ok:
            print(f"[OK] Backend chụp hình: {name}  ({arr.shape[1]}x{arr.shape[0]})")
            return name, fn
        if fallback is None:
            fallback = (name, fn, why)
    if fallback:
        name, fn, why = fallback
        print(f"[!!] Backend '{name}' chụp được nhưng nội dung đáng ngờ ({why}).")
        print("     Nếu là 'wallpaper' thì ảnh before/after sẽ luôn giống nhau và")
        print("     script sẽ kết luận SAI là 'không ăn'. Hãy cấp quyền trước.")
        sys.exit(3)
    print("[X] Không backend nào chụp được -> chạy poc2_capture.py để xem chi tiết.")
    sys.exit(3)


def diff_score(a, b):
    """% pixel thay đổi rõ rệt giữa 2 frame (0..100)."""
    ga = np.asarray(Image.fromarray(a[:, :, :3]).convert("L").resize((180, 380)), float)
    gb = np.asarray(Image.fromarray(b[:, :, :3]).convert("L").resize((180, 380)), float)
    return float((np.abs(ga - gb) > 22).mean() * 100)


# ------------------------------------------------------- injection methods
def m_pyautogui(x, y):
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.click(x, y)


def _cgevent(x, y, tap):
    p = Quartz.CGPointMake(x, y)
    for ev_type in (Quartz.kCGEventMouseMoved,
                    Quartz.kCGEventLeftMouseDown,
                    Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, ev_type, p, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(tap, ev)
        time.sleep(CLICK_HOLD if ev_type == Quartz.kCGEventLeftMouseDown else 0.03)


def m_cg_hid(x, y):
    _cgevent(x, y, Quartz.kCGHIDEventTap)


def m_cg_session(x, y):
    _cgevent(x, y, Quartz.kCGSessionEventTap)


_PID = {"pid": 0}


def m_cg_to_pid(x, y):
    p = Quartz.CGPointMake(x, y)
    for ev_type in (Quartz.kCGEventMouseMoved,
                    Quartz.kCGEventLeftMouseDown,
                    Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, ev_type, p, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPostToPid(_PID["pid"], ev)
        time.sleep(CLICK_HOLD if ev_type == Quartz.kCGEventLeftMouseDown else 0.03)


def m_applescript(x, y):
    r = subprocess.run(
        ["osascript", "-e",
         f'tell application "System Events" to click at {{{int(x)}, {int(y)}}}'],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().split("\n")[0][:60])


METHODS = [
    ("pyautogui.click", m_pyautogui),
    ("CGEventPost -> HID tap", m_cg_hid),
    ("CGEventPost -> Session tap", m_cg_session),
    ("CGEventPostToPid", m_cg_to_pid),
    ("AppleScript System Events", m_applescript),
]


# ------------------------------------------------------------------- main
def measure_noise(cap, win, rounds=3):
    """Mức thay đổi ảnh khi KHÔNG có input nào — ngưỡng chống dương tính giả."""
    worst = 0.0
    for _ in range(rounds):
        a = cap(win)
        time.sleep(SETTLE)
        worst = max(worst, diff_score(a, cap(win)))
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--point", nargs=2, type=int, metavar=("X", "Y"),
                    help="toạ độ tuyệt đối trên màn Mac (point). Bỏ trống = chọn bằng chuột")
    ap.add_argument("--only", type=int, help="chỉ chạy 1 method (1-5)")
    args = ap.parse_args()

    print("=" * 74)
    print("POC #1 — iPHONE MIRRORING CÓ NHẬN SYNTHETIC MOUSE EVENT KHÔNG?")
    print("=" * 74)
    screen_ok, ax_ok = check_permissions()
    if not (screen_ok and ax_ok):
        print()
        print("!! DỪNG: POC #1 cần CẢ HAI quyền.")
        print("   - Thiếu Screen Recording -> chụp ra hình nền desktop, so ảnh vô nghĩa,")
        print("     script sẽ kết luận sai là 'không method nào ăn'.")
        print("   - Thiếu Accessibility    -> chính các event bị chặn ngay từ đầu.")
        if not screen_ok:
            Quartz.CGRequestScreenCaptureAccess()
        print("   Cấp cả 2 quyền -> QUIT hẳn Terminal -> mở lại -> chạy lại.")
        sys.exit(1)
    print()
    win = require_window()
    _PID["pid"] = win["pid"]
    os.makedirs(OUT, exist_ok=True)

    _, cap = pick_backend(win)
    scale = cap(win).shape[1] / win["w"]
    print(f"[i ] Scale factor Retina = {scale:.2f}  "
          f"(toạ độ pixel trong ảnh phải CHIA {scale:.2f} để ra point khi click)")

    # --- chọn điểm click ---
    if args.point:
        tx, ty = args.point
    else:
        print("\n" + "-" * 74)
        print("Chuẩn bị:")
        print("  1. Đưa màn hình iPhone về HOME SCREEN (có icon app).")
        print("  2. Rê chuột thật lên MỘT ICON APP trong cửa sổ iPhone Mirroring.")
        print("  3. GIỮ NGUYÊN chuột ở đó rồi bấm Enter (đừng click).")
        input("     Enter khi đã rê chuột đúng chỗ... ")
        import pyautogui
        tx, ty = pyautogui.position()
    if not (win["x"] <= tx <= win["x"] + win["w"]
            and win["y"] <= ty <= win["y"] + win["h"]):
        print(f"[X] Điểm ({tx},{ty}) nằm NGOÀI cửa sổ iPhone Mirroring. Dừng.")
        sys.exit(4)
    print(f"[OK] Điểm click mục tiêu: ({tx}, {ty}) — trong cửa sổ, "
          f"offset ({tx-win['x']}, {ty-win['y']}) point")

    activate(win["pid"])
    time.sleep(0.8)

    print("\nĐo mức nhiễu nền (không input)...", end=" ", flush=True)
    noise = measure_noise(cap, win)
    thresh = max(noise * 3, 1.5)
    print(f"nhiễu = {noise:.2f}%  ->  ngưỡng kết luận = {thresh:.2f}%")

    methods = METHODS if not args.only else [METHODS[args.only - 1]]
    print("\n" + "=" * 74)
    results = []
    for i, (name, fn) in enumerate(methods, 1):
        print(f"\n[{i}/{len(methods)}] {name}")
        if not args.point:
            input("        Đưa iPhone về Home Screen, rê chuột về đúng icon cũ, Enter... ")
            import pyautogui
            tx, ty = pyautogui.position()
        activate(win["pid"])
        time.sleep(0.6)

        before = cap(win)
        try:
            fn(tx, ty)
        except Exception as e:
            print(f"        LỖI khi bắn event: {e}")
            results.append((name, None))
            continue
        time.sleep(SETTLE)
        after = cap(win)

        d = diff_score(before, after)
        ok = d > thresh
        tag = name.split()[0].replace(".", "_")
        Image.fromarray(before[:, :, :3]).save(os.path.join(OUT, f"click_{i}_{tag}_before.png"))
        Image.fromarray(after[:, :, :3]).save(os.path.join(OUT, f"click_{i}_{tag}_after.png"))
        print(f"        thay đổi màn hình = {d:.2f}%  ->  "
              f"{'ĂN — event được nhận' if ok else 'KHÔNG ăn'}")
        results.append((name, d))

    # --- tổng kết ---
    print("\n" + "=" * 74)
    print(f"{'METHOD':<32}{'ĐỔI MÀN':>10}{'KẾT LUẬN':>14}")
    print("-" * 74)
    winners = []
    for name, d in results:
        if d is None:
            print(f"{name:<32}{'-':>10}{'LỖI':>14}")
        elif d > thresh:
            print(f"{name:<32}{d:>9.2f}%{'ĂN':>14}")
            winners.append(name)
        else:
            print(f"{name:<32}{d:>9.2f}%{'không ăn':>14}")

    print("=" * 74)
    if winners:
        print(f"BLOCKER #1 THÔNG. Dùng được: {', '.join(winners)}")
        print("  -> plan_bot.md khả thi ở phần điều khiển. Sang sửa lỗi toạ độ Retina.")
    else:
        print("BLOCKER #1 CHẶN. Không method nào điều khiển được iPhone Mirroring.")
        print("  -> Phải đổi hướng: Appium/WebDriverAgent trên iPhone, hoặc Android emulator.")
        print("  -> Kiểm tra lại quyền Accessibility trước khi kết luận (xem đầu output).")
    print(f"\nẢnh before/after đã lưu ở: {OUT}/ — mở xem để tự xác nhận.")
    print("=" * 74)


if __name__ == "__main__":
    main()
