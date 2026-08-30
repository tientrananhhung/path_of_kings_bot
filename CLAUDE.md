# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Toàn bộ code, comment và tên test trong repo này viết bằng **tiếng Việt**. Giữ nguyên
quy ước đó khi thêm code mới.

## Lệnh

Không có `pip`/`python` toàn cục — mọi lệnh chạy qua venv của dự án:

```bash
./.venv/bin/python -m pytest tests/ -q
```

```bash
./.venv/bin/python -m pytest "tests/test_ad_gates.py::test_cửa_hình_học_chặn_nút_install_ở_giữa"
```

Tên test là tiếng Việt có dấu → luôn **quote** khi chạy một test lẻ hoặc dùng `-k`.

```bash
./.venv/bin/pip install -e ".[vlm,dev]"    # cài lại sau khi đổi pyproject
./.venv/bin/python -m pok doctor           # kiểm tra quyền + cửa sổ + FPS — chạy trước tiên
./.venv/bin/python -m pok ui               # cách dùng chính, http://127.0.0.1:8765
./.venv/bin/python -m pok probe            # chạy cả 3 tầng trên frame hiện tại, in ra terminal
./.venv/bin/python -m pok capture          # chụp 1 frame ra data/captures/
```

Không có linter/formatter nào được cấu hình.

### TCC — vì sao không chạy được `pok` từ agent/IDE

macOS cấp quyền Screen Recording + Accessibility theo **app cha** của process và đọc
quyền **lúc app khởi động**. Chạy `pok ui`/`doctor`/`probe`/`capture` từ agent hoặc IDE
sẽ thất bại dù đã cấp quyền cho Terminal. Có hai script bọc để chạy dưới TCC identity
của Terminal.app:

- `poc/run_ui.command` — kill rồi chạy lại `pok ui`, tee log ra `poc/out/ui.log`,
  tự mở browser khi cổng sẵn sàng. **Mặc định `--lan`** (double-click không truyền
  được tham số); `--local` để khoá về 127.0.0.1. Đặt `HF_HUB_OFFLINE=1`.
- `poc/run.command` — chạy lệnh đọc từ `poc/out/cmd.txt`, log ra `poc/out/run.log`

Khởi động nhanh: double-click `~/Desktop/POK Bot.command` (hoặc ⌘Space →
`POK Bot.app` trong `~/Applications`). Cả hai chỉ gọi lại `poc/run_ui.command`.
App là AppleScript `tell application "Terminal" to do script` chứ **không tự chạy
python** — nhờ vậy python vẫn là con của Terminal.app và thừa hưởng đúng TCC identity.
LaunchAgent hay Automator app tự spawn python sẽ nhận hình nền desktop, không phải
cửa sổ iPhone. Tạo lại lối tắt bằng `poc/install_launcher.command`.

**Test thì chạy được từ đâu cũng được** — chúng thuần logic, không đụng capture/OCR/VLM.

## Kiến trúc

`AppContext` (trong [cli.py](src/pok/cli.py)) là chỗ duy nhất nối các phần lại:
một `CaptureService`, một `EventBus`, một `BotEngine`. `pok ui` và `pok run` chỉ khác
nhau ở việc có bọc FastAPI hay không.

### Một luồng chụp, nhiều người tiêu thụ

[`CaptureService`](src/pok/core/capture.py) chạy **một** thread chụp
(`CGWindowListCreateImage`), đẩy vào ring buffer. Engine, web WebSocket, MJPEG và
`/api/probe` đều đọc `latest()` từ đây — **đừng bao giờ tự gọi `grab()` trong code mới**.

Throttle theo nhu cầu: `ctx.capture.demand` là callback do `AppContext` gắn vào,
trả `viewers > 0 or engine.running`. Không ai xem → hạ xuống 2 FPS. `measured_fps`
phải là nhịp thật của vòng lặp (gồm sleep), không phải năng lực chụp.

### Ba hệ toạ độ — nguồn lỗi số 1

Xem [coords.py](src/pok/core/coords.py). Quy ước bắt buộc:

| Hệ | Dùng ở đâu |
|---|---|
| **rel** 0..1 | config TOML, EventBus, overlay web, mọi API của `Actuator` |
| **local** point | ảnh chụp, `TextBox`, `Candidate`, kết quả perception |
| **screen** point | chỉ bên trong `Actuator` khi gọi `CGEventPost` |

Perception trả **local**, config chứa **rel**, actuator nhận **rel**. Chuyển local→rel
bằng `c.cx / w, c.cy / h` với `h, w = bgr.shape[:2]` ngay tại chỗ gọi. Ảnh chụp là
point-resolution (scale 1.0) nên pixel ảnh == local point, nhưng vẫn đi qua `coords.py`
thay vì cộng thẳng.

Apple Vision trả bbox gốc **góc dưới-trái, y hướng lên** — [ocr.py](src/pok/perception/ocr.py)
đã lật (`cy = (1 - y_vision) * h`). Không lật là tap ngược màn.

### Ba tầng nhận thức — AI không chạy liên tục

| Tầng | Module | Gọi từ đâu | Chi phí |
|---|---|---|---|
| A numpy/OpenCV | [cheap.py](src/pok/perception/cheap.py) | mỗi tick (`update_idle`, rule engine) | < 5ms |
| B Apple Vision OCR | [ocr.py](src/pok/perception/ocr.py) | qua `classify()`, giãn cách theo state | 62ms |
| C Florence-2 | [vlm.py](src/pok/perception/vlm.py) | chỉ ở `AD_CLOSING` bước 3, trên **dải 25% trên cùng** | ~600ms |

