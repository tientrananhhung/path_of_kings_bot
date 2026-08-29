"""Cửa kích thước tuyệt đối cho tầng C, và blind tap theo màn hình thật.

Vì sao cần cửa này — số đo, không phải phòng xa. Chạy Florence-2 trên 7 màn
(5 quảng cáo + 2 game) x 2 prompt x 4 góc, lấy mọi ứng viên lọt đủ 4 cửa cũ:

    22 ứng viên, chỉ 3 cái ĐÚNG (lệch < 10pt so với nút đóng thật)
        đúng: 26x26, 47x46, 46x46
        sai : 3x11 3x11 2x11 3x12 14x14 17x17 23x22 32x31 47x46 47x46
              57x50 62x12 65x30 69x63 103x59 104x60 114x72 114x73 129x62

Tức tầng C có độ chính xác 3/22 = 14%. Trong phiên `20260828-155109` nó đã tap
hai lần — (29,115) và (322,67) — trong khi nút skip thật ở (376,123), rồi bot
escalate về Home. Khoảng [20,50] giữ cả 3 cái đúng và loại 15/19 cái sai, còn
lại 4 cái (47x46 x2, 23x22, 32x31) -> độ chính xác 3/7 = 43%.

Cặp 47x46 xuất hiện ở CẢ HAI phía: một cái đúng (tl, lệch 1pt) và một cái sai
(tr, lệch 318pt) trên cùng tấm ảnh. Kích thước không tách nổi hai cái đó — đây
là trần của cửa này, ghi lại để khỏi ai đi siết thêm mà tưởng sẽ khá hơn.

Cửa kích thước TƯƠNG ĐỐI theo crop (`_gate_size`) không tách được: nó chỉ chặn
box phủ gần hết crop, còn box 103-129pt trong ô 130 thì lọt.
"""
import cv2
import numpy as np
import pytest
from pathlib import Path

from pok.engine.ad_closer import AdCloser
from pok.perception.types import Candidate, TextBox

FIX = Path(__file__).parent / "fixtures"

CFG = {
    "min_edge_density": 0.0,        # cô lập cửa kích thước
    "edge_band_pct": 0.15,
    "max_area_pct": 0.04,
    "corner_box": 130,
    "blocklist": ["install", "cài đặt", "download", "tải"],
    "close_keywords": ["skip", "đóng", "close"],
    "vlm": {"corners": ["tr", "tl"], "min_side_pt": 20, "max_side_pt": 50},
    "blind_tap": [{"at": [0.93, 0.10]}, {"at": [0.07, 0.13]}],
}
W, H = 410, 898
CROP_AREA = 130.0 * 130.0


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, e):
        self.events.append(e)

    def log(self, *a, **k):
        pass


@pytest.fixture
def closer():
    return AdCloser(CFG, vlm=None, bus=FakeBus())


def cand(side, cx=376, cy=122):
    return Candidate(cx=cx, cy=cy, w=side, h=side, label="close button",
                     score=1.0, origin="vlm:tr")


def loc(closer, c):
    return closer.filter_candidates(
        [c], np.zeros((H, W, 3), dtype=np.uint8), [], in_corner_crop=True,
        crop_area=CROP_AREA, side_range=(20.0, 50.0))


# ── ba ứng viên ĐÚNG đo được phải lọt ───────────────────────────────────────

@pytest.mark.parametrize("side", [26, 46, 47])
def test_ứng_viên_đúng_đo_được_vẫn_lọt(closer, side):
    assert len(loc(closer, cand(side))) == 1, f"cạnh {side}pt bị chặn oan"


# ── ứng viên SAI nằm ngoài khoảng phải bị chặn ──────────────────────────────

