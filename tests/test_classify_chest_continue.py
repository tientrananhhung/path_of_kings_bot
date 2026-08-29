"""Nút CONTINUE của game KHÔNG được làm màn game bị phân loại thành quảng cáo.

Bug đã gặp thật, phiên data/sessions/20260830-045859 + 20260830-050446:
màn rương vàng cuối lượt có nút CONTINUE ở (116,779) — ry=0.867 nên lọt dải
mép 18% — và "continue" nằm trong `close_keywords` -> classify ra AD.

Hậu quả là một vòng lặp kín, không phải một lần nhận nhầm:
  GAME_PLAY thấy AD  -> AD_WATCHING (return TRƯỚC KHI chạy luật)
  AD_WATCHING 5 giây -> AD_CLOSING
  AD_CLOSING thấy luật CONTINUE khớp -> tưởng đã đóng xong -> GAME_PLAY
  ... lặp lại, 5 giây/vòng, suốt 60 giây không một `action` nào được bắn.
Luật "Rương vàng end -> chọn CONTINUE" vì thế không bao giờ chạy được.
"""
from pathlib import Path

import cv2
import pytest

from pok.config import Config
from pok.perception.classify import classify, keywords_for_classify
from pok.perception.types import ScreenKind

FIX = Path(__file__).parent / "fixtures"
ADS = Config().ads          # cấu hình thật đang dùng, không phải bộ số riêng


def anh(name):
    img = cv2.imread(str(FIX / name))
    assert img is not None, f"thiếu fixture {name}"
    return img


def test_màn_rương_vàng_có_nút_continue_vẫn_là_game():
    res = classify(anh("game_chest_continue.png"),
                   ad_keywords=keywords_for_classify(ADS), ad_icon=ADS)
    assert res.kind is ScreenKind.GAME, res.reason


@pytest.mark.parametrize("tu", ["continue", "done", "xong"])
def test_chữ_trên_nút_của_game_không_nằm_trong_classify_keywords(tu):
    """Ba chữ này đều là nút THẬT của Path of Kings -> không được dùng để
    phân loại. Chúng vẫn ở lại `close_keywords` để TÌM NÚT trong quảng cáo."""
    assert tu not in [k.lower() for k in keywords_for_classify(ADS)]
    assert tu in [k.lower() for k in ADS.get("close_keywords", [])]


def test_vẫn_bắt_được_keyword_quảng_cáo_thật():
    kws = [k.lower() for k in keywords_for_classify(ADS)]
    assert "skip" in kws and "bỏ qua" in kws
