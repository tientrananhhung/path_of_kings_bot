"""Tầng A — < 5ms. numpy/OpenCV thuần, chạy mỗi frame."""
from __future__ import annotations

import cv2
import numpy as np


def phash(bgr: np.ndarray, size: int = 16) -> np.ndarray:
    g = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (size, size),
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(g)[:8, :8]
    med = np.median(dct[1:, 1:])
    return (dct > med).flatten()


def phash_distance(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def color_at(bgr: np.ndarray, rel: tuple[float, float]) -> tuple[int, int, int]:
    h, w = bgr.shape[:2]
    x = min(w - 1, max(0, int(rel[0] * w)))
    y = min(h - 1, max(0, int(rel[1] * h)))
    b, g, r = bgr[y, x]
    return (int(r), int(g), int(b))


def color_matches(bgr: np.ndarray, rel: tuple[float, float],
                  rgb: tuple[int, int, int], tolerance: int = 30) -> bool:
    r, g, b = color_at(bgr, rel)
    return (abs(r - rgb[0]) <= tolerance and abs(g - rgb[1]) <= tolerance
            and abs(b - rgb[2]) <= tolerance)


def template_match(bgr: np.ndarray, template_bgr: np.ndarray,
                   region: tuple[float, float, float, float] | None = None
                   ) -> tuple[float, tuple[int, int]]:
    """Trả (score, tâm khớp theo local point)."""
    h, w = bgr.shape[:2]
    ox, oy = 0, 0
    img = bgr
    if region:
        x0 = int(region[0] * w); y0 = int(region[1] * h)
        x1 = int(region[2] * w); y1 = int(region[3] * h)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 - x0 < template_bgr.shape[1] or y1 - y0 < template_bgr.shape[0]:
            return (0.0, (0, 0))
        img = bgr[y0:y1, x0:x1]
        ox, oy = x0, y0
    res = cv2.matchTemplate(img, template_bgr, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    th, tw = template_bgr.shape[:2]
    return (float(score), (ox + loc[0] + tw // 2, oy + loc[1] + th // 2))


BEZEL_MAX_V = 0.15      # viền trên/dưới không thể quá 15% chiều cao
BEZEL_MAX_H = 0.10      # viền trái/phải không thể quá 10% chiều rộng
BEZEL_INK = 8           # <= mức này coi là đen thuần


def content_rect(bgr: np.ndarray) -> tuple[int, int, int, int]:
    """Khung MÀN HÌNH iPhone thật bên trong cửa sổ, trả (x, y, w, h).

    Cửa sổ iPhone Mirroring vẽ một khung máy bo góc màu đen quanh màn hình.
    Đo trên 45 ảnh trong data/captures: 44 ảnh cho viền ĐÚNG BẰNG
    T=38 B=8 L=8 R=8 trên cửa sổ 410x898 -> nội dung 394x852 tại (8,38),
    khớp gần như chính xác màn iPhone 6.1" (393x852 point).

    Vì sao phải có hàm này — bug đã gặp thật, đo trong phiên 20260828-155109:

      1. `crop_corner` cắt góc CỬA SỔ, nên ô góc `tr` 130x130 gồm 38 hàng đen
         thuần ở trên và 8 cột đen bên phải. Florence-2 nhận một tấm crop mà
         gần một phần ba là viền máy.
      2. Blind tap khai báo rel (0.93, 0.05) -> điểm (381,45) trên cửa sổ. Trừ
         viền đi thì đó là 7pt tính từ mép trên MÀN HÌNH, tức vùng notch/status
         bar, không phải chỗ nút đóng bao giờ nằm. Hai blind tap của bước 5 vì
         thế bắn vào chỗ trống rồi bot escalate về Home.

    Dò theo hàng/cột đen thuần từ ngoài vào. Có chặn trên (`BEZEL_MAX_*`) để
    một quảng cáo nền đen thật không làm cắt lẹm vào nội dung.
    """
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    rows = np.where(g.max(axis=1) > BEZEL_INK)[0]
    cols = np.where(g.max(axis=0) > BEZEL_INK)[0]
    if rows.size == 0 or cols.size == 0:
        return (0, 0, w, h)
    top = min(int(rows[0]), int(h * BEZEL_MAX_V))
    bot = min(h - 1 - int(rows[-1]), int(h * BEZEL_MAX_V))
    left = min(int(cols[0]), int(w * BEZEL_MAX_H))
    right = min(w - 1 - int(cols[-1]), int(w * BEZEL_MAX_H))
    return (left, top, w - left - right, h - top - bot)


def crop_top_band(bgr: np.ndarray, pct: float) -> tuple[np.ndarray, tuple[int, int]]:
    """Cắt dải TRÊN CÙNG theo tỉ lệ chiều cao. Trả (ảnh, offset local (x,y)).

    Thay cho 4 ô góc ở tầng C. Đo trên mọi nút đóng đã gặp — ✕ App Store (46,145)
    y/h=0.161 · ✕ E.D.E.N (32,121) 0.135 · ✕ Binance (371,91) 0.101 · ✕ playable
    (372,68) 0.076 · nút tròn skip (376,123) 0.137 — **5/5 đều dưới 0.17**.
    Dải 25% giữ trọn cả năm, mà chỉ tốn MỘT lần gọi VLM thay vì bốn.
    """
    h, w = bgr.shape[:2]
    bh = max(1, min(h, int(round(h * pct))))
    return (np.ascontiguousarray(bgr[0:bh, 0:w]), (0, 0))


def crop_corner(bgr: np.ndarray, corner: str, box: int) -> tuple[np.ndarray, tuple[int, int]]:
    """Cắt ô góc. Trả (ảnh, offset local (x,y)).

    Crop góc là bắt buộc cho tầng C: trên cả ảnh, Florence-2 gán nhãn nút
    Install là "close button". Crop vừa phóng nút X nhỏ lên ~5.9x, vừa loại
    decoy khỏi khung nhìn.
    """
    h, w = bgr.shape[:2]
    b = min(box, w, h)
    if corner == "tr":
        x0, y0 = w - b, 0
    elif corner == "tl":
        x0, y0 = 0, 0
    elif corner == "br":
        x0, y0 = w - b, h - b
    elif corner == "bl":
        x0, y0 = 0, h - b
    else:
        raise ValueError(f"corner không hợp lệ: {corner}")
    return (np.ascontiguousarray(bgr[y0:y0 + b, x0:x0 + b]), (x0, y0))


def crop_rel(bgr: np.ndarray, rect: tuple[float, float, float, float]
             ) -> tuple[np.ndarray, tuple[int, int]]:
    h, w = bgr.shape[:2]
    x0 = max(0, int(rect[0] * w)); y0 = max(0, int(rect[1] * h))
    x1 = min(w, int(rect[2] * w)); y1 = min(h, int(rect[3] * h))
    return (np.ascontiguousarray(bgr[y0:y1, x0:x1]), (x0, y0))


def edge_density(bgr: np.ndarray, cx: float, cy: float, r: int = 22) -> float:
    """Mật độ cạnh quanh một điểm. Dùng để loại ứng viên nằm trên NỀN TRỐNG.

    Đo thật trên quảng cáo đầu tiên gặp được:
        nền trắng trống (VLM dương tính giả)   1.97
        viên thuốc "Reward granted"           10.83
        dấu ✕ thật                             5.29
    -> ngưỡng 3.0 loại được vùng trống, giữ lại nút thật.
    """
    h, w = bgr.shape[:2]
    x0, x1 = int(max(0, cx - r)), int(min(w, cx + r))
    y0, y1 = int(max(0, cy - r)), int(min(h, cy + r))
    patch = bgr[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if g.shape[0] < 2 or g.shape[1] < 2:
        return 0.0
    return float((np.abs(np.diff(g, axis=0)).mean()
                  + np.abs(np.diff(g, axis=1)).mean()) / 2)


def encode_jpeg(bgr: np.ndarray, quality: int = 75, scale: float = 1.0) -> bytes:
    """cv2.imencode: 0.56ms @410x898 q75 = 15.2KB. Pillow chậm 2.7x."""
    img = bgr
    if scale != 1.0:
        img = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("imencode thất bại")
    return buf.tobytes()
