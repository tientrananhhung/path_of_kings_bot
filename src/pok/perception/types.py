from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ScreenKind(str, Enum):
    UNKNOWN = "UNKNOWN"
    GAME = "GAME"
    AD = "AD"
    PAUSE = "PAUSE"          # "iPhone đang được sử dụng"
    HOME = "HOME"
    SPOTLIGHT = "SPOTLIGHT"
    JIGGLE = "JIGGLE"        # chế độ chỉnh sửa icon
    APPSTORE = "APPSTORE"
    NO_CONTENT = "NO_CONTENT"  # chụp ra hình nền desktop -> thiếu quyền


@dataclass
class TextBox:
    text: str
    conf: float
    cx: float          # local point
    cy: float
    w: float
    h: float

    @property
    def rel_center(self) -> tuple[float, float]:
        return (self.cx, self.cy)


@dataclass
class Candidate:
    """Ứng viên nút đóng quảng cáo."""
    cx: float                    # local point
    cy: float
    w: float
    h: float
    label: str
    score: float = 0.0
    origin: str = ""             # "ocr" | "vlm:tr" | "blind"
    blocked: bool = False
    block_reason: str | None = None
    nearby_text: list[str] = field(default_factory=list)


@dataclass
class ClassifyResult:
    kind: ScreenKind
    reason: str = ""
    texts: list[TextBox] = field(default_factory=list)
    hf: float = 0.0
