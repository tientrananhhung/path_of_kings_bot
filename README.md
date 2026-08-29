# POK Bot — Path of Kings (macOS + iPhone Mirroring)

Bot tự động chơi game và đóng quảng cáo trên iPhone qua **iPhone Mirroring** của
macOS. Điều khiển bằng **web UI** (xem/bấm được từ iPad hoặc máy khác) vì bot
chiếm chuột vật lý của Mac.

- Kiến trúc và lý do từng quyết định: [`PLAN.md`](PLAN.md)
- Số đo benchmark và các cạm bẫy đã gặp: [`poc/README.md`](poc/README.md)

---

## Cài đặt

```bash
cd "/Users/tientran/Tong Hop/path_of_kings_tool"
python3.11 -m venv .venv
./.venv/bin/pip install -e ".[vlm,dev]"
```

`[vlm]` kéo torch + transformers (~150MB) cho tầng C. Bỏ nó nếu chỉ cần tầng A/B
(khi đó đặt `vlm.enabled = false` trong `config/ads.toml`).

Weights Florence-2 (~450MB) tự tải lần đầu vào `~/.cache/huggingface/hub/`.

## Cấp quyền — bắt buộc, làm một lần

macOS đọc quyền **lúc app khởi động** và cấp theo **app cha** của process.

1. Mở **Terminal.app** (không chạy qua IDE/agent — quyền cấp theo app cha).
2. `System Settings > Privacy & Security > Screen & System Audio Recording` → bật cho **Terminal**.
3. `System Settings > Privacy & Security > Accessibility` → bật cho **Terminal**.
4. **`Cmd+Q` quit hẳn Terminal** rồi mở lại. Đóng cửa sổ không đủ.
5. Mở **iPhone Mirroring**, để iPhone khoá / không chạm vào cho nó kết nối.

Thiếu quyền Screen Recording thì macOS **không** báo lỗi — nó trả **hình nền
desktop** đã bóc hết cửa sổ. `pok doctor` phát hiện việc này bằng mật độ cạnh
(`hf < 1.0`).

## Chạy

```bash
./.venv/bin/python -m pok doctor
```

Kiểm tra quyền, tìm cửa sổ, đo scale + FPS, xác nhận ảnh chụp là thật. Chạy cái
này trước tiên.

```bash
./.venv/bin/python -m pok ui
```

Mở http://127.0.0.1:8765 — đây là cách dùng chính.

```bash
./.venv/bin/python -m pok ui --lan
```

Bind `0.0.0.0` để xem từ iPad/điện thoại. **Nên đặt `web.token`** trong
`config/app.toml` trước khi làm việc này.

Lệnh khác:

```bash
./.venv/bin/python -m pok probe      # chạy cả 3 tầng trên frame hiện tại, in ra terminal
```

```bash
./.venv/bin/python -m pok capture    # chụp 1 frame ra data/captures/
```

```bash
./.venv/bin/python -m pok run        # chạy bot không UI
```

## Hotkey toàn cục

Cần thiết vì bot chiếm chuột — bàn phím vẫn dùng được.

| Tổ hợp | Chức năng |
|---|---|
| `⌃⌥⌘S` | Start / Pause |
| `⌃⌥⌘K` | **KILL** — dừng ngay |
| `⌃⌥⌘C` | Chụp frame vào `data/captures/` |

## Bảy màn hình

| Tab | Dùng để |
|---|---|
| **Dashboard** | livestream 25–30 FPS + overlay hành động, start/stop/kill, log |
| **Game Rules** | tầng A — thêm/sửa luật, chọn toạ độ bằng cách click lên ảnh, lưu là reload nóng |
| **Ads** | tầng C — keyword, blocklist, ngưỡng lọc, chạy thử pipeline từng bước |
| **Capture** | thu ảnh quảng cáo thật + gắn tag. **Đây là bước quyết định của dự án** |
| **Sessions** | phiên đã chạy, ads đóng ở bước nào, xem lại `events.jsonl` |
| **Probe** | chạy cả 3 tầng cạnh nhau kèm ms, vẽ mọi box lên ảnh |
| **Settings** | doctor, cấu hình stream, hotkey, MJPEG dự phòng |

## Ba tầng nhận thức

Một luồng chụp duy nhất, chia sẻ cho mọi tầng và cả web. **AI không chạy liên tục.**

| Tầng | Chạy khi nào | Chi phí đo được |
|---|---|---|
| **A** numpy/OpenCV | mỗi frame | < 5ms |
| **B** Apple Vision OCR | cần đọc chữ | 62ms |
| **C** Florence-2 trên crop góc | chỉ khi B thất bại, ≤4 lần/quảng cáo | 531ms/góc |

Trong `GAME_PLAY`, tầng C chạy **0 lần**. Duty cycle tầng C ≈ **1.8%**.

Lần gọi VLM đầu tiên mất **12.3s** (nạp model + warm-up MPS), nên engine
prewarm ở nền ngay lúc Start — đừng để 12s đó rơi vào lúc gặp quảng cáo đầu.

## Lọc an toàn 3 cửa

Phần quan trọng nhất. Florence-2 (cả `base` và `base-ft`) khi nhận **cả ảnh** đã
thực sự gán nhãn nút **Install** màu xanh là "close button". Bấm vào đó là mở App
Store. Mọi ứng viên phải qua:

1. **Hình học** — tâm phải trong dải mép 15%, hoặc trong ô góc đã crop.
   Riêng cửa này chặn được cả nút Install (205,731) lẫn X giả (205,640).
