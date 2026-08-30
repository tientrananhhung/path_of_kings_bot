"""Bước 2c — detector tự train, đứng giữa 2b (dò ✕) và tầng C (Florence-2).

Vì sao thêm tầng này: `close_icon` ở 2b là luật VIẾT TAY cho đúng một hình
(mực trên hai đường chéo, đường giữa trống), nên nút tròn `▶▶|` của quảng cáo
playable hay nút đóng đang tắt có vành đếm giờ thì nó mù. YOLO là chính nó
phiên bản tự học — cùng vai trò, học được nhiều hình.

Đặt TRƯỚC tầng C vì rẻ hơn ~30 lần (20ms so với 600ms).

CHƯA CÓ MODEL. Yêu cầu quan trọng nhất của bộ test này: thiếu model thì
pipeline phải chạy y hệt như trước, không lỗi, không đứng.
"""
import time

import numpy as np
import pytest

from pok.config import Config
from pok.engine.ad_closer import AdAttempt, AdCloser
from pok.engine.machine import BotEngine
from pok.engine.states import BotState
from pok.perception.types import Candidate, ClassifyResult, ScreenKind, TextBox
from pok.perception.yolo import YoloDetector

W, H = 410, 898


class Bus:
    def publish(self, e): pass
    def log(self, *a, **k): pass


class Cap:
    demand = None
    def latest(self): return None


class YoloGia:
    """Detector giả — trả về đúng thứ đã hẹn, đếm số lần bị gọi."""
    def __init__(self, cands=(), enabled=True):
        self.cands, self.enabled, self.goi = list(cands), enabled, 0

    def detect(self, bgr):
        self.goi += 1
        return list(self.cands)

    def info(self): return {"enabled": self.enabled}


def anh(seed=1):
    return np.random.default_rng(seed).integers(0, 255, (H, W, 3), np.uint8)


def cand(cx=372, cy=68, side=14, score=0.9):
    return Candidate(cx=cx, cy=cy, w=side, h=side, label="close_button",
                     score=score, origin="yolo")


# ── chưa có model: không được làm hỏng gì ──────────────────────────────────

def test_chưa_có_model_thì_tắt():
    d = YoloDetector({"yolo": {"enabled": True,
                               "model": "data/models/khong-ton-tai.pt"}})
    assert d.enabled is False
    assert d.detect(anh()) == []
    assert "không thấy file trọng số" in d.load_error


def test_bật_mà_mất_file_model_thì_tự_tắt():
    """File trọng số nằm trong data/ nên KHÔNG lên git. Máy khác clone về sẽ
    thiếu nó — lúc đó bước 2c phải tự bỏ qua, không được để engine ném lỗi mỗi
    2 giây giữa lúc đang đóng quảng cáo."""
    cfg = dict(Config().ads)
    cfg["yolo"] = {**cfg.get("yolo", {}), "model": "data/models/khong-co.pt"}
    d = YoloDetector(cfg)
    assert d.want is True and d.enabled is False
    assert d.detect(anh()) == []


def test_lọc_theo_class():
    """Để rỗng thì nhận hết. Đo thật: model hiện tại định vị đúng dấu ✕ (lệch
    2pt) nhưng gán nhãn `normal_arrow`, nên lọc theo class sẽ vứt đi đúng thứ
    duy nhất nó làm được."""
    goc = Config().ads
    assert YoloDetector(goc).classes == set(), "mặc định phải nhận mọi class"

    cfg = dict(goc)
    cfg["yolo"] = {**goc.get("yolo", {}), "classes": ["close_button"]}
    assert YoloDetector(cfg).classes == {"close_button"}


def test_không_có_detector_thì_bước_2c_trả_rỗng():
    closer = AdCloser(Config().ads, vlm=None, bus=Bus(), yolo=None)
    assert closer.step_yolo(anh(), []) == []


# ── có model: đi qua ĐỦ cửa lọc như mọi tầng khác ──────────────────────────

@pytest.fixture
def closer():
    return AdCloser(Config().ads, vlm=None, bus=Bus(), yolo=None)


def test_ứng_viên_giữa_màn_bị_cửa_hình_học_chặn(closer):
    """Không được miễn trừ chỉ vì nó là model của mình. Cửa lọc là thứ duy nhất
    từng chặn được việc bot tap vào nút Install."""
    closer.yolo = YoloGia([cand(cx=205, cy=449)])      # giữa màn
    assert closer.step_yolo(anh(), []) == []


def test_ứng_viên_sát_mép_thì_qua(closer):
    closer.yolo = YoloGia([cand(cx=372, cy=68)])
    (c,) = closer.step_yolo(anh(), [])
    assert (c.cx, c.cy) == (372, 68) and c.origin == "yolo"


