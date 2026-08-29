# RUNBOOK — Thêm một event mới vào bot

Từ lúc game hiện một event lạ đến lúc bot xử lý được nó, chạy ổn định.

Quy trình này đã dùng thật cho event **PVP RAID**. Mọi con số ở đây là đo được,
không phải ước lượng.

> **Quy ước:** mọi lệnh chạy từ thư mục dự án.
> ```bash
> cd "/Users/tientran/Tong Hop/path_of_kings_tool"
> ```

---

## Bước 0 — Điều kiện tiên quyết

Web UI phải **đang chạy trong Terminal.app** (không phải qua IDE/agent — quyền
TCC cấp theo app cha):

```bash
./.venv/bin/python -m pok ui
```

Kiểm tra nhanh:

```bash
./.venv/bin/python poc/show.py doctor
```

Cần thấy `screen_recording: true`, `accessibility: true`, và `window` không null.

**Lưu ý về quyền:** các lệnh `pok capture` / `pok probe` tự tạo tiến trình chụp
riêng nên **chỉ chạy được trong Terminal.app đã cấp quyền**. Nếu bạn chạy chúng
từ chỗ khác sẽ gặp:

```
không chụp được: RuntimeError: CGWindowListCreateImage trả None
```

Cách chắc ăn hơn: dùng **API / hotkey**, vì chúng đi qua tiến trình server đã có
quyền. Runbook này ưu tiên cách đó.

---

## Bước 1 — Chụp màn event mới

Đưa game về đúng màn cần xử lý, rồi:

```bash
curl -s -X POST http://127.0.0.1:8765/api/capture/shot
```

Hoặc bấm hotkey **⌃⌥⌘C**, hoặc nút "Chụp ngay" ở tab **Capture**.

Ảnh vào `data/captures/`. Lấy file mới nhất:

```bash
ls -t data/captures/*.png | head -1
```

Mở ra xem. Ghi lại: **chữ gì đặc trưng cho màn này**, và **cần tap/swipe ở đâu**.

---

## Bước 2 — Xem OCR đọc được gì

**Bước bắt buộc, đừng bỏ.** OCR thường đọc khác mắt người.

```bash
./.venv/bin/python poc/show.py rules
```

Xem dòng `OCR:`. Ví dụ thật từ màn PVP RAID:

```
section 411-3 | 15,13m c | 1,84k * | war endedi | pup raid |
a rival player stole their castle! | ... | run | pup raid | swipe to decide
```

Banner trên màn hình ghi **"PVP RAID"** nhưng OCR đọc **"PUP RAID"** — font pixel
biến chữ V thành U. Luật khớp `"pvp raid"` sẽ **không bao giờ** khớp.
Nên dùng `"raid"`.

Muốn xem toạ độ từng vùng chữ (có sẵn cả `local point` và `rel`):

```bash
./.venv/bin/python poc/show.py ocr
```

```
1.00 (  206,   95) rel=(0.502,0.106)   208x  26  'NEW GEAR FOUND!'
1.00 (  205,  184) rel=(0.500,0.205)    58x  21  'DIVINE'
```

### Chọn loại điều kiện

| Loại | Dùng khi | Chi phí | Lưu ý |
|---|---|---|---|
| `text` | màn có chữ đặc trưng | 0 (dùng OCR đã có) | **ưu tiên dùng cái này** |
| `color` | không có chữ, nhưng có nút màu ở vị trí cố định | < 1ms | dễ vỡ khi game đổi theme |
| `template` | không chữ, không màu đặc trưng | ~2–5ms | phải cắt ảnh, xem Bước 3b |
| `idle` | dự phòng khi kẹt | 0 | luôn để `priority` cao nhất (bắn cuối) |

Chọn chuỗi `contains` **đủ đặc trưng nhưng chịu được lỗi OCR**. Nguyên tắc:
lấy phần OCR đọc chắc chắn đúng, bỏ ký tự dễ đọc sai.

---

## Bước 3 — Đo toạ độ

Đừng ước lượng bằng mắt. Vẽ lưới:

```bash
./.venv/bin/python poc/grid.py "data/captures/<file>.png" 140 530 280 790 20
```

Tham số: `<ảnh> x0 y0 x1 y1 <bước lưới>`. Kết quả ở `poc/out/grid.png`.
Nhãn trên lưới là **local point**. Đổi sang `rel` bằng cách chia `410 x 898`.

Ví dụ thật (màn PVP RAID):

```
lưỡi kiếm  y 535-625
nắm tay    y 645-690
cánh tay   y 690-745,  tâm x = 205
-> điểm bắt đầu (205, 700) = rel (0.500, 0.780)
```

Cách nhanh hơn: mở tab **Dashboard**, click lên ảnh livestream — góc phải hiện
`rel=(0.xxx, 0.yyy)`. Hoặc ở tab **Game Rules** bấm **chọn** rồi click lên ảnh.

> Khi bật *"tap khi click ảnh"* thì click sẽ **TAP THẬT** xuống iPhone.
> Tắt nó nếu chỉ muốn đọc toạ độ.

### Bước 3b — Nếu dùng `template`