# Đúng kích thước ĐO ĐƯỢC, không phải box vuông: một box vuông 114pt có diện
# tích vượt 4% cửa sổ nên bị cửa `size` chặn trước, không kiểm được cửa `side`.
@pytest.mark.parametrize("w,h", [
    (3, 11), (3, 12), (14, 14), (17, 17),          # quá nhỏ
    (57, 50), (62, 12), (65, 30), (69, 63),        # quá to
    (103, 59), (104, 60), (114, 72), (114, 73), (129, 62),
])
def test_ứng_viên_sai_ngoài_khoảng_bị_chặn(closer, w, h):
    c = Candidate(cx=376, cy=122, w=w, h=h, label="close button",
                  score=1.0, origin="vlm:tr")
    assert loc(closer, c) == []
    assert c.block_reason == "side", \
        f"{w}x{h} bị chặn vì {c.block_reason}, không phải cửa cạnh"


@pytest.mark.parametrize("w,h", [(47, 46), (23, 22), (32, 31)])
def test_bốn_ứng_viên_sai_còn_lọt_là_trần_của_cửa_này(closer, w, h):
    """Ghi lại giới hạn đã biết thay vì giả vờ cửa này sạch 100%."""
    c = Candidate(cx=376, cy=122, w=w, h=h, label="close button",
                  score=1.0, origin="vlm:tr")
    assert len(loc(closer, c)) == 1


def test_cửa_tương_đối_theo_crop_không_thay_thế_được_cửa_này(closer):
    """Box 114pt trong ô 130 chỉ chiếm 77% crop -> `_gate_size` cho lọt."""
    c = cand(114)
    assert closer._gate_size(c, W, H, CROP_AREA) is False   # 114² > 4% cửa sổ
    nho = Candidate(cx=376, cy=122, w=114, h=60, label="x", score=1, origin="vlm:tr")
    assert closer._gate_size(nho, W, H, CROP_AREA) is True  # lọt cửa cũ...
    assert closer._gate_side(nho, (20.0, 50.0)) is False    # ...nhưng cạnh 114


def test_không_truyền_side_range_thì_cửa_này_tắt(closer):
    """Bước 2/2b không dùng cửa này — nó chỉ hợp lệ cho tầng C."""
    c = Candidate(cx=376, cy=122, w=114, h=60, label="x", score=1,
                  origin="vlm:tr")
    kept = closer.filter_candidates(
        [c], np.zeros((H, W, 3), dtype=np.uint8), [],
        in_corner_crop=True, crop_area=CROP_AREA)
    assert len(kept) == 1


# ── blind tap ───────────────────────────────────────────────────────────────

def test_blind_tap_quy_đổi_theo_màn_hình_thật_không_phải_cửa_sổ(closer):
    """(0.93, 0.10) phải ra điểm trên MÀN HÌNH, không phải trên cửa sổ.

    Theo cửa sổ: (381, 90). Theo màn hình (8,38,394,852): (374, 123) — đúng chỗ
    nút skip thật (376,123) của quảng cáo playable đã đo.
    """
    img = cv2.imread(str(FIX / "ad_playable_skip.png"))
    diem = closer.blind_points(img, [])
    assert diem, "không còn điểm blind tap nào"
    x, y = diem[0][0] * W, diem[0][1] * H
    lech = ((x - 376) ** 2 + (y - 123) ** 2) ** 0.5
    assert lech < 12, f"blind tap đầu tiên lệch {lech:.0f}pt — ({x:.0f},{y:.0f})"


def test_blind_tap_bị_chặn_khi_rơi_gần_nút_tải(closer):
    """Blind tap là điểm ĐOÁN, phải đi qua blocklist như mọi ứng viên khác.

    Trên quảng cáo playable thật, điểm trái ở (35,149) cách chữ "Download"
    của biểu tượng app chỉ ~37pt — nằm trong bán kính 40pt của cửa blocklist.
    """
    img = cv2.imread(str(FIX / "ad_playable_skip.png"))
    texts = [TextBox(text="Download", conf=1.0, cx=51, cy=175, w=60, h=14)]
    truoc = closer.blind_points(img, [])
    sau = closer.blind_points(img, texts)
    assert len(sau) < len(truoc), "blocklist không chặn được blind tap nào"
    assert any(e["reason"] == "blocklist" and e["origin"] == "blind"
               for e in closer.bus.events), "không publish event bị chặn"
