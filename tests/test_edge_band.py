"""Dương tính giả đã xảy ra thật: bot đang xem TikTok, classify khớp keyword
đóng quảng cáo trong nội dung video tuỳ ý -> chuyển sang AD_WATCHING.

Nút đóng thật nằm SÁT MÉP. Chữ ở giữa màn là nội dung.
"""
import numpy as np

from pok.perception.classify import _near_edge
from pok.perception.types import TextBox

W, H = 410, 898


def tb(cx, cy, text="skip"):
    return TextBox(text=text, conf=1.0, cx=cx, cy=cy, w=40, h=16)


def test_góc_trên_phải_là_sát_mép():
    assert _near_edge(tb(380, 44), W, H)


def test_mép_dưới_là_sát_mép():
    assert _near_edge(tb(335, 834), W, H)


def test_giữa_màn_không_phải_sát_mép():
    assert not _near_edge(tb(205, 449), W, H)
    assert not _near_edge(tb(205, 640), W, H)   # X giả
    assert not _near_edge(tb(205, 731), W, H)   # nút Install


def test_nội_dung_video_ở_giữa_bị_bỏ_qua():
    """Chữ 'skip' trong caption video ở giữa màn không được kích hoạt AD."""
    assert not _near_edge(tb(180, 400, "đừng skip nha"), W, H)
