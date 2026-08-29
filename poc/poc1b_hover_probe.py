#!/usr/bin/env python
"""POC #1b — probe KHÔNG side-effect: iPhone Mirroring có phản ứng với synthetic
mouse-move không?

Khác poc1_click.py: chỉ bắn mouse-move, KHÔNG click. Nút macOS sáng lên trạng
thái hover khi con trỏ đi qua, nên nếu ảnh vùng nút đổi -> event đã tới được app.
Dùng khi không có mục tiêu click an toàn (ví dụ iPhone Mirroring đang ở màn pause).

Chạy:  ./.venv/bin/python poc/poc1b_hover_probe.py --point X Y
       (X Y = toạ độ point tuyệt đối của một nút trong cửa sổ)
"""
import argparse
import os
import sys
import time

import numpy as np
import Quartz
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import activate, check_permissions, require_window  # noqa: E402
from poc1_click import pick_backend  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
BOX = 70          # nửa cạnh vùng crop quanh nút (point)
SETTLE = 0.9


def move_to(x, y, tap):
    ev = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, Quartz.CGPointMake(x, y),
        Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(tap, ev)


def crop(arr, win, cx, cy, scale):
    """Cắt vùng quanh (cx,cy) point tuyệt đối, từ ảnh chụp cửa sổ."""
    lx = int((cx - win["x"] - BOX) * scale)
    ly = int((cy - win["y"] - BOX) * scale)
    s = int(BOX * 2 * scale)
    h, w = arr.shape[:2]
    lx, ly = max(0, min(lx, w - 1)), max(0, min(ly, h - 1))
    return arr[ly:min(ly + s, h), lx:min(lx + s, w), :3]


def diff_pct(a, b):
    ga = np.asarray(Image.fromarray(a).convert("L").resize((120, 120)), float)
    gb = np.asarray(Image.fromarray(b).convert("L").resize((120, 120)), float)
    return float((np.abs(ga - gb) > 10).mean() * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--point", nargs=2, type=int, required=True, metavar=("X", "Y"))
    args = ap.parse_args()
    tx, ty = args.point

    print("=" * 74)
    print("POC #1b — PROBE HOVER (không click, không side-effect)")
    print("=" * 74)
    screen_ok, ax_ok = check_permissions()
    if not screen_ok:
        print("!! DỪNG: thiếu Screen Recording -> chụp ra wallpaper, so ảnh vô nghĩa.")
        sys.exit(1)
    print()
    win = require_window()
    os.makedirs(OUT, exist_ok=True)

    _, cap = pick_backend(win)
    scale = cap(win).shape[1] / win["w"]
    print(f"[i ] scale = {scale:.2f}")
    print("[i ] backend phải KHÔNG vẽ con trỏ vào ảnh, nếu không kết quả là rác.")

    import pyautogui
    pyautogui.FAILSAFE = False
    home = pyautogui.position()          # lưu để trả chuột về chỗ cũ
    park = (win["x"] - 60, win["y"] + 40)  # điểm "đậu" ngoài cửa sổ

    activate(win["pid"])
    time.sleep(0.8)

    taps = [("kCGHIDEventTap", Quartz.kCGHIDEventTap),
            ("kCGSessionEventTap", Quartz.kCGSessionEventTap)]

    # nhiễu nền: chuột đậu ngoài, chụp 2 lần
    move_to(*park, Quartz.kCGHIDEventTap)
    time.sleep(SETTLE)
    base = crop(cap(win), win, tx, ty, scale)
    time.sleep(SETTLE)
    noise = diff_pct(base, crop(cap(win), win, tx, ty, scale))
    print(f"[i ] nhiễu nền vùng nút = {noise:.2f}%")
    thresh = max(noise * 3, 0.5)

    print(f"\n{'EVENT TAP':<24}{'ĐỔI VÙNG NÚT':>16}{'KẾT LUẬN':>16}")
    print("-" * 60)
    results = []
    for name, tap in taps:
        move_to(*park, tap)
        time.sleep(SETTLE)
        before = crop(cap(win), win, tx, ty, scale)
        move_to(tx, ty, tap)                   # <- chỉ move, không click
        time.sleep(SETTLE)
        after = crop(cap(win), win, tx, ty, scale)
        d = diff_pct(before, after)
        ok = d > thresh
        Image.fromarray(before).save(os.path.join(OUT, f"hover_{name}_off.png"))
        Image.fromarray(after).save(os.path.join(OUT, f"hover_{name}_on.png"))
        print(f"{name:<24}{d:>15.2f}%{('ĂN' if ok else 'không'):>16}")
        results.append((name, d, ok))

    pyautogui.moveTo(*home)                    # trả chuột về chỗ cũ
    print("=" * 74)
    good = [r[0] for r in results if r[2]]
    if good:
        print(f"Synthetic mouse-move TỚI ĐƯỢC app qua: {', '.join(good)}")
        print("  -> pipeline event thông. Click cũng sẽ tới (cùng cơ chế CGEventPost).")
    else:
        print("Không tap nào tạo phản ứng hover -> KHÔNG KẾT LUẬN ĐƯỢC.")
        print("  Nút accent của macOS gần như không đổi hình khi hover, nên probe")
        print("  này vốn yếu. Phải chạy poc1_click.py để có câu trả lời thật.")
    print(f"\nẢnh off/on ở {OUT}/hover_*.png — xem để tự xác nhận.")
    print("=" * 74)


if __name__ == "__main__":
    main()
