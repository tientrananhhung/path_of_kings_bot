#!/usr/bin/env python
"""Dựng bộ dữ liệu YOLO từ ảnh đã có, TỰ GÁN NHÃN ở mức tối đa có thể.

Nhãn để train cần ba thứ: ảnh · khung · class. Ba nguồn, xếp theo độ tin cậy:

  1. data/samples/index.jsonl  — cú tap đã được XÁC NHẬN đóng được quảng cáo.
     Nhãn chắc nhất: bot tap chỗ đó rồi về được màn game.
  2. close_icon.find()         — dò dấu ✕ bằng hình học, đo được 8/8 đúng trên
     ảnh quảng cáo. Chỉ lấy trên ảnh KHÔNG phải màn game.
  3. SEED thủ công             — nút mà máy chưa dò được, phải chỉ tay.

Và nguồn thứ tư quan trọng không kém: **màn game làm nhãn ÂM**. Ảnh không có
khung nào dạy model biết chỗ nào KHÔNG phải nút đóng. Đặc biệt
20260830-061939-9845.png: `close_icon` bắt nhầm chữ X trong "LOST EXPLORER" —
đúng loại nhầm lẫn cần dạy model tránh.

Giữ nguyên 6 class của roboflow_v1.pt để fine-tune không phải dựng lại đầu ra.

    ./.venv/bin/python poc/build_yolo_dataset.py
"""
import json
import random
import shutil
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pok.perception import close_icon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "yolo"
# Giữ đúng thứ tự class của model đang có, xem `YOLO(...).names`
NAMES = ["X-Button", "cancel_button", "close_button", "extended_arrow",
         "normal_arrow", "skip_button"]
X_BUTTON, SKIP_BUTTON = 0, 5

# Nút máy chưa dò được, chỉ tay. (tên ảnh -> [(class, cx, cy, w, h)])
SEED = {
    # Quảng cáo playable "Vượt Tường Thép": nút skip là dấu >> trong vòng tròn
    # mờ ở góc trên phải. Không phải ✕ nên close_icon mù; Florence-2 thấy
    # nhưng box 73x40 lệch tâm 15pt và bị cửa _gate_side chặn.
    "20260830-162622-61363.png": [(SKIP_BUTTON, 373, 135, 30, 30)],
}
# Ảnh bị gán nhãn SAI, phải vào tập ÂM chứ không được thành nhãn dương.
#
# `hit` là bằng chứng GIÁN TIẾP: quảng cáo tự tắt trong cửa sổ 1.2 giây sau cú
# tap cũng được ghi là hit. Hai mẫu dưới đây chính là ca đó — VLM chỉ vào NÚT
# BÁNH RĂNG của game ở (44,86), bot tap, rồi "về được màn game" nên ghi hit.
# Xem lại ảnh thì rõ: một tấm là màn trang bị "Upgraded Acid Fang", một tấm là
# dialog "CRYPTO GOBLIN". Đây đúng là lý do phải liếc qua tập mẫu trước khi
# train — nếu không, model sẽ học rằng nút bánh răng của game là nút đóng.
CHAC_CHAN_LA_GAME = {
    "20260830-061939-9845.png",   # close_icon bắt nhầm chữ X trong "LOST EXPLORER"
    "20260830-155522-176.png",    # vlm:top chỉ vào bánh răng (44,86), màn trang bị
    "20260830-161259-477.png",    # vlm:top chỉ vào bánh răng (44,86), dialog goblin
}


def la_man_game(name: str, tag: str | None) -> bool:
    return name in CHAC_CHAN_LA_GAME or tag == "game" or name.startswith("game_")


