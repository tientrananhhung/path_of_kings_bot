"""Ghi mẫu huấn luyện — bot tự gán nhãn cho chính nó.

Nhãn để train detector cần đúng ba thứ: tấm ảnh, cái khung, tên class. Cả ba
đều đã có sẵn trong vòng đời một lần đóng quảng cáo, chỉ là trước giờ bị vứt đi:

    1. bot tìm ra ứng viên ở (372,68) 14x14           -> cái khung
    2. tap vào đó, giữ lại frame ngay trước khi tap    -> tấm ảnh
    3. `confirm_delay_s` giây sau, kiểm tra kết quả:
         về được màn game  -> `hit`, chỗ đó ĐÚNG là nút đóng
         màn hình y nguyên -> `miss`, chỗ đó KHÔNG phải nút đóng

Nghĩa là cứ để bot chạy như thường thì dữ liệu tự sinh ra, không ai phải ngồi
khoanh tay từng tấm ảnh.

Cảnh báo về nhãn `hit`: nó là bằng chứng gián tiếp. Quảng cáo TỰ tắt trong cửa
sổ 1.2 giây sau cú tap cũng được ghi là `hit`. Cửa sổ ngắn nên xác suất trùng
hợp thấp, nhưng đừng coi tập này là nhãn vàng — trước khi train nên liếc qua.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np

# Đo trên máy này, ảnh 410x898: PNG 7ms, JPEG q92 1ms. 7ms cho một lần tap
# (nhiều nhất mỗi 2 giây) là rẻ hơn nhiều so với việc dựng thêm một thread ghi
# nền, nên ghi thẳng trong tick. Dùng PNG chứ không JPEG: nút đóng chỉ 14x14
# point, nén mất mát ăn mất đúng thứ mình cần dạy cho model.
INDEX = "index.jsonl"


class SampleWriter:
    """Ghi ảnh + nhãn vào `root`. Tắt bằng `enabled=False` thì mọi lời gọi là no-op."""

    def __init__(self, root: Path, enabled: bool = True):
        self.root = Path(root)
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self.written = 0

    def record(self, bgr: np.ndarray, box: dict | None, outcome: str,
               meta: dict | None = None) -> str | None:
        """Ghi một mẫu. Trả tên file ảnh, hoặc None nếu không ghi.

        box    : {"cx","cy","w","h"} theo point local của ảnh, hoặc None
        outcome: "hit" | "miss" | "fail"

        `box=None` dành cho mẫu KHÓ — quảng cáo mà cả ba tầng đều bó tay, nên
        không có toạ độ nào để ghi. Đây là mẫu quý nhất và là loại DUY NHẤT
        phải khoanh tay, vì theo định nghĩa bot không biết nút nằm đâu.
        """
        if not self.enabled or bgr is None:
            return None
        h, w = bgr.shape[:2]
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.png"
        rec = {
            "ts": round(time.time(), 3),
            "image": name,
            "img_w": w,
            "img_h": h,
            "box": ({k: round(float(box.get(k, 0)), 1)
                     for k in ("cx", "cy", "w", "h")} if box else None),
            # rel để đối chiếu nhanh với log `action`; train thì dùng box ở trên
            "rel": ([round(float(box.get("cx", 0)) / max(1, w), 4),
                     round(float(box.get("cy", 0)) / max(1, h), 4)] if box else None),
            "outcome": outcome,
            **(meta or {}),
        }
        try:
            with self._lock:
                self.root.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(self.root / name), bgr):
                    return None
                with (self.root / INDEX).open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                self.written += 1
        except Exception:      # ghi mẫu KHÔNG được phép làm chết vòng lặp bot
            return None
        return name
