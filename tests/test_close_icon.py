"""Dò dấu ✕ đóng quảng cáo — dùng ảnh THẬT làm fixture.

Lý do module này tồn tại: trên quảng cáo thật đầu tiên gặp được, nút ✕ ở
(32,122) nhưng Florence-2 trả về (68,106) — lệch 36pt, trúng viên thuốc
"Reward granted" bên cạnh. Tap vào đó không đóng được quảng cáo.
"""
from pathlib import Path

import cv2
import pytest

from pok.perception import close_icon
from pok.perception.cheap import edge_density

FIX = Path(__file__).parent / "fixtures"
CORNERS = {"tl": (0, 0, 130, 130), "tr": (280, 0, 410, 130),
           "bl": (0, 768, 130, 898), "br": (280, 768, 410, 898)}
X_THAT = (32, 122)      # toạ độ nút ✕ thật, đo bằng mắt trên ảnh phóng to


def corner_gray(name: str, corner: str):
    img = cv2.imread(str(FIX / name))
    assert img is not None, f"thiếu fixture {name}"
    x0, y0, x1, y1 = CORNERS[corner]
    return cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), (x0, y0)


def test_tìm_đúng_dấu_x_thật_sai_số_dưới_3_point():
    gray, (ox, oy) = corner_gray("ad_close_x.png", "tl")
    hits = close_icon.find(gray)
    assert hits, "không tìm thấy dấu ✕ nào ở góc trên-trái"
    best = hits[0]
    cx, cy = best.cx + ox, best.cy + oy
    lech = ((cx - X_THAT[0]) ** 2 + (cy - X_THAT[1]) ** 2) ** 0.5
    assert lech < 3, f"lệch {lech:.1f}pt — tâm=({cx:.0f},{cy:.0f})"
    assert best.score > 0.5
    assert best.mid < 0.05      # đường giữa gần như không có mực


@pytest.mark.parametrize("corner", ["tr", "bl", "br"])
def test_ba_góc_còn_lại_của_quảng_cáo_không_có_x(corner):
    gray, _ = corner_gray("ad_close_x.png", corner)
    assert close_icon.find(gray) == []


@pytest.mark.parametrize("name", ["game_upgrade.png", "game_empyreal.png"])
@pytest.mark.parametrize("corner", list(CORNERS))
def test_màn_game_không_có_dương_tính_giả(name, corner):
    gray, _ = corner_gray(name, corner)
    assert close_icon.find(gray) == [], f"{name} góc {corner} báo có ✕"


def test_ngưỡng_lỏng_thì_lọt_dương_tính_giả():
    """Chứng minh ngưỡng 0.35/0.15 là cần thiết, không phải con số bừa."""
    gray, _ = corner_gray("game_upgrade.png", "tr")
    assert close_icon.find(gray, min_score=0.15, max_mid=0.9) != []
    assert close_icon.find(gray) == []


def test_mật_độ_cạnh_loại_được_nền_trống():
    img = cv2.imread(str(FIX / "ad_close_x.png"))
    trong = edge_density(img, 341, 106)     # nền trắng trơn, VLM dương tính giả
    that = edge_density(img, 32, 122)       # dấu ✕ thật
    assert trong < 3.0 < that, f"trống={trong:.2f} thật={that:.2f}"


def test_frame_tối_không_bị_coi_là_thiếu_quyền():
    """Bug đã gặp thật: quảng cáo video nền đen có mật độ cạnh thấp (hf=0.73),
    bị coi là 'thiếu quyền -> hình nền desktop' và bot tự dừng sau 8 frame.
    Quyền là dữ kiện của tiến trình, không suy ra từ frame."""
    import numpy as np

    from pok.perception.classify import classify
    from pok.perception.types import ScreenKind

    toi = np.full((898, 410, 3), 8, dtype=np.uint8)     # gần như đen, hf ~ 0

    r = classify(toi, permission_ok=False)
    assert r.kind is ScreenKind.NO_CONTENT

    r = classify(toi, permission_ok=True)
    assert r.kind is not ScreenKind.NO_CONTENT
    assert r.kind is not ScreenKind.GAME, "frame phẳng không được coi là màn game"
    assert r.kind is ScreenKind.UNKNOWN


# ── Nút ✕ KHÔNG nhất thiết ở sát góc ────────────────────────────────────────
# Đo thật trên tấm App Store sheet mà quảng cáo mở ra: ✕ ở (46,145).
# y=145 NGOÀI ô góc 130x130 -> cách quét theo crop góc không bao giờ thấy nó.
# Nên bước 2b quét CẢ FRAME rồi để cửa hình học lọc theo dải mép.

BAND = 0.15
W, H = 410, 898


def near_edge(cx, cy, band=BAND):
    rx, ry = cx / W, cy / H
    return rx <= band or rx >= 1 - band or ry <= band or ry >= 1 - band


def scan(name):
    img = cv2.imread(str(FIX / name))
    assert img is not None, f"thiếu fixture {name}"
    hits = close_icon.find(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    return [h for h in hits if near_edge(h.cx, h.cy)]


@pytest.mark.parametrize("name,mong_doi", [
    ("appstore_sheet_x_low.png", (46, 145)),   # ✕ THẤP hơn ô góc 130
    ("ad_dark_x_topright.png", (371, 91)),     # ✕ trắng trên nền đen
    ("ad_close_x.png", (32, 122)),             # ✕ đen trên nền trắng
])
def test_quét_cả_frame_tìm_đúng_x_mọi_vị_trí(name, mong_doi):
    keep = scan(name)
    assert len(keep) == 1, f"{name}: {len(keep)} ứng viên, mong đợi 1"
    h = keep[0]
    lech = ((h.cx - mong_doi[0]) ** 2 + (h.cy - mong_doi[1]) ** 2) ** 0.5
    assert lech < 3, f"lệch {lech:.1f}pt — ({h.cx:.0f},{h.cy:.0f})"


def test_crop_góc_130_bỏ_sót_x_ở_145():
    """Vì sao phải bỏ cách crop góc — giữ lại làm bằng chứng."""
    img = cv2.imread(str(FIX / "appstore_sheet_x_low.png"))
    from pok.perception.cheap import crop_corner
    for c in ("tl", "tr", "bl", "br"):
        crop, _ = crop_corner(img, c, 130)
        assert close_icon.find(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)) == []
    assert len(scan("appstore_sheet_x_low.png")) == 1      # quét cả frame thì thấy


@pytest.mark.parametrize("name", ["game_upgrade.png", "game_empyreal.png"])
def test_quét_cả_frame_không_dương_tính_giả_trên_màn_game(name):
    assert scan(name) == []
