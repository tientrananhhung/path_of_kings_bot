"""PerceptionWorker — chạy model nặng trong thread riêng có queue.

Mục đích: UI (màn Probe) và BotEngine đều gọi được mà không ai chặn ai.
BotEngine gọi đồng bộ (chờ kết quả) vì ở state AD_CLOSING chờ 0.5s là ổn.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Job:
    fn: Callable[[], Any]
    name: str
    result: Any = None
    error: str | None = None
    ms: float = 0.0
    done: threading.Event = None  # type: ignore[assignment]


class PerceptionWorker:
    def __init__(self):
        self.q: queue.Queue[Job] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="perception",
                                        daemon=True)
        self.busy = False
        self.last: dict[str, float] = {}
        self._start_lock = threading.Lock()

    def start(self) -> None:
        """Idempotent. Phải gọi được nhiều lần và từ nhiều nơi."""
        with self._start_lock:
            if not self._thread.is_alive():
                try:
                    self._thread.start()
                except RuntimeError:
                    pass   # đã start trước đó

    def stop(self) -> None:
        self._stop.set()

    def submit(self, fn: Callable[[], Any], name: str = "job") -> Job:
        # Bug đã gặp: worker chỉ được start trong engine.start(). Gọi /api/probe
        # trước khi bấm Start thì job nằm mãi trong queue và run_sync chờ hết
        # timeout (60s × 4 góc) -> request treo. Tự start ở đây.
        self.start()
        job = Job(fn=fn, name=name, done=threading.Event())
        self.q.put(job)
        return job

    def run_sync(self, fn: Callable[[], Any], name: str = "job",
                 timeout: float = 30.0) -> Job:
        job = self.submit(fn, name)
        if not job.done.wait(timeout):
            job.error = f"timeout sau {timeout}s (worker alive={self.alive})"
        return job

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            self.busy = True
            t0 = time.perf_counter()
            try:
                job.result = job.fn()
            except Exception as e:  # noqa: BLE001
                job.error = f"{type(e).__name__}: {e}"
            job.ms = (time.perf_counter() - t0) * 1000
            self.last[job.name] = job.ms
            self.busy = False
            job.done.set()
