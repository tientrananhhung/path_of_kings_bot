"""Tầng C — Florence-2. Lazy load, CHỈ chạy trên crop góc.

Benchmark thật (poc/bench_florence.py, M1 16GB, MPS fp16, num_beams=1):
  latency ≈ 430ms cố định + 13ms/token
  crop góc 130x130, <OPEN_VOCABULARY_DETECTION> "close button": 531ms, Δ0pt
  CẢ ẢNH, cùng prompt: trả về nút INSTALL (205,731) — sai và nguy hiểm

Vì vậy module này KHÔNG cung cấp API nào nhận cả màn hình. Chỉ nhận crop.
Checkpoint gốc microsoft/Florence-2-base KHÔNG load được với transformers 5.x
(RobertaTokenizer has no attribute image_token) -> dùng bản florence-community.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from .types import Candidate

_TASK = "<OPEN_VOCABULARY_DETECTION>"


class FlorenceVLM:
    def __init__(self, cfg: dict):
        v = cfg.get("vlm", {})
        self.model_id = v.get("model", "florence-community/Florence-2-base-ft")
        self.device = v.get("device", "mps")
        self.dtype_name = v.get("dtype", "float16")
        self.beams = int(v.get("beams", 1))
        self.prompts = list(v.get("prompts", ["close button"]))
        self.enabled = bool(v.get("enabled", True))
        self._model = None
        self._proc = None
        self._lock = threading.Lock()
        self.load_error: str | None = None
        self.last_ms = 0.0
        self.warm_size = 130

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        """Nạp model. Chỉ gọi lần đầu cần tầng C (~1.5s, 416MB fp16)."""
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True
            try:
                import torch
                from transformers import (AutoProcessor,
                                          Florence2ForConditionalGeneration)
                dtype = getattr(torch, self.dtype_name)
                self._proc = AutoProcessor.from_pretrained(self.model_id)
                m = Florence2ForConditionalGeneration.from_pretrained(
                    self.model_id, dtype=dtype)
                self._model = m.to(self.device).eval()
                self._torch = torch
                self.load_error = None
                return True
            except Exception as e:  # noqa: BLE001
                self.load_error = f"{type(e).__name__}: {e}"
                self._model = None
                return False

    def prewarm(self, bus=None) -> None:
        """Nạp model + chạy 1 inference giả ở NỀN.

        Đo thật: lần gọi đầu 12304ms (nạp + warm-up MPS), các lần sau 518-545ms.
        Nếu không prewarm thì 12s đó rơi đúng vào lúc gặp quảng cáo đầu tiên và
        chặn cả vòng lặp bot.
        """
        def _job() -> None:
            import time as _t
            t0 = _t.perf_counter()
            if not self.load():
                if bus:
                    bus.log("warn", f"VLM nạp thất bại: {self.load_error}")
                return
            try:
                dummy = np.zeros((self.warm_size, self.warm_size, 3), dtype=np.uint8)
                self.detect_in_crop(dummy)
            except Exception:
                pass
            if bus:
                bus.log("info", f"VLM prewarm xong {(_t.perf_counter()-t0)*1000:.0f}ms",
                        sys=True)

        threading.Thread(target=_job, name="vlm-prewarm", daemon=True).start()

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._proc = None

    def detect_in_crop(self, crop_bgr: np.ndarray, prompt: str | None = None
                       ) -> list[Candidate]:
        """Tìm nút đóng TRONG MỘT CROP. Toạ độ trả về là local của crop."""
        if not self.enabled:
            return []
        if not self.load():
            return []
        import cv2
        from PIL import Image

        prompts = [prompt] if prompt else self.prompts
        img = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
        out: list[Candidate] = []
        t0 = time.perf_counter()
        with self._lock:
            for p in prompts:
                try:
                    out.extend(self._run(img, p))
                except Exception:
                    continue
        self.last_ms = (time.perf_counter() - t0) * 1000
        return out

    def _run(self, img, prompt: str) -> list[Candidate]:
        torch = self._torch
        inputs = self._proc(text=_TASK + prompt, images=img, return_tensors="pt")
        inputs = {k: (v.to(self.device) if hasattr(v, "to") else v)
                  for k, v in inputs.items()}
        pv = inputs.get("pixel_values")
        if pv is not None and pv.dtype.is_floating_point:
            inputs["pixel_values"] = pv.to(self._model.dtype)
        with torch.inference_mode():
            ids = self._model.generate(**inputs, max_new_tokens=128,
                                       num_beams=self.beams, do_sample=False)
        text = self._proc.batch_decode(ids, skip_special_tokens=False)[0]
        parsed = self._proc.post_process_generation(
            text, task=_TASK, image_size=(img.width, img.height))
        d = parsed.get(_TASK) or {}
        boxes = d.get("bboxes") or []
        labels = d.get("bboxes_labels") or d.get("labels") or [prompt] * len(boxes)
        res = []
        for b, lab in zip(boxes, labels):
            if len(b) != 4:
                continue
            res.append(Candidate(
                cx=(b[0] + b[2]) / 2, cy=(b[1] + b[3]) / 2,
                w=abs(b[2] - b[0]), h=abs(b[3] - b[1]),
                label=str(lab), score=1.0, origin="vlm",
            ))
        return res

    def info(self) -> dict:
        return {
            "enabled": self.enabled,
            "model": self.model_id,
            "device": self.device,
            "dtype": self.dtype_name,
            "beams": self.beams,
            "loaded": self.loaded,
            "load_error": self.load_error,
            "last_ms": round(self.last_ms, 1),
        }
