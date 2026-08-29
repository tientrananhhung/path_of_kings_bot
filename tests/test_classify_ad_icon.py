"""Dấu ✕ sát mép là bằng chứng để `classify` kết luận AD.

Bug đã gặp thật, đây là lý do module này tồn tại: tấm App Store sheet của
quảng cáo Binance chỉ khớp ĐÚNG MỘT hint App Store ("Nhận") nên không đủ ngưỡng
2, lại chẳng có keyword đóng nào -> rơi vào nhánh mặc định GAME. Engine ở
GAME_PLAY nên KHÔNG BAO GIỜ vào AD_CLOSING, không bao giờ gọi `step_icon`, và
quảng cáo đứng nguyên đó — dù `close_icon.find()` đã thấy nút ✕ ở (46,145) với
điểm 0.61 ngay từ đầu. Tầng dò không hỏng; `classify` mới hỏng.

Đo trên 44 ảnh trong data/captures: 11 màn quảng cáo đều ra AD kèm đúng một ứng
viên qua đủ 4 cửa lọc, 33 màn game thuần giữ GAME với 0 ứng viên.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from pok.config import Config
from pok.engine.ad_closer import AdCloser
from pok.perception import close_icon
from pok.perception.classify import classify, keywords_for_classify
from pok.perception.types import ScreenKind

FIX = Path(__file__).parent / "fixtures"
W, H = 410, 898

# Ngưỡng thật trong config/ads.toml — test phải chạy đúng cấu hình đang dùng,
# không phải một bộ số riêng. Đổi ngưỡng mà test đỏ thì ngưỡng sai.
ADS = Config().ads


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, e):
        self.events.append(e)

    def log(self, *a, **k):
        pass


def anh(name):
    img = cv2.imread(str(FIX / name))
    assert img is not None, f"thiếu fixture {name}"
    return img


def phan_loai(img):
    return classify(img, ad_keywords=keywords_for_classify(ADS), ad_icon=ADS)


# ── màn quảng cáo phải ra AD ────────────────────────────────────────────────

@pytest.mark.parametrize("name,x_that", [
    # Ca chính của bug: ✕ ở y=145, KHÔNG khớp hint App Store nào đủ ngưỡng,
    # không có keyword -> trước đây ra GAME và bot đứng im.
    ("appstore_sheet_x_low.png", (46, 145)),
    ("ad_dark_x_topright.png", (371, 91)),      # ✕ trắng trên nền đen
    ("ad_close_x.png", (32, 121)),              # ✕ đen trên nền trắng
    ("ad_reward_granted.png", (32, 121)),
    ("ad_countdown_dialog.png", (33, 121)),
])
def test_màn_quảng_cáo_có_dấu_x_sát_mép_được_phân_loại_là_ad(name, x_that):
    res = phan_loai(anh(name))
    assert res.kind is ScreenKind.AD, f"{name} ra {res.kind.value}: {res.reason}"
    assert f"({x_that[0]},{x_that[1]})" in res.reason, res.reason


def test_sheet_app_store_có_x_thì_đóng_bằng_x_chứ_không_gesture_home():
    """APPSTORE -> watchdog gesture Home, mất phiên chơi VÀ mất phần thưởng.

    Trang App Store có ✕ sát mép là sheet mở đè lên quảng cáo, không phải app
    App Store thật. Có ✕ thì phải đi đường AD để bấm ✕.
    """
    res = phan_loai(anh("ad_reward_granted.png"))
    assert res.kind is ScreenKind.AD
    assert res.kind is not ScreenKind.APPSTORE


# ── màn game KHÔNG được ra AD ───────────────────────────────────────────────

@pytest.mark.parametrize("name", ["game_upgrade.png", "game_empyreal.png"])
def test_màn_game_không_bị_coi_là_quảng_cáo(name):
    assert phan_loai(anh(name)).kind is ScreenKind.GAME


def _ve_dau_x(img, cx, cy, r=9):
    cv2.line(img, (cx - r, cy - r), (cx + r, cy + r), (250, 250, 250), 2)
    cv2.line(img, (cx + r, cy - r), (cx - r, cy + r), (250, 250, 250), 2)
    return img


def _nen_nhieu():
    """Nền nhiễu: hf cao nên không rơi vào nhánh NO_CONTENT/UNKNOWN."""
    rng = np.random.default_rng(7)
    return rng.integers(0, 90, (H, W, 3), dtype=np.uint8)


def test_dấu_x_GIỮA_màn_không_làm_lật_sang_ad():
    """Dải mép chính là thứ chặn dương tính giả, không phải may mắn.

    Đo trên data/captures: 4 màn game có ✕ bị `close_icon` bắt, nhưng đều ở
    giữa màn (y/h = 0.70-0.78) nên dải mép loại hết. Test này dựng lại đúng
    tình huống đó bằng ảnh tổng hợp.
    """
    giua = _ve_dau_x(_nen_nhieu(), W // 2, H // 2)
    gray = cv2.cvtColor(giua, cv2.COLOR_BGR2GRAY)
    assert close_icon.find(gray), "fixture hỏng: phải dò ra ✕ thì test mới có nghĩa"
    assert phan_loai(giua).kind is not ScreenKind.AD


def test_cùng_dấu_x_đó_nhưng_sát_mép_thì_lật_sang_ad():
    """Cặp đôi với test trên: chỉ đổi VỊ TRÍ, mọi thứ khác giữ nguyên."""
    mep = _ve_dau_x(_nen_nhieu(), 40, 60)
    assert phan_loai(mep).kind is ScreenKind.AD


# ── tương thích ngược ───────────────────────────────────────────────────────

def test_không_truyền_ad_icon_thì_giữ_nguyên_hành_vi_cũ():
    """`ad_icon=None` tắt hẳn tầng dò — các test cũ gọi `classify(img)` phải
    không bị đổi nghĩa."""
    img = anh("appstore_sheet_x_low.png")
    assert classify(img, ad_keywords=keywords_for_classify(ADS)).kind \
        is ScreenKind.GAME


# ── nối đầu-cuối: phân loại xong thì bước 2b phải ra đúng nút ───────────────

def test_phân_loại_ad_rồi_bước_2b_trả_về_đúng_nút_đóng():
    """Khoá cả chuỗi: classify -> AD, rồi step_icon -> đúng 1 ứng viên ở (46,145).

    Đây là chỗ trước đây đứt: classify ra GAME nên step_icon không bao giờ chạy.
    """
    img = anh("appstore_sheet_x_low.png")
    res = phan_loai(img)
    assert res.kind is ScreenKind.AD

    closer = AdCloser(ADS, vlm=None, bus=FakeBus())
    cands = closer.step_icon(img, res.texts)
    assert len(cands) == 1, [(c.cx, c.cy) for c in cands]
    c = cands[0]
    lech = ((c.cx - 46) ** 2 + (c.cy - 145) ** 2) ** 0.5
    assert lech < 3, f"lệch {lech:.1f}pt — ({c.cx:.0f},{c.cy:.0f})"
    assert not c.blocked


@pytest.mark.parametrize("name", ["game_upgrade.png", "game_empyreal.png"])
def test_màn_game_thì_bước_2b_không_trả_ứng_viên_nào(name):
    img = anh(name)
    res = phan_loai(img)
    closer = AdCloser(ADS, vlm=None, bus=FakeBus())
    assert closer.step_icon(img, res.texts) == []
