"""`min_watch_seconds` là TRẦN, không phải giấc ngủ cố định.

Bug đã gặp — phiên data/sessions/20260830-081318:

    07.05  GAME_PLAY -> AD_WATCHING   (luật khai báo enters_ad)
    12.07  AD_WATCHING -> AD_CLOSING  đã chờ 5.0s   <- quảng cáo CÒN ĐANG TẢI
    12.89  tap bước 3 VLM @ rel (0.906, 0.150)
    14.88  classify APPSTORE                        <- cú tap mở App Store
    57.73  không đóng được -> escalate về Home
    ...    5 cú vuốt Home mới thoát ra

Một cú tap sớm tốn 60 giây. Nhiều quảng cáo hiện nút đóng NGAY nhưng đang tắt,
quanh nó là vòng tròn đếm giờ — vòng tròn là ĐỒ HOẠ nên `countdown_left()`
(đọc chữ) không thấy. Chờ đủ lâu là cách duy nhất hiện có.

Nhưng chờ lâu chỉ an toàn khi nó là TRẦN: cùng phiên đó có 4 lần vào
AD_WATCHING rồi ra ngay vì thật ra chẳng có quảng cáo nào (luật `enters_ad`
báo nhầm). Nếu ngủ cứng 120 giây thì mỗi lần như thế mất trắng 2 phút.
"""
import time

import numpy as np
import pytest

import pok.engine.machine as machine
from pok.config import Config
from pok.engine.machine import BotEngine
from pok.engine.states import TIMEOUTS, BotState
from pok.perception.types import ClassifyResult, ScreenKind, TextBox

W, H = 410, 898
ADS = Config().ads


class Bus:
    def __init__(self): self.events = []
    def publish(self, e): self.events.append(e)
    def log(self, *a, **k): pass


class Win:
    x = y = 0
    w, h, pid = W, H, 999


class Frame:
    def __init__(self): self.id = 1; self.bgr = np.zeros((H, W, 3), np.uint8); self.win = Win()


class Cap:
    demand = None
    def latest(self): return Frame()


def man(kind, chu=()):
    return ClassifyResult(kind, "giả",
                          [TextBox(t, 0.9, 205, 300, 80, 20) for t in chu], hf=9.0)


@pytest.fixture
def eng():
    e = BotEngine(Config(), Bus(), Cap())
    e.state = BotState.AD_WATCHING
    e.entered_at = time.time()
    return e


def anh(seed=1):
    """Ảnh có nội dung để phash phân biệt được hai màn khác nhau."""
    return np.random.default_rng(seed).integers(0, 255, (H, W, 3), np.uint8)


BGR = anh(1)
KHAC = anh(2)          # "màn hình đã đổi" — quảng cáo đã hiện lên


def test_chờ_đủ_lâu_cho_quảng_cáo_tải_xong_rồi_mới_quét():
    """5 giây là quá sớm — đã tap vào ứng viên rác và mở App Store. Nhưng cũng
    không cần dài: `_ad_left` bảo đảm quảng cáo đã hiện rồi mới tính giờ."""
    assert 5.0 < float(ADS["min_watch_seconds"]) <= 15.0


def test_trần_TỔNG_cho_một_quảng_cáo_là_120s():
    """Quảng cáo có thể dài tới 120 giây. Đây là trần cho toàn bộ việc quét tìm
    nút đóng trước khi escalate (vuốt Home, mất phần thưởng) — KHÔNG phải thời
    gian ngồi chờ trước khi bắt đầu quét."""
    assert float(ADS["rescan_max_s"]) >= 120.0


def test_timeout_state_phải_lớn_hơn_mọi_khoảng_chờ():
    """Nếu không, STUCK cắt ngang giữa lúc đang xem hoặc đang quét."""
    assert TIMEOUTS[BotState.AD_WATCHING] > (float(ADS["min_watch_seconds"])
                                             + float(ADS["no_ad_grace_s"]))
    assert TIMEOUTS[BotState.AD_CLOSING] > (float(ADS["rescan_max_s"])
                                            + float(ADS["countdown_max_wait_s"]))


def test_chưa_hết_trần_thì_không_đi_quét(eng):
    """Đây là cú tap đã mở App Store: 5 giây sau khi vào, màn còn đang tải."""
    eng._ad_left = True          # quảng cáo đã hiện lên rồi
    eng.entered_at = time.time() - 5.0
    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)

    assert eng.state is BotState.AD_WATCHING


def test_về_tới_màn_game_thì_ra_NGAY_không_chờ_hết_trần(eng):
    """Luật tầng A khớp = chữ ký màn game. Cùng bằng chứng mà AD_CLOSING dùng."""
    eng._ad_left = True          # quảng cáo đã hiện lên rồi
    eng.entered_at = time.time() - 2.0
    eng._state_ad_watching(man(ScreenKind.GAME, ["PVP RAID"]), Win(), BGR)

    assert eng.state is BotState.GAME_PLAY


def test_hết_trần_thì_mới_sang_quét(eng):
    eng._ad_left = True          # quảng cáo đã hiện lên rồi
    eng.entered_at = time.time() - (float(ADS["min_watch_seconds"]) + 1)
    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)

    assert eng.state is BotState.AD_CLOSING


