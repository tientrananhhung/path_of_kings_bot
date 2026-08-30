"""Tầng mạnh đang chờ tap lại thì DỪNG, không rơi xuống tầng yếu hơn.

Bug đã gặp — phiên data/sessions/20260830-170024, kẹt 60 giây trên sheet
App Store của quảng cáo "Jackpot Dreams". Sheet đó có hai nút ở đỉnh:
✕ đóng bên TRÁI (46,145) và nút SHARE bên PHẢI (364,145).

    2b tìm đúng ✕ (46,145) 18x18  -> tap -> điểm vào cooldown retry_after_s
    chu kỳ sau: 2b bị `already_tried` bỏ qua -> RƠI XUỐNG tầng 3
    tầng 3 tap 'circle button' (364,145) 47x48 = nút SHARE -> mở sheet chia sẻ
    chu kỳ sau: 2b tap ✕ -> đóng sheet chia sẻ, quay lại App Store
    ✕ lại vào cooldown -> lại rơi xuống tầng 3 -> lại tap share... vô tận

Gốc rễ: "đang chờ tap lại" bị đối xử y như "không tìm thấy". Hai chuyện khác
hẳn nhau — chờ thì phải chờ, đi thử thứ kém tin cậy hơn là đi ngược.
"""
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from pok.config import Config
from pok.engine.ad_closer import AdAttempt, AdCloser
from pok.engine.machine import BotEngine
from pok.engine.states import BotState
from pok.perception.types import Candidate, ClassifyResult, ScreenKind

FIX = Path(__file__).parent / "fixtures"
W, H = 410, 898
X_DUNG = (46, 145)       # ✕ đóng, bên trái
SHARE = (364, 145)       # nút chia sẻ, bên phải — tap vào là mở sheet chia sẻ


class Bus:
    def publish(self, e): pass
    def log(self, *a, **k): pass


class Cap:
    demand = None
    def latest(self): return None


class Act:
    def __init__(self): self.taps = []
    def tap(self, rel, win, **k): self.taps.append((round(rel[0]*W), round(rel[1]*H))); return True
    def swipe(self, *a, **k): return True
    def home_gesture(self, *a, **k): return True
    def ensure_focus(self, win): return False


def anh(seed=1):
    return np.random.default_rng(seed).integers(0, 255, (H, W, 3), np.uint8)


@pytest.fixture
def eng():
    e = BotEngine(Config(), Bus(), Cap())
    e.act = Act()
    e.state = BotState.AD_CLOSING
    e.entered_at = time.time()
    e.attempt = AdAttempt()
    e.attempt.last_scan = 0.0
    e.vlm.enabled = True
    e.closer.yolo = None
    # 2b luôn thấy ✕ đúng; tầng 3 luôn thấy nút share
    e.closer.step_ocr = lambda *a, **k: []
    e.closer.step_icon = lambda *a, **k: [
        Candidate(cx=X_DUNG[0], cy=X_DUNG[1], w=18, h=18, label="✕",
                  score=0.62, origin="icon")]
    e.closer.step_vlm_top = lambda *a, **k: [
        Candidate(cx=SHARE[0], cy=SHARE[1], w=47, h=48, label="circle button",
                  score=1.0, origin="vlm:top")]
    return e


def man():
    return ClassifyResult(ScreenKind.AD, "sheet App Store", [], hf=9.0)


def test_lần_đầu_tap_đúng_dấu_X(eng):
    eng._state_ad_closing(man(), object(), anh())
    assert eng.act.taps == [X_DUNG]


def test_dấu_X_đang_cooldown_thì_KHÔNG_tap_nút_share(eng):
    """Đây là vòng lặp đã kẹt 60 giây."""
    eng._state_ad_closing(man(), object(), anh())      # tap ✕
    eng.attempt.last_scan = 0.0                        # cho phép quét lại ngay

    eng._state_ad_closing(man(), object(), anh())

    assert eng.act.taps == [X_DUNG], "không được rơi xuống tầng 3 tap nút share"
    assert SHARE not in eng.act.taps


def test_hết_cooldown_thì_tap_lại_ĐÚNG_dấu_X(eng):
    eng._state_ad_closing(man(), object(), anh())
    han = float(Config().ads["retry_after_s"])
    eng.attempt.tried_points = [(x, y, t - han - 1) for x, y, t in eng.attempt.tried_points]
    eng.attempt.last_scan = 0.0

    eng._state_ad_closing(man(), object(), anh())

    assert eng.act.taps == [X_DUNG, X_DUNG]


def test_tầng_trên_không_thấy_gì_thì_VẪN_rơi_xuống_tầng_dưới(eng):
    """Chặn fallthrough chỉ áp khi tầng trên CÓ ứng viên đang chờ. Không thấy
    gì thì tầng dưới vẫn phải được chạy, nếu không tầng C thành vô dụng."""
    eng.closer.step_icon = lambda *a, **k: []

    eng._state_ad_closing(man(), object(), anh())

    assert eng.act.taps == [SHARE]


def test_ảnh_thật_hai_nút_ở_hai_bên(eng):
    """Trên ảnh thật: 2b ra ✕ bên trái, tầng C ra nút share bên phải."""
    from pok.perception.classify import classify, keywords_for_classify
    ADS = Config().ads
    img = cv2.imread(str(FIX / "appstore_sheet_share.png"))
    r = classify(img, ad_keywords=keywords_for_classify(ADS), ad_icon=ADS)
    closer = AdCloser(ADS, vlm=None, bus=Bus(), yolo=None)

    (c,) = closer.step_icon(img, r.texts)
    assert abs(c.cx - X_DUNG[0]) <= 3 and abs(c.cy - X_DUNG[1]) <= 3
