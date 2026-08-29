#!/usr/bin/env python
"""Thử thuật toán tìm dấu ✕ bằng OpenCV — CHÍNH XÁC TỚI PIXEL, không dùng VLM.

Ý tưởng: dấu ✕ có đặc trưng hình học rất riêng — mực nằm trên HAI ĐƯỜNG CHÉO
của ô bao, còn đường giữa ngang và giữa dọc thì trống. Dấu "+" thì ngược lại.
Nên điểm phân biệt = (mực trên chéo) - (mực trên đường giữa).

  ./.venv/bin/python poc/find_x.py <ảnh> [x0 y0 x1 y1]
"""
import sys

import cv2
import numpy as np

MIN_SIDE, MAX_SIDE = 9, 46          # cạnh ô bao của dấu ✕, tính bằng point
N = 24                              # chuẩn hoá patch về N x N để tính điểm


def x_score(patch: np.ndarray) -> tuple[float, float, float]:
    """Trả (điểm_x, mực_trên_chéo, mực_trên_đường_giữa). Patch là ảnh xám."""
    p = cv2.resize(patch, (N, N), interpolation=cv2.INTER_AREA).astype(np.float32)
    # nền = giá trị trung vị của viền; mực = pixel lệch nhiều so với nền
    border = np.concatenate([p[0], p[-1], p[:, 0], p[:, -1]])
    bg = float(np.median(border))
    ink = np.abs(p - bg)
    if ink.max() < 12:              # patch phẳng, không có gì
        return (0.0, 0.0, 0.0)
    ink = ink / ink.max()

    idx = np.arange(N)
    diag = (ink[idx, idx].mean() + ink[idx, N - 1 - idx].mean()) / 2

    m = N // 2
    keep = (np.abs(idx - m) > N * 0.18)      # bỏ vùng tâm, chỗ nào cũng có mực
    mid = (ink[m, keep].mean() + ink[keep, m].mean()) / 2
    return (float(diag - mid), float(diag), float(mid))


def find(gray: np.ndarray) -> list[dict]:
    out = []
    # thử cả hai chiều: mực đậm trên nền sáng, và mực sáng trên nền đậm
    for invert in (False, True):
        g = 255 - gray if invert else gray
        th = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 15, 6)
        cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
                continue
            if not (0.65 <= w / h <= 1.55):
                continue
            pad = 2
            y0, y1 = max(0, y - pad), min(gray.shape[0], y + h + pad)
            x0, x1 = max(0, x - pad), min(gray.shape[1], x + w + pad)
            sc, diag, mid = x_score(gray[y0:y1, x0:x1])
            if sc > 0.18 and diag > 0.35:
                out.append({"cx": x + w / 2, "cy": y + h / 2, "w": w, "h": h,
                            "score": round(sc, 3), "diag": round(diag, 3),
                            "mid": round(mid, 3), "inv": invert})
    # gộp các ứng viên trùng nhau
    out.sort(key=lambda d: -d["score"])
    kept = []
    for d in out:
        if all(abs(d["cx"] - k["cx"]) > 8 or abs(d["cy"] - k["cy"]) > 8 for k in kept):
            kept.append(d)
    return kept


if __name__ == "__main__":
    path = sys.argv[1]
    img = cv2.imread(path)
    if len(sys.argv) >= 6:
        x0, y0, x1, y1 = (int(v) for v in sys.argv[2:6])
    else:
        x0, y0, x1, y1 = 0, 0, img.shape[1], img.shape[0]
    crop = img[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    res = find(gray)
    print(f"{path}  vùng ({x0},{y0})-({x1},{y1})  -> {len(res)} ứng viên ✕")
    for d in res[:12]:
        print(f"  điểm={d['score']:.3f} chéo={d['diag']:.3f} giữa={d['mid']:.3f} "
              f"tâm=({x0 + d['cx']:.0f},{y0 + d['cy']:.0f}) {d['w']}x{d['h']} "
              f"{'nền tối' if d['inv'] else 'nền sáng'}")
