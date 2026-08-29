"""Quy đổi toạ độ.

Ba hệ dùng trong dự án:
  - rel   : tỉ lệ 0..1 so với cửa sổ. Dùng trong config, bền với việc di chuyển cửa sổ.
  - local : point tính từ góc trên-trái cửa sổ.
  - screen: point tuyệt đối trên màn hình Mac. Đây là hệ CGEventPost dùng.

Ảnh chụp bằng CGWindowListCreateImage + kCGWindowImageNominalResolution trả về
POINT-resolution (scale 1.0 trên máy đích) nên pixel ảnh == local point. Vẫn
giữ tham số scale để không vỡ nếu Apple đổi hành vi hoặc chạy máy khác.
"""
from __future__ import annotations

from .window import WindowInfo


def rel_to_local(rel: tuple[float, float], win: WindowInfo) -> tuple[int, int]:
    return (int(round(rel[0] * win.w)), int(round(rel[1] * win.h)))


def rel_to_screen(rel: tuple[float, float], win: WindowInfo) -> tuple[int, int]:
    lx, ly = rel_to_local(rel, win)
    return (win.x + lx, win.y + ly)


def local_to_screen(local: tuple[float, float], win: WindowInfo) -> tuple[int, int]:
    return (int(round(win.x + local[0])), int(round(win.y + local[1])))


def local_to_rel(local: tuple[float, float], win: WindowInfo) -> tuple[float, float]:
    return (local[0] / win.w, local[1] / win.h)


def pixel_to_local(px: tuple[float, float], scale: float) -> tuple[float, float]:
    return (px[0] / scale, px[1] / scale)


def inside(screen: tuple[float, float], win: WindowInfo) -> bool:
    return (win.x <= screen[0] <= win.x + win.w
            and win.y <= screen[1] <= win.y + win.h)


def rel_rect_to_local(rect: tuple[float, float, float, float],
                      win: WindowInfo) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    return (int(x0 * win.w), int(y0 * win.h), int(x1 * win.w), int(y1 * win.h))
