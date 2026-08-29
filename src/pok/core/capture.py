"""CaptureService — một luồng chụp duy nhất, chia sẻ cho mọi tầng và cả web.

Backend: CGWindowListCreateImage. Đã benchmark (poc/README.md):
  15.9ms/frame (63 FPS), chụp RIÊNG cửa sổ, KHÔNG vẽ con trỏ chuột,
  trả point-resolution nên không có bug toạ độ Retina.
Các backend khác đều tệ hơn: pyautogui 112ms + vẽ con trỏ, mss vẽ con trỏ.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np
import Quartz

from .window import WindowInfo, find


@dataclass
class Frame:
    id: int
    ts: float
    bgr: np.ndarray          # HxWx3, BGR
    win: WindowInfo


def _cgimage_to_bgr(img) -> np.ndarray:
    if img is None:
        raise RuntimeError("CGWindowListCreateImage trả None (thiếu quyền Screen Recording?)")
    w = Quartz.CGImageGetWidth(img)
    h = Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    buf = np.frombuffer(data, dtype=np.uint8)
    bgra = buf[: bpr * h].reshape(h, bpr // 4, 4)[:, :w, :]
    return np.ascontiguousarray(bgra[:, :, :3])   # BGRA -> BGR


def grab(win: WindowInfo) -> np.ndarray:
    img = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        win.id,
        Quartz.kCGWindowImageBoundsIgnoreFraming
        | Quartz.kCGWindowImageNominalResolution,
    )
    return _cgimage_to_bgr(img)


def high_freq_energy(bgr: np.ndarray) -> float:
    """Mật độ cạnh. Phân biệt ảnh thật với HÌNH NỀN DESKTOP.

    Khi thiếu quyền Screen Recording, macOS KHÔNG trả ảnh đen — nó trả hình nền
    desktop đã bóc hết cửa sổ. Hình nền có std ~35, cao hơn cả màn game tối,
    nên mọi phép thử kiểu `std > 0` đều cho dương tính giả.
    Đã hiệu chuẩn thật: màn iPhone 1.67-2.04, hình nền 0.46. Ngưỡng 1.0.
    """
    import cv2
    g = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (205, 449),
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    return float((np.abs(np.diff(g, axis=0)).mean()
                  + np.abs(np.diff(g, axis=1)).mean()) / 2)


class CaptureService:
    def __init__(self, bundle_id: str, target_fps: int = 30, ring_size: int = 60,
                 idle_fps: int = 2):
        self.bundle_id = bundle_id
        self.period = 1.0 / max(1, target_fps)
        # Khi không ai tiêu thụ frame (engine dừng VÀ không có client web nào),
        # chụp 47 FPS tốn ~16% CPU một cách vô ích. Hạ xuống idle_fps.
        self.idle_period = 1.0 / max(1, idle_fps)
        self.demand: Callable[[], bool] = lambda: True
        self.ring: deque[Frame] = deque(maxlen=ring_size)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._counter = 0
        self.win: WindowInfo | None = None
        self.last_error: str | None = None
        self.measured_fps = 0.0      # nhịp thật của vòng lặp
        self.grab_ms = 0.0           # thời gian chụp 1 frame (không tính sleep)

    # --- vòng đời ---
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- vòng lặp ---
    def _run(self) -> None:
        recent: deque[float] = deque(maxlen=30)
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                # bounds cửa sổ có thể đổi khi user di chuyển -> refresh mỗi frame,
                # CGWindowListCopyWindowInfo rẻ (~0.3ms).
                win = find(self.bundle_id)
                if win is None:
                    self.win = None
                    self.last_error = "không tìm thấy cửa sổ iPhone Mirroring"
                    time.sleep(0.5)
                    continue
                self.win = win
                bgr = grab(win)
                self._counter += 1
                with self._lock:
                    self.ring.append(Frame(self._counter, time.time(), bgr, win))
                self.last_error = None
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                time.sleep(0.3)

            work = time.perf_counter() - t0
            self.grab_ms = work * 1000
            try:
                period = self.period if self.demand() else self.idle_period
            except Exception:
                period = self.period
            if work < period:
                time.sleep(period - work)

            # measured_fps phải là NHỊP THẬT của vòng lặp (gồm cả sleep), không
            # phải "chạy được bao nhiêu". Trước đây chỉ đo phần làm việc nên nó
            # báo 47 FPS ngay cả khi đang throttle xuống 2 FPS.
            recent.append(time.perf_counter() - t0)
            if recent:
                self.measured_fps = 1.0 / max(1e-6, sum(recent) / len(recent))

    # --- đọc ---
    def latest(self) -> Frame | None:
        with self._lock:
            return self.ring[-1] if self.ring else None

    def snapshot_ring(self) -> list[Frame]:
        with self._lock:
            return list(self.ring)

    def get_by_id(self, frame_id: int) -> Frame | None:
        with self._lock:
            for f in reversed(self.ring):
                if f.id == frame_id:
                    return f
        return None
