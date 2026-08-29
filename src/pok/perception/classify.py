"""Phân loại màn hình. Dùng tầng A trước, chỉ gọi OCR khi cần.

Bốn trạng thái đặc biệt dưới đây đều ĐÃ XẢY RA THẬT khi làm POC, không phải
suy đoán: PAUSE (chạm vào iPhone), JIGGLE (giữ chuột lâu), SPOTLIGHT (tap sai),
NO_CONTENT (thiếu quyền -> chụp ra hình nền desktop).
"""
from __future__ import annotations

import re

import cv2

from ..core.capture import high_freq_energy
from . import close_icon
from .ocr import joined, recognize
from .types import ClassifyResult, ScreenKind

PAUSE_HINTS = ("đang được sử dụng", "đã kết thúc do", "iphone in use",
               "iphone đang được")
JIGGLE_HINTS = ("xong", "done")
SPOTLIGHT_HINTS = ("gợi ý của siri", "tìm kiếm gần đây", "siri suggestions",
                   "recent searches")
HOME_HINTS = ("tìm kiếm", "search")
APPSTORE_HINTS = ("app store", "nhận", "cài đặt", "in-app purchases",
                  "mua trong ứng dụng")


def _near_edge(t, w: int, h: int, band: float = 0.18) -> bool:
    rx, ry = t.cx / max(1, w), t.cy / max(1, h)
    return rx <= band or rx >= 1 - band or ry <= band or ry >= 1 - band