def test_AD_CLOSING_dùng_chung_bằng_chứng_về_game(eng):
    """Hai state dùng hai tiêu chuẩn khác nhau là công thức tạo vòng lặp."""
    eng.state = BotState.AD_CLOSING
    eng.entered_at = time.time()
    assert eng._back_to_game(man(ScreenKind.GAME, ["PVP RAID"]), BGR) == "có luật tầng A khớp"
    assert eng._back_to_game(man(ScreenKind.HOME), BGR) == "về Home Screen"
    assert eng._back_to_game(man(ScreenKind.AD, ["quảng cáo lạ"]), BGR) is None


# ── phải RỜI màn game rồi mới được kết luận gì ─────────────────────────────

def test_chưa_rời_màn_game_thì_KHÔNG_được_kết_luận_đã_đóng(eng):
    """Regression, phiên data/sessions/20260830-111459 — 187 giây đứng im.

    Luật `enters_ad` bắn lúc 6.3s. 0.2 giây sau bot tự kết luận "quảng cáo đã
    đóng" rồi về GAME_PLAY — trong khi quảng cáo CÒN CHƯA TẢI, màn hình vẫn là
    dialog UPGRADE cũ. Tức chính cái luật vừa mở quảng cáo lại thành bằng chứng
    "đã về game".

    Sau đó quảng cáo hiện lên; `classify` trả GAME (playable không có ✕, không
    keyword) nên không còn đường nào quay lại AD_CLOSING nữa."""
    eng.entered_at = time.time() - 0.2
    eng._state_ad_watching(man(ScreenKind.GAME, ["UPGRADE YOUR GEAR"]), Win(), BGR)

    assert eng.state is BotState.AD_WATCHING


def test_màn_hình_đổi_thì_đánh_dấu_đã_rời(eng):
    """Đường vào bằng luật `enters_ad`: lúc đó màn hình vẫn là màn GAME, phải
    chờ nó đổi mới biết quảng cáo đã hiện."""
    eng._state_ad_watching(man(ScreenKind.GAME), Win(), BGR)    # ghi mốc
    assert eng._ad_left is False

    eng._state_ad_watching(man(ScreenKind.GAME), Win(), KHAC)   # quảng cáo hiện
    assert eng._ad_left is True


def test_rời_rồi_thì_bằng_chứng_về_game_mới_có_giá_trị(eng):
    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)
    eng._state_ad_watching(man(ScreenKind.AD), Win(), KHAC)     # đã rời

    eng._state_ad_watching(man(ScreenKind.GAME, ["PVP RAID"]), Win(), KHAC)
    assert eng.state is BotState.GAME_PLAY


def test_màn_hình_KHÔNG_đổi_sau_grace_thì_kết_luận_không_có_quảng_cáo(eng):
    """Luật `enters_ad` báo nhầm, hoặc game không mở ad lần này. Đừng ngồi hết
    trần 120 giây trên một màn game."""
    eng._state_ad_watching(man(ScreenKind.GAME), Win(), BGR)
    eng.entered_at = time.time() - (float(ADS.get("no_ad_grace_s", 5.0)) + 0.1)

    eng._state_ad_watching(man(ScreenKind.GAME), Win(), BGR)

    assert eng.state is BotState.GAME_PLAY
    assert eng._ad_left is False


def test_grace_không_được_cắt_ngang_việc_xem_quảng_cáo_thật():
    """Grace chỉ áp khi màn hình CHƯA TỪNG đổi. Quảng cáo thật thì `_ad_left`
    đã bật từ lâu trước mốc này."""
    assert float(ADS["no_ad_grace_s"]) < float(ADS["min_watch_seconds"])


def test_classify_nói_AD_thì_KHÔNG_được_áp_cửa_grace(eng):
    """Regression, phiên data/sessions/20260830-154455.

    Quảng cáo end-card nền đen, ảnh TĨNH, có ✕ rõ ở (372,126). Vào AD_WATCHING
    vì classify ra AD — nhưng phash không bao giờ đổi, nên cửa grace kết luận
    "không có quảng cáo nào" rồi về GAME_PLAY. classify lại ra AD, vào lại.
    Vòng lặp 5 giây/lần, không bao giờ tới AD_CLOSING (cần 8s) nên không bao
    giờ tap được dấu ✕ nằm ngay đó.

    `classify == AD` tự nó đã là bằng chứng đang ở trong quảng cáo. Cửa grace
    chỉ dành cho ca vào bằng luật `enters_ad` mà quảng cáo không hiện ra."""
    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)
    assert eng._ad_left is True, "classify AD là đủ, khỏi cần màn hình đổi"

    eng.entered_at = time.time() - (float(ADS["no_ad_grace_s"]) + 1)
    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)      # vẫn ảnh TĨNH
    assert eng.state is BotState.AD_WATCHING, "không được đá ra vì màn không đổi"


def test_ảnh_tĩnh_vẫn_sang_được_AD_CLOSING(eng):
    """Đích đến thật sự: quảng cáo tĩnh phải tới được bước quét nút đóng."""
    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)
    eng.entered_at = time.time() - (float(ADS["min_watch_seconds"]) + 1)

    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)

    assert eng.state is BotState.AD_CLOSING
