"""Sửa app.js xong mà trình duyệt vẫn chạy bản cũ = tính năng "không hoạt động".

Bug đã gặp thật: thêm ô search vào tab Game Rules. `index.html` được phục vụ
mới nên ô search hiện ra, nhưng `/static/app.js` do `StaticFiles` phục vụ chỉ
kèm `etag` + `last-modified`, KHÔNG có `Cache-Control` — trình duyệt được phép
dùng lại bản cũ mà không hỏi lại server. Gõ vào ô search không lọc gì.
"""
from pathlib import Path

from pok.ui.server import bust_cache


def test_gắn_mtime_vào_js_và_css(tmp_path: Path):
    (tmp_path / "app.js").write_text("//")
    (tmp_path / "style.css").write_text("/**/")
    html = bust_cache(
        '<link href="/static/style.css"><script src="/static/app.js"></script>',
        tmp_path)

    assert "/static/app.js?v=" in html
    assert "/static/style.css?v=" in html


def test_sửa_file_thì_url_đổi(tmp_path: Path):
    f = tmp_path / "app.js"
    f.write_text("//")
    cu = bust_cache('<script src="/static/app.js">', tmp_path)

    import os
    os.utime(f, (0, 1_700_000_000))     # giả lập sửa file
    moi = bust_cache('<script src="/static/app.js">', tmp_path)

    assert cu != moi, "đổi file mà URL không đổi thì trình duyệt vẫn ăn bản cũ"


def test_thiếu_file_thì_không_nổ(tmp_path: Path):
    html = '<script src="/static/app.js"></script>'
    assert bust_cache(html, tmp_path) == html
