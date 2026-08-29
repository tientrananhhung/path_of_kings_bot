#!/usr/bin/env python
"""POC #2 — CÂU HỎI: Chụp được cửa sổ iPhone Mirroring không, bằng API nào, bao nhiêu FPS?

Thử 6 backend, đo ms/frame, kiểm tra ảnh có thật (không đen/trắng trơn),
và tính scale factor Retina (pixel / point) — chính là con số làm code mẫu
trong plan_bot.md click lệch gấp đôi.

Chạy:  ./.venv/bin/python poc/poc2_capture.py [số_vòng_lặp]
"""
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import Quartz
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import check_permissions, require_window  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
_args = [a for a in sys.argv[1:] if not a.startswith("-")]
N = int(_args[0]) if _args else 10


# ---------------------------------------------------------------- helpers
def cgimage_to_np(img):
    """CGImage -> numpy array (H, W, 4)."""
    if img is None:
        raise RuntimeError("CGImage is None")
    w = Quartz.CGImageGetWidth(img)
    h = Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    buf = np.frombuffer(data, dtype=np.uint8)
    return buf[: bpr * h].reshape(h, bpr // 4, 4)[:, :w, :].copy()


def verdict(arr):
    """(mean, std) độ sáng — std ~0 nghĩa là ảnh đen/trắng trơn."""
    g = arr[:, :, :3].mean(axis=2)
    return float(g.mean()), float(g.std())


def high_freq_energy(arr):
    """Năng lượng tần số cao (mật độ cạnh). Đã hiệu chuẩn bằng số đo thật:

        màn iPhone thật (kể cả màn pause khá trơn)  : 1.67 - 2.04
        hình nền desktop khi thiếu quyền            : 0.46

    Dùng cái này chứ đừng dùng std: hình nền desktop có std ~35, cao hơn nhiều
    màn game tối, nên std cho dương tính giả 100%.
    """
    g = np.asarray(Image.fromarray(arr[:, :, :3]).convert("L").resize((205, 449)), float)
    return float((np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean()) / 2)


def looks_like_mirror(arr):
    """Có đúng là nội dung cửa sổ iPhone Mirroring không? -> (ok, nhãn)

    CẢNH BÁO: khi thiếu quyền Screen Recording, macOS KHÔNG trả ảnh đen — nó
    trả HÌNH NỀN DESKTOP đã bóc hết cửa sổ. Đây là cạm bẫy chính của POC này.
    """
    _, std = verdict(arr)
    if std < 2.0:
        return False, "ĐEN/TRƠN"
    hf = high_freq_energy(arr)
    if hf < 1.0:
        return False, f"wallpaper({hf:.2f})"
    return True, f"OK({hf:.2f})"


# --------------------------------------------------------------- backends
def bk_screencapture_window(win):
    """CLI screencapture, chỉ định window-id. Đáng tin nhất, chậm nhất."""
    p = os.path.join(tempfile.gettempdir(), "poc_sc_win.png")
    subprocess.run(["screencapture", "-x", "-o", "-l", str(win["id"]), "-t", "png", p],
                   check=True, capture_output=True)
    return np.array(Image.open(p).convert("RGBA"))


def bk_screencapture_region(win):
    """CLI screencapture, chỉ định vùng theo point."""
    p = os.path.join(tempfile.gettempdir(), "poc_sc_reg.png")
    r = f"{win['x']},{win['y']},{win['w']},{win['h']}"
    subprocess.run(["screencapture", "-x", "-R", r, "-t", "png", p],
                   check=True, capture_output=True)
    return np.array(Image.open(p).convert("RGBA"))


_sct = None


def bk_mss(win):
    """mss — plan_bot.md khuyên dùng cái này. Dựa trên API đã deprecated từ macOS 14."""
    global _sct
    if _sct is None:
        import mss
        _sct = mss.MSS()
    shot = _sct.grab({"left": win["x"], "top": win["y"],
                      "width": win["w"], "height": win["h"]})
    return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)


def bk_pyautogui(win):
    """pyautogui.screenshot — chính xác cái code mẫu trong plan đang dùng."""
    import pyautogui
    img = pyautogui.screenshot(region=(win["x"], win["y"], win["w"], win["h"]))
    return np.array(img.convert("RGBA"))


def bk_cgwindowlist(win):
    """CGWindowListCreateImage — deprecated macOS 14+, có thể trả None/đen."""
    img = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        win["id"],
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution,
    )
    return cgimage_to_np(img)


_sck_filter = None


