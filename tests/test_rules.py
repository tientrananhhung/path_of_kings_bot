import numpy as np

from pok.engine.rules import RuleEngine

GAME = {"rule": [
    {"name": "ưu tiên cao", "enabled": True, "priority": 10,
     "when": {"kind": "color", "at": [0.5, 0.5], "rgb": [0, 255, 0], "tolerance": 10},
     "do": {"action": "tap", "at": [0.5, 0.5]}},
    {"name": "ưu tiên thấp", "enabled": True, "priority": 90,
     "when": {"kind": "idle", "seconds": 5},
     "do": {"action": "tap", "at": [0.5, 0.9]}},
    {"name": "đã tắt", "enabled": False, "priority": 1,
     "when": {"kind": "always"}, "do": {"action": "tap", "at": [0, 0]}},
]}


def green():
    img = np.zeros((898, 410, 3), dtype=np.uint8)
    img[:, :] = (0, 255, 0)      # BGR
    return img


def test_bỏ_luật_đã_tắt_và_theo_priority():
    e = RuleEngine(GAME)
    hit = e.evaluate(green(), idle_seconds=0.0)
    assert hit and hit[0].name == "ưu tiên cao"


def test_idle_chỉ_khớp_khi_đủ_thời_gian():
    e = RuleEngine(GAME)
    black = np.zeros((898, 410, 3), dtype=np.uint8)
    assert e.evaluate(black, idle_seconds=1.0) is None
    hit = e.evaluate(black, idle_seconds=9.0)
    assert hit and hit[0].name == "ưu tiên thấp"


def test_phash_phát_hiện_màn_hình_không_đổi():
    e = RuleEngine(GAME)
    black = np.zeros((898, 410, 3), dtype=np.uint8)
    e.update_idle(black)
    second = e.update_idle(black)
    assert second >= 0.0
    e.update_idle(green())          # đổi hẳn -> reset
    assert e.update_idle(green()) < 1.0


def test_test_khô_đánh_giá_cả_luật_đang_tắt():
    """Quy trình là viết luật ở trạng thái TẮT -> test khô -> mới bật.
    Nếu evaluate bỏ qua luật tắt thì bước test khô vô nghĩa."""
    cfg = {"rule": [{"name": "đang tắt", "enabled": False, "priority": 1,
                     "when": {"kind": "text", "contains": "new gear found"},
                     "do": {"action": "tap", "at": [0.5, 0.5]}}]}
    e = RuleEngine(cfg)
    img = np.zeros((898, 410, 3), dtype=np.uint8)
    low = "new gear found! | divine"
    assert e.evaluate(img, 0.0, low) is None                      # chạy thật: bỏ qua
    hit = e.evaluate(img, 0.0, low, ignore_enabled=True)          # test khô: đánh giá
    assert hit and hit[0].name == "đang tắt"


def test_cooldown_chặn_bắn_lặp_nhưng_test_khô_vẫn_đánh_giá():
    cfg = {"rule": [{"name": "r", "enabled": True, "priority": 1, "cooldown_s": 5.0,
                     "when": {"kind": "always"},
                     "do": {"action": "tap", "at": [0.5, 0.5]}}]}
    e = RuleEngine(cfg)
    img = np.zeros((898, 410, 3), dtype=np.uint8)
    hit = e.evaluate(img, 0.0)
    assert hit
    e.note_fired(hit[0])
    assert e.evaluate(img, 0.0) is None                            # đang cooldown
    assert e.cooldown_left(hit[0]) > 4.0
    assert e.evaluate(img, 0.0, ignore_cooldown=True) is not None   # test khô


def test_tap_text_bền_hơn_toạ_độ_cố_định():
    """Bằng chứng thật đã quan sát trên màn RITUAL TROUBLE.

    Sau khi tap Pray, màn hình đổi sang bảng phần thưởng nhưng tiêu đề
    "RITUAL TROUBLE" VẪN CÒN -> luật vẫn khớp. Nếu dùng toạ độ cố định
    at=[0.256,0.657] thì bot sẽ tap vào ô phần thưởng ở giữa. Với tap_text,
    chữ 'pray' đã biến mất nên bot BỎ LƯỢT thay vì tap sai.
    """
    from pok.perception.types import TextBox

    def find(texts, needle):
        return next((t for t in texts
                     if needle in t.text.lower().strip()), None)

    trước = [TextBox("RITUAL TROUBLE", 1.0, 206, 143, 188, 26),
             TextBox("Pray", 1.0, 102, 642, 40, 20),
             TextBox("Smack", 1.0, 205, 641, 58, 18)]
    sau = [TextBox("RITUAL TROUBLE", 1.0, 206, 143, 188, 26),
           TextBox("YOUR REWARD", 1.0, 102, 660, 60, 14),
           TextBox("COLLECT", 1.0, 300, 760, 80, 20)]

    assert find(trước, "pray") is not None
    assert find(sau, "pray") is None          # -> bỏ lượt, không tap sai


def test_tap_text_dy_lệch_lên_giữa_thẻ():
    """dy dịch điểm tap khỏi nhãn vào giữa thẻ. Đo thật: nhãn 'Pray' ở
    (102,642) = rel y 0.715; dy=-0.055 -> 0.660, tức local y 592 ≈ tâm thẻ
    (thẻ y 500-680)."""
    H = 898
    ry = 642 / H + (-0.055)
    assert abs(ry - 0.660) < 0.002
    assert 500 < ry * H < 680


def test_cờ_enters_ad_được_đọc_từ_config():
    """Quảng cáo video mấy chục giây đầu KHÔNG có nút đóng, nên classify không
    có cách nào nhận ra 'đang ở quảng cáo'. Luật phải tự khai báo."""
    cfg = {"rule": [
        {"name": "vào ads", "enabled": True, "priority": 1, "enters_ad": True,
         "when": {"kind": "always"}, "do": {"action": "tap", "at": [0.5, 0.5]}},
        {"name": "không vào ads", "enabled": True, "priority": 2,
         "when": {"kind": "always"}, "do": {"action": "tap", "at": [0.5, 0.5]}},
    ]}
    e = RuleEngine(cfg)
    by_name = {r.name: r for r in e.rules}
    assert by_name["vào ads"].enters_ad is True
    assert by_name["không vào ads"].enters_ad is False