def _icon_near_edge(bgr, cfg: dict):
    """Dấu ✕ SÁT MÉP -> đang ở quảng cáo. Trả IconHit hoặc None.

    Vì sao đây là tín hiệu phân loại hợp lệ, trong khi keyword thì phải rất dè
    chừng (xem `_match_word`): dấu ✕ được đo bằng hình học chứ không phải chữ,
    nên không dính bug kiểu `"x" in "Dược Xuan"`.

    Đo thật trên 44 ảnh chụp trong data/captures (`icon_min_score=0.35`,
    dải mép 0.18):

        8 màn quảng cáo  -> đều tìm ra ✕ đúng chỗ, sát mép:
            App Store sheet Binance   (46,145) điểm 0.61-0.66
            App Store sheet E.D.E.N   (32,121) điểm 0.62
            ad Binance nền đen        (371, 91) điểm 0.64
            ad playable "3 hour..."   (372, 68) điểm 0.60
        25 màn game thuần -> 0 ứng viên sát mép. Có 4 ✕ bị bắt nhưng đều ở
            GIỮA màn (y/h = 0.70-0.78) nên dải mép loại hết.

    -> 0 dương tính giả, 8/8 dương tính thật. Chính là thứ `classify` cần.

    Bug đã gặp thật, đây là cách sửa: App Store sheet Binance chỉ khớp ĐÚNG MỘT
    hint App Store ("Nhận") nên không đủ ngưỡng 2, lại không có keyword đóng nào
    -> rơi vào nhánh mặc định GAME. Engine ở GAME_PLAY nên không bao giờ vào
    AD_CLOSING, không bao giờ gọi `step_icon`, và quảng cáo đứng nguyên đó dù
    tầng dò đã thấy nút ✕ từ lâu.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hits = close_icon.find(
        gray,
        min_score=float(cfg.get("icon_min_score", 0.35)),
        max_mid=float(cfg.get("icon_max_mid", 0.15)))
    h, w = bgr.shape[:2]
    band = float(cfg.get("icon_classify_band", 0.18))
    for hit in hits:
        rx, ry = hit.cx / max(1, w), hit.cy / max(1, h)
        if rx <= band or rx >= 1 - band or ry <= band or ry >= 1 - band:
            return hit
    return None


def keywords_for_classify(ads_cfg: dict) -> list[str]:
    """Keyword được phép dùng để KẾT LUẬN "màn này là quảng cáo".

    Tách khỏi `close_keywords` (thứ dùng để TÌM NÚT khi đã biết đang ở quảng
    cáo) vì hai việc chịu rủi ro khác nhau — xem comment trong config/ads.toml.
    Thiếu `classify_keywords` thì lùi về `close_keywords` để config cũ vẫn chạy.
    """
    kws = ads_cfg.get("classify_keywords")
    if kws:
        return list(kws)
    return list(ads_cfg.get("close_keywords", []))


def _match_word(haystack: str, keywords: list[str]) -> str | None:
    """Khớp theo BIÊN TỪ, và bỏ keyword quá ngắn.

    Bug đã gặp thật: `"x" in low` khớp chữ "Dược Xuan" trên màn TikTok -> mọi
    màn hình bị phân loại là quảng cáo -> bot vào AD_CLOSING và tap bừa 4 góc.
    Keyword 1-2 ký tự (x, ×, ✕) hữu ích cho việc TÌM NÚT (ocr.find_any so khớp
    cả cụm text) nhưng vô dụng và nguy hiểm cho việc PHÂN LOẠI MÀN HÌNH.
    """
    for k in keywords:
        k = k.lower().strip()
        if len(k) < 3:
            continue
        if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", haystack):
            return k
    return None


def classify(bgr, *, ad_keywords: list[str] | None = None,
             ad_icon: dict | None = None,
             need_ocr: bool = True,
             permission_ok: bool = True) -> ClassifyResult:
    """permission_ok: trạng thái quyền Screen Recording THẬT của tiến trình.

    Bug đã gặp: mật độ cạnh thấp được coi là "thiếu quyền -> macOS trả hình nền
    desktop", nhưng một quảng cáo video NỀN ĐEN cũng có mật độ cạnh thấp
    (đo được hf=0.73, dải trên mean=0.2 std=5.1). Bot tưởng thiếu quyền rồi tự
    dừng sau 8 frame. Quyền là dữ kiện của tiến trình, không phải thứ suy ra từ
    từng frame — nên chỉ báo NO_CONTENT khi quyền thật sự thiếu.
    """
    hf = high_freq_energy(bgr)
    if hf < 1.0 and not permission_ok:
        return ClassifyResult(ScreenKind.NO_CONTENT,
                              f"hf={hf:.2f} và THIẾU quyền Screen Recording "
                              f"-> đang chụp ra hình nền desktop", hf=hf)
    if not need_ocr:
        return ClassifyResult(ScreenKind.UNKNOWN, "chưa OCR", hf=hf)

    texts = recognize(bgr)
    low = joined(texts)
    exact = {t.text.lower().strip() for t in texts}

    # Dấu ✕ sát mép — tính MỘT LẦN (6-16ms), dùng ở hai chỗ bên dưới: nhánh
    # App Store và cửa cuối ngay trước nhánh mặc định GAME.
    edge_x = _icon_near_edge(bgr, ad_icon) if ad_icon else None

    if any(h in low for h in PAUSE_HINTS):
        return ClassifyResult(ScreenKind.PAUSE, "khớp hint pause", texts, hf)
    if any(h in low for h in SPOTLIGHT_HINTS):
        return ClassifyResult(ScreenKind.SPOTLIGHT, "khớp hint spotlight", texts, hf)
    if exact & set(JIGGLE_HINTS):
        return ClassifyResult(ScreenKind.JIGGLE, "thấy nút Xong/Done", texts, hf)
    if sum(1 for h in APPSTORE_HINTS if h in low) >= 2:
        # Trang App Store CÓ ✕ sát mép là tấm sheet mở đè lên quảng cáo, không
        # phải app App Store thật. Đóng bằng ✕ thì game vẫn chạy và giữ được
        # phần thưởng; để watchdog gesture Home là mất cả hai. Không thấy ✕ thì
        # đúng là đã bị đẩy hẳn sang App Store -> giữ nguyên đường cũ.
        if edge_x is not None:
            return ClassifyResult(
                ScreenKind.AD,
                f"sheet App Store có ✕ sát mép @({edge_x.cx:.0f},"
                f"{edge_x.cy:.0f}) điểm={edge_x.score:.2f} -> đóng bằng ✕",
                texts, hf)
        return ClassifyResult(ScreenKind.APPSTORE, "khớp nhiều hint App Store", texts, hf)

    # Home Screen: có ô tìm kiếm + nhiều nhãn icon
    if any(h in low for h in HOME_HINTS) and len(texts) >= 8:
        return ClassifyResult(ScreenKind.HOME, "ô tìm kiếm + nhiều nhãn icon",
                              texts, hf)

    if ad_keywords:
        # Chỉ tính keyword nằm SÁT MÉP. Nút đóng quảng cáo thật ở mép/góc; chữ
        # ở giữa màn là nội dung. Không có điều kiện này thì nội dung tuỳ ý
        # (feed video) sinh dương tính giả liên tục — đã xảy ra thật với TikTok.
        h_img, w_img = bgr.shape[:2]
        for t in texts:
            if not _near_edge(t, w_img, h_img):
                continue
            hit = _match_word(t.text.lower().strip(), ad_keywords)
            if hit:
                return ClassifyResult(
                    ScreenKind.AD,
                    f"keyword {hit!r} sát mép @({t.cx:.0f},{t.cy:.0f})",
                    texts, hf)

    # Không có keyword nào khớp không có nghĩa là không phải quảng cáo: rất
    # nhiều quảng cáo chỉ có mỗi dấu ✕ vẽ bằng đồ hoạ, OCR không đọc ra chữ nào.
    # Đây là cửa cuối trước khi rơi vào nhánh mặc định GAME.
    if edge_x is not None:
        return ClassifyResult(
            ScreenKind.AD,
            f"dấu ✕ sát mép @({edge_x.cx:.0f},{edge_x.cy:.0f}) "
            f"điểm={edge_x.score:.2f}",
            texts, hf)

    if hf < 1.0:
        # Quyền đủ nhưng frame gần như phẳng: màn tối/đang chuyển cảnh. KHÔNG
        # được coi là màn game — nếu không, lúc đang ở AD_CLOSING nó sẽ bị hiểu
        # là "đã đóng xong quảng cáo".
        return ClassifyResult(ScreenKind.UNKNOWN,
                              f"frame gần như phẳng (hf={hf:.2f}), quyền vẫn đủ",
                              texts, hf)

    return ClassifyResult(ScreenKind.GAME, "không khớp màn hệ thống nào",
                          texts, hf)
