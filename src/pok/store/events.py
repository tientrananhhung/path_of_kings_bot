"""EventBus — pub/sub trong process + ghi JSONL ra phiên hiện tại."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable


class EventBus:
    def __init__(self, buffer: int = 500):
        self._subs: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self.recent: deque[dict] = deque(maxlen=buffer)
        self._sink: Path | None = None
        self._fh = None

    def open_session(self, path: Path) -> None:
        self.close_session()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._sink = path
        self._fh = path.open("a", encoding="utf-8")

    def close_session(self) -> None:
        if self._fh:
            try:
                self._fh.close()
            finally:
                self._fh = None
                self._sink = None

    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._subs.append(fn)
        def unsub() -> None:
            with self._lock:
                if fn in self._subs:
                    self._subs.remove(fn)
        return unsub

    def publish(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", time.time())
        with self._lock:
            self.recent.append(event)
            subs = list(self._subs)
            fh = self._fh
        if fh:
            try:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
                fh.flush()
            except Exception:
                pass
        for fn in subs:
            try:
                fn(event)
            except Exception:
                pass

    def log(self, level: str, msg: str, **extra: Any) -> None:
        self.publish({"type": "log", "level": level, "msg": msg, **extra})