def bk_screencapturekit(win):
    """ScreenCaptureKit / SCScreenshotManager — API được Apple hậu thuẫn hiện nay."""
    import threading

    import ScreenCaptureKit as SCK

    global _sck_filter
    if _sck_filter is None:
        done = threading.Event()
        box = {}

        def got(content, err):
            box["content"], box["err"] = content, err
            done.set()

        SCK.SCShareableContent.getShareableContentWithCompletionHandler_(got)
        if not done.wait(10):
            raise RuntimeError("SCShareableContent timeout")
        if box.get("err") is not None:
            raise RuntimeError(f"SCShareableContent error: {box['err']}")
        target = next((w for w in box["content"].windows()
                       if int(w.windowID()) == win["id"]), None)
        if target is None:
            raise RuntimeError("window không có trong SCShareableContent")
        _sck_filter = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(target)

    cfg = SCK.SCStreamConfiguration.alloc().init()
    cfg.setWidth_(win["w"])
    cfg.setHeight_(win["h"])
    cfg.setCaptureResolution_(SCK.SCCaptureResolutionBest)
    # Bắt buộc: nếu để window server vẽ con trỏ vào ảnh thì mọi phép so ảnh
    # before/after sẽ dương tính giả — con trỏ di chuyển cũng làm ảnh khác nhau,
    # dù app KHÔNG hề nhận được event. Đã gặp thật khi làm POC này.
    cfg.setShowsCursor_(False)

    done = threading.Event()
    box = {}

    def shot(img, err):
        box["img"], box["err"] = img, err
        done.set()

    SCK.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
        _sck_filter, cfg, shot)
    if not done.wait(10):
        raise RuntimeError("captureImage timeout")
    if box.get("err") is not None:
        raise RuntimeError(f"captureImage error: {box['err']}")
    return cgimage_to_np(box["img"])


BACKENDS = [
    ("screencapture -l (window id)", bk_screencapture_window),
    ("screencapture -R (region)", bk_screencapture_region),
    ("mss.grab", bk_mss),
    ("pyautogui.screenshot", bk_pyautogui),
    ("CGWindowListCreateImage", bk_cgwindowlist),
    ("ScreenCaptureKit", bk_screencapturekit),
]


# ------------------------------------------------------------------- main
def main():
    print("=" * 74)
    print("POC #2 — BENCHMARK CHỤP CỬA SỔ iPHONE MIRRORING")
    print("=" * 74)
    screen_ok, _ = check_permissions()
    if not screen_ok and "--force" not in sys.argv:
        print()
        print("!! DỪNG: thiếu quyền Screen Recording.")
        print("   Nếu chạy tiếp, macOS sẽ trả HÌNH NỀN DESKTOP thay vì màn iPhone")
        print("   và mọi số đo FPS bên dưới đều vô nghĩa.")
        print("   Đang mở hộp thoại xin quyền...")
        Quartz.CGRequestScreenCaptureAccess()
        print("   Cấp quyền -> QUIT hẳn Terminal -> mở lại -> chạy lại script.")
        print("   (Muốn chạy bất chấp để xem cơ chế: thêm cờ --force)")
        sys.exit(1)
    print()
    win = require_window()
    os.makedirs(OUT, exist_ok=True)
    print(f"\nChạy {N} vòng/backend...\n")

    hdr = f"{'BACKEND':<32}{'ms/frame':>10}{'FPS':>7}{'PIXEL':>13}{'SCALE':>7}{'ẢNH':>17}"
    print(hdr)
    print("-" * len(hdr))

    rows = []
    for name, fn in BACKENDS:
        try:
            arr = fn(win)                      # warm-up (không tính giờ)
            t0 = time.perf_counter()
            for _ in range(N):
                arr = fn(win)
            ms = (time.perf_counter() - t0) / N * 1000

            h, w = arr.shape[:2]
            scale = w / win["w"]
            content_ok, ok = looks_like_mirror(arr)

            Image.fromarray(arr[:, :, :3]).save(
                os.path.join(OUT, f"cap_{name.split()[0].replace('.','_')}.png"))

            print(f"{name:<32}{ms:>10.1f}{1000/ms:>7.1f}"
                  f"{f'{w}x{h}':>13}{scale:>7.2f}{ok:>17}")
            rows.append((name, ms, scale, content_ok))
        except Exception as e:
            msg = str(e).split("\n")[0][:36]
            print(f"{name:<32}{'FAIL':>10}   {msg}")
            rows.append((name, None, None, False))

    print()
    good = [r for r in rows if r[1] and r[3]]
    print("=" * 74)
    if not good:
        print("KẾT LUẬN: KHÔNG backend nào chụp được nội dung cửa sổ.")
        if any(r[1] for r in rows):
            print("  Có backend chạy nhanh nhưng nội dung là 'NGHI:wallpaper' -> gần như")
            print("  chắc chắn thiếu quyền Screen Recording (macOS bóc hết cửa sổ, chỉ")
            print("  chừa hình nền). Cấp quyền, QUIT Terminal, chạy lại.")
        else:
            print("  -> Kiểm tra quyền Screen Recording, hoặc iPhone Mirroring chặn capture.")
            print("  -> Nếu đã có quyền mà vẫn vậy: plan_bot.md không khả thi theo hướng này.")
    else:
        good.sort(key=lambda r: r[1])
        n, ms, scale, _ = good[0]
        print(f"KẾT LUẬN: nhanh nhất & hợp lệ = '{n}'  ({ms:.1f}ms = {1000/ms:.1f} FPS)")
        print(f"  Scale factor Retina = {scale:.2f}")
        if abs(scale - 1.0) > 0.01:
            print(f"  !! Toạ độ YOLO phải CHIA {scale:.2f} trước khi click.")
            print(f"     Code mẫu plan_bot.md thiếu bước này -> click lệch ~{scale:.0f}x.")
        if 1000 / ms < 10:
            print(f"  !! Dưới 10 FPS. Plan ghi 'giới hạn 10-15 FPS' là không đạt được.")
    print(f"\nẢnh mẫu đã lưu ở: {OUT}/  — mở ra xem có đúng màn game không.")
    print("=" * 74)


if __name__ == "__main__":
    main()