def thu_thap() -> dict[str, list[tuple]]:
    """{đường dẫn ảnh: [(class, cx, cy, w, h), ...]}. List rỗng = nhãn âm."""
    tags_path = ROOT / "data" / "captures" / "_tags.json"
    tags = json.loads(tags_path.read_text()) if tags_path.exists() else {}
    ra: dict[str, list[tuple]] = {}
    seen_hash: set[str] = set()

    anh = sorted((ROOT / "data" / "captures").glob("*.png")) + \
        sorted((ROOT / "tests" / "fixtures").glob("*.png"))
    for p in anh:
        img = cv2.imread(str(p))
        if img is None:
            continue
        # captures và fixtures trùng nhau nhiều — khử theo nội dung ảnh
        import hashlib
        h = hashlib.md5(img.tobytes()).hexdigest()
        if h in seen_hash:
            continue
        seen_hash.add(h)

        t = tags.get(p.name)
        t = t.get("tag") if isinstance(t, dict) else t
        hh, ww = img.shape[:2]

        if p.name in SEED:
            ra[str(p)] = list(SEED[p.name])
            continue
        if la_man_game(p.name, t):
            ra[str(p)] = []                       # nhãn ÂM
            continue

        hits = [x for x in close_icon.find(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                                           min_score=0.35, max_mid=0.15)
                if x.cy / hh <= 0.25 or x.cx / ww <= 0.15 or x.cx / ww >= 0.85]
        if hits:
            ra[str(p)] = [(X_BUTTON, x.cx, x.cy, x.w + 6, x.h + 6) for x in hits]

    # nguồn 1: mẫu bot tự xác nhận
    idx = ROOT / "data" / "samples" / "index.jsonl"
    if idx.exists():
        for line in idx.read_text().splitlines():
            d = json.loads(line)
            if d.get("outcome") != "hit" or not d.get("box"):
                continue
            img_p = ROOT / "data" / "samples" / d["image"]
            if d["image"] in CHAC_CHAN_LA_GAME:
                ra[str(img_p)] = []               # nhãn ÂM, xem chú thích ở trên
            elif img_p.exists():
                b = d["box"]
                ra[str(img_p)] = [(X_BUTTON, b["cx"], b["cy"],
                                   max(b["w"], 14), max(b["h"], 14))]
    return ra


def main() -> None:
    data = thu_thap()
    duong = {k: v for k, v in data.items() if v}
    am = {k: v for k, v in data.items() if not v}
    print(f"{len(duong)} ảnh có nhãn · {len(am)} ảnh âm (màn game)")
    for k, v in duong.items():
        print(f"   {Path(k).name[:28]:28} " +
              ", ".join(f"{NAMES[c]}@({cx:.0f},{cy:.0f}) {w:.0f}x{h:.0f}"
                        for c, cx, cy, w, h in v))

    # Ảnh SEED luôn vào TRAIN. Class hiếm (nút >> hiện chỉ có ĐÚNG MỘT mẫu) mà
    # rơi vào val thì model không thể học được gì từ nó — lần train đầu đúng
    # như vậy: 20/20 trên train, nhưng sót đúng cái nút >> vì nó nằm ở val.
    # Không đo được nó còn hơn không học được nó.
    bat_buoc_train = {k for k in data if Path(k).name in SEED}
    keys = sorted(set(data) - bat_buoc_train)
    random.Random(42).shuffle(keys)
    n_val = max(2, len(keys) // 5)
    chia = {"val": keys[:n_val], "train": keys[n_val:] + sorted(bat_buoc_train)}

    if OUT.exists():
        shutil.rmtree(OUT)
    for split, ks in chia.items():
        (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)
        for k in ks:
            p = Path(k)
            img = cv2.imread(k)
            hh, ww = img.shape[:2]
            cv2.imwrite(str(OUT / "images" / split / p.name), img)
            dong = [f"{c} {cx/ww:.6f} {cy/hh:.6f} {w/ww:.6f} {h/hh:.6f}"
                    for c, cx, cy, w, h in data[k]]
            (OUT / "labels" / split / f"{p.stem}.txt").write_text("\n".join(dong))

    yaml = (f"path: {OUT}\ntrain: images/train\nval: images/val\n"
            f"nc: {len(NAMES)}\nnames: {NAMES}\n")
    (OUT / "data.yaml").write_text(yaml)
    print(f"\ntrain {len(chia['train'])} · val {len(chia['val'])} -> {OUT}")


if __name__ == "__main__":
    main()
