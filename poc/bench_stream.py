#!/usr/bin/env python
"""Đo chi phí encode JPEG để stream frame lên web — quyết định FPS khả thi.

Capture đã đo 15.9ms (63 FPS). Câu hỏi: encode + gửi tốn thêm bao nhiêu,
và băng thông bao nhiêu, để chốt FPS stream mà KHÔNG làm chậm vòng lặp bot.
"""
import io, time
import cv2
import numpy as np
from PIL import Image

SRC = "poc/out/real/cap_CGWindowListCreateImage.png"
arr = cv2.cvtColor(np.array(Image.open(SRC).convert("RGB")), cv2.COLOR_RGB2BGR)
H, W = arr.shape[:2]
print(f"frame gốc: {W}x{H}\n")

def bench(fn, n=50):
    fn()
    t0 = time.perf_counter()
    for _ in range(n):
        buf = fn()
    return (time.perf_counter() - t0) / n * 1000, len(buf)

rows = []
for scale, label in ((1.0, "410x898 (gốc)"), (0.75, "308x674"), (0.5, "205x449")):
    img = arr if scale == 1.0 else cv2.resize(arr, None, fx=scale, fy=scale,
                                              interpolation=cv2.INTER_AREA)
    for q in (60, 75, 85):
        ms, nbytes = bench(lambda i=img, q=q: cv2.imencode(
            ".jpg", i, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes())
        rows.append(("cv2", label, q, ms, nbytes))

# Pillow để so
def pil_enc(q):
    b = io.BytesIO()
    Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)).save(b, "JPEG", quality=q)
    return b.getvalue()
ms, nbytes = bench(lambda: pil_enc(75))
rows.append(("Pillow", "410x898 (gốc)", 75, ms, nbytes))

hdr = f"{'ENCODER':<8}{'KÍCH THƯỚC':<18}{'Q':>4}{'ms':>7}{'KB/frame':>10}{'@15fps Mbps':>13}{'@30fps Mbps':>13}"
print(hdr); print("-" * len(hdr))
for enc, label, q, ms, nb in rows:
    kb = nb / 1024
    print(f"{enc:<8}{label:<18}{q:>4}{ms:>7.2f}{kb:>10.1f}"
          f"{kb*8*15/1024:>13.2f}{kb*8*30/1024:>13.2f}")

print("\nWebSocket binary vs base64: base64 phình +33% -> dùng binary.")
print(f"Ngân sách 1 frame @30 FPS = 33.3ms. Capture 15.9ms + encode "
      f"{rows[3][3]:.1f}ms = {15.9+rows[3][3]:.1f}ms -> còn dư.")