`BotEngine._need_classify()` là chốt chặn tầng B: 2.0s/lần trong `GAME_PLAY`, 0.8s ở
state khác. Kết quả cache trong `self.last_classify` và dùng lại cho mọi handler trong
tick đó.

Tầng C chạy trong [`PerceptionWorker`](src/pok/perception/worker.py) — thread riêng có
queue, để UI và engine không chặn nhau. `worker.start()` idempotent và tự gọi trong
`submit()` (bug đã gặp: gọi `/api/probe` trước khi Start làm job kẹt queue 60s).
Lần gọi VLM đầu mất 12.3s → `vlm.prewarm()` chạy ở nền ngay lúc `engine.start()`.

### Lọc an toàn 3 cửa — invariant quan trọng nhất

Florence-2 (cả `base` và `base-ft`) khi nhận **cả ảnh** đã thực sự gán nhãn nút
**Install** màu xanh là "close button". Vì vậy:

- `FlorenceVLM` **không có API nào nhận cả màn hình**, chỉ `detect_in_crop()`. Đừng thêm.
- Mọi `Candidate`, dù từ tầng nào, phải đi qua `AdCloser.filter_candidates()`:
  hình học (dải mép 15% hoặc trong crop góc) → kích thước (≤4% cửa sổ **và** ≤50% diện
  tích crop) → blocklist (OCR bán kính 40pt quanh candidate).
- Ngưỡng theo crop là bắt buộc, không phải phòng xa: khi không thấy gì Florence-2 trả
  box phủ gần hết crop, và với `corner_box` nhỏ hơn 130 thì box đó lọt cửa tuyệt đối.
- Candidate bị chặn vẫn publish event `candidate_blocked` để web vẽ đỏ gạch chéo.

**Bán kính blocklist khác nhau theo độ mạnh bằng chứng**, và đo tới **cạnh** hộp chữ chứ
không phải tâm-cộng-nửa-hộp. Bug đã gặp (phiên `20260830-080353`, bot đứng im 46 giây trên
quảng cáo có ✕ to rõ ở góc): `classify` dùng chính dấu ✕ (372,68) làm bằng chứng "đây là
quảng cáo", rồi `filter_candidates` vứt đúng dấu ✕ đó vì chữ `PLAY NOW` ở gần. Cạnh hộp chữ
cách 38.8pt, nhưng luật cũ cộng nửa chiều rộng hộp (94/2) vào bán kính 40 thành **87pt**.
Chiều dài một chuỗi chữ không nói gì về vị trí nút bấm.

| nguồn ứng viên | bán kính | vì sao |
|---|---|---|
| `vlm:*`, `ocr` | 40pt | model đoán — Florence-2 từng gán nhãn nút Install là "close button" |
| `icon` (tầng 2b) | 20pt | bằng chứng **hình học**, không phải đoán |

Điểm nằm **trong** hộp chữ thì chặn bất kể nguồn. Khoá trong
[tests/test_blocklist_ban_kinh.py](tests/test_blocklist_ban_kinh.py).

[tests/test_ad_gates.py](tests/test_ad_gates.py) khoá các ca này lại. Đổi ngưỡng trong
`config/ads.toml` mà test đỏ thì ngưỡng sai, không phải test sai.

### Hai kiểu khớp keyword — đừng dùng nhầm

- `classify._match_word()` — khớp theo **biên từ**, **bỏ keyword < 3 ký tự**. Dùng để
  **phân loại màn hình**. Bug đã gặp: `"x" in low` khớp chữ "Dược Xuan" trên TikTok →
  mọi màn bị coi là quảng cáo → bot tap bừa 4 góc.
- `ocr.find_any()` — khớp **substring**. Dùng để **tìm nút** khi đã biết đang ở màn nào.

Thêm điều kiện nữa ở `classify()`: keyword quảng cáo chỉ tính khi **sát mép** (`_near_edge`,
18%) — chữ ở giữa màn là nội dung.

Và hai danh sách keyword, **đừng dùng nhầm** (`keywords_for_classify()` chọn hộ):

- `ads.close_keywords` — **tìm nút** khi đã biết đang ở quảng cáo. Rộng tay được.
- `ads.classify_keywords` — **kết luận màn này là quảng cáo**. Hẹp. Chữ nào cũng nằm trên
  nút của *game* thì không được có ở đây.

Bug đã gặp thật (`data/sessions/20260830-045859`): màn rương vàng cuối lượt có nút
**CONTINUE** ở (116,779) → `ry=0.867` lọt dải mép → `"continue"` trong `close_keywords`
→ `classify` ra `AD`. Vòng lặp kín 5 giây/vòng suốt 60 giây, **không một `action` nào**:
`_state_game` thấy AD là `return` sang `AD_WATCHING` trước khi chạy luật → 5s →
`AD_CLOSING` → luật CONTINUE khớp nên tưởng đã đóng xong → `GAME_PLAY` → lặp lại.
Khoá lại trong [tests/test_classify_chest_continue.py](tests/test_classify_chest_continue.py).

### Luật tầng A khớp ⇒ màn đó là GAME, dù classify nói AD

