"""Bug thật đã gặp: keyword 1 ký tự 'x' khớp chữ 'Dược Xuan' trên màn TikTok
-> mọi màn hình bị phân loại là quảng cáo -> bot tap bừa 4 góc."""
from pok.perception.classify import _match_word

KWS = ["skip", "skip ad", "close", "đóng", "continue", "tiếp tục",
       "done", "xong", "no thanks", "bỏ qua", "×", "✕", "x"]


def test_single_char_keyword_không_gây_dương_tính_giả():
    tiktok = "dược xuan | bài đăng 2 | trang chủ | cửa hàng | hộp thư | hồ sơ"
    assert _match_word(tiktok, KWS) is None


def test_khớp_quảng_cáo_thật():
    assert _match_word("install | skip ad | 4.8 free", KWS) == "skip"
    assert _match_word("bỏ qua quảng cáo | cài đặt", KWS) == "bỏ qua"


def test_biên_từ():
    assert _match_word("skipper of the ship", ["skip"]) is None
    assert _match_word("please skip now", ["skip"]) == "skip"


def test_bỏ_keyword_ngắn():
    assert _match_word("xxxxx", ["x", "××"]) is None