2. **Blocklist chữ** — OCR quanh ứng viên bán kính 40pt; khớp
   `install / cài đặt / get / tải / mở / play / mua …` → loại.
3. **Kích thước** — > 4% diện tích cửa sổ, hoặc > 50% diện tích crop → loại.
   Ngưỡng theo crop là bắt buộc: khi không thấy gì, Florence-2 trả box phủ gần
   hết crop.

Ứng viên bị chặn vẫn được vẽ lên overlay (đỏ gạch chéo + lý do) — để bạn **thấy
được** lọc an toàn đang làm việc, thay vì bot "im lặng không làm gì".

## Cấu trúc

```text
config/         app.toml · game.toml (luật tầng A) · ads.toml (tầng C)
data/           captures/ · sessions/<ts>/{events.jsonl,stats.json} · debug/ · templates/
poc/            script benchmark + bằng chứng đo lường (giữ lại để debug)
src/pok/
  core/         window · capture · coords · actuator · safety · permissions
  perception/   types · cheap (A) · ocr (B) · vlm (C) · classify · worker
  engine/       states · machine · rules · ad_closer · watchdog
  store/        events · stats
  ui/           server (FastAPI) · hotkey · static/{index.html,app.js,style.css}
tests/          23 test — coords, keyword, lọc an toàn, safety, rules
```

```bash
./.venv/bin/python -m pytest tests/ -q
```

## Bốn ca watchdog

Cả bốn đều **đã xảy ra thật** khi làm POC, không phải suy đoán.

| Ca | Phát hiện | Khôi phục |
|---|---|---|
| iPhone Mirroring pause | OCR "iPhone đang được sử dụng" | tap "Kết nối" |
| Jiggle mode (chỉnh sửa icon) | OCR thấy nút "Xong" | tap nút đó |
| Spotlight mở ngoài ý muốn | OCR "Gợi ý của Siri" | gesture Home |
| Bị đẩy sang App Store | OCR nhiều hint App Store | gesture Home + mở lại game |

## Việc tiếp theo

Dùng tab **Capture** thu **30–50 ảnh quảng cáo thật** rồi gắn tag
(`text_button` / `icon_only` / `countdown` / `playable` / `redirect`).

Đó là thứ duy nhất hiện đang chặn: nó cho biết bao nhiêu % quảng cáo là nút **có
chữ** (OCR 62ms xử lý được) so với **icon-only** (cần VLM 531ms), và quan trọng
nhất — nút X thật có thật sự nằm ở **góc** hay không. Nếu không, cửa hình học
15% mép sẽ chặn luôn cả X thật và tầng C phải đổi sang lọc bằng kích thước +
độ tương phản thay vì vị trí.

## Rủi ro cần biết

Automation game vi phạm ToS của hầu hết mobile game → có khả năng ban account.
Tự động xem quảng cáo nhận thưởng về bản chất là ad fraud với nhà quảng cáo;
AppLovin / Unity Ads / IronSource có detection riêng, hệ quả thường là cắt
reward hoặc chặn thiết bị.

---

## Workflow làm một luật mới

Đây là quy trình đã dùng để làm luật PVP RAID, làm mẫu cho các màn khác.

**1. Chụp màn hình đang cần xử lý**

```bash
cd "/Users/tientran/Tong Hop/path_of_kings_tool" && ./.venv/bin/python -m pok capture
```

**2. Lấy toạ độ chính xác.** Đừng ước lượng bằng mắt — vẽ lưới lên ảnh:

```bash
cd "/Users/tientran/Tong Hop/path_of_kings_tool" && ./.venv/bin/python poc/grid.py data/captures/<file>.png 140 530 280 790
```

**3. Xem OCR đọc được gì.** Bước này bắt buộc, vì OCR thường đọc khác mắt người:

```bash
cd "/Users/tientran/Tong Hop/path_of_kings_tool" && ./.venv/bin/python -m pok probe
```

Ví dụ thật: banner **"PVP RAID"** bị OCR đọc thành **"PUP RAID"** (font pixel
biến V thành U). Luật khớp `"pvp raid"` sẽ **không bao giờ** khớp. Dùng `"raid"`.

**4. Viết luật vào `config/game.toml`**, `enabled = false` trước đã.

**5. Test khô — đánh giá mà KHÔNG hành động:**

```bash
curl -s -X POST http://127.0.0.1:8765/api/rules/test | python3 -m json.tool
```

Trả về từng luật khớp/không khớp, `cooldown_left`, luật nào sẽ bắn, và hành động
gì. Chạy cái này trước khi bật luật.

**6. Bật luật, chạy, rồi TINH CHỈNH tham số swipe.** Đây là bước dễ bị bỏ qua
nhất. Đo thật trên màn PVP RAID (`poc/tune_swipe.py`):

| `to` | `duration_ms` | Kết quả |
|---|---|---|
| 0.110 | 260 | **không commit** — animation trả về |
| 0.050 | 400 | **không commit** |
| 0.050 | **600** | **COMMIT ✓** |

Game này cần drag **chậm**. Swipe nhanh làm card dịch rồi bật lại. Ba tham số
điều chỉnh: `duration_ms`, `steps`, `hold_end_ms` (giữ ở điểm cuối trước khi nhả).

**7. Đặt `cooldown_s`.** Bắt buộc với luật `text`/`template`: OCR chỉ làm mới
mỗi ~2s, nên không có cooldown thì luật khớp lại trên dữ liệu cũ ở **mọi tick**
(12 lần/giây) và bot swipe liên tục.
