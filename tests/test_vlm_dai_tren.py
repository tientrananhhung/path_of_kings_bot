"""Tầng C quét MỘT dải trên cùng, không còn 4 ô góc — và không còn blind tap.

Vì sao bỏ crop góc: nút đóng không nhất thiết sát góc. ✕ của App Store sheet ở
(46,145) nằm NGOÀI ô góc 130x130 nên tầng C trước đây không bao giờ nhìn thấy
nó. Mọi nút đóng đã đo được đều nằm trong 17% trên cùng (bảng dưới), nên một
dải 25% giữ trọn cả năm mà chỉ tốn MỘT lần gọi VLM (~0.6s) thay vì bốn (~4.2s).

Vì sao bỏ blind tap: đo trên 57 phiên, nó đóng được đúng 1/45 lần, đổi lại là
6 cú tap mù vào màn quảng cáo.
"""
from pathlib import Path

import numpy as np
import pytest

from pok.config import Config
from pok.engine.ad_closer import AdCloser
from pok.perception import cheap
from pok.perception.types import Candidate

W, H = 410, 898
BAND = float(Config().ads.get("vlm_band_top", 0.25))

# Nút đóng THẬT đã đo được, toạ độ local trên ảnh 410x898.
NUT_THAT = {
    "✕ App Store sheet": (46, 145),
    "✕ E.D.E.N": (32, 121),
    "✕ Binance nền đen": (371, 91),
    "✕ quảng cáo playable": (372, 68),
    "nút tròn skip playable": (376, 123),
}


class FakeBus:
    def publish(self, e): pass
    def log(self, *a, **k): pass


class FakeVLM:
    """Trả về đúng một box tại toạ độ LOCAL CỦA CROP đã hẹn trước."""
    def __init__(self, cx, cy, side=30):
        self.cx, self.cy, self.side = cx, cy, side
        self.crop_shape = None

    def detect_in_crop(self, crop):
        self.crop_shape = crop.shape[:2]
        return [Candidate(cx=self.cx, cy=self.cy, w=self.side, h=self.side,
                          label="circle button", score=1.0)]


@pytest.mark.parametrize("ten,diem", NUT_THAT.items())
def test_mọi_nút_đóng_đã_đo_đều_nằm_trong_dải(ten, diem):
    """Cơ sở để chọn 0.25. Nút thấp nhất là ✕ App Store ở y/h = 0.161."""
    assert diem[1] / H <= BAND, f"{ten} ở y/h={diem[1]/H:.3f}, ngoài dải {BAND}"


def test_dải_không_rộng_quá_mức_cần():
    """0.25 đã dư 55% so với nút thấp nhất (0.161). Rộng hơn nữa là mời thêm
    dương tính giả mà không thêm nút đóng nào."""
    thap_nhat = max(y / H for _, y in NUT_THAT.values())
    assert thap_nhat < BAND <= thap_nhat * 1.6


def test_crop_dải_trên_đúng_kích_thước_và_offset():
    img = np.zeros((H, W, 3), np.uint8)
    crop, (ox, oy) = cheap.crop_top_band(img, 0.25)

    assert crop.shape[:2] == (int(H * 0.25), W)
    assert (ox, oy) == (0, 0)


def test_toạ_độ_trả_về_đã_cộng_lại_viền_máy():
    """Crop cắt theo MÀN HÌNH THẬT (trừ viền 38pt trên, 8pt trái), nên toạ độ
    VLM trả ra phải được cộng lại offset đó mới thành toạ độ của ảnh chụp.
    Quên bước này là tap lệch nguyên cái viền."""
    img = np.zeros((H, W, 3), np.uint8)
    img[38:H - 8, 8:W - 8] = 60          # dựng "màn hình thật" trong cửa sổ
    sx, sy, sw, sh = cheap.content_rect(img)

    vlm = FakeVLM(cx=100, cy=50)
    closer = AdCloser({"vlm_band_top": 0.25, "min_edge_density": 0.0,
                       "max_area_pct": 0.04,
                       "vlm": {"min_side_pt": 20, "max_side_pt": 50}},
                      vlm=vlm, bus=FakeBus())
    (c,) = closer.step_vlm_top(img, [])

    assert (c.cx, c.cy) == (100 + sx, 50 + sy)
    assert c.origin == "vlm:top"
    assert vlm.crop_shape == (int(sh * 0.25), sw)     # cắt của màn, không của cửa sổ


def test_không_còn_blind_tap():
    """Khoá quyết định: bỏ hẳn, không phải tắt bằng config."""
    assert not hasattr(AdCloser, "blind_points")
    assert not Config().ads.get("blind_tap")


def test_không_còn_quét_theo_góc():
    assert not hasattr(AdCloser, "step_vlm_corner")
    assert not hasattr(AdCloser, "corners")


def test_chỉ_một_prompt_và_không_phải_close_button():
    """Đo trên dải 25% của 6 ảnh: mọi prompt chứa chữ "close" trúng 0/6 —
    Florence-2 trả box phủ trọn crop, tức "không thấy gì". "circle button"
    trúng 3/3. Nó tả HÌNH DẠNG, không tả CHỨC NĂNG."""
    prompts = Config().ads.get("vlm", {}).get("prompts", [])
    assert len(prompts) == 1
    assert "close" not in prompts[0].lower()
