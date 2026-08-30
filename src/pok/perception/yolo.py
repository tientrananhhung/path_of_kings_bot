"""Bước 2c — detector tự train, tìm nút đóng quảng cáo.

Vì sao thêm một tầng nữa vào giữa, khi đã có 2b và tầng C:

    2b  close_icon   luật VIẾT TAY cho ĐÚNG MỘT hình (dấu ✕)     7ms   chính xác
    2c  YOLO         luật TỰ HỌC cho NHIỀU hình                 ~20ms  chờ đo
    3   Florence-2   model tả ảnh đời thường, không biết UI     600ms  43%

`close_icon` mạnh vì nó là detector chuyên biệt, nhưng nó chỉ biết đúng một
hình: mực nằm trên hai đường chéo, đường giữa trống. Nút tròn `▶▶|` của quảng
cáo playable, hay nút đóng đang tắt có vành đếm giờ, thì nó mù.

YOLO chính là `close_icon` phiên bản tự học — cùng vai trò, cùng bản chất
(trả toạ độ, không sinh chữ, không thấy gì thì trả rỗng), nhưng học được nhiều
hình thay vì một hình viết tay.

MODEL HIỆN TẠI — `data/models/roboflow_v1.pt`, YOLOv8n 3.0M tham số, 30 epoch,
6 class (`X-Button` `cancel_button` `close_button` `extended_arrow`
`normal_arrow` `skip_button`). Đo thật, đây là những gì nó làm được:

    latency          18ms (trung vị, MPS) — rẻ hơn tầng C 33 lần
    dương tính giả   0 trên 3 màn game và 27 màn game trong data/captures
    ĐỘ PHỦ           1/7 fixture quảng cáo · 2/29 ảnh trong data/captures

Tức là nó gần như KHÔNG thấy gì. Nhưng hai lần hiếm hoi nó thấy thì đều trúng:
(372,66) và (369,93) — lệch 2pt so với hai dấu ✕ thật. Và cả hai lần nó gán
nhãn `normal_arrow`.

=> Định vị đã học được, PHÂN LOẠI thì chưa. Vì vậy `classes` trong config để
RỖNG (nhận mọi class): lọc theo class sẽ vứt đi đúng hai lần nó làm được việc.
Siết lại khi model có đủ dữ liệu.

=> Và vì vậy nó KHÔNG thay được bước 2b: `close_icon` tìm ra 8/8 dấu ✕, YOLO
tìm ra 2. Bước 2c hiện là "thêm một cơ hội", không phải tầng chính.

Thiếu file trọng số hoặc chưa cài `ultralytics` thì `enabled` là False, bước 2c
trả rỗng và pipeline chạy y như trước. File `.pt` nằm trong data/ nên KHÔNG lên
git — máy khác clone về sẽ tự động chạy ở chế độ không có 2c.

`ultralytics` là AGPL-3.0 và đòi `opencv-python` trong khi dự án dùng
`opencv-python-headless` cùng version — hai gói ghi đè lên nhau. Cài bằng
`--no-deps` rồi cài tay phần còn lại (xem pyproject.toml). Nó KHÔNG đụng tới
torch 2.13 / transformers 5.16 của Florence-2, đã kiểm bằng `pip --dry-run`.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from ..config import ROOT
from .types import Candidate


class YoloDetector:
    def __init__(self, cfg: dict):
        y = cfg.get("yolo", {}) or {}
        self.want = bool(y.get("enabled", False))
        # Đường dẫn tương đối tính từ GỐC DỰ ÁN, không phải thư mục đang đứng.
        # Nếu không thì `pok ui` chạy từ chỗ khác sẽ không thấy model, và bước
        # 2c im lặng tự tắt — kiểu hỏng khó nhận ra nhất.
        mp = str(y.get("model", "")).strip()
        self.model_path = str(ROOT / mp) if mp and not Path(mp).is_absolute() else mp
        self.conf = float(y.get("conf", 0.35))
        self.imgsz = int(y.get("imgsz", 640))
        self.device = str(y.get("device", "mps"))
        # Rỗng = nhận mọi class. Xem comment trong config/ads.toml: model hiện
        # tại định vị đúng nhưng gán nhãn sai, lọc theo class là vứt đi đúng
        # những lần nó làm được việc.
        self.classes = {str(c).lower() for c in (y.get("classes") or [])}
        self._model = None
        self._lock = threading.Lock()
        self.load_error: str | None = None
        self.last_ms = 0.0

    @property
    def enabled(self) -> bool:
        """Bật trong config VÀ có file trọng số thật.

        Bật mà thiếu file thì coi như tắt — thà bỏ qua bước 2c còn hơn để engine
        ném lỗi mỗi 2 giây trong lúc đang đóng quảng cáo.
        """
        return bool(self.want and self.model_path and Path(self.model_path).exists())

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        if self._model is not None:
            return True
        if not self.enabled:
            self.load_error = (
                "chưa bật" if not self.want
                else f"không thấy file trọng số: {self.model_path or '(chưa đặt)'}")
            return False
        with self._lock:
            if self._model is not None:
                return True
            try:
                from ultralytics import YOLO
                from ultralytics.utils import SETTINGS
                # Mặc định `sync = True`: ultralytics gửi dữ liệu sử dụng ra
                # server của họ. Bot chạy hàng giờ liền, không có lý do gì để
                # mỗi phiên lại kèm một lời gọi mạng — và một lời gọi mạng treo
                # là một tick engine treo.
                if SETTINGS.get("sync"):
                    SETTINGS.update({"sync": False})
            except ImportError:
                self.load_error = ("chưa cài ultralytics — "
                                   "./.venv/bin/pip install ultralytics")
                return False
            try:
                self._model = YOLO(self.model_path)
                self.load_error = None
            except Exception as e:      # noqa: BLE001
                self.load_error = f"{type(e).__name__}: {e}"
                return False
        return True

    def detect(self, bgr: np.ndarray) -> list[Candidate]:
        """Tìm nút đóng trên CẢ FRAME. Toạ độ trả về là local point.

        Quét cả frame chứ không crop như tầng C: detector được train trên chính
        ảnh quảng cáo của game này nên không cần crop để "phóng to" mục tiêu,
        và nút đóng không phải lúc nào cũng ở góc — ✕ của App Store sheet ở
        (46,145) từng nằm ngoài mọi ô góc.
        """
        if not self.load():
            return []
        t0 = time.perf_counter()
        try:
            with self._lock:
                res = self._model.predict(bgr, conf=self.conf, imgsz=self.imgsz,
                                          device=self.device, verbose=False)
        except Exception as e:          # noqa: BLE001
            self.load_error = f"predict: {type(e).__name__}: {e}"
            return []
        finally:
            self.last_ms = (time.perf_counter() - t0) * 1000

        out: list[Candidate] = []
        for r in res or []:
            names = getattr(r, "names", {}) or {}
            for b in getattr(r, "boxes", []) or []:
                x0, y0, x1, y1 = (float(v) for v in b.xyxy[0])
                cls = int(b.cls[0]) if b.cls is not None else -1
                ten = str(names.get(cls, cls))
                if self.classes and ten.lower() not in self.classes:
                    continue
                out.append(Candidate(
                    cx=(x0 + x1) / 2, cy=(y0 + y1) / 2,
                    w=x1 - x0, h=y1 - y0,
                    label=ten,
                    score=float(b.conf[0]) if b.conf is not None else 0.0,
                    origin="yolo"))
        out.sort(key=lambda c: -c.score)
        return out

    def prewarm(self, bus=None) -> None:
        """Nạp model + chạy một inference giả ở NỀN.

        Đo thật trên máy này: nạp 1310ms, predict LẦN ĐẦU 1743ms, các lần sau
        30ms. Tức khoảng 3 giây khởi động nguội — không prewarm thì 3 giây đó
        rơi đúng vào lúc gặp quảng cáo đầu tiên và chặn cả vòng lặp bot, y hệt
        bài học đã có với Florence-2.
        """
        def _job() -> None:
            import time as _t
            t0 = _t.perf_counter()
            if not self.load():
                if bus:
                    bus.log("warn", f"YOLO nạp thất bại: {self.load_error}")
                return
            try:
                self.detect(np.zeros((898, 410, 3), dtype=np.uint8))
            except Exception:      # noqa: BLE001
                pass
            if bus:
                bus.log("info", f"YOLO prewarm xong {(_t.perf_counter()-t0)*1000:.0f}ms",
                        sys=True)

        threading.Thread(target=_job, name="yolo-prewarm", daemon=True).start()

    def info(self) -> dict:
        return {
            "enabled": self.enabled,
            "want": self.want,
            "model": self.model_path,
            "conf": self.conf,
            "classes": sorted(self.classes) or "tất cả",
            "device": self.device,
            "loaded": self.loaded,
            "load_error": self.load_error,
            "last_ms": round(self.last_ms, 1),
        }
