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


BGR = np.zeros((H, W, 3), np.uint8)


def test_trần_đủ_dài_để_quảng_cáo_tải_xong():
    assert float(ADS.get("min_watch_seconds", 5.0)) >= 120.0


def test_timeout_state_phải_lớn_hơn_trần():
    """Nếu không, STUCK cắt ngang đúng lúc đang ngồi xem cho hết quảng cáo."""
    assert TIMEOUTS[BotState.AD_WATCHING] > float(ADS.get("min_watch_seconds"))


def test_chưa_hết_trần_thì_không_đi_quét(eng):
    """Đây là cú tap đã mở App Store: 5 giây sau khi vào, màn còn đang tải."""
    eng.entered_at = time.time() - 5.0
    eng._state_ad_watching(man(ScreenKind.AD), Win(), BGR)

    assert eng.state is BotState.AD_WATCHING


def test_về_tới_màn_game_thì_ra_NGAY_không_chờ_hết_trần(eng):
    """Luật tầng A khớp = chữ ký màn game. Cùng bằng chứng mà AD_CLOSING dùng."""
    eng.entered_at = time.time() - 2.0
    eng._state_ad_watching(man(ScreenKind.GAME, ["PVP RAID"]), Win(), BGR)

    assert eng.state is BotState.GAME_PLAY


def test_hết_trần_thì_mới_sang_quét(eng):
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