Cắt template **từ ảnh trong `data/captures/`**, không phải từ `Cmd+Shift+4`.

Ảnh của bot là **point-resolution 410x898**. Ảnh chụp bằng phím tắt macOS là
**2x Retina** → `matchTemplate` không bao giờ khớp.

Lưu vào `data/templates/`, dùng **PNG** (JPEG có artifact làm tụt score). Cắt
càng nhỏ càng tốt, bỏ nền. Trong luật chỉ ghi **tên file**:

```toml
[rule.when]
kind = "template"
template = "arrow_right.png"      # -> data/templates/arrow_right.png
region = [0.6, 0.4, 1.0, 0.7]     # luôn đặt region: nhanh hơn + tránh khớp nhầm
min_score = 0.82                  # bắt đầu 0.80; sai thì tăng 0.88-0.92
```

Template được cache trong RAM sau lần đọc đầu → thay file thì phải Stop/Start.

---

## Bước 4 — Viết luật, để TẮT trước

Thêm vào `config/game.toml`:

```toml
[[rule]]
name = "TÊN EVENT -> hành động"
enabled = false          # bật ở Bước 6, sau khi test khô
priority = 10            # số nhỏ = xét trước
cooldown_s = 3.0         # BẮT BUỘC với text/template, xem Bước 8
[rule.when]
kind = "text"
contains = "chuỗi đặc trưng"
[rule.do]
action = "swipe"         # tap | swipe | hold
from = [0.500, 0.780]
to   = [0.050, 0.780]
duration_ms = 600        # tinh chỉnh ở Bước 7
steps = 24
hold_end_ms = 140
```

Hoặc làm hết trong tab **Game Rules** (có nút `+ luật`, `chọn` toạ độ,
`Lưu & reload nóng`) — không cần chạm file.

### Ý nghĩa từng field của `do`

| Field | Nghĩa |
|---|---|
| `at` | điểm tap/hold, rel 0..1 |
| `from` / `to` | điểm đầu/cuối swipe |
| `duration_ms` | tổng thời lượng drag — **yếu tố quyết định commit** |
| `steps` | số điểm nội suy (mặc định 18) |
| `hold_end_ms` | giữ chuột ở điểm cuối trước khi nhả (mặc định 80) |

---

## Bước 5 — Nạp config và TEST KHÔ

Nếu sửa file bằng tay thì nạp vào server đang chạy:

```bash
curl -s -X POST http://127.0.0.1:8765/api/config/game -H 'Content-Type: application/json' \
  -d "$(./.venv/bin/python -c "import tomllib,json;print(json.dumps(tomllib.load(open('config/game.toml','rb'))))")"
```

(Bấm `Lưu & reload nóng` trong UI thì không cần lệnh này.)

Test khô — **đánh giá mà KHÔNG hành động**:

```bash
./.venv/bin/python poc/show.py rules
```

```
  [x] p10  text      —     cd=0.0s  PVP RAID -> swipe trái (Run)
  [ ] p20  text      KHỚP  cd=0.0s  NEW GEAR -> swipe trái (Discard)
  [ ] p90  idle      —     cd=0.0s  tap giữa màn khi đứng yên

sẽ bắn   : None
hành động: None
```

Cách đọc:

- `[x]` / `[ ]` = luật đang bật / tắt
- `KHỚP` = điều kiện đúng trên frame này. Test khô **đánh giá cả luật đang tắt và
  luật đang trong cooldown** — chính vì quy trình là viết-tắt-rồi-test-rồi-bật.
- `sẽ bắn` = luật thực sự được chọn khi chạy. Ở ví dụ trên là `None` vì luật khớp
  đang tắt. Đó là kết quả đúng: *"điều kiện đúng rồi, chỉ chưa bật"*.

**Không KHỚP?** Xem lại `ocr_joined` ở Bước 2 — gần như luôn là do chuỗi
`contains` không có thật trong text OCR đọc được.

---

## Bước 6 — Bật luật và chạy ngắn

Đổi `enabled = true`, nạp lại, rồi:

```bash
curl -s -X POST http://127.0.0.1:8765/api/control/start
```

Mở tab **Dashboard** và xem:

- **Overlay** vẽ đường swipe qua đúng các điểm nội suy thật, kèm nhãn tên luật
- Dấu **đỏ gạch chéo** = hành động bị chặn, nhãn ghi rõ lý do
- **Log** hiện `ACTION swipe ... blocked=False`

Dừng sau vài giây:

```bash
curl -s -X POST http://127.0.0.1:8765/api/control/stop
```

Xem chính xác bot đã làm gì:

```bash
./.venv/bin/python poc/show.py events
```

```
STATE  PREFLIGHT -> GAME_PLAY   sync -> GAME
ACTION swipe  ok    rule   [0.5, 0.78] -> [0.0498, 0.7795] 600ms  PVP RAID -> swipe trái (Run)
```

---

## Bước 7 — Tinh chỉnh swipe (bước dễ bị bỏ qua nhất)

Swipe có thể **ăn mà không commit**: card dịch rồi bật lại, màn hình không đổi.
Nhìn ảnh không phân biệt được — phải đo.

