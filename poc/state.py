"""Cho biết cửa sổ iPhone Mirroring đang ở trạng thái nào (dùng Apple Vision OCR)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image
from common import require_window
from poc2_capture import bk_cgwindowlist
from bench_ocr import ocr

PAUSE_HINTS = ["đang được sử dụng", "phản chiếu iphone đã kết thúc",
               "iphone in use", "kết nối", "connect"]


def snapshot():
    win = require_window()
    arr = bk_cgwindowlist(win)
    p = os.path.join(tempfile.gettempdir(), "poc_state.png")
    Image.fromarray(arr[:, :, :3]).save(p)
    res = ocr(p)
    H, W = arr.shape[:2]
    texts = []
    for txt, conf, (bx, by, bw, bh) in res:
        texts.append((txt, conf, int((bx + bw / 2) * W), int((1 - (by + bh / 2)) * H)))
    joined = " | ".join(t[0].lower() for t in texts)
    paused = any(h in joined for h in PAUSE_HINTS)
    return win, texts, paused, p


if __name__ == "__main__":
    win, texts, paused, p = snapshot()
    print(f"\nTRẠNG THÁI: {'PAUSE (chưa kết nối)' if paused else 'ĐANG KẾT NỐI (live)'}")
    print(f"ảnh: {p}\nOCR thấy {len(texts)} vùng chữ:")
    for txt, conf, cx, cy in texts:
        print(f"  {conf:.2f} ({cx:>4},{cy:>4})  {txt!r}")
