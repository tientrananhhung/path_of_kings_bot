"""Không được tap nút đóng khi đang đếm ngược phần thưởng.

Bug đã gặp thật (ảnh `ad_countdown_dialog.png`): quảng cáo hiện
"Reward in 23 seconds" ở (111,122) và nút ✕ ở (31,123) — cách nhau 80pt.
Bot tap ✕ ngay -> dialog "Close Video? You will lose your reward", đếm ngược
DỪNG, mất thưởng. Tệ hơn: hai nút của dialog nằm giữa màn nên bị cửa hình học
chặn, bot không tap được gì nữa và kẹt tới lúc escalate.
"""
import tomllib
from pathlib import Path

import cv2
import pytest

from pok.engine.ad_closer import AdAttempt, AdCloser
from pok.perception.ocr import recognize
from pok.perception.types import TextBox

FIX = Path(__file__).parent / "fixtures"
CFG = tomllib.load(open(Path(__file__).parents[1] / "config" / "ads.toml", "rb"))


class FakeBus:
    def publish(self, e): pass
    def log(self, *a, **k): pass


@pytest.fixture
def closer():
    return AdCloser(CFG, vlm=None, bus=FakeBus())


def tb(text, cx, cy, w=80, h=16):
    return TextBox(text=text, conf=1.0, cx=cx, cy=cy, w=w, h=h)


# ── đếm ngược ──────────────────────────────────────────────────────────────
def test_đọc_ra_số_giây_còn_lại(closer):
    left = closer.countdown_left([tb("Reward in 23 seconds", 111, 122)])
    assert left is not None
    assert 24 <= left <= 25          # 23 + countdown_extra_wait_s = 1.5


def test_khớp_pattern_nhưng_không_có_số_thì_dùng_mặc_định(closer):
    """Pattern chờ thật nhưng OCR không đọc ra số giây."""
    left = closer.countdown_left([tb("Reward in a moment", 111, 122)])
    assert left == pytest.approx(6.0 + 1.5)


def test_không_đếm_ngược_thì_trả_none(closer):
    assert closer.countdown_left([tb("X", 31, 123, 12, 12)]) is None
    assert closer.countdown_left([]) is None


def test_ảnh_thật_đang_đếm_ngược(closer):
    img = cv2.imread(str(FIX / "ad_countdown_dialog.png"))
    assert img is not None
    left = closer.countdown_left(recognize(img))
    assert left is not None, "không nhận ra đang đếm ngược"
    assert left > 20, f"đọc sai số giây: {left}"


# ── dialog Close Video? ────────────────────────────────────────────────────
def test_tìm_được_nút_resume_trên_ảnh_thật(closer):
    img = cv2.imread(str(FIX / "ad_countdown_dialog.png"))
    btn = closer.resume_button(recognize(img))
    assert btn is not None, "không tìm ra nút RESUME VIDEO"
    assert "resume" in btn.text.lower()
    assert abs(btn.cx - 263) < 12 and abs(btn.cy - 538) < 12


def test_không_có_dialog_thì_trả_none(closer):
    assert closer.resume_button([tb("Reward in 23 seconds", 111, 122)]) is None


def test_nút_resume_nằm_giữa_màn_nên_cửa_hình_học_sẽ_chặn(closer):
    """Lý do phải xử lý riêng thay vì đưa qua filter_candidates."""
    from pok.perception.types import Candidate
    img = cv2.imread(str(FIX / "ad_countdown_dialog.png"))
    c = Candidate(cx=263, cy=538, w=100, h=24, label="RESUME VIDEO", origin="vlm")
    assert closer.filter_candidates([c], img, []) == []
    assert c.block_reason == "geometry"


# ── thời gian chờ không ăn vào hạn quét ────────────────────────────────────
def test_thời_gian_chờ_không_tính_vào_hạn_quét():
    a = AdAttempt()
    a.waiting_s = 30.0
    assert a.scanning_elapsed() < 1.0
    assert a.elapsed() >= 0.0


# ── Bug: hoãn quét VÔ HẠN ──────────────────────────────────────────────────
# "Ad 2 of 2" từng nằm trong countdown_patterns. Nó là chỉ số tiến độ TỒN TẠI
# SUỐT quảng cáo, nên mỗi tick lại hoãn thêm 7.5s và bot không bao giờ tap —
# ngay cả khi trên màn đã có "Reward granted". Đã xảy ra thật, xem log phiên
# 20260828-150626.

def test_ad_n_of_m_không_phải_đếm_ngược(closer):
    assert closer.countdown_left([tb("Ad 1 of 2", 357, 496)]) is None
    assert closer.countdown_left([tb("Ad 2 of 2", 357, 496)]) is None


def test_reward_granted_thắng_mọi_pattern_chờ(closer):
    """Tín hiệu DƯƠNG: đã nhận thưởng -> thôi chờ ngay."""
    texts = [tb("• Reward granted", 88, 122), tb("Reward in 12 seconds", 111, 122)]
    assert closer.countdown_left(texts) is None


def test_vẫn_chờ_khi_có_đồng_hồ_thật_dù_kèm_ad_n_of_m(closer):
    texts = [tb("Reward in 12 seconds", 111, 122), tb("Ad 2 of 2", 357, 496)]
    left = closer.countdown_left(texts)
    assert left is not None and 13 <= left <= 14


def test_ảnh_thật_đã_nhận_thưởng_thì_không_chờ(closer):
    img = cv2.imread(str(FIX / "ad_reward_granted.png"))
    assert img is not None
    texts = recognize(img)
    joined = " | ".join(t.text.lower() for t in texts)
    assert "reward granted" in joined and "ad 2 of 2" in joined, joined[:150]
    assert closer.countdown_left(texts) is None, "vẫn đòi chờ dù đã nhận thưởng"


def test_trần_chờ_có_trong_config():
    assert float(CFG["countdown_max_wait_s"]) > 0
