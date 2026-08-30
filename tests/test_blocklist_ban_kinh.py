"""Cửa blocklist không được vứt đi dấu ✕ đúng.

Bug đã gặp thật — phiên data/sessions/20260830-080353, 46 giây bot đứng im:

    06:xx classify AD | dấu ✕ sát mép @(372,68) điểm=0.60
    06:xx   chặn [blocklist] ✕ icon @(372,68) nearby=['play now']
    ... lặp lại 20 lần, mỗi 2 giây, cho tới khi người dùng tắt tay

`classify` dùng CHÍNH dấu ✕ đó làm bằng chứng "đây là quảng cáo", rồi
`filter_candidates` vứt đúng dấu ✕ đó đi vì "không an toàn". Hai chỗ mâu thuẫn
nhau, và quảng cáo dễ nhất — có ✕ to rõ ở góc — trở thành ca bot không đóng nổi.

Hai nguyên nhân, sửa cả hai:

1. `ocr.text_near` cộng NỬA CHIỀU RỘNG hộp chữ vào bán kính. "PLAY NOW" hộp
   94x18 -> vùng cấm phình ra ±87pt theo trục x. Chiều dài một chuỗi chữ không
   nói gì về vị trí nút bấm.
2. Cùng một bán kính áp cho cả ứng viên VLM (model đoán) lẫn dấu ✕ (hình học).
"""
from pathlib import Path

import cv2
import pytest

from pok.config import Config
from pok.engine.ad_closer import AdCloser
from pok.perception.ocr import recognize, text_near
from pok.perception.types import Candidate, TextBox

FIX = Path(__file__).parent / "fixtures"
ADS = Config().ads

# Số đo thật trên tests/fixtures/ad_x_gan_play_now.png
X_THAT = (372, 68)
PLAY_NOW = TextBox("PLAY NOW", 0.9, 317, 115, 94, 18)
KHOANG_CACH_TOI_CANH = 38.8


class Bus:
    def publish(self, e): pass
    def log(self, *a, **k): pass


@pytest.fixture
def closer():
    return AdCloser(ADS, vlm=None, bus=Bus())


def cand(origin="icon", cx=X_THAT[0], cy=X_THAT[1]):
    return Candidate(cx=cx, cy=cy, w=14, h=14, label="✕", score=0.6,
                     origin=origin)


# ── ca thật ────────────────────────────────────────────────────────────────

def test_dấu_X_của_quảng_cáo_thật_phải_qua_được_lọc(closer):
    """Ca kết thúc 46 giây bot đứng im. Chạy trên ảnh chụp thật của phiên đó."""
    img = cv2.imread(str(FIX / "ad_x_gan_play_now.png"))
    assert img is not None
    h, w = img.shape[:2]

    qua = closer.step_icon(img, recognize(img))

    assert len(qua) == 1, "dấu ✕ ở (372,68) phải qua được lọc"
    c = qua[0]
    assert abs(c.cx - X_THAT[0]) <= 2 and abs(c.cy - X_THAT[1]) <= 2


def test_ngưỡng_nằm_đúng_hai_bên_khoảng_cách_đo_được():
    """38.8pt — mức 40 của VLM chặn, mức 20 của icon cho qua. Đổi hai số này
    thì phải đổi có ý thức, không phải vô tình."""
    r_vlm = float(ADS.get("blocklist_radius_pt", 40))
    r_icon = float(ADS.get("blocklist_radius_icon_pt", 20))
    assert r_icon < KHOANG_CACH_TOI_CANH < r_vlm


def test_ứng_viên_VLM_ở_đúng_chỗ_đó_vẫn_bị_chặn(closer):
    """Nới cho tầng 2b KHÔNG được nới cho tầng C — Florence-2 đã thực sự gán
    nhãn nút Install là "close button"."""
    ok, _ = closer._gate_blocklist(cand(origin="vlm:top"), [PLAY_NOW])
    assert ok is False


def test_dấu_X_ở_đúng_chỗ_đó_thì_qua(closer):
    ok, _ = closer._gate_blocklist(cand(origin="icon"), [PLAY_NOW])
    assert ok is True


# ── an toàn: vẫn phải chặn nút cài đặt ─────────────────────────────────────

@pytest.mark.parametrize("cach_canh", [0, 5, 15, 19])
def test_vẫn_chặn_khi_sát_nút_Install(closer, cach_canh):
    """Nới bán kính không được phép mở đường tap vào nút cài app."""
    t = TextBox("Install", 0.9, 200 + 30 + cach_canh, 700, 60, 20)
    ok, near = closer._gate_blocklist(cand(origin="icon", cx=200, cy=700), [t])
    assert ok is False and near == ["install"]


def test_điểm_nằm_TRONG_hộp_chữ_luôn_bị_chặn(closer):
    """Tap thẳng vào chữ thì bất kể nguồn nào cũng sai."""
    t = TextBox("Install", 0.9, 200, 700, 60, 20)
    ok, _ = closer._gate_blocklist(cand(origin="icon", cx=200, cy=700), [t])
    assert ok is False


# ── phép đo khoảng cách ────────────────────────────────────────────────────

def test_chiều_dài_chuỗi_chữ_không_làm_phình_vùng_cấm():
    """Luật cũ cộng nửa chiều rộng hộp chữ vào bán kính: chữ dài gấp đôi thì
    vùng cấm rộng gấp đôi, dù nút bấm chẳng dịch đi đâu."""
    ngan = TextBox("get", 0.9, 100, 100, 20, 18)
    dai = TextBox("get the app now", 0.9, 100, 100, 200, 18)

    # điểm cách TÂM 60pt, nằm ngoài cả hai hộp theo trục x
    assert text_near([ngan], 160, 100, radius=40) == []
    assert text_near([dai], 160, 100, radius=40) == ["get the app now"]  # vẫn nằm TRONG hộp

    # điểm cách CẠNH của hộp dài đúng 50pt -> ngoài bán kính 40
    assert text_near([dai], 100 + 100 + 50, 100, radius=40) == []
