"""Chống race: không được hành động dựa trên OCR của màn hình đã đổi.

Bug đã gặp thật: bot swipe trái liên tục qua chuỗi màn gear (SOLARIUS SET,
PVP RAID...). Một event MỚI xuất hiện nhưng classify chỉ làm mới mỗi 2 giây,
nên luật cũ vẫn khớp trên dữ liệu cũ và swipe chạy sai màn.
"""
from pathlib import Path

import cv2
import pytest

from pok.engine.machine import STALE_PHASH_DIST
from pok.perception.cheap import phash, phash_distance

FIX = Path(__file__).parent / "fixtures"


def h(name):
    img = cv2.imread(str(FIX / name))
    assert img is not None, f"thiếu fixture {name}"
    return phash(img)


def test_cùng_một_màn_thì_phash_gần_nhau():
    """Đo thật: cùng màn chụp cách 1.2s -> khoảng cách 0."""
    a = h("game_upgrade.png")
    assert phash_distance(a, a) == 0


@pytest.mark.parametrize("n1,n2", [
    ("game_upgrade.png", "game_empyreal.png"),
    ("game_upgrade.png", "ad_close_x.png"),
    ("game_empyreal.png", "ad_countdown_dialog.png"),
    ("ad_close_x.png", "ad_dark_x_topright.png"),
])
def test_hai_màn_khác_nhau_vượt_ngưỡng(n1, n2):
    d = phash_distance(h(n1), h(n2))
    assert d > STALE_PHASH_DIST, f"{n1} vs {n2}: lệch {d}, ngưỡng {STALE_PHASH_DIST}"


def test_ngưỡng_nằm_giữa_hai_vùng_đo_được():
    """Cùng màn 0-4, khác event 11-33 -> ngưỡng phải nằm giữa."""
    assert 4 < STALE_PHASH_DIST < 11