Nửa còn lại của bug trên, và là chốt tổng quát cho mọi keyword nhận nhầm sau này:
`_state_ad_closing` vốn lấy "có luật tầng A khớp" làm bằng chứng dương *đã về game*.
Nay `_state_game` và `_state_sync` dùng **cùng** bằng chứng đó qua `_rule_signature()` —
hai chỗ dùng hai tiêu chuẩn khác nhau chính là thứ tạo ra vòng lặp.

Bằng chứng phải là luật engine **thật sự hành động được**: luật đang tắt không tính, luật
đã nằm trong `_declined` (khớp nhưng không làm được trên chính kết quả OCR này) cũng
không tính. Nếu không, bot đứng im trong `GAME_PLAY` — state **duy nhất không có timeout**.
Luật đang cooldown thì vẫn tính (màn hình có đổi đâu). Xem
[tests/test_game_rule_beats_ad.py](tests/test_game_rule_beats_ad.py).

### Luật text: keyword trên HUD phải chặn bằng `y_min`/`y_max`

`rules.evaluate` khớp luật text bằng **substring trên toàn bộ chữ của màn hình**. Bug đã
gặp thật: nav bar đáy màn hình của game đọc ra

    ... | tauern | shop | pup raid | bosses | rank

nên luật `contains = "pup raid"` (priority 2, swipe TRÁI) khớp ở **mọi màn**, kể cả lúc
nhân vật đang chạy — bot quẹt trái không ngừng. OCR đọc `PVP` thành `PUP` nên đừng ngạc
nhiên khi thấy cả hai cách viết trong config.

Cách chặn: `when.y_max` (và `y_min`) — chữ phải nằm trong dải dọc đó. Trên dialog PVP RAID
thật, tiêu đề ở `y/h = 0.192`, nav bar ở ~0.95, nên `y_max = 0.5` giữ dialog và loại nav
bar. Không khai báo thì giữ nguyên hành vi cũ (khớp cả màn).

Khai báo vùng thì `evaluate` **phải** được truyền `texts=` — không có `TextBox` thì không
biết chữ nằm đâu, và luật sẽ không bao giờ khớp.
`WHEN_FIELDS.text` trong [app.js](src/pok/ui/static/app.js) phải liệt kê `y_min`/`y_max`,
nếu không lần Lưu kế tiếp từ web UI sẽ xoá sạch chúng.
Xem [tests/test_rule_vung_doc.py](tests/test_rule_vung_doc.py).

### `download`/`install` sát mép — bắt quảng cáo playable

Quảng cáo **playable** trượt cả bốn cửa còn lại của `classify`: không keyword đóng, không
dấu ✕ (nút đóng là `▶▶|`), không đủ hint App Store, `hf` bình thường → rơi vào nhánh mặc
định `GAME`. Bot tưởng đang chơi game và đứng im 187 giây
(`data/sessions/20260830-111459`).

Tín hiệu cứu được ca này là **icon app kèm nhãn `Download` ở góc trên trái** — khung chuẩn
của mọi playable. Đo trên 30 ảnh `data/captures`: `download`/`install` xuất hiện ở **0 màn
game, 2 màn quảng cáo**. Game không có nút tải app nào nên rủi ro rất thấp.

### Dấu ✕ sát mép — bằng chứng phân loại thứ ba

Rất nhiều quảng cáo **không có chữ nào** để bắt: nút đóng vẽ bằng đồ hoạ, OCR đọc ra
rỗng. `classify()` vì thế còn một cửa cuối trước nhánh mặc định GAME —
`_icon_near_edge()` chạy `close_icon.find()` trên **cả frame** rồi giữ hit nằm trong dải
`icon_classify_band` (18%). Có hit → `AD`.

Đây là tín hiệu hình học, không phải chữ, nên **không** dính bug kiểu `"x" in "Dược Xuan"`.
Đo trên 44 ảnh `data/captures`: 11 màn quảng cáo ra `AD` với đúng 1 ứng viên qua đủ 4 cửa,
33 màn game giữ `GAME` với 0 ứng viên. Bốn dấu ✕ bị bắt trên màn game đều ở **giữa**
(`y/h` 0.70–0.78) nên dải mép loại hết.

Trang App Store **có** ✕ sát mép được coi là `AD` chứ không phải `APPSTORE`: đó là sheet
mở đè lên quảng cáo, đóng bằng ✕ thì giữ được phiên chơi và phần thưởng, còn để watchdog
gesture Home là mất cả hai. Không thấy ✕ mới là bị đẩy hẳn sang App Store.

Bug đã gặp thật, và là lý do cửa này tồn tại: App Store sheet của quảng cáo Binance chỉ
khớp **một** hint App Store (`"Nhận"`) nên không đủ ngưỡng 2, lại không có keyword đóng
nào → rơi vào `GAME`. Engine ở `GAME_PLAY` nên không bao giờ vào `AD_CLOSING`, không bao
giờ gọi `step_icon`, và quảng cáo đứng nguyên — dù `close_icon.find()` đã thấy nút ✕ ở
(46,145) điểm 0.61 ngay từ đầu. Khoá lại trong
[tests/test_classify_ad_icon.py](tests/test_classify_ad_icon.py).

### Cửa sổ ≠ màn hình — viền máy là 38pt phía trên

