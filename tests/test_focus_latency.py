"""1.3 giây giành focus phải nằm TRƯỚC quyết định, không được nằm giữa quyết
định và lúc chuột chạm màn.

Đo thật trên phiên data/sessions/20260830-052421 — 16/16 hành động:

    hành động     sleep lý thuyết     thời gian thật     dư ra
    tap                   0.13s             1.40s        1.27s
    swipe                 0.72s             2.08s        1.36s

Phần dư HẰNG SỐ như nhau cho cả tap lẫn swipe -> không phải do độ dài cú vuốt,
mà là phần mở màn cố định: `_ensure_focus` thấy cửa sổ iPhone Mirroring không
frontmost (người dùng đang nhìn web UI) nên `activate()` + `sleep(0.25)`.

Hậu quả: luật quyết định đúng trên màn A, nhưng 1.3 giây sau chuột mới chạm
màn — lúc đó game đã sang màn B, và cú swipe trái rơi vào màn đang chạy. Cửa
chống-lệch-màn (`STALE_PHASH_DIST`) không cứu được vì nó chạy TRƯỚC 1.3 giây đó.
"""
import time

import numpy as np
import pytest

import pok.engine.machine as machine
from pok.config import Config
from pok.core.actuator import Actuator
from pok.core.safety import SafetyGuard
from pok.engine.machine import BotEngine
from pok.engine.states import BotState
from pok.perception.types import ClassifyResult, ScreenKind, TextBox

W, H = 410, 898


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, e):
        self.events.append(e)

    def log(self, level, msg):
        self.events.append({"type": "log", "level": level, "msg": msg})

    def kinds(self):
        return [e["type"] for e in self.events]


class Win:
    x = y = 0
    w, h, pid = W, H, 999


class Frame:
    def __init__(self, i):
        self.id = i
        self.bgr = np.full((H, W, 3), 40, np.uint8)
        self.win = Win()


class FakeCapture:
    demand = None
    lan_goi = 0

    def latest(self):
        FakeCapture.lan_goi += 1
        return Frame(FakeCapture.lan_goi)


class FakeAct:
    def __init__(self, phai_activate):
        self.phai_activate = phai_activate
        self.calls = []

    def ensure_focus(self, win):
        self.calls.append("focus")
        return self.phai_activate

    def swipe(self, *a, **k):
        self.calls.append("swipe")
        return True

    def tap(self, *a, **k):
        self.calls.append("tap")
        return True


@pytest.fixture
def eng(monkeypatch):
    # không chạy OCR thật — test này thuần logic thứ tự
    monkeypatch.setattr(machine, "classify", lambda *a, **k: ClassifyResult(
        ScreenKind.GAME, "giả", [TextBox("PVP RAID", 0.9, 205, 300, 80, 20)], hf=9.0))
    e = BotEngine(Config(), FakeBus(), FakeCapture())
    e._perm_ok = lambda: True
    e.state = BotState.GAME_PLAY
    e.entered_at = time.time()
    return e


def test_giành_focus_trước_khi_OCR_và_trước_khi_quyết_định(eng):
    """Tick phải hỏi focus trước tiên, rồi vẫn chạy tiếp bình thường."""
    eng.act = FakeAct(phai_activate=True)
    eng._tick()

    assert eng.act.calls[0] == "focus", "phải lấy focus trước khi OCR"
    assert "classify" in eng.bus.kinds()


def test_lấy_focus_không_bao_giờ_được_khoá_vòng_lặp(eng):
    """Regression: `is_frontmost` từng đọc qua NSWorkspace và LUÔN trả False
    (NSWorkspace không cập nhật trong tiến trình không bơm run loop). Lúc đó
    engine bỏ lượt mỗi khi "vừa activate" -> mọi tick đều bỏ -> bot đứng im
    hoàn toàn, và GAME_PLAY không có timeout nên không gì kêu lên.

    Dù `ensure_focus` có báo "vừa activate" ở MỌI tick, luật vẫn phải chạy."""
    eng.act = FakeAct(phai_activate=True)
    for _ in range(3):
        eng._tick()

    assert "swipe" in eng.act.calls, "focus không được phép chặn hành động"


def test_ảnh_được_chụp_lại_sau_khi_cửa_sổ_lên_trước(eng):
    """Ảnh chụp trước lúc activate là ảnh của màn hình khi cửa sổ còn ở dưới —
    không được dùng nó để quyết định."""
    eng.act = FakeAct(phai_activate=True)
    truoc = eng.capture.lan_goi
    eng._tick()
    assert eng.capture.lan_goi > truoc + 1, "phải gọi latest() lại sau activate"


def test_cửa_sổ_đã_frontmost_thì_hành_động_đi_ngay(eng):
    """Đây là trạng thái bình thường sau tick đầu: focus tốn ~0ms, luật bắn
    ngay trên đúng kết quả OCR vừa đọc."""
    eng.act = FakeAct(phai_activate=False)
    eng._tick()

    assert eng.act.calls == ["focus", "swipe"]
    assert "classify" in eng.bus.kinds()


def test_action_event_mang_theo_ms_thật():
    """Không có số này thì không cách nào biết hành động rơi vào màn nào — bug
    1.3 giây đã phải suy ngược từ khoảng cách giữa các event classify."""
    bus = FakeBus()
    guard = SafetyGuard(Config().app)
    guard.kill()                      # chặn ngay, KHÔNG bắn CGEventPost thật
    act = Actuator(guard, bus)

    assert act.tap((0.5, 0.5), Win(), label="thử") is False
    (ev,) = [e for e in bus.events if e.get("type") == "action"]
    assert ev["blocked"] and ev["block_reason"] == "killed"
    assert isinstance(ev["ms"], int) and ev["ms"] >= 0


def test_is_frontmost_không_được_hỏi_NSWorkspace():
    """`NSWorkspace.frontmostApplication()` KHÔNG cập nhật trong tiến trình
    không bơm run loop. Đo trực tiếp: sau `activate(iPhone)` (trả True, 8ms),
    window server báo 'Phản chiếu iPhone' suốt từ +0.25s đến +1.50s, còn
    NSWorkspace vẫn khăng khăng app cũ — mãi mãi.

    Hậu quả đã xảy ra thật: mỗi hành động activate + sleep(0.25) vô ích, rồi khi
    biến nó thành điều kiện chặn thì bot đứng im. Phải hỏi window server."""
    import inspect

    from pok.core import window

    src = inspect.getsource(window.is_frontmost)
    than = src.split('"""')[2]          # bỏ docstring, chỉ xét phần thân hàm
    assert "NSWorkspace" not in than
    assert "CGWindowListCopyWindowInfo" in than
    # pid không tồn tại -> False, không được ném lỗi
    assert window.is_frontmost(-1) is False
