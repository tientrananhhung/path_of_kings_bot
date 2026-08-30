"""Đo cú tap có ăn không, và biến kết quả đó thành mẫu huấn luyện.

Vì sao cần: `closed_by_step` chỉ ghi "lúc phát hiện đã về game thì đang ở bước
mấy". Quảng cáo TỰ tắt trong lúc VLM chạy 0.6s cũng được tính cho VLM. Nên con
số đang có — 2b đóng 4 lần, VLM đóng 7 lần — không chứng minh được điều gì, và
không thể dùng để so tầng nào hơn tầng nào.

Và vì nhãn để train detector cần đúng ba thứ (ảnh · khung · class) mà cả ba đều
đã nằm sẵn trong vòng đời một lần đóng quảng cáo, chỉ là trước giờ bị vứt đi.
"""
import json
import time

import cv2
import numpy as np
import pytest

from pok.engine.ad_closer import AdAttempt
from pok.engine.machine import BotEngine
from pok.engine.states import BotState
from pok.perception import cheap
from pok.perception.types import Candidate, ClassifyResult, ScreenKind, TextBox
from pok.store.samples import SampleWriter
from pok.config import Config

W, H = 410, 898


class Bus:
    def __init__(self): self.msgs = []
    def publish(self, e): pass
    def log(self, lv, msg, **k): self.msgs.append(msg)


class Cap:
    demand = None
    def latest(self): return None


