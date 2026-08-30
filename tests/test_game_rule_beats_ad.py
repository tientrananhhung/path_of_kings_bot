"""Luật tầng A khớp thì màn đó là GAME, dù `classify` nói AD.

Đây là nửa thứ hai của bug rương vàng (xem test_classify_chest_continue.py).
Kể cả khi keyword đã được siết, `classify` vẫn còn tín hiệu yếu khác (dấu ✕ sát
mép) có thể nhận nhầm màn game. Nếu `_state_game` cứ thấy AD là `return` sang
AD_WATCHING trước khi chạy luật, còn `_state_ad_closing` lại lấy "có luật tầng A
khớp" làm bằng chứng đã về game, thì hai chỗ đá nhau thành vòng lặp kín và bot
không bao giờ hành động. Hai chỗ phải dùng CÙNG một bằng chứng.
"""
import numpy as np
import pytest

from pok.config import Config
from pok.engine.machine import BotEngine
from pok.engine.states import BotState
from pok.perception.types import ClassifyResult, ScreenKind, TextBox

W, H = 410, 898


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, e):
        self.events.append(e)

    def log(self, level, msg, **extra):
        self.events.append({"type": "log", "level": level, "msg": msg})


class FakeCapture:
    demand = None

    def latest(self):
        return None


class FakeAct:
    """Chặn mọi CGEventPost — test không được chạm vào chuột thật."""
    def __init__(self):
        self.done = []

    def tap(self, at, win, **kw):
        self.done.append(("tap", at, kw.get("label")))
        return True

    def swipe(self, a, b, win, **kw):
        self.done.append(("swipe", a, b, kw.get("label")))
        return True

    def hold(self, at, win, **kw):
        self.done.append(("hold", at, kw.get("label")))
        return True


def engine_gia():
    eng = BotEngine(Config(), FakeBus(), FakeCapture())
    eng.act = FakeAct()
    eng.state = BotState.GAME_PLAY
    return eng


def man_hinh(texts):
    """ClassifyResult giả — KHÔNG chạy OCR (test phải thuần logic)."""
    return ClassifyResult(
        ScreenKind.AD, "keyword giả sát mép",
        [TextBox(t, 0.9, cx, cy, 60, 20) for t, cx, cy in texts], hf=6.4)


BGR = np.zeros((H, W, 3), np.uint8)
WIN = {"x": 0, "y": 0, "w": W, "h": H}


def test_classify_AD_nhưng_có_luật_khớp_thì_ở_lại_GAME_PLAY():
    eng = engine_gia()
    # đúng màn rương vàng: nút CONTINUE ở đáy, luật "Rương vàng end" khớp
    eng._state_game(man_hinh([("CONTINUE", 116, 779)]), WIN, BGR, 0.0)

    assert eng.state is BotState.GAME_PLAY
    assert eng.act.done, "phải bấm CONTINUE chứ không được đứng im"
    assert eng.act.done[0][0] == "tap"


def test_classify_AD_mà_không_luật_nào_khớp_thì_vẫn_vào_AD_WATCHING():
    eng = engine_gia()
    eng._state_game(man_hinh([("Install", 200, 730), ("4.8", 60, 60)]),
                    WIN, BGR, 0.0)

    assert eng.state is BotState.AD_WATCHING
    assert not eng.act.done


def test_luật_đã_thử_mà_không_làm_được_thì_hết_là_bằng_chứng():
    """Không có cửa này thì một luật khớp-nhưng-vô-dụng giữ bot ở GAME_PLAY
    vĩnh viễn — GAME_PLAY là state DUY NHẤT không có timeout."""
    eng = engine_gia()
    eng._declined.add("Rương vàng end -> chọn CONTINUE")
    eng._state_game(man_hinh([("CONTINUE", 116, 779)]), WIN, BGR, 0.0)

    assert eng.state is BotState.AD_WATCHING


def test_luật_đang_cooldown_vẫn_là_bằng_chứng_màn_game():
    """Vừa bấm CONTINUE xong, luật vào cooldown 2s. Trong 2s đó màn hình vẫn là
    màn game — không được vì thế mà tụt sang AD_WATCHING."""
    eng = engine_gia()
    rule = next(r for r in eng.rules.rules if "Rương vàng" in r.name)
    eng.rules.note_fired(rule)
    eng._state_game(man_hinh([("CONTINUE", 116, 779)]), WIN, BGR, 0.0)

    assert eng.state is BotState.GAME_PLAY
    assert not eng.act.done      # đang cooldown thì chờ, không bấm lại