`cheap.content_rect()` trả khung màn hình iPhone thật bên trong cửa sổ. Đo trên 45 ảnh
`data/captures`: 44 ảnh cho **T=38 B=8 L=8 R=8** trên cửa sổ 410×898 → nội dung **394×852
tại (8,38)**, khớp màn iPhone 6.1" (393×852 point).

Bỏ qua chuyện này là bug đã gặp thật (phiên `data/sessions/20260828-155109`):

- `crop_corner` cắt góc **cửa sổ** → ô `tr` 130×130 có 38 hàng đen thuần ở trên và 8 cột
  đen bên phải; gần 1/3 tấm crop đưa cho Florence-2 là viền máy.
- `blind_tap.at = [0.93, 0.05]` hiểu theo cửa sổ ra (381,45) — trừ viền thì chỉ cách mép
  trên **màn hình** 7pt, tức vùng notch. Cả hai blind tap của bước 5 bắn vào chỗ trống rồi
  bot escalate về Home.

Nay `blind_tap.at` là rel theo **màn hình thật**, `blind_points()` lo quy đổi sang rel cửa
sổ cho `Actuator`, và blind tap **cũng phải qua cửa blocklist** — nó là điểm đoán, không
có gì bảo đảm dưới nó không phải nút Install.

### Bước 2c — detector tự train

`data/models/close_button_v2.pt` — YOLOv8n fine-tune từ `roboflow_v1.pt`, **imgsz 960**,
47 ảnh. Vị trí: giữa 2b và tầng C, vì rẻ hơn tầng C ~26 lần.

| | |
|---|---|
| latency | **23ms** @ imgsz 960 |
| train (38 ảnh) | trúng **20/20**, dương tính giả **0** |
| val (9 ảnh) | trúng 3/4, dương tính giả **0** |

**`imgsz` phải khớp lúc train.** Ảnh 410×898 mà nút chỉ 14×14: ở 640 letterbox co xuống
~10px, sát ngưỡng nhìn thấy của đầu ra P3 (stride 8); ở 960 thành ~15px. Model đầu tiên
(`roboflow_v1.pt`, train ở 640) chỉ tìm ra **2/29** ảnh — gần như mù. Cùng dữ liệu, chuyển
sang 960 thì thành 20/20.

Nó làm được thứ tầng C làm sai: trên sheet App Store (hai nút ở đỉnh — ✕ bên trái, **share**
bên phải), YOLO chọn đúng ✕ (46,145) còn Florence-2 chọn nút share (364,145).

Ứng viên 2c đi qua **đủ** cửa lọc như mọi tầng khác. Riêng `_gate_side` [20,50] **không**
áp: khoảng đó đo cho Florence-2 trên crop góc 130×130, mượn sang detector khác là chặn oan
dấu ✕ thật 14×14.

#### Vòng lặp dữ liệu

    bot chạy -> data/samples/ (SampleWriter ghi hit/miss)
             -> poc/build_yolo_dataset.py
             -> poc/train_yolo.py  -> data/models/close_button_v2.pt

Mỗi lần train là train **TOÀN BỘ** dữ liệu, và luôn xuất phát lại từ `roboflow_v1.pt`.
Không train tiếp chỉ bằng ảnh mới: mạng nơ-ron sẽ quên sạch phần cũ. Không nối tiếp từ bản
trước: mỗi vòng sẽ chồng thêm một lớp lệch không tách ra được, và kết quả hết tái lập.

**Phải liếc qua tập mẫu trước khi train.** `hit` là bằng chứng gián tiếp và đã sinh ra 3
nhãn sai thật: hai lần VLM chỉ vào **nút bánh răng của game** ở (44,86), bot tap, quảng cáo
tự tắt ngay sau nên bị ghi là trúng; một lần `close_icon` bắt nhầm **chữ X trong
"LOST EXPLORER"**. Cả ba nay nằm trong `CHAC_CHAN_LA_GAME` của
[poc/build_yolo_dataset.py](poc/build_yolo_dataset.py) và được dùng làm **nhãn âm** — nhãn
âm khó, quý hơn ảnh game thường.

Class hiếm phải nằm trong tập **train**: nút `▶▶`/`>>` chỉ có đúng MỘT mẫu, lần train đầu
nó rơi vào val nên model không học được gì từ nó (20/20 train nhưng sót đúng cái đó).
Không đo được nó còn hơn không học được nó.

File `.pt` nằm trong `data/` nên **không lên git**; máy khác clone về sẽ tự chạy ở chế độ
không có 2c (`enabled` kiểm tra cả file có tồn tại không).

`ultralytics` đòi `opencv-python` trong khi dự án dùng `opencv-python-headless` cùng
version — hai gói ghi đè nhau, nên cài bằng `--no-deps` (xem `pyproject.toml`). Nó **không**
đụng torch 2.13 / transformers 5.16.

Xem [tests/test_yolo_buoc_2c.py](tests/test_yolo_buoc_2c.py).

### Tầng C — một lần quét dải 25% trên cùng, prompt `"circle button"`

Không còn quét 4 ô góc 130×130. Lý do bỏ: nút đóng không nhất thiết sát góc — ✕ của
App Store sheet ở (46,145) nằm **ngoài** ô góc nên tầng C không bao giờ nhìn thấy. Mọi nút
đóng đã đo đều nằm trong 17% trên cùng (`y/h`: 0.161 · 0.135 · 0.101 · 0.076 · 0.137), nên
dải 25% giữ trọn 5/5 mà **1 lần gọi ~0.6s thay cho 4 lần ~4.2s**.