def test_vẫn_chặn_khi_sát_nút_Install(closer):
    closer.yolo = YoloGia([cand(cx=372, cy=68)])
    chu = [TextBox("Install", 0.9, 372, 90, 60, 20)]
    assert closer.step_yolo(anh(), chu) == []


def test_KHÔNG_áp_cửa_side_của_Florence(closer):
    """Khoảng [20,50] đo riêng cho Florence-2 trên crop góc 130x130. Áp cho
    detector khác là mượn số đo của một chế độ không liên quan — dấu ✕ thật
    14x14 sẽ bị chặn oan."""
    closer.yolo = YoloGia([cand(cx=372, cy=68, side=14)])
    assert len(closer.step_yolo(anh(), [])) == 1


# ── vị trí trong pipeline ──────────────────────────────────────────────────

@pytest.fixture
def eng():
    e = BotEngine(Config(), Bus(), Cap())
    e.act = type("A", (), {"tap": lambda s, *a, **k: True,
                           "swipe": lambda s, *a, **k: True,
                           "home_gesture": lambda s, *a, **k: True,
                           "ensure_focus": lambda s, w: False})()
    e.state = BotState.AD_CLOSING
    e.entered_at = time.time()
    e.attempt = AdAttempt()
    e.attempt.last_scan = 0.0
    return e


def man_quang_cao():
    return ClassifyResult(ScreenKind.AD, "quảng cáo lạ", [], hf=9.0)


def test_2c_chạy_TRƯỚC_tầng_C(eng):
    """Rẻ hơn 30 lần thì phải được hỏi trước."""
    eng.closer.yolo = YoloGia([cand()])
    eng.vlm.enabled = True
    goi_vlm = []
    eng.closer.step_vlm_top = lambda *a, **k: goi_vlm.append(1) or []

    eng._state_ad_closing(man_quang_cao(), object(), anh())

    assert eng.closer.yolo.goi == 1
    assert goi_vlm == [], "2c ra ứng viên thì không được đụng tới VLM"
    assert eng.attempt.step == 23      # 23 = bước 2c trong closed_by_step


def test_2c_trượt_thì_rơi_xuống_tầng_C(eng):
    eng.closer.yolo = YoloGia([])
    eng.vlm.enabled = True
    goi_vlm = []
    eng.closer.step_vlm_top = lambda *a, **k: goi_vlm.append(1) or []

    eng._state_ad_closing(man_quang_cao(), object(), anh())

    assert eng.closer.yolo.goi == 1 and goi_vlm == [1]


def test_cú_tap_của_2c_cũng_được_ghi_làm_mẫu(eng):
    """Mọi tầng đều góp mẫu huấn luyện, không riêng VLM."""
    eng.closer.yolo = YoloGia([cand()])
    eng._state_ad_closing(man_quang_cao(), object(), anh())

    assert eng.attempt.pending is not None
    assert eng.attempt.pending["origin"] == "yolo"
    assert eng.attempt.pending["step"] == "2c"


def test_KHÔNG_áp_cửa_nền_trống_cho_2c(closer):
    """Cửa `min_edge_density` đo cho Florence-2 — nó sinh ra để chặn VLM bịa
    box trên vùng nền trống. Detector tự train không có tật đó.

    Và trên ảnh thật nó KHÔNG tách nổi hai thứ (end-card nền xám phẳng của
    quảng cáo video):

        nút ▶▶| THẬT   2.52
        nền tối trống  2.34

    chênh 0.18. Hạ ngưỡng để nhận nút thì nhận luôn nền trống — dùng sai công
    cụ, không phải sai ngưỡng. Model đã học đúng nút này rồi mà vẫn bị chính
    cửa lọc của mình vứt đi."""
    import numpy as np
    phang = np.full((H, W, 3), 60, np.uint8)          # nền phẳng, mật độ cạnh ~0
    closer.yolo = YoloGia([cand(cx=376, cy=122, side=28)])

    (c,) = closer.step_yolo(phang, [])
    assert (c.cx, c.cy) == (376, 122)


def test_tầng_C_thì_VẪN_áp_cửa_nền_trống(closer):
    """Nới cho 2c không được nới cho tầng C."""
    import numpy as np
    from pok.perception.types import Candidate
    phang = np.full((H, W, 3), 60, np.uint8)
    c = Candidate(cx=376, cy=122, w=28, h=28, label="circle button",
                  score=1.0, origin="vlm:top")

    assert closer.filter_candidates([c], phang, []) == []
    assert c.block_reason == "empty_area"
