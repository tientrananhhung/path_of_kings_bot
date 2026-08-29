"""Tạo ảnh quảng cáo giả 410x898 để test ca khó nhất: nút X nhỏ, mờ, ở góc.

Không thay được quảng cáo thật, nhưng cho một mục tiêu ĐÃ BIẾT TRƯỚC toạ độ
nên đo được chính xác model có tìm ra hay không, và lệch bao nhiêu point.
"""
from PIL import Image, ImageDraw, ImageFont
import json, os

W, H = 410, 898
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def font(sz):
    for p in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def build():
    im = Image.new("RGB", (W, H), (18, 22, 40))
    d = ImageDraw.Draw(im)
    for y in range(H):                                  # nền gradient
        d.line([(0, y), (W, y)], fill=(18 + y // 18, 22 + y // 30, 40 + y // 12))

    d.rounded_rectangle([70, 210, 340, 480], 26, fill=(240, 180, 60))
    d.text((122, 320), "GAME ART", font=font(30), fill=(60, 40, 10))
    d.text((60, 520), "Puzzle Master 3D", font=font(28), fill=(255, 255, 255))
    d.text((92, 566), "4.8 ★  ·  Free", font=font(18), fill=(190, 195, 210))

    d.rounded_rectangle([70, 700, 340, 762], 31, fill=(52, 199, 89))   # nút Install
    d.text((150, 720), "Install", font=font(24), fill=(255, 255, 255))

    truth = {}

    # nút X: nhỏ, mờ (dark pattern kinh điển) — góc trên phải
    cx, cy, r = 380, 44, 11
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(70, 74, 92))
    d.line([cx - 5, cy - 5, cx + 5, cy + 5], fill=(150, 154, 170), width=2)
    d.line([cx - 5, cy + 5, cx + 5, cy - 5], fill=(150, 154, 170), width=2)
    truth["close_x_icon"] = [cx, cy]

    # nút X GIẢ: to, rõ, giữa màn — bấm vào là mở App Store
    d.rounded_rectangle([166, 620, 244, 660], 8, outline=(120, 125, 145), width=2)
    d.text((196, 630), "X", font=font(20), fill=(120, 125, 145))
    truth["fake_x_decoy"] = [205, 640]

    # nút Skip dạng chữ, góc dưới phải
    d.text((300, 826), "Skip Ad", font=font(15), fill=(170, 175, 195))
    truth["skip_text"] = [335, 834]

    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "fake_ad.png")
    im.save(p)
    with open(os.path.join(OUT, "fake_ad_truth.json"), "w") as f:
        json.dump(truth, f, indent=2)
    print("đã tạo", p)
    for k, v in truth.items():
        print(f"  ground truth {k:<16} = {v}")
    return p


if __name__ == "__main__":
    build()
