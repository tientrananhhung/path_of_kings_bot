"""Luật text phải chặn được keyword nằm trên HUD cố định.

Bug đã gặp thật (log 06:34:40 của người dùng). Nav bar đáy màn hình của Path of
Kings đọc ra:

    ... | tauern | shop | pup raid | bosses | rank

Luật `contains = "pup raid"` khớp substring trên TOÀN BỘ chữ của màn hình nên
nó khớp ở MỌI màn — kể cả lúc nhân vật đang chạy — và bot quẹt trái không ngừng.
Trên dialog PVP RAID thật, tiêu đề nằm ở y/h = 0.192; nav bar ở đáy ~0.95.
`y_max` tách được hai chỗ đó.
"""
import numpy as np
import pytest

from pok.perception.types import TextBox
from pok.engine.rules import RuleEngine

H, W = 898, 410
BGR = np.zeros((H, W, 3), np.uint8)


def chu(text, ry):
    """TextBox ở vị trí dọc ry (0..1)."""
    return TextBox(text, 0.9, W / 2, ry * H, 80, 20)


def engine(y_max=None):
    when = {"kind": "text", "contains": "pup raid"}
    if y_max is not None:
        when["y_max"] = y_max
    return RuleEngine({"rule": [{
        "name": "PVP RAID", "enabled": True, "priority": 2, "cooldown_s": 0,
        "when": when, "do": {"action": "swipe", "from": [0.5, 0.78], "to": [0.05, 0.78]},
    }]})


NAV = [chu("Section 417-3", 0.10), chu("war actiue!", 0.16),
       chu("tauern", 0.95), chu("shop", 0.95), chu("pup raid", 0.95),
       chu("bosses", 0.95), chu("rank", 0.95)]
DIALOG = [chu("PUP RAID", 0.192), chu("A rival player stole their castle!", 0.28),
          chu("Run", 0.714), chu("PUP RAID", 0.715)] + NAV[2:]


def low(texts):
    return " | ".join(t.text.lower() for t in texts)


def test_nav_bar_đáy_màn_KHÔNG_được_kích_hoạt_luật():
    hit = engine(y_max=0.5).evaluate(BGR, 0.0, low(NAV), texts=NAV)
    assert hit is None


def test_dialog_thật_vẫn_kích_hoạt():
    hit = engine(y_max=0.5).evaluate(BGR, 0.0, low(DIALOG), texts=DIALOG)
    assert hit is not None
    assert hit[1]["y"] == 0.192          # khớp ở TIÊU ĐỀ, không phải nav bar


def test_không_khai_báo_vùng_thì_giữ_nguyên_hành_vi_cũ():
    """Luật cũ không có y_min/y_max phải chạy y như trước — khớp cả nav bar."""
    assert engine().evaluate(BGR, 0.0, low(NAV), texts=NAV) is not None


def test_đây_chính_là_bug_đã_gặp():
    """Cùng một màn hình: không có vùng thì bắn (sai), có vùng thì im (đúng)."""
    assert engine().evaluate(BGR, 0.0, low(NAV), texts=NAV) is not None
    assert engine(y_max=0.5).evaluate(BGR, 0.0, low(NAV), texts=NAV) is None


def test_vùng_hẹp_hơn_thì_loại_cả_tiêu_đề():
    """y_max = 0.15 thì tiêu đề ở 0.192 cũng bị loại — biên được tôn trọng."""
    assert engine(y_max=0.15).evaluate(BGR, 0.0, low(DIALOG), texts=DIALOG) is None


def test_thiếu_texts_thì_luật_có_vùng_không_khớp_bừa():
    """Gọi evaluate mà quên truyền texts -> không được coi là khớp."""
    assert engine(y_max=0.5).evaluate(BGR, 0.0, low(DIALOG)) is None
