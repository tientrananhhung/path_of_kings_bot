from pok.core.safety import SafetyGuard
from pok.core.window import WindowInfo

W = WindowInfo(id=1, pid=2, name="t", x=1029, y=30, w=410, h=898)
CFG = {"safety": {"max_taps_per_min": 3, "max_hold_ms": 250,
                  "max_consecutive_stuck": 2,
                  "forbidden_zones": [[0.0, 0.9, 1.0, 1.0]]}}


def test_chặn_ngoài_bounds():
    g = SafetyGuard(CFG)
    assert not g.check_action((10, 10), W).allowed
    assert g.check_action((1234, 479), W).reason is None


def test_vùng_cấm():
    g = SafetyGuard(CFG)
    v = g.check_action((1234, 30 + int(0.95 * 898)), W)
    assert not v.allowed and v.reason == "forbidden_zone"


def test_rate_limit():
    g = SafetyGuard(CFG)
    for _ in range(3):
        assert g.check_action((1234, 479), W).allowed
        g.note_action()
    assert g.check_action((1234, 479), W).reason == "rate_limit"


def test_clamp_hold_chống_jiggle_mode():
    g = SafetyGuard(CFG)
    assert g.clamp_hold_ms(2000) == 250
    assert g.clamp_hold_ms(80) == 80


def test_kill_switch():
    g = SafetyGuard(CFG)
    g.kill()
    assert g.check_action((1234, 479), W).reason == "killed"
    g.reset()
    assert g.check_action((1234, 479), W).allowed


def test_stuck_đếm_liên_tiếp():
    g = SafetyGuard(CFG)
    assert not g.note_stuck()
    assert g.note_stuck()
    g.clear_stuck()
    assert not g.note_stuck()
