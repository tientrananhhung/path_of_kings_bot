#!/usr/bin/env python
"""Vẽ lưới toạ độ lên ảnh để đọc chính xác vị trí — đừng ước lượng bằng mắt.

  ./.venv/bin/python poc/grid.py <ảnh> [x0 y0 x1 y1] [bước]

Nhãn trên lưới là toạ độ LOCAL POINT trong cửa sổ (chia cho 410x898 để ra rel).
"""
import os
import sys

from PIL import Image, ImageDraw

path = sys.argv[1]
im = Image.open(path).convert("RGB")
W, H = im.size
if len(sys.argv) >= 6:
    x0, y0, x1, y1 = (int(v) for v in sys.argv[2:6])
else:
    x0, y0, x1, y1 = 0, 0, W, H
step = int(sys.argv[6]) if len(sys.argv) >= 7 else 25

crop = im.crop((x0, y0, x1, y1))
zoom = max(1, min(4, 1200 // max(1, crop.width)))
z = crop.resize((crop.width * zoom, crop.height * zoom), Image.NEAREST)
d = ImageDraw.Draw(z)
for gy in range(y0 - y0 % step, y1, step):
    y = (gy - y0) * zoom
    if y < 0:
        continue
    d.line([(0, y), (z.width, y)], fill=(255, 0, 0))
    d.text((3, y + 2), str(gy), fill=(255, 255, 0))
for gx in range(x0 - x0 % step, x1, step):
    x = (gx - x0) * zoom
    if x < 0:
        continue
    d.line([(x, 0), (x, z.height)], fill=(0, 255, 255))
    d.text((x + 2, 3), str(gx), fill=(0, 255, 255))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "grid.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
z.save(out)
print(f"ảnh {W}x{H} · vùng ({x0},{y0})-({x1},{y1}) · lưới {step}pt · zoom {zoom}x")
print(f"-> {out}")
print(f"rel = local / ({W}, {H})")
