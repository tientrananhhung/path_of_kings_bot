"""Tìm dấu ✕ đóng quảng cáo bằng OpenCV — chính xác tới pixel, < 5ms.

Vì sao cần, dù đã có VLM: trên quảng cáo thật đầu tiên gặp được, nút ✕ ở
(32,122) nhưng Florence-2 trả về (68,106) — lệch 36pt, trúng viên thuốc
"Reward granted" bên cạnh. Tap vào đó không đóng được quảng cáo.

Đặc trưng hình học của dấu ✕ rất riêng và rẻ để đo: mực nằm trên HAI ĐƯỜNG
CHÉO của ô bao, còn đường giữa ngang và giữa dọc thì TRỐNG. Dấu "+" thì ngược
lại. Nên điểm phân biệt = (mực trên chéo) − (mực trên đường giữa).

Đo thật trên ảnh quảng cáo và ba màn game:

    loại       điểm   chéo   giữa
    ✕ THẬT    0.616  0.622  0.007
    giả       0.247  0.487  0.240
    giả       0.218  0.422  0.204

-> ngưỡng `điểm > 0.35` VÀ `giữa < 0.15` cho đúng ✕ thật lọt, sai số 1 point.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MIN_SIDE, MAX_SIDE = 9, 46      # cạnh ô bao dấu ✕, point
NORM = 24                       # chuẩn hoá patch về NORM x NORM để tính điểm
MIN_SCORE = 0.35
MAX_MID = 0.15
MIN_DIAG = 0.35


@dataclass
class IconHit:
    cx: float
    cy: float
    w: int
    h: int
    score: float
    diag: float
    mid: float


def _score(patch: np.ndarray) -> tuple[float, float, float]:
    """(điểm, mực_trên_chéo, mực_trên_đường_giữa) cho một patch xám."""
    if patch.size == 0:
        return (0.0, 0.0, 0.0)
    p = cv2.resize(patch, (NORM, NORM), interpolation=cv2.INTER_AREA).astype(np.float32)
    border = np.concatenate([p[0], p[-1], p[:, 0], p[:, -1]])
    bg = float(np.median(border))
    ink = np.abs(p - bg)
    if ink.max() < 12:          # patch phẳng, không có gì
        return (0.0, 0.0, 0.0)
    ink = ink / ink.max()

    idx = np.arange(NORM)
    diag = float((ink[idx, idx].mean() + ink[idx, NORM - 1 - idx].mean()) / 2)
    m = NORM // 2
    keep = np.abs(idx - m) > NORM * 0.18        # bỏ vùng tâm: chỗ nào cũng có mực
    mid = float((ink[m, keep].mean() + ink[keep, m].mean()) / 2)
    return (diag - mid, diag, mid)


def find(gray: np.ndarray, *, min_score: float = MIN_SCORE,
         max_mid: float = MAX_MID, min_diag: float = MIN_DIAG) -> list[IconHit]:
    """Tìm mọi dấu ✕ trong ảnh xám. Toạ độ trả về là local của ảnh truyền vào."""
    found: list[IconHit] = []
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
            patch = gray[max(0, y - pad):min(gray.shape[0], y + h + pad),
                         max(0, x - pad):min(gray.shape[1], x + w + pad)]
            sc, diag, mid = _score(patch)
            if sc >= min_score and diag >= min_diag and mid <= max_mid:
                found.append(IconHit(x + w / 2, y + h / 2, w, h,
                                     round(sc, 3), round(diag, 3), round(mid, 3)))

    found.sort(key=lambda d: -d.score)
    kept: list[IconHit] = []
    for d in found:                                     # gộp trùng
        if all(abs(d.cx - k.cx) > 8 or abs(d.cy - k.cy) > 8 for k in kept):
            kept.append(d)
    return kept
