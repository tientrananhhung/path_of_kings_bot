"""Tầng A — rule engine đọc từ config/game.toml.

Không hard-code luật nào. Game có màn mới thì thêm luật vào TOML, reload nóng.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..perception import cheap


@dataclass
class Rule:
    name: str
    enabled: bool
    priority: int
    when: dict
    do: dict
    cooldown_s: float = 2.0     # cùng một luật không được bắn lại trong khoảng này
    enters_ad: bool = False     # bấm/swipe cái này thì CHẮC CHẮN vào xem quảng cáo


class RuleEngine:
    def __init__(self, game_cfg: dict, templates_dir: Path | None = None):
        self.templates_dir = templates_dir
        self._templates: dict[str, np.ndarray] = {}
        self.reload(game_cfg)
        self._last_hash: np.ndarray | None = None
        self._hash_since = time.time()

    def reload(self, game_cfg: dict) -> None:
        rules = []
        for r in game_cfg.get("rule", []):
            rules.append(Rule(
                name=r.get("name", "?"),
                enabled=bool(r.get("enabled", True)),
                priority=int(r.get("priority", 50)),
                when=r.get("when", {}) or {},
                do=r.get("do", {}) or {},
                cooldown_s=float(r.get("cooldown_s", 2.0)),
                enters_ad=bool(r.get("enters_ad", False)),
            ))
        rules.sort(key=lambda x: x.priority)
        self.rules = rules
        self._fired: dict[str, float] = getattr(self, "_fired", {})

    # --- theo dõi "màn hình không đổi" ---
    def update_idle(self, bgr: np.ndarray) -> float:
        h = cheap.phash(bgr)
        if self._last_hash is None or cheap.phash_distance(h, self._last_hash) > 3:
            self._last_hash = h
            self._hash_since = time.time()
        return time.time() - self._hash_since

    def reset_idle(self) -> None:
        self._last_hash = None
        self._hash_since = time.time()

    # --- template ---
    def _template(self, name: str) -> np.ndarray | None:
        if name in self._templates:
            return self._templates[name]
        if not self.templates_dir:
            return None
        path = self.templates_dir / name
        if not path.exists():
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            return None
        self._templates[name] = img
        return img

    # --- đánh giá ---
    def evaluate(self, bgr: np.ndarray, idle_seconds: float,
                 texts_low: str = "", *, ignore_enabled: bool = False,
                 ignore_cooldown: bool = False,
                 skip: set[str] | None = None,
                 texts: list | None = None) -> tuple[Rule, dict] | None:
        """Trả (rule khớp đầu tiên theo priority, thông tin phụ) hoặc None.

        skip: bỏ qua các luật đã thử mà không hành động được (ví dụ tap_text
        không tìm thấy chữ) -> cho luật tiếp theo có cơ hội. Nếu không có cơ chế
        này thì một luật khớp-nhưng-không-làm-được sẽ ăn mất lượt và luật đúng
        phía sau không bao giờ chạy. Đã gặp thật: màn phần thưởng vẫn còn tiêu đề
        "RITUAL TROUBLE" nên luật Pray khớp, nhưng chữ 'pray' đã biến mất.

        ignore_enabled/ignore_cooldown: dành cho TEST KHÔ. Quy trình khuyến nghị
        là viết luật ở trạng thái tắt rồi test khô trước khi bật, nên test khô
        phải đánh giá được cả luật đang tắt và luật đang trong cooldown.
        """
        now = time.time()
        skip = skip or set()
        for rule in self.rules:
            if rule.name in skip:
                continue
            if not rule.enabled and not ignore_enabled:
                continue
            # Chống bắn lặp: OCR chỉ làm mới mỗi ~2s nên luật text/template sẽ
            # khớp lại trên dữ liệu cũ ở mọi tick nếu không có cooldown.
            if (not ignore_cooldown
                    and now - self._fired.get(rule.name, 0.0) < rule.cooldown_s):
                continue
            kind = rule.when.get("kind", "always")
            info: dict = {}
            ok = False

            if kind == "always":
                ok = True
            elif kind == "idle":
                ok = idle_seconds >= float(rule.when.get("seconds", 12))
                info["idle"] = round(idle_seconds, 1)
            elif kind == "color":
                at = tuple(rule.when.get("at", [0.5, 0.5]))
                rgb = tuple(rule.when.get("rgb", [0, 0, 0]))
                tol = int(rule.when.get("tolerance", 30))
                ok = cheap.color_matches(bgr, at, rgb, tol)
                info["color_at"] = cheap.color_at(bgr, at)
            elif kind == "template":
                tpl = self._template(rule.when.get("template", ""))
                if tpl is None:
                    continue
                region = rule.when.get("region")
                score, center = cheap.template_match(
                    bgr, tpl, tuple(region) if region else None)
                ok = score >= float(rule.when.get("min_score", 0.8))
                info["score"] = round(score, 3)
                info["center"] = center
            elif kind == "text":
                needle = str(rule.when.get("contains", "")).lower()
                y0, y1 = rule.when.get("y_min"), rule.when.get("y_max")
                if not needle:
                    ok = False
                elif y0 is None and y1 is None:
                    ok = needle in texts_low
                else:
                    # Ràng buộc VÙNG DỌC — bắt buộc với keyword cũng xuất hiện
                    # trên HUD. Bug đã gặp thật: nav bar đáy màn hình đọc ra
                    # "tauern | shop | pup raid | bosses | rank", nên luật
                    # "pup raid" khớp ở MỌI màn và bot quẹt trái không ngừng.
                    # Trên dialog thật, tiêu đề "PUP RAID" ở y/h = 0.192.
                    ok, hh = False, (bgr.shape[0] if bgr is not None else 1)
                    for t in (texts or []):
                        if needle not in t.text.lower():
                            continue
                        ry = t.cy / max(1, hh)
                        if float(y0 or 0.0) <= ry <= float(y1 or 1.0):
                            ok, info["y"] = True, round(ry, 3)
                            break
                        info.setdefault("y_loại", []).append(round(ry, 3))

            if ok:
                return (rule, info)
        return None

    def note_fired(self, rule: Rule) -> None:
        self._fired[rule.name] = time.time()

    def cooldown_left(self, rule: Rule) -> float:
        return max(0.0, rule.cooldown_s - (time.time() - self._fired.get(rule.name, 0.0)))