```bash
./.venv/bin/python poc/tune_swipe.py --marker "swipe to decide" \
  --from-x 0.50 --y 0.78 --to-x 0.11 0.05 --ms 260 400 600
```

`--marker` là chữ mốc: **mất đi = đã commit**. Kết quả thật trên màn PVP RAID:

| `to_x` | `ms` | Commit? |
|---|---|---|
| 0.110 | 260 | không |
| 0.050 | 400 | không |
| 0.050 | **600** | **CÓ** |

Game này cần drag **chậm**. Script in ra dòng `DÙNG:` để copy vào `game.toml`.

Không biến thể nào commit thì thử theo thứ tự:

1. tăng `--ms` (800, 1200)
2. kéo xa hơn `--to-x 0.02`
3. tăng `--hold-end 300`
4. tăng `--steps 40`

---

## Bước 8 — Cooldown và chống lặp

`classify` (có OCR, 62ms) chỉ chạy **mỗi ~2 giây**, nhưng vòng lặp bot tick
**12 lần/giây**. Không có cooldown thì luật `text` khớp lại trên **OCR cũ** ở mọi
tick → bot swipe ~24 lần trong 2 giây.

Đặt `cooldown_s` **lớn hơn thời gian animation của game**. Kinh nghiệm:

| Loại màn | `cooldown_s` |
|---|---|
| swipe quyết định có animation | 3.0 |
| tap nút đơn giản | 1.5 |
| dự phòng `idle` | 5.0 |

Kiểm tra: chạy 10 giây, số action nên bằng `10 / cooldown_s` chứ không phải 120.

---

## Bước 9 — Chạy dài và đọc số

```bash
curl -s -X POST http://127.0.0.1:8765/api/control/start
```

Sau vài phút:

```bash
./.venv/bin/python poc/show.py stats
```

Cần thấy: `swipes` tăng đều, `blocked` = 0,
`stuck` = 0.

`stuck` tăng nghĩa là có màn hình bot **không có luật nào xử lý** → quay lại
Bước 1 cho màn đó.

---

## Bảng chẩn đoán

Đều là lỗi đã gặp thật.

| Hiện tượng | Nguyên nhân | Xử lý |
|---|---|---|
| Test khô không KHỚP | chuỗi `contains` khác text OCR đọc (V→U, l→I, 0→O) | đọc `ocr_joined`, dùng phần đọc chắc |
| Swipe ăn nhưng màn không đổi | `duration_ms` quá ngắn | Bước 7, thường cần 600ms+ |
| Bot swipe liên tục hàng chục lần | thiếu `cooldown_s` | đặt 3.0 |
| `out_of_bounds` | toạ độ rel > 1 hoặc < 0 | kiểm tra lại `at`/`to` |
| `forbidden_zone` | trúng vùng cấm trong `app.toml` | sửa `safety.forbidden_zones` |
| `rate_limit` | > 90 tap/phút | thường là dấu hiệu thiếu cooldown |
| `template` không bao giờ khớp | template cắt từ ảnh Retina 2x | cắt lại từ `data/captures/` |
| Bot dừng, log `frame không có nội dung` | vừa di chuyển cửa sổ iPhone Mirroring | tự phục hồi; dừng thật sau 8 frame liên tiếp |
| `pok capture` báo `CGWindowListCreateImage trả None` | chạy ngoài Terminal đã cấp quyền | dùng `/api/capture/shot` hoặc ⌃⌥⌘C |
| Test khô báo `—` cho luật vừa viết | chuỗi `contains` không có trong `ocr_joined` | `show.py ocr` để xem chữ thật |
| Luật bị nhồi field lạ (`at=[0]`, `min_score`…) | bug cũ của nút Lưu trong UI (đã sửa) | lưu lại một lần từ UI để dọn |

---

## Checklist trước khi coi là xong

- [ ] Test khô KHỚP đúng luật mong muốn, không khớp luật khác
- [ ] Chạy thật: overlay vẽ đúng chỗ, log `blocked=False`
- [ ] Swipe **commit** được (mốc nhận biết biến mất)
- [ ] `cooldown_s` đúng — 10 giây không sinh quá `10/cooldown_s` action
- [ ] Chạy 5 phút: `stuck` = 0, `blocked` = 0
- [ ] Đã ghi lại vào comment trong `game.toml`: toạ độ đo được và vì sao chọn
      `duration_ms` đó

---

## Ví dụ hoàn chỉnh — event PVP RAID

Luật cuối cùng sau khi đi hết 9 bước:

```toml
[[rule]]
name = "PVP RAID -> swipe trái (Run)"
enabled = true
priority = 10
cooldown_s = 3.0
[rule.when]
kind = "text"
contains = "raid"        # OCR đọc "PUP RAID", không phải "PVP RAID"
[rule.do]
action = "swipe"
from = [0.500, 0.780]    # tâm cánh tay cầm kiếm, đo được (205, 700)
to   = [0.050, 0.780]    # sang trái = "Run"; phải = "PVP RAID"
duration_ms = 600        # 260ms và 400ms KHÔNG commit, 600ms có
steps = 24
hold_end_ms = 140
```