Prompt: **`"circle button"`, một cái duy nhất, và cố ý KHÔNG chứa chữ "close"**. Đo trên
dải 25% của 6 ảnh, mỗi prompt ~580ms:

| prompt | trúng |
|---|---|
| `close button` / `close icon` / `close` / `skip button` | **0/6** — trả box phủ trọn crop = "không thấy gì" |
| `circular button` | 2/3 |
| **`circle button`** | **3/3** |

Florence-2 train trên ảnh đời thường nên **không có khái niệm "nút đóng"**; tả hình dạng
thì nó nhìn ra, tả chức năng thì không. Giá phải trả: nó cũng chỉ ra nút bánh răng của game
ở (44,86) 32×32 — chấp nhận được vì `_state_ad_closing` thoát ngay khi có luật tầng A khớp.

Cảnh báo: ngưỡng `_gate_side` **[20,50]** được đo dưới chế độ CŨ (2 prompt, crop góc
130×130). Dưới chế độ mới, nút thật đo được là 26×28, 30×34 và **một ✕ thật 18×18 bị chặn**
vì dưới ngưỡng 20. Ca đó tầng 2b vẫn bắt được nên chưa mất gì, nhưng ngưỡng này đáng đo lại.

### Đang chờ tap lại ≠ không tìm thấy

Bốn bước tìm nút xếp theo độ tin cậy giảm dần (2 → 2b → 2c → 3). Tầng nào có ứng viên
nhưng đang trong cửa `retry_after_s` thì **dừng luôn**, không rơi xuống tầng yếu hơn.

Bug đã gặp (`data/sessions/20260830-170024`, kẹt 60 giây trên sheet App Store). Sheet đó
có **hai** nút ở đỉnh: ✕ đóng bên trái (46,145) và nút **share** bên phải (364,145).

    2b tìm đúng ✕ (46,145) 18×18 → tap → điểm vào cooldown 15s
    chu kỳ sau: 2b bị `already_tried` bỏ qua → RƠI XUỐNG tầng 3
    tầng 3 tap `circle button` (364,145) 47×48 = nút SHARE → mở sheet chia sẻ
    chu kỳ sau: 2b tap ✕ → đóng sheet chia sẻ, quay lại App Store
    ✕ lại vào cooldown → lại rơi xuống tầng 3 → lại tap share… vô tận

Nút share 47×48 lọt cửa `_gate_side` [20,50] một cách hợp lệ — không siết ngưỡng nào cứu
được. Gốc rễ là **"đang chờ tap lại" bị đối xử y như "không tìm thấy"**. Xem
[tests/test_cooldown_khong_tut_tang.py](tests/test_cooldown_khong_tut_tang.py).

### Xác nhận tap — và bot tự gán nhãn cho chính nó

`closed_by_step` **không chứng minh được tầng nào đang gánh việc**: nó chỉ ghi "lúc phát
hiện đã về game thì đang ở bước mấy", nên quảng cáo tự tắt trong lúc VLM chạy 0.6s cũng
được tính cho VLM. Đừng dùng nó để so tầng.

`_confirm_tap()` mới là chỗ đo thật, dùng `ads.confirm_delay_s` (1.2s):

| kết cục | điều kiện | dùng làm |
|---|---|---|
| `hit` | về được màn game trong cửa sổ chờ | mẫu **dương** — chỗ đó đúng là nút đóng |
| `miss` | hết cửa sổ mà phash y nguyên (d ≤ 3) | mẫu **âm** |
| (bỏ) | màn đổi nhưng vẫn ở quảng cáo | không kết luận được, **không ghi mẫu** |

Kết quả vào `stats.hit_by_origin` tách theo `ocr` / `icon` / `vlm:top`, và vào
`data/samples/` qua [`SampleWriter`](src/pok/store/samples.py): ảnh PNG **của frame ngay
TRƯỚC lúc tap** + khung ứng viên + kết cục. Chụp lại sau khi tap là muộn — màn hình đã đổi.

Đây là dữ liệu để train detector sau này: nhãn cần đúng ba thứ (ảnh · khung · class) và cả
ba đều đã có sẵn trong vòng đời một lần đóng quảng cáo. Bot chạy bình thường là dữ liệu tự
sinh, không ai phải ngồi khoanh tay từng tấm.

Khi **cả ba tầng bó tay** (escalate ở bước 5), bot lưu frame với `box: null`, kèm danh
sách điểm đã thử. Đây là mẫu **quý nhất** và là loại **duy nhất phải khoanh tay**. Phải lưu
đúng khoảnh khắc đó: ngay sau là gesture Home, màn hình biến mất — chờ người dùng tự bấm
chụp thì gần như luôn muộn.

**`hit` là bằng chứng gián tiếp** — quảng cáo tự tắt đúng trong cửa sổ 1.2s cũng ra `hit`.
Hiếm, nhưng đừng coi tập này là nhãn vàng; liếc qua trước khi train.
Tắt bằng `ads.collect_samples = false`. Xem
[tests/test_xac_nhan_tap.py](tests/test_xac_nhan_tap.py).

### Ngân sách thời gian cho một quảng cáo

