"""Thống kê phiên — quan trọng nhất: ad đóng được ở BƯỚC NÀO của pipeline."""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SessionStats:
    started: float = field(default_factory=time.time)
    ticks: int = 0
    taps: int = 0
    swipes: int = 0
    blocked: int = 0
    ads_seen: int = 0
    ads_closed: int = 0
    ads_failed: int = 0
    # Tap có ăn không — đo bằng `confirm_delay_s`, KHÔNG suy từ closed_by_step.
    # `closed_by_step` chỉ ghi "lúc phát hiện đã về game thì đang ở bước mấy",
    # nên quảng cáo tự tắt trong lúc VLM chạy cũng được tính cho VLM.
    taps_hit: int = 0
    taps_miss: int = 0
    hit_by_origin: dict[str, dict] = field(default_factory=dict)
    closed_by_step: dict[str, int] = field(default_factory=dict)
    block_reasons: dict[str, int] = field(default_factory=dict)
    stuck: int = 0
    watchdog: dict[str, int] = field(default_factory=dict)
    state_seconds: dict[str, float] = field(default_factory=dict)

    def note_close(self, step: str) -> None:
        self.ads_closed += 1
        self.closed_by_step[step] = self.closed_by_step.get(step, 0) + 1

    def note_tap(self, origin: str, hit: bool) -> None:
        """Ghi kết quả THẬT của một cú tap, tách theo nguồn ứng viên.

        Đây là thứ duy nhất trả lời được "tầng nào đang gánh việc": ocr / icon
        (tầng 2b) / vlm:top (tầng C). Không có nó thì mọi so sánh giữa các tầng
        đều là đoán.
        """
        if hit:
            self.taps_hit += 1
        else:
            self.taps_miss += 1
        d = self.hit_by_origin.setdefault(origin, {"hit": 0, "miss": 0})
        d["hit" if hit else "miss"] += 1

    def note_block(self, reason: str) -> None:
        self.blocked += 1
        self.block_reasons[reason] = self.block_reasons.get(reason, 0) + 1

    def note_watchdog(self, kind: str) -> None:
        self.watchdog[kind] = self.watchdog.get(kind, 0) + 1

    def add_state_time(self, state: str, seconds: float) -> None:
        self.state_seconds[state] = self.state_seconds.get(state, 0.0) + seconds

    @property
    def uptime(self) -> float:
        return time.time() - self.started

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uptime"] = round(self.uptime, 1)
        return d

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