def anh(seed):
    """Ảnh có nội dung thật để phash phân biệt được."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (H, W, 3), dtype=np.uint8)


@pytest.fixture
def eng(tmp_path):
    e = BotEngine(Config(), Bus(), Cap())
    e.samples = SampleWriter(tmp_path, enabled=True)
    e.state = BotState.AD_CLOSING
    e.entered_at = time.time()
    return e


def cand(cx=372, cy=68, origin="icon"):
    return Candidate(cx=cx, cy=cy, w=14, h=14, label="✕", score=0.6, origin=origin)


def dat_tap(eng, a, img, tre_s=0.0, origin="icon"):
    eng._note_tap(a, img, cand(origin=origin), "2b", "✕ điểm=0.6")
    a.pending["at"] -= tre_s
    return a


# ── kết cục hit ────────────────────────────────────────────────────────────

def test_về_được_màn_game_thì_là_TRÚNG(eng, tmp_path):
    a = AdAttempt()
    img = anh(1)
    dat_tap(eng, a, img)

    eng._confirm_tap(a, anh(2), back="có luật tầng A khớp")

    assert eng.stats.taps_hit == 1 and eng.stats.taps_miss == 0
    assert eng.stats.hit_by_origin["icon"] == {"hit": 1, "miss": 0}
    assert a.pending is None


def test_mẫu_lưu_ĐÚNG_ảnh_trước_lúc_tap(eng, tmp_path):
    """Sau cú tap màn hình đã đổi — chụp lại lúc đó là muộn. Mẫu phải là frame
    ngay TRƯỚC khi tap, nếu không nhãn chỉ vào một tấm ảnh khác."""
    truoc, sau = anh(1), anh(2)
    a = AdAttempt()
    dat_tap(eng, a, truoc)

    eng._confirm_tap(a, sau, back="về Home Screen")

    (dong,) = [json.loads(l) for l in (tmp_path / "index.jsonl").read_text().splitlines()]
    luu = cv2.imread(str(tmp_path / dong["image"]))
    assert cheap.phash_distance(cheap.phash(luu), cheap.phash(truoc)) == 0
    assert cheap.phash_distance(cheap.phash(luu), cheap.phash(sau)) > 3


def test_nhãn_ghi_đủ_ba_thứ_cần_để_train(eng, tmp_path):
    a = AdAttempt()
    dat_tap(eng, a, anh(1))
    eng._confirm_tap(a, anh(2), back="có luật tầng A khớp")

    (d,) = [json.loads(l) for l in (tmp_path / "index.jsonl").read_text().splitlines()]
    assert d["image"].endswith(".png")                      # ảnh
    assert d["box"] == {"cx": 372.0, "cy": 68.0, "w": 14.0, "h": 14.0}   # khung
    assert d["outcome"] == "hit"                            # class
    assert d["img_w"] == W and d["img_h"] == H
    assert d["origin"] == "icon" and d["step"] == "2b"


# ── kết cục miss ───────────────────────────────────────────────────────────

def test_màn_hình_y_nguyên_sau_cửa_sổ_chờ_là_TRƯỢT(eng, tmp_path):
    img = anh(1)
    a = AdAttempt()
    dat_tap(eng, a, img, tre_s=5.0)

    eng._confirm_tap(a, img, back=None)          # cùng ảnh -> phash không đổi

    assert eng.stats.taps_miss == 1 and eng.stats.taps_hit == 0
    assert json.loads((tmp_path / "index.jsonl").read_text())["outcome"] == "miss"


def test_chưa_hết_cửa_sổ_chờ_thì_chưa_kết_luận(eng, tmp_path):
    img = anh(1)
    a = AdAttempt()
    dat_tap(eng, a, img, tre_s=0.0)

    eng._confirm_tap(a, img, back=None)

    assert a.pending is not None, "phải chờ đủ confirm_delay_s mới kết luận"
    assert eng.stats.taps_hit == eng.stats.taps_miss == 0
    assert not (tmp_path / "index.jsonl").exists()


def test_màn_đổi_nhưng_vẫn_ở_quảng_cáo_thì_KHÔNG_ghi_mẫu(eng, tmp_path):
    """Không kết luận được: có thể do chính quảng cáo chuyển cảnh. Ghi bừa vào
    tập huấn luyện là dạy model học nhiễu."""
    a = AdAttempt()
    dat_tap(eng, a, anh(1), tre_s=5.0)

    eng._confirm_tap(a, anh(9), back=None)

    assert a.pending is None
    assert eng.stats.taps_hit == eng.stats.taps_miss == 0
    assert not (tmp_path / "index.jsonl").exists()


# ── tách theo tầng: mục đích chính của cả việc này ─────────────────────────

def test_thống_kê_tách_theo_TẦNG_sinh_ra_ứng_viên(eng):
    for origin, back in [("icon", "về game"), ("icon", None),
                         ("vlm:top", None), ("ocr", "về game")]:
        a = AdAttempt()
        dat_tap(eng, a, anh(1), tre_s=5.0, origin=origin)
        eng._confirm_tap(a, anh(1), back=back)

    assert eng.stats.hit_by_origin == {
        "icon": {"hit": 1, "miss": 1},
        "vlm:top": {"hit": 0, "miss": 1},
        "ocr": {"hit": 1, "miss": 0},
    }


def test_tắt_thu_thập_thì_không_ghi_gì(eng, tmp_path):
    eng.samples.enabled = False
    a = AdAttempt()
    dat_tap(eng, a, anh(1))
    eng._confirm_tap(a, anh(2), back="về game")

    assert eng.stats.taps_hit == 1, "vẫn phải đếm, chỉ không ghi ảnh"
    assert not (tmp_path / "index.jsonl").exists()


def test_lỗi_ghi_đĩa_không_được_làm_chết_bot(eng):
    eng.samples.root = eng.samples.root / "khong-the-tao" / "\0"
    a = AdAttempt()
    dat_tap(eng, a, anh(1))
    eng._confirm_tap(a, anh(2), back="về game")      # không được ném lỗi

    assert eng.stats.taps_hit == 1


# ── mẫu KHÓ: cả ba tầng đều bó tay ─────────────────────────────────────────

class ActGia:
    def __init__(self): self.lam = []
    def tap(self, *a, **k): self.lam.append("tap"); return True
    def swipe(self, *a, **k): self.lam.append("swipe"); return True
    def home_gesture(self, *a, **k): self.lam.append("home"); return True
    def ensure_focus(self, win): return False


def test_escalate_lưu_frame_làm_mẫu_khó(eng, tmp_path):
    """Quảng cáo không tầng nào đóng nổi là mẫu QUÝ NHẤT — và phải lưu đúng lúc
    escalate. Ngay sau đó là gesture Home, màn hình đó biến mất; chờ người dùng
    tự bấm chụp thì gần như luôn muộn."""
    eng.act = ActGia()
    eng.vlm.enabled = False
    eng.closer.yolo = None          # test thuần logic, không nạp model thật
    a = AdAttempt()
    a.started = time.time() - 999          # đã quét quá rescan_max_s
    a.tried_points = [(0.907, 0.076, time.time()), (0.137, 0.126, time.time())]
    a.last_scan = 0.0
    eng.attempt = a

    eng._state_ad_closing(ClassifyResult(ScreenKind.AD, "quảng cáo lạ", [], hf=9.0),
                          object(), anh(1))

    (d,) = [json.loads(l) for l in (tmp_path / "index.jsonl").read_text().splitlines()]
    assert d["outcome"] == "fail"
    assert d["box"] is None, "bó tay thì không có toạ độ nào để ghi"
    assert d["tried"] == [[0.907, 0.076], [0.137, 0.126]], "phải ghi đã thử chỗ nào"
    assert (tmp_path / d["image"]).exists()
    assert eng.act.lam == ["home"], "vẫn phải escalate như cũ"
    assert eng.stats.ads_failed == 1
