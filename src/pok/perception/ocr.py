"""Tầng B — Apple Vision OCR. 61.8ms 'accurate', tiếng Việt confidence 1.00.

Đo thật (poc/bench_ocr.py): level 'fast' nhanh 5x nhưng mất hết dấu
('Kết nối' -> 'K6t n6i') nên chỉ dùng 'accurate' cho tiếng Việt.

CẢNH BÁO toạ độ: Vision trả bounding box chuẩn hoá 0..1 với GỐC GÓC DƯỚI-TRÁI,
y hướng LÊN. Phải lật: cy_local = (1 - y_vision) * H. Không lật là tap ngược màn.
"""
from __future__ import annotations

import os
import tempfile
import threading

import cv2
import numpy as np
import Vision
from Foundation import NSURL

from .types import TextBox

_LANGS = ["vi-VT", "en-US"]
_lock = threading.Lock()


def _tmp_png(bgr: np.ndarray) -> str:
    path = os.path.join(tempfile.gettempdir(), f"pok_ocr_{threading.get_ident()}.png")
    cv2.imwrite(path, bgr)
    return path


def recognize(bgr: np.ndarray, *, accurate: bool = True) -> list[TextBox]:
    h, w = bgr.shape[:2]
    path = _tmp_png(bgr)
    out: list[TextBox] = []

    def handler(request, error):  # noqa: ANN001
        for obs in request.results() or []:
            cand = obs.topCandidates_(1)
            if not cand:
                continue
            bb = obs.boundingBox()
            bx, by = bb.origin.x, bb.origin.y
            bw, bh = bb.size.width, bb.size.height
            out.append(TextBox(
                text=str(cand[0].string()),
                conf=float(cand[0].confidence()),
                cx=(bx + bw / 2) * w,
                cy=(1.0 - (by + bh / 2)) * h,   # lật trục y
                w=bw * w,
                h=bh * h,
            ))

    req = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(handler)
    req.setRecognitionLevel_(0 if accurate else 1)
    req.setRecognitionLanguages_(_LANGS)
    req.setUsesLanguageCorrection_(accurate)
    with _lock:
        Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(path), None).performRequests_error_([req], None)
    return out


def joined(texts: list[TextBox]) -> str:
    return " | ".join(t.text.lower() for t in texts)


def find_any(texts: list[TextBox], keywords: list[str]) -> list[TextBox]:
    """Khớp keyword theo substring, không phân biệt hoa/thường."""
    kws = [k.lower().strip() for k in keywords if k.strip()]
    hits = []
    for t in texts:
        low = t.text.lower().strip()
        for k in kws:
            if k == low or (len(k) > 1 and k in low):
                hits.append(t)
                break
    return hits


def text_near(texts: list[TextBox], cx: float, cy: float,
              radius: float = 40.0) -> list[str]:
    """Chữ nằm trong `radius` point quanh điểm, đo tới CẠNH hộp chữ.

    Bản cũ so `|t.cx - cx| <= radius + t.w/2` — tức là cộng thêm NỬA CHIỀU RỘNG
    hộp chữ vào bán kính. Chữ càng dài thì vùng cấm càng phình ra, mà chiều dài
    một chuỗi chữ chẳng nói gì về việc nút bấm nằm đâu.

    Bug đã gặp thật (phiên data/sessions/20260830-080353): quảng cáo có ✕ rõ
    ràng ở (372,68) và nút "PLAY NOW" hộp 94x18 ở (317,115).

        khoảng cách thật từ ✕ tới CẠNH hộp chữ : 38.8pt
        ngưỡng của luật cũ theo trục x         : 40 + 94/2 = 87pt  -> CHẶN

    Tầng 2b tìm đúng ✕ mỗi 2 giây suốt 46 giây, lần nào cũng bị chính bộ lọc
    của mình vứt đi, bot đứng im tới lúc bị tắt tay.

    Điểm nằm TRONG hộp chữ -> khoảng cách 0 -> luôn tính là gần.
    """
    res = []
    for t in texts:
        dx = max(0.0, abs(t.cx - cx) - t.w / 2)
        dy = max(0.0, abs(t.cy - cy) - t.h / 2)
        if (dx * dx + dy * dy) <= radius * radius:
            res.append(t.text.lower().strip())
    return res