| tham số | giá trị | nghĩa là gì |
|---|---|---|
| `min_watch_seconds` | **8s** | chờ SAU KHI quảng cáo đã hiện, rồi mới bắt đầu tìm nút đóng |
| `no_ad_grace_s` | **5s** | màn hình không đổi sau ngần này → chẳng có quảng cáo nào, về game |
| `rescan_max_s` | **120s** | **trần TỔNG**: quét tối đa ngần này rồi mới escalate (vuốt Home) |
| `retry_after_s` | **15s** | tap không ăn thì chờ ngần này rồi được tap lại chỗ cũ |
| `TIMEOUTS[AD_CLOSING]` | **210s** | phải > `rescan_max_s` + `countdown_max_wait_s` |

Quảng cáo có thể dài tới 120 giây, nên **đừng bỏ cuộc sớm hơn thế** — nhưng cũng đừng ngồi
chờ 120 giây trước khi thử. Hai chuyện khác nhau: `min_watch_seconds` là lúc **bắt đầu**,
`rescan_max_s` là lúc **bỏ cuộc**.

`retry_after_s` là mảnh ghép làm cho việc quét sớm an toàn: nút đóng lúc đầu thường **đang
tắt**, quanh nó là vòng tròn đếm giờ. Tap lúc đó không ăn. Nếu `already_tried` cấm vĩnh viễn
thì đúng cái nút thật bị loại khỏi danh sách mãi mãi, kể cả sau khi nó sáng lên.

`AD_WATCHING` cũng thoát **ngay** khi có bằng chứng đã về màn game (`_back_to_game`, dùng
chung với `AD_CLOSING`).

Vì sao không quét ngay ở giây thứ 5 — phiên `data/sessions/20260830-081318`: quét lúc đó,
quảng cáo **còn đang tải** (OCR ra 4 chữ). Bước 3 tap ứng viên VLM ở
rel (0.906, 0.150) → **mở thẳng App Store**, kẹt 45 giây, phải escalate + 5 cú vuốt Home.
Một cú tap sớm tốn **60 giây**.

Nhiều quảng cáo hiện nút đóng **ngay** nhưng đang tắt, quanh nó là vòng tròn đếm giờ. Vòng
tròn là **đồ hoạ**, `countdown_left()` đọc chữ nên không thấy — `retry_after_s` là cách xử lý:
cứ tap, không ăn thì 15 giây sau tap lại, tới khi nút sáng. `TIMEOUTS[AD_WATCHING]` (150s) **phải lớn hơn** `min_watch_seconds`, nếu không
STUCK cắt ngang.

**Nhưng phải RỜI được màn game trước đã.** Bằng chứng "có luật tầng A khớp" đúng ở **cả hai
phía**: trước khi quảng cáo kịp hiện, và sau khi đã đóng xong. Bug đã gặp
(`data/sessions/20260830-111459`): luật `enters_ad` bắn lúc 6.3s, **0.2 giây sau** bot kết
luận "quảng cáo đã đóng" và về `GAME_PLAY` — màn hình lúc đó vẫn là dialog UPGRADE, nên
chính cái luật vừa mở quảng cáo lại thành bằng chứng đã về game. Quảng cáo hiện lên sau đó,
`classify` trả `GAME` (playable: không ✕, không keyword) → không còn đường nào quay lại
`AD_CLOSING`. **Bot đứng im 187 giây.**

Nay `_state_ad_watching` ghi `_ad_entry_hash` ở tick đầu và chỉ nhận bằng chứng về-game sau
khi phash đã lệch quá `STALE_PHASH_DIST`. Màn hình không đổi sau `ads.no_ad_grace_s` (5s)
→ kết luận **không có quảng cáo nào** và về `GAME_PLAY` luôn.

**Nhưng cửa grace đó chỉ áp khi `classify` KHÔNG nói AD.** Bug đã gặp
(`data/sessions/20260830-154455`): quảng cáo end-card nền đen, ảnh **tĩnh**, có ✕ rõ ở
(372,126). Vào `AD_WATCHING` vì classify ra AD, nhưng phash không bao giờ đổi → grace kết
luận "không có quảng cáo nào" → `GAME_PLAY` → classify lại ra AD → vào lại. Vòng lặp 5
giây/lần, không bao giờ tới `AD_CLOSING` (cần 8s) nên không bao giờ tap được dấu ✕ nằm ngay
đó. `classify == AD` **tự nó** đã là bằng chứng đang ở trong quảng cáo.
Xem [tests/test_ad_watching_tran.py](tests/test_ad_watching_tran.py).

### Đã bỏ: blind tap

Sáu điểm tap đoán ở bước 5 đã bỏ hẳn. Đo trên 57 phiên: nó đóng được **1/45** lần, đổi lại
là 6 cú tap mù vào màn quảng cáo. Hết `rescan_max_s` thì escalate về Home luôn.

### Số cũ giữ lại làm mốc — độ chính xác 14% của chế độ crop góc

Chạy Florence-2 trên 7 màn × 2 prompt × 4 góc: **22 ứng viên lọt đủ 4 cửa cũ, chỉ 3 cái
đúng**. Trong phiên thật nó tap (29,115) và (322,67) trong khi nút skip ở (376,123).

Hai thứ chỉnh được, đều đã đo:

