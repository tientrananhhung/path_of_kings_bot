from pok.core.coords import inside, local_to_rel, rel_to_local, rel_to_screen
from pok.core.window import WindowInfo

W = WindowInfo(id=1, pid=2, name="test", x=1029, y=30, w=410, h=898)


def test_rel_to_local():
    assert rel_to_local((0.0, 0.0), W) == (0, 0)
    assert rel_to_local((1.0, 1.0), W) == (410, 898)
    assert rel_to_local((0.5, 0.5), W) == (205, 449)


def test_rel_to_screen_adds_window_origin():
    assert rel_to_screen((0.0, 0.0), W) == (1029, 30)
    assert rel_to_screen((0.5, 0.5), W) == (1234, 479)


def test_roundtrip():
    for rel in [(0.1, 0.2), (0.93, 0.05), (0.5, 0.86)]:
        local = rel_to_local(rel, W)
        back = local_to_rel(local, W)
        assert abs(back[0] - rel[0]) < 0.005
        assert abs(back[1] - rel[1]) < 0.005


def test_inside_bounds():
    assert inside((1029, 30), W)
    assert inside((1439, 928), W)
    assert not inside((1028, 30), W)
    assert not inside((1234, 929), W)
