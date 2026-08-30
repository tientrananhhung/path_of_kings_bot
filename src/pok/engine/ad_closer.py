"""Tầng C — pipeline đóng quảng cáo, 6 bước, dừng ở bước nào tìm ra thì tap.

LỌC AN TOÀN 3 CỬA là phần quan trọng nhất của cả dự án. Lý do cụ thể:
Florence-2 (cả base và base-ft) khi nhận CẢ ẢNH đã gán nhãn nút INSTALL màu
xanh là "close button". Bấm vào đó là mở App Store. Ba cửa lọc:
  1. hình học  — tâm phải trong dải mép 15% hoặc trong ô góc
  2. blocklist — OCR quanh candidate, khớp Install/Cài đặt/Get/Tải... -> loại
  3. kích thước — diện tích > 4% cửa sổ -> loại
Cửa 1 một mình đã chặn được cả nút Install (205,731) lẫn X giả (205,640).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..perception import cheap, close_icon, ocr
from ..perception.types import Candidate, TextBox


# `\b` sau alternation KHÔNG dùng được: với "23 seconds", sau "second" là "s"
# (vẫn là ký tự từ) nên không có word boundary -> regex trượt. Dùng (?![a-z]).
# Đòi PHẢI có đơn vị thời gian: "ad 1 of 2" là chỉ số tiến độ, không phải đếm
# ngược — nếu lấy số bừa thì nó thành "chờ 1 giây".
COUNTDOWN_RE = re.compile(r"(\d{1,3})\s*(?:seconds?|secs?|giây|s)(?![a-z])",
                          re.IGNORECASE)


@dataclass
class AdAttempt:
    started: float = field(default_factory=time.time)
    waiting_s: float = 0.0          # tổng thời gian NGỒI CHỜ đếm ngược (thật)
    wait_until: float = 0.0          # hoãn quét tới mốc này
    wait_tick: float = 0.0           # tick chờ gần nhất, để cộng waiting_s
    said_wait: str = ""              # để log một lần mỗi mốc, khỏi spam
    step: int = 0
    # (rel_x, rel_y, lúc tap). CÓ mốc thời gian vì nút đóng lúc đầu thường
    # đang TẮT (vành tròn đếm giờ chạy quanh nó). Tap lúc đó không ăn, nhưng
    # nếu ghi vĩnh viễn là "đã thử" thì đúng cái nút thật sẽ bị loại mãi mãi,
    # kể cả sau khi nó sáng lên.
    tried_points: list[tuple[float, float, float]] = field(default_factory=list)
    last_scan: float = 0.0
    candidates: list[Candidate] = field(default_factory=list)
    # Cú tap vừa bắn, đang chờ xem có ăn không. Giữ luôn frame NGAY TRƯỚC lúc
    # tap để làm mẫu huấn luyện — sau khi tap thì màn hình đã đổi, chụp lại là
    # muộn. Xem `BotEngine._confirm_tap`.
    pending: dict | None = None

    def elapsed(self) -> float:
        return time.time() - self.started

    def scanning_elapsed(self) -> float:
        """Thời gian THẬT SỰ đi quét, không tính lúc ngồi chờ đếm ngược.

        Nếu tính cả thời gian chờ thì một quảng cáo đếm ngược 30 giây sẽ ăn hết
        rescan_max_s=45 và bot nhảy sang blind tap trong khi lẽ ra chỉ cần chờ.
        """
        return max(0.0, self.elapsed() - self.waiting_s)


class AdCloser:
    def __init__(self, ads_cfg: dict, vlm, bus, yolo=None):
        self.cfg = ads_cfg
        self.vlm = vlm
        self.yolo = yolo
        self.bus = bus

    # ------------------------------------------------------------ lọc
    def _gate_geometry(self, c: Candidate, w: int, h: int,
                       in_crop: bool) -> bool:
        if in_crop:
            return True
        band = float(self.cfg.get("edge_band_pct", 0.15))
        rx, ry = c.cx / w, c.cy / h
        return (rx <= band or rx >= 1 - band or ry <= band or ry >= 1 - band)

    def _gate_size(self, c: Candidate, w: int, h: int,
                   crop_area: float | None = None) -> bool:
        """Nút đóng thật thì nhỏ. Hai ngưỡng:

        - tuyệt đối: <= max_area_pct diện tích cửa sổ
        - tương đối theo crop: <= 50% diện tích crop

        Ngưỡng tương đối là bắt buộc. Khi không tìm thấy gì trong crop,
        Florence-2 trả về box phủ gần hết crop. Với corner_box=130 thì box đó
        (16900px²) tình cờ vượt ngưỡng tuyệt đối (4% × 410×898 = 14727px²) nên
        bị chặn — nhưng chỉ là may. corner_box=120 (14400px²) sẽ LỌT và bot tap
        bừa vào góc.
        """
        area = max(1.0, c.w * c.h)
        if area > float(self.cfg.get("max_area_pct", 0.04)) * (w * h):
            return False
        if crop_area and area > 0.5 * crop_area:
            return False
        return True

    def _gate_side(self, c: Candidate, rng: tuple[float, float]) -> bool:
        """Cạnh lớn nhất của box phải nằm trong khoảng đo được. CHỈ cho tầng C.

        Đo trên 7 màn (5 quảng cáo + 2 game), 2 prompt, 4 góc — 22 ứng viên lọt
        đủ 4 cửa cũ, trong đó chỉ 3 cái ĐÚNG (lệch < 10pt so với nút thật):

            đúng : 26, 46, 47
            sai  : 11 11 11 12 14 17 23 32 47 57 62 65 69 103 104 114 129

        Khoảng [20, 50] giữ cả 3 cái đúng và loại 15/19 cái sai -> độ chính xác
        của tầng C đi từ 3/22 = 14% lên 3/7 = 43%. Bốn cái sai còn lọt là
        47x46 (hai lần), 23x22 và 32x31 — cặp 47x46 xuất hiện ở cả phía đúng
        lẫn phía sai trên cùng một ảnh, nên kích thước không tách nổi. Đó là
        trần của cửa này. Đây là cửa duy nhất tách được, kích thước
        tương đối theo crop thì không (xem `_gate_size`).
        """
        return rng[0] <= max(c.w, c.h) <= rng[1]

    def _gate_content(self, c: Candidate, bgr: np.ndarray) -> bool:
        """Quanh ứng viên phải CÓ NỘI DUNG, không được là nền trống.

        Florence-2 trả về box ở vùng nền trắng trơn (dương tính giả). Đo thật:
        nền trống 1.97 · viên thuốc 10.83 · dấu ✕ thật 5.29 -> ngưỡng 3.0.
        """
        thr = float(self.cfg.get("min_edge_density", 3.0))
        return cheap.edge_density(bgr, c.cx, c.cy) >= thr

    def _gate_blocklist(self, c: Candidate, texts: list[TextBox]) -> tuple[bool, list[str]]:
        """Bán kính khác nhau theo ĐỘ MẠNH của bằng chứng.

        Cửa này sinh ra để canh tầng C: Florence-2 đã thực sự gán nhãn nút
        Install là "close button", nên ứng viên VLM phải bị nghi ngờ.

        Dấu ✕ của tầng 2b thì khác hẳn — nó là bằng chứng HÌNH HỌC, đo bằng
        "mực nằm trên hai đường chéo, đường giữa trống", không phải model đoán.
        Áp cùng một bán kính rộng cho cả hai là lấy mức nghi ngờ dành cho thứ
        yếu nhất mà đè lên thứ chắc nhất — và đó chính là thứ làm hỏng phiên
        20260830-080353: ✕ đúng ở (372,68) cách cạnh chữ "PLAY NOW" 38.8pt, bị
        chặn 20 lần liên tiếp trong 46 giây.

        Điểm nằm TRONG hộp chữ thì chặn bất kể nguồn — đó là tap thẳng vào chữ.
        """
        block = [b.lower() for b in self.cfg.get("blocklist", [])]
        r = float(self.cfg.get(
            "blocklist_radius_icon_pt" if c.origin == "icon"
            else "blocklist_radius_pt",
            20.0 if c.origin == "icon" else 40.0))
        near = ocr.text_near(texts, c.cx, c.cy, radius=r)
        for t in near:
            for b in block:
                if b in t:
                    return (False, near)
        return (True, near)

    def filter_candidates(self, cands: list[Candidate], bgr: np.ndarray,
                          texts: list[TextBox], *, in_crop: bool = False,
                          crop_area: float | None = None,
                          side_range: tuple[float, float] | None = None
                          ) -> list[Candidate]:
        h, w = bgr.shape[:2]
        kept: list[Candidate] = []
        for c in cands:
            if not self._gate_geometry(c, w, h, in_crop):
                c.blocked, c.block_reason = True, "geometry"
            elif not self._gate_size(c, w, h, crop_area):
                c.blocked, c.block_reason = True, "size"
            elif side_range and not self._gate_side(c, side_range):
                c.blocked, c.block_reason = True, "side"
            elif c.origin != "yolo" and not self._gate_content(c, bgr):
                # KHÔNG áp cho tầng 2c. Cửa này đo cho Florence-2, sinh ra để
                # chặn nó bịa box trên vùng nền trống — một model tả ảnh đời
                # thường thì hay làm vậy. Detector tự train thì không.
                #
                # Và nó KHÔNG tách nổi hai thứ trên ảnh thật (end-card nền xám
                # phẳng của quảng cáo video):
                #     nút ▶▶| THẬT      2.52
                #     nền tối trống     2.34
                # chênh 0.18. Hạ ngưỡng để nhận nút thì nhận luôn nền trống.
                # Dùng sai công cụ, không phải sai ngưỡng.
                c.blocked, c.block_reason = True, "empty_area"
            else:
                ok, near = self._gate_blocklist(c, texts)
                c.nearby_text = near
                if not ok:
                    c.blocked, c.block_reason = True, "blocklist"
            if c.blocked:
                self.bus.publish({
                    "type": "candidate_blocked", "reason": c.block_reason,
                    "label": c.label, "origin": c.origin,
                    "cx": round(c.cx, 1), "cy": round(c.cy, 1),
                    "rel": [round(c.cx / w, 4), round(c.cy / h, 4)],
                    "nearby": c.nearby_text,
                })
            else:
                kept.append(c)
        return kept

    # -------------------------------------------------- bước 2: OCR keyword
    def step_ocr(self, bgr: np.ndarray, texts: list[TextBox]) -> list[Candidate]:
        hits = ocr.find_any(texts, self.cfg.get("close_keywords", []))
        cands = [Candidate(cx=t.cx, cy=t.cy, w=t.w, h=t.h, label=t.text,
                           score=t.conf, origin="ocr") for t in hits]
        return self.filter_candidates(cands, bgr, texts)

    # ---------------------------------------------- đang đếm ngược thưởng?
    def countdown_left(self, texts: list[TextBox]) -> float | None:
        """Còn bao nhiêu giây đếm ngược, hoặc None nếu không đang đếm.

        Bug đã gặp thật: quảng cáo hiện "Reward in 23 seconds" ở (111,122) và
        nút ✕ ở (31,123) — cách nhau 80pt. Bot tap ✕ ngay -> hiện dialog
        "Close Video? You will lose your reward", đếm ngược DỪNG, mất thưởng.
        Tệ hơn: hai nút của dialog nằm giữa màn nên bị cửa hình học chặn, bot
        không tap được gì nữa và kẹt cho tới khi escalate.
        """
        # Đã nhận thưởng xong -> KHÔNG còn phải chờ, dù trên màn vẫn còn chữ
        # kiểu "Ad 2 of 2". Đây là tín hiệu DƯƠNG, ưu tiên cao nhất.
        done = [d.lower() for d in self.cfg.get("reward_done_patterns", [])]
        low_all = " | ".join(t.text.lower().strip() for t in texts)
        if any(d in low_all for d in done):
            return None

        pats = [p.lower() for p in self.cfg.get("countdown_patterns", [])]
        if not pats:
            return None
        for t in texts:
            low = t.text.lower().strip()
            if not any(p in low for p in pats):
                continue
            m = COUNTDOWN_RE.search(low)
            secs = float(m.group(1)) if m else float(
                self.cfg.get("countdown_default_wait_s", 6.0))
            return secs + float(self.cfg.get("countdown_extra_wait_s", 1.5))
        return None

    # ------------------------- dialog "Close Video?" -> bấm RESUME VIDEO
    def resume_button(self, texts: list[TextBox]) -> TextBox | None:
        """Nút cần bấm khi dialog xác nhận đóng video đã hiện, hoặc None.

        KHÔNG đi qua filter_candidates: nút nằm giữa màn nên cửa hình học sẽ
        chặn. Đây là hành động có chủ đích trên một dialog đã nhận diện được,
        không phải ứng viên đoán được.
        """
        hints = [h.lower() for h in self.cfg.get("resume_dialog_hints", [])]
        want = str(self.cfg.get("resume_button_text", "resume video")).lower()
        if not hints or not want:
            return None
        low = " | ".join(t.text.lower().strip() for t in texts)
        if not any(h in low for h in hints):
            return None
        for t in texts:
            if want in t.text.lower().strip():
                return t
        return None

    # ------------------------------- bước 2b: dò dấu ✕ bằng OpenCV (< 5ms)
    def step_icon(self, bgr: np.ndarray, texts: list[TextBox]) -> list[Candidate]:
        """Quét CẢ FRAME tìm dấu ✕, rồi để cửa hình học lọc theo dải mép.

        KHÔNG dùng crop góc nữa. Lý do đo được: trên tấm App Store sheet mà
        quảng cáo mở ra, nút ✕ nằm ở (46,145) — y=145 NGOÀI ô góc 130x130 nên
        không bao giờ được nhìn thấy. Nút đóng không nhất thiết ở sát góc; nó có
        thể thấp hơn.

        Quét cả frame chỉ 6-16ms (VLM tốn 485ms/góc), nên không cần tiết kiệm.
        Đo trên 5 ảnh thật, sau khi lọc dải mép 15%:
            App Store sheet  -> 1 ứng viên, đúng (46,145)
            ad Binance đen   -> 1 ứng viên, đúng (371,91)
            ad Vượt Tường Thép -> 1 ứng viên, đúng (32,121)
            2 màn GAME       -> 0 ứng viên
        """
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        cands = [
            Candidate(cx=hit.cx, cy=hit.cy, w=hit.w, h=hit.h, label="✕",
                      score=hit.score, origin="icon")
            for hit in close_icon.find(
                gray,
                min_score=float(self.cfg.get("icon_min_score", 0.35)),
                max_mid=float(self.cfg.get("icon_max_mid", 0.15)))
        ]
        cands.sort(key=lambda c: -c.score)
        # in_crop=False -> cửa hình học (dải mép) được áp dụng
        return self.filter_candidates(cands, bgr, texts)

    # ------------------------------------------ bước 2c: detector tự train
    def step_yolo(self, bgr: np.ndarray, texts: list[TextBox]) -> list[Candidate]:
        """Detector tự train, quét cả frame. Rỗng nếu chưa có model.

        Đi qua ĐỦ cửa lọc như mọi tầng khác. Không được miễn trừ chỉ vì nó
        được train trên dữ liệu của chính mình: chừng nào chưa có số đo thì nó
        vẫn là model đoán, và cửa lọc là thứ duy nhất từng chặn được việc bot
        tap vào nút Install.

        KHÔNG áp `side_range`: khoảng [20,50] đo riêng cho Florence-2 trên crop
        góc, không có cơ sở nào để áp cho detector khác.
        """
        if self.yolo is None:
            return []
        return self.filter_candidates(self.yolo.detect(bgr), bgr, texts)

    # --------------------------------- bước 3: VLM trên dải 25% trên cùng
    def step_vlm_top(self, bgr: np.ndarray,
                     texts: list[TextBox]) -> list[Candidate]:
        """Hỏi VLM MỘT lần trên dải trên cùng, thay cho 4 lần quét 4 góc.

        Vì sao bỏ crop góc: nút đóng không nhất thiết sát góc — ✕ của App Store
        sheet ở (46,145) nằm NGOÀI ô góc 130x130 nên trước đây không bao giờ
        được nhìn thấy. Còn dải trên thì giữ trọn 5/5 nút đã đo (xem
        `cheap.crop_top_band`), và 4 lần gọi ~4.2s rút còn 1 lần ~0.6s.

        Cắt theo MÀN HÌNH THẬT, không phải cửa sổ: viền máy 38pt phía trên là
        đen thuần, đưa cho Florence-2 chỉ tổ nhiễu. Xem `cheap.content_rect`.
        """
        pct = float(self.cfg.get("vlm_band_top", 0.25))
        sx, sy, sw, sh = cheap.content_rect(bgr)
        screen = bgr[sy:sy + sh, sx:sx + sw]
        crop, (ox, oy) = cheap.crop_top_band(screen, pct)
        raw = self.vlm.detect_in_crop(crop)
        for c in raw:
            c.cx += ox + sx
            c.cy += oy + sy
            c.origin = "vlm:top"
        v = self.cfg.get("vlm", {})
        # in_crop=True: đã giới hạn theo dải trên nên không áp cửa dải mép nữa —
        # chính dải trên LÀ ràng buộc hình học. Vẫn PHẢI truyền crop_area:
        # không thấy gì thì Florence-2 trả box phủ gần hết crop.
        return self.filter_candidates(
            raw, bgr, texts, in_crop=True,
            crop_area=float(crop.shape[0] * crop.shape[1]),
            side_range=(float(v.get("min_side_pt", 20)),
                        float(v.get("max_side_pt", 50))))

    # ------------------------------------------------------------ tiện ích
    def already_tried(self, attempt: AdAttempt, rel: tuple[float, float],
                      tol: float = 0.05) -> bool:
        """Vừa tap chỗ này mà không ăn thì đừng tap lại NGAY — nhưng được tap
        lại sau `retry_after_s`.

        Vì sao không cấm vĩnh viễn: rất nhiều quảng cáo hiện nút đóng ngay từ
        đầu nhưng đang TẮT, quanh nó là vòng tròn đếm giờ. Tap lúc đó không ăn.
        Nếu ghi vĩnh viễn là "đã thử" thì đúng cái nút thật bị loại khỏi danh
        sách mãi mãi, kể cả sau khi nó sáng lên — và bot sẽ escalate về Home
        trong khi nút đóng nằm ngay đó.
        """
        han = float(self.cfg.get("retry_after_s", 15.0))
        now = time.time()
        return any(abs(rel[0] - p[0]) < tol and abs(rel[1] - p[1]) < tol
                   and now - p[2] < han
                   for p in attempt.tried_points)

