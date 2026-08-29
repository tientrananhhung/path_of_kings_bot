"""Khung màn hình iPhone thật nằm bên trong cửa sổ — viền máy không phải nội dung.

Bug đã gặp thật, đo trong phiên `data/sessions/20260828-155109`: bot vào
AD_CLOSING trên một quảng cáo playable, tầng C tap hai lần rồi blind tap hai lần,
tất cả đều trượt, cuối cùng escalate về Home. Nút skip thật ở (376,123).

  - `crop_corner` cắt góc CỬA SỔ nên ô `tr` 130x130 có 38 hàng đen thuần ở trên
    và 8 cột đen bên phải — gần 1/3 tấm crop là viền máy.
  - blind tap khai báo (0.93, 0.05) hiểu theo cửa sổ ra (381,45); trừ viền 38pt
    thì chỉ cách mép trên MÀN HÌNH 7pt, tức vùng notch.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from pok.perception.cheap import BEZEL_MAX_H, BEZEL_MAX_V, content_rect

FIX = Path(__file__).parent / "fixtures"

# Đo trên 45 ảnh data/captures: 44 ảnh cho ĐÚNG con số này.
# 410 - 8 - 8 = 394 và 898 - 38 - 8 = 852 -> khớp màn iPhone 6.1" (393x852pt).
KHUNG = (8, 38, 394, 852)


@pytest.mark.parametrize("name", [
    "ad_playable_skip.png", "appstore_sheet_x_low.png", "ad_close_x.png",
    "ad_dark_x_topright.png", "ad_reward_granted.png",
    "game_upgrade.png", "game_empyreal.png",
])
def test_dò_đúng_khung_màn_hình_trên_ảnh_thật(name):
    img = cv2.imread(str(FIX / name))
    assert img is not None, f"thiếu fixture {name}"
    assert content_rect(img) == KHUNG


def test_quảng_cáo_nền_đen_không_làm_cắt_lẹm_vào_nội_dung():
    """Chặn trên `BEZEL_MAX_*` tồn tại để làm gì.

    Một quảng cáo video nền đen có thể đen thuần rất nhiều hàng từ mép vào. Nếu
    không có trần, `content_rect` sẽ nuốt luôn phần nội dung đó và mọi toạ độ
    lệch theo.
    """
    h, w = 898, 410
    den = np.zeros((h, w, 3), dtype=np.uint8)
    den[600:620, 200:220] = 255        # chỉ một đốm sáng ở giữa dưới
    x, y, cw, ch = content_rect(den)
    assert y <= int(h * BEZEL_MAX_V), "viền trên vượt trần"
    assert x <= int(w * BEZEL_MAX_H), "viền trái vượt trần"
    assert cw >= w - 2 * int(w * BEZEL_MAX_H)
    assert ch >= h - 2 * int(h * BEZEL_MAX_V)


def test_ảnh_đen_tuyền_trả_về_cả_cửa_sổ():
    den = np.zeros((898, 410, 3), dtype=np.uint8)
    assert content_rect(den) == (0, 0, 410, 898)


def test_không_có_viền_thì_trả_nguyên_kích_thước():
    sang = np.full((898, 410, 3), 200, dtype=np.uint8)
    assert content_rect(sang) == (0, 0, 410, 898)
