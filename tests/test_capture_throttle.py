"""Luồng chụp phải hạ nhịp khi không ai tiêu thụ frame.

Chụp 47 FPS khi engine dừng và không có client web nào là tốn ~16% CPU vô ích.
Test này dùng grab giả nên không cần quyền Screen Recording.
"""
import time

import numpy as np
import pytest

import pok.core.capture as cap_mod
from pok.core.capture import CaptureService
from pok.core.window import WindowInfo

WIN = WindowInfo(id=1, pid=2, name="fake", x=0, y=0, w=410, h=898)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(cap_mod, "find", lambda _b: WIN)
    monkeypatch.setattr(cap_mod, "grab",
                        lambda _w: np.zeros((898, 410, 3), dtype=np.uint8))


def measure(svc, secs=1.0):
    time.sleep(0.25)                     # bỏ frame đầu
    a = svc.latest()
    time.sleep(secs)
    b = svc.latest()
    return (b.id - a.id) / secs


def test_chạy_full_fps_khi_có_người_xem(fake):
    svc = CaptureService("x", target_fps=40, idle_fps=4)
    svc.demand = lambda: True
    svc.start()
    try:
        assert measure(svc) > 20
    finally:
        svc.stop()


def test_hạ_nhịp_khi_không_ai_xem(fake):
    svc = CaptureService("x", target_fps=40, idle_fps=4)
    svc.demand = lambda: False
    svc.start()
    try:
        r = measure(svc, 1.5)
        assert r < 8, f"vẫn chạy {r:.1f} fps dù không ai xem"
    finally:
        svc.stop()


def test_đổi_nhịp_ngay_khi_có_người_xem(fake):
    watching = {"on": False}
    svc = CaptureService("x", target_fps=40, idle_fps=4)
    svc.demand = lambda: watching["on"]
    svc.start()
    try:
        assert measure(svc, 1.0) < 8
        watching["on"] = True
        assert measure(svc, 1.0) > 20
    finally:
        svc.stop()


def test_measured_fps_là_nhịp_thật_không_phải_năng_lực(fake):
    """Bug đã gặp: measured_fps chỉ đo phần làm việc, bỏ qua sleep, nên báo
    47 FPS ngay cả khi đang throttle xuống 2 FPS."""
    svc = CaptureService("x", target_fps=40, idle_fps=4)
    svc.demand = lambda: False
    svc.start()
    try:
        time.sleep(1.5)
        assert svc.measured_fps < 8, f"measured_fps={svc.measured_fps:.1f} — sai"
        assert svc.grab_ms >= 0
    finally:
        svc.stop()
