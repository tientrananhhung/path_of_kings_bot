"""Lọc an toàn 3 cửa — phần quan trọng nhất của dự án.

Florence-2 đã thực sự gán nhãn nút Install là 'close button'. Ba cửa này là
thứ duy nhất ngăn bot bấm vào đó và mở App Store.
"""
import numpy as np
import pytest

from pok.engine.ad_closer import AdCloser
from pok.perception.types import Candidate, TextBox


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, e):
        self.events.append(e)

    def log(self, *a, **k):
        pass


CFG = {
    # 0.0: các test dưới đây kiểm tra cửa HÌNH HỌC / BLOCKLIST / KÍCH THƯỚC,
    # nên tắt cửa "nền trống" để cô lập. Cửa đó có test riêng bên dưới, dùng
    # ảnh quảng cáo thật.
    "min_edge_density": 0.0,
    "edge_band_pct": 0.15,
    "max_area_pct": 0.04,
    "corner_box": 130,
    "blocklist": ["install", "cài đặt", "get", "tải"],
    "close_keywords": ["skip", "đóng", "close"],
    "vlm": {"corners": ["tr", "tl"]},
}
W, H = 410, 898


@pytest.fixture
def closer():
    return AdCloser(CFG, vlm=None, bus=FakeBus())


def bgr():
    return np.zeros((H, W, 3), dtype=np.uint8)


def test_cửa_hình_học_chặn_nút_install_ở_giữa(closer):
    """Toạ độ thật từ benchmark: Florence-2 trả nút Install ở (205,731)."""
    c = Candidate(cx=205, cy=731, w=270, h=62, label="close button", origin="vlm")
    kept = closer.filter_candidates([c], bgr(), [])
    assert kept == []
    assert c.block_reason == "geometry"


def test_cửa_hình_học_chặn_x_giả_ở_giữa(closer):
    """X giả to ở giữa màn, toạ độ thật (205,640)."""
    c = Candidate(cx=205, cy=640, w=78, h=40, label="close button", origin="vlm")
    kept = closer.filter_candidates([c], bgr(), [])
    assert kept == []
    assert c.block_reason == "geometry"


def test_x_thật_ở_góc_được_qua(closer):
    """X thật nhỏ ở góc trên-phải, toạ độ thật (380,44)."""
    c = Candidate(cx=380, cy=44, w=22, h=22, label="close button", origin="vlm")
    kept = closer.filter_candidates([c], bgr(), [])
    assert len(kept) == 1
    assert not c.blocked


def test_cửa_blocklist_chặn_dù_ở_góc(closer):
    c = Candidate(cx=380, cy=44, w=22, h=22, label="close button", origin="vlm")
    texts = [TextBox(text="Install", conf=1.0, cx=385, cy=50, w=50, h=16)]
    kept = closer.filter_candidates([c], bgr(), texts)
    assert kept == []
    assert c.block_reason == "blocklist"


def test_cửa_kích_thước_tương_đối_chặn_box_phủ_hết_crop(closer):
    """Khi không thấy gì trong crop, Florence-2 trả box phủ gần hết crop.

    Với corner_box=130 box đó tình cờ vượt ngưỡng tuyệt đối. Nhưng nếu
    corner_box=120 thì 14400px² < 4%×410×898 = 14727px² -> LỌT nếu không có
    ngưỡng tương đối theo crop.
    """
    box = 120
    c = Candidate(cx=380, cy=60, w=box, h=box, label="close button", origin="vlm")
    kept = closer.filter_candidates([c], bgr(), [], in_crop=True,
                                    crop_area=float(box * box))
    assert kept == []
    assert c.block_reason == "size"


def test_không_tap_lại_đúng_chỗ_vừa_trượt(closer):
    from pok.engine.ad_closer import AdAttempt
    a = AdAttempt()
    a.tried_points.append((0.93, 0.05))
    assert closer.already_tried(a, (0.93, 0.05))
    assert closer.already_tried(a, (0.95, 0.06))
    assert not closer.already_tried(a, (0.07, 0.05))


def test_cửa_nền_trống_dùng_ảnh_thật(closer):
    """Cửa thứ 4: loại ứng viên nằm trên nền trơn.

    Florence-2 trả về box ở vùng nền trắng trống (341,106) trên quảng cáo thật.
    Đo được: nền trống 1.97 · dấu ✕ thật 5.29 -> ngưỡng 3.0.
    """
    import pathlib

    import cv2

    img = cv2.imread(str(pathlib.Path(__file__).parent / "fixtures" / "ad_close_x.png"))
    cfg = dict(CFG, min_edge_density=3.0)
    c2 = AdCloser(cfg, vlm=None, bus=FakeBus())

    trong = Candidate(cx=341, cy=106, w=20, h=20, label="close button", origin="vlm")
    assert c2.filter_candidates([trong], img, [], in_crop=True,
                                crop_area=130.0 * 130) == []
    assert trong.block_reason == "empty_area"

    that = Candidate(cx=32, cy=122, w=13, h=12, label="✕", origin="icon:tl")
    assert len(c2.filter_candidates([that], img, [], in_crop=True,
                                    crop_area=130.0 * 130)) == 1