- **Prompt.** `"close button"` một mình là không đủ. Trên quảng cáo playable, nút đóng là
  nút tròn `▶▶|` chứ không phải ✕; với `"close button"` Florence-2 trả box phủ 98% crop
  (= không thấy gì), còn `"circular button"` trả đúng (376,122) 26×26 — **lệch 1pt**.
- **Cửa `_gate_side`** (chỉ áp cho tầng C): cạnh lớn nhất phải trong `[20, 50]`pt. Giữ cả
  3 cái đúng, loại 15/19 cái sai → 14% lên **43%**.

Trần của cửa này: cặp 47×46 xuất hiện ở **cả hai phía** — một cái đúng (tl, lệch 1pt) và
một cái sai (tr, lệch 318pt) trên cùng tấm ảnh. Kích thước không tách nổi. Đừng siết thêm
mà tưởng sẽ khá hơn.

HoughCircles đã thử và **loại**: nó bắt cả nút UI của game (màn `game_upgrade` có circle
ngay tại (375,124), đúng chỗ nút skip của quảng cáo).

### State machine

[machine.py](src/pok/engine/machine.py) tick 12 Hz. **Không sleep dài trong state** —
mỗi state có `entered_at`, handler kiểm tra `self.elapsed`. Timeout khai báo tập trung
trong [states.py](src/pok/engine/states.py), hết hạn → `STUCK`.

`Watchdog.handle()` chạy **trước** mọi state handler và có quyền cướp state. Bốn ca
(PAUSE / JIGGLE / SPOTLIGHT / APPSTORE) đều đã xảy ra thật khi làm POC.

`_state_ad_closing()` là pipeline 6 bước có state riêng trong `AdAttempt`
(`step`, `corner_idx`, `blind_idx`, `tried_points`) — mỗi tick **làm đúng một việc rồi
`return`**, không lặp hết pipeline trong một tick.

### Focus phải giành TRƯỚC khi quyết định

`Actuator.ensure_focus()` gọi `activate()` + `sleep(0.25)` khi cửa sổ iPhone Mirroring
không frontmost — tức là **mọi lúc người dùng đang nhìn web UI**. Đo trên
`data/sessions/20260830-052421`, 16/16 hành động: tap tốn 1.40s (sleep lý thuyết 0.13s),
swipe tốn 2.08s (lý thuyết 0.72s). Phần dư **1.27–1.37s là hằng số**, giống hệt nhau cho
tap và swipe → không phải độ dài cú vuốt, mà là phần mở màn cố định.

Hậu quả: luật quyết định đúng trên màn A, 1.3 giây sau chuột mới chạm màn, lúc đó game đã
sang màn B → swipe trái rơi vào màn đang chạy. Cửa `STALE_PHASH_DIST` **không cứu được**
vì nó chạy trước 1.3 giây đó. Vì vậy `_tick()` gọi `act.ensure_focus(win)` **trước** cả
OCR, rồi chụp lại ảnh và OCR lại ngay trong tick đó.

Trong 1.3 giây mới giải thích được 0.26s (`activate()` 8ms + `sleep(0.25)`); **~1.0s còn
lại chưa rõ** — trường `ms` của event `action` sinh ra để đo nốt.

**`is_frontmost` phải hỏi window server, không được hỏi `NSWorkspace`.** Đo trực tiếp:
`activate(iPhone)` trả True sau 8ms, window server báo `Phản chiếu iPhone` từ +0.25s đến
+1.50s, còn `NSWorkspace.frontmostApplication()` vẫn khăng khăng app cũ **mãi mãi** — nó
không cập nhật trong tiến trình không bơm run loop, mà engine là thread thuần.

Và việc lấy focus **không bao giờ được `return`** khỏi tick. Đã gặp thật: `is_frontmost`
luôn False → mọi tick đều tưởng "vừa activate" → bỏ lượt → **bot đứng im hoàn toàn**, mà
`GAME_PLAY` là state duy nhất không có timeout nên không gì kêu lên.
Xem [tests/test_focus_latency.py](tests/test_focus_latency.py).

Event `action` mang theo `ms` — thời gian THẬT tới lúc nhả chuột. Thiếu số này thì không
biết hành động rơi vào màn nào; bug trên đã phải suy ngược từ khoảng cách giữa các event
`classify`.

### SafetyGuard — chặn cứng

Mọi hành động đi qua `Actuator`, và `Actuator` gọi `guard.check_action()` trước khi
`CGEventPost`. Không có đường vòng. `clamp_hold_ms` giới hạn 250ms vì giữ lâu hơn là
iOS vào jiggle mode (đã gặp thật).

Chỉ dùng `CGEventPost` → `kCGHIDEventTap`. `CGEventPostToPid` và AppleScript System
Events **không tới được** iPhone Mirroring (đo bằng `poc/poc1d_live_test.py`: 1.6% và
0.0% đổi màn = nhiễu).

### EventBus — hợp đồng với web UI

[events.py](src/pok/store/events.py) là pub/sub + ghi `data/sessions/<ts>/events.jsonl`.
`Actuator` publish event `action` cho **mọi** hành động, **kể cả khi bị SafetyGuard chặn**
(`blocked: true` + `block_reason`) — overlay web dựa vào đó để vẽ. Swipe publish **điểm
nội suy thật**, không phải đường thẳng giả định. Thêm hành động mới thì phải giữ đúng
hợp đồng này, nếu không bot sẽ "im lặng không làm gì" dưới mắt người dùng.

