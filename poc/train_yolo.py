#!/usr/bin/env python
"""Fine-tune detector nút đóng quảng cáo từ bộ dữ liệu poc/build_yolo_dataset.py.

    ./.venv/bin/python poc/build_yolo_dataset.py     # dựng dữ liệu trước
    ./.venv/bin/python poc/train_yolo.py

Vì sao `imgsz=960` chứ không phải 640 mặc định: ảnh chụp là 410x898 point, nút
đóng chỉ 14x14. Ở 640 thì letterbox co xuống còn ~10px — sát ngưỡng nhìn thấy
của đầu ra P3 (stride 8). Ở 960 nó thành ~15px. Đo được: model cũ train ở 640
chỉ tìm ra 2/29 ảnh.

Vì sao fine-tune chứ không train từ đầu: bộ dữ liệu chỉ vài chục ảnh. Trọng số
cũ đã học được "định vị icon nhỏ ở góc" (hai lần nó phát hiện đều lệch 2pt so
với ✕ thật), chỉ phần phân loại là chưa tới.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "yolo" / "data.yaml"
BASE = ROOT / "data" / "models" / "roboflow_v1.pt"
OUT = ROOT / "data" / "models" / "close_button_v2.pt"


def main() -> None:
    if not DATA.exists():
        sys.exit(f"chưa có {DATA} — chạy poc/build_yolo_dataset.py trước")
    from ultralytics import YOLO
    from ultralytics.utils import SETTINGS
    if SETTINGS.get("sync"):
        SETTINGS.update({"sync": False})

    m = YOLO(str(BASE) if BASE.exists() else "yolov8n.pt")
    m.train(
        data=str(DATA),
        epochs=150,
        imgsz=960,
        batch=8,
        device="mps",
        workers=2,
        project=str(ROOT / "runs"),
        name="close_button_v2",
        exist_ok=True,
        patience=50,
        # Bộ dữ liệu bé và mục tiêu bé -> tăng biến đổi hình học, giữ nguyên
        # màu sắc vì nút đóng phân biệt nhau chủ yếu bằng hình.
        degrees=5.0, translate=0.2, scale=0.5, fliplr=0.0, mosaic=0.5,
        close_mosaic=30, verbose=False, plots=False,
    )
    best = ROOT / "runs" / "close_button_v2" / "weights" / "best.pt"
    if best.exists():
        shutil.copy(best, OUT)
        print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