### Config

Ba file TOML trong `config/`, đọc qua `Config` với đường dẫn có dấu chấm
(`cfg.get("app.capture.target_fps", 30)`). Section trùng tên module: `app` / `game` / `ads`.

Lưu từ web UI (`POST /api/config/{section}`) ghi lại bằng `tomli_w` và **xoá hết comment**.
Sửa comment thì sửa tay file, đừng lưu từ UI.

Reload nóng chỉ có tác dụng nếu `set_config` được cập nhật: `game` → `rules.reload()`,
`ads` → gán lại `closer.cfg`, `app` → `guard.__init__()` + `stream_cfg`. Thêm object nào
đọc config lúc khởi tạo thì phải thêm vào đó, không thì phải restart mới có tác dụng.

### Web UI

[server.py](src/pok/ui/server.py) — FastAPI. Stream qua WebSocket **binary**: header
12 byte (`>Id` = frame_id uint32 BE + ts double BE) + JPEG. Overlay **không** vẽ vào
JPEG — detection gửi riêng bằng JSON kèm `frame_id`, client vẽ lên canvas. Backpressure:
luôn gửi frame mới nhất, không xếp hàng. State gửi 4 Hz, độc lập nhịp frame.
`FrameCache` encode JPEG một lần cho mọi client. `uvicorn` cần package `websockets`,
thiếu nó thì `/ws` trả 404 chứ không báo lỗi.

Hotkey toàn cục ([hotkey.py](src/pok/ui/hotkey.py)) là bắt buộc chứ không phải tiện ích:
bot **chiếm chuột vật lý** nên không bấm được nút trên UI cùng máy.

## Cạm bẫy đã đo được

- **Thiếu quyền Screen Recording không báo lỗi** — macOS trả **hình nền desktop** đã bóc
  hết cửa sổ. Hình nền có `std ~35`, cao hơn màn game tối, nên `std > 0` cho dương tính
  giả. Phát hiện bằng `high_freq_energy()`: màn iPhone 1.67–2.04, hình nền 0.46, ngưỡng
  **1.0**. `ScreenKind.NO_CONTENT` → engine dừng ngay.
- **Tên cửa sổ bị localized** ("Phản chiếu iPhone") → dò theo bundle id
  `com.apple.ScreenContinuity`, không bao giờ theo tên.
- **OCR level `fast`** nhanh 5x nhưng mất hết dấu tiếng Việt (`Kết nối` → `K6t n6i`) →
  chỉ dùng `accurate`.
- **Checkpoint `microsoft/Florence-2-base`** không load được với transformers 5.x →
  dùng `florence-community/Florence-2-base-ft`.

## Tài liệu

- [PLAN.md](PLAN.md) — thiết kế hiện hành, có lý do từng quyết định. Đây là nguồn đúng.
- [plan_bot.md](plan_bot.md) — **plan cũ đã bị thay thế** (YOLOv8 + `pyautogui` + `sleep(32)`).
  Đừng lấy làm căn cứ.
- [poc/README.md](poc/README.md) — số đo benchmark thật trên máy này. Mọi con số
  hard-code trong code đều truy được về đây.
- `poc/` giữ lại để debug, không phải code chết. `poc/state.py`, `poc/fix_pos.py`,
  `poc/restore_home.py` dùng được độc lập khi cần chẩn đoán tay.

## Việc đang chặn dự án

**Câu hỏi "nút X có nằm ở góc không" đã có đáp án — là KHÔNG.** Đo trên 44 ảnh trong
`data/captures`: ✕ xuất hiện ở (46,145), (32,121), (371,91), (372,68). Cái ở y=145 nằm
**ngoài** ô góc 130×130, nên cách quét theo crop góc của tầng C không bao giờ thấy nó.
Lời giải đang dùng là bước 2b — `close_icon.find()` quét **cả frame** (16ms) rồi để dải
mép lọc — chứ không phải đổi tầng C sang lọc theo kích thước + tương phản.

Mẫu quảng cáo mà bước 2b **trượt** thì đã có: quảng cáo **playable**
(`tests/fixtures/ad_playable_skip.png`) đóng bằng nút tròn `▶▶|`, không có dấu ✕ nào.
Đó là ca duy nhất tầng C hiện đang gánh — và nó chỉ gánh được sau khi thêm prompt
`"circular button"`.

Việc còn lại, theo thứ tự:

1. **`classify` không nhận ra quảng cáo playable.** Không ✕, không keyword → ra `GAME`.
   Hiện chỉ vào được `AD_CLOSING` nhờ luật khai báo `enters_ad`. Nếu bot rơi vào màn này
   bằng đường khác thì đứng im. Chưa có tín hiệu nào tách được nút skip của quảng cáo với
   nút tròn của game — HoughCircles đã thử và trượt.
2. **Bốn ứng viên sai vẫn lọt cửa `_gate_side`**, hai trong số đó trên màn game. Chỉ hại
   khi bot đang ở `AD_CLOSING` nhầm trên màn game, mà ca đó `_state_ad_closing` thoát ngay
   ở bước kiểm `rules.evaluate`. Chấp nhận được, nhưng nên theo dõi.
3. Thu thêm mẫu quảng cáo playable để biết nút skip có luôn tròn và luôn ở góc phải không.
