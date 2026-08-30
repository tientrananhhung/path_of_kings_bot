# PLAN — Bot Path of Kings (macOS + iPhone Mirroring)

> Phiên bản 2, ngày 2026-08-28. Thay thế `plan_bot.md`.
> Mọi con số trong file này là **đo thật** trên máy đích (macOS 26.4.1, MacBook M1 16GB),
> không phải ước lượng. Nguồn: `poc/README.md`.

---

## 0. Bối cảnh và những gì đã chốt

### 0.1 Đã kiểm chứng bằng POC

| Hạng mục | Kết quả đo | Script |
|---|---|---|
| Cửa sổ iPhone Mirroring | bundle `com.apple.ScreenContinuity`, tên **localized** ("Phản chiếu iPhone"), 410x898 point | `poc/common.py` |
| Chụp màn hình | `CGWindowListCreateImage` — **15.9ms (63 FPS)**, point-resolution, không vẽ con trỏ | `poc/poc2_capture.py` |
| Điều khiển | `CGEventPost` → `kCGHIDEventTap` — **swipe 7.87%, tap 74.26%** thay đổi màn → ăn | `poc/poc1d_live_test.py` |
| OCR tiếng Việt | Apple Vision `accurate` — **61.8ms**, confidence 1.00 | `poc/bench_ocr.py` |
| VLM tìm nút icon | Florence-2-base-ft, crop góc 130x130 — **531ms, Δ0pt** | `poc/bench_florence.py` |

### 0.2 Đã loại trừ

- `pyautogui.screenshot` — 112ms (chậm 7x), trả 2x gây click lệch, vẽ con trỏ vào ảnh.
- `mss` — nhanh nhưng vẽ con trỏ; không dùng cho so ảnh.
- `CGEventPostToPid` — **không** điều khiển được (bỏ qua window server, iPhone Mirroring cần đường HID).
- AppleScript `System Events → click at` — **không ăn** (đi qua Accessibility API, không phải HID).
- YOLOv8 — **bỏ hoàn toàn cho combat**. Game đủ dễ, chỉ cần swipe/tap theo vị trí.
  (Vẫn dùng cho việc KHÁC: bước 2c tìm nút đóng quảng cáo — xem CLAUDE.md.)
- Florence-2 trên **cả màn hình** — gán nhãn nút **Install** là "close button". Bắt buộc crop góc.

### 0.3 Ràng buộc thiết kế phát sinh từ POC

1. **Bot chiếm chuột vật lý.** Không thể vừa chạy bot vừa dùng máy. → UI phải điều khiển được **không cần chuột**: global hotkey + web UI xem/bấm được từ thiết bị khác.
2. **iPhone Mirroring tự pause** mỗi khi chạm vào iPhone. Đã gặp thật. → cần watchdog.
3. **Giữ chuột lâu trên Home Screen làm iOS vào jiggle mode.** Đã tự gây ra. → giới hạn thời gian giữ chuột, và có recovery.
4. **Tap sai có thể mở Spotlight / mở app lạ.** Đã tự gây ra. → cần phân loại màn hình trước mỗi hành động.
5. Latency Florence-2 = **430ms cố định + 13ms/token**. → hỏi câu cho ra ít token; không OCR cả màn hình bằng VLM.

### 0.4 Non-goals (không làm)

- Không train model. Không gán nhãn dataset. Tầng C dùng zero-shot.
- Không nhận diện quái / skill / thanh máu bằng AI.
- Không chạy trên iPhone thật qua WebDriverAgent/Appium.
- Không chống phát hiện (anti-detection), không giả lập hành vi người.
- Không hỗ trợ Windows/Linux/Android.

---

## 1. Kiến trúc

### 1.1 Sơ đồ tầng

```text
┌──────────────────────────────────────────────────────────────────────┐
│  WEB UI (FastAPI + WebSocket)   ←── xem/điều khiển từ máy khác/iPad  │
│  GLOBAL HOTKEY (⌃⌥⌘ P/S/K)      ←── điều khiển khi chuột bị chiếm    │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ đọc AppState, gửi Command
┌────────────────────────────▼─────────────────────────────────────────┐
│  SUPERVISOR — vòng đời, watchdog, safety guard, kill switch          │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ CAPTURE       │   │ BOT ENGINE      │   │ PERCEPTION       │
│ thread 63 FPS │──▶│ state machine   │──▶│ WORKER thread    │
│ ring buffer   │   │                 │◀──│ (model nặng)     │
└───────────────┘   └────────┬────────┘   └──────────────────┘
                             │ Action(tap/swipe/wait)
                    ┌────────▼────────┐
                    │ ACTUATOR        │
                    │ CGEventPost HID │
                    └─────────────────┘
```

### 1.2 Ba tầng nhận thức (theo chi phí)

| Tầng | Chạy khi nào | Công nghệ | Chi phí | Dùng để |
|---|---|---|---|---|
| **A** | mỗi frame, 10–15 FPS | numpy + OpenCV: color probe, template match, perceptual hash | **< 5ms** | phân loại màn hình, phát hiện thay đổi, luật game (swipe/tap vị trí) |
| **B** | khi tầng A báo "có chữ cần đọc" | Apple Vision OCR `accurate` | **62ms** | đọc nút có chữ: Skip / Đóng / Continue / Done, phát hiện màn pause, phát hiện blocklist (Install) |
| **C** | chỉ khi B không tìm ra nút đóng | Florence-2-base-ft, crop góc 130x130, MPS fp16, `num_beams=1` | **531ms/góc** | tìm nút X dạng **icon** không có chữ |

Nguyên tắc: **không bao giờ nhảy tầng.** Tầng C chỉ chạy sau khi A và B đã thất bại.
Ở trạng thái chơi game bình thường, tầng B và C **không chạy** → CPU gần như rảnh.

### 1.3 Luồng dữ liệu

- `CaptureService` chạy độc lập, ghi frame mới nhất vào ring buffer (giữ 60 frame ≈ 4s lịch sử để debug).
- `BotEngine` đọc frame mới nhất (không chờ), quyết định, phát `Action`.
- `PerceptionWorker` là thread riêng có queue: `BotEngine` gọi đồng bộ (chờ kết quả) vì trong state đóng ads thì chờ 0.5s là chấp nhận được; UI gọi bất đồng bộ cho tính năng Probe.
- `EventBus` phát mọi sự kiện (state change, action, detection, error) → UI stream qua WS, đồng thời ghi JSONL vào `data/sessions/`.

### 1.4 Ngân sách tính toán — AI **không** chạy liên tục

Điểm dễ hiểu sai nhất của kiến trúc này. Nói rõ:

**Chụp ảnh là MỘT luồng duy nhất, liên tục.** Tầng A, B, C và livestream web đều
đọc từ cùng ring buffer đó. Không có chuyện chụp riêng cho từng tầng.

**Tầng C (Florence-2) chỉ chạy khi hội đủ 4 điều kiện:**

1. State đang là `AD_CLOSING`
2. Đã chờ hết `min_watch_seconds`
3. Tầng B (OCR 62ms) đã tìm **không ra** nút có chữ
4. Chỉ trên **crop góc 130x130**, tối đa 4 góc

Trong `GAME_PLAY`, tầng C chạy **0 lần**.

**Dòng thời gian một tick khi chơi game** (~83ms ở 12 FPS):

```text
capture 15.9ms → tầng A <5ms → quyết định → swipe/tap     dư ~62ms
```

**Dòng thời gian một quảng cáo 30 giây (trường hợp tệ nhất):**

```text
phát hiện AD           tầng A, <5ms
chờ min_watch          chỉ tầng A quét phash
OCR full frame         62ms       ← tầng B, MỘT lần
  thấy "Skip Ad" → tap, xong. Tầng C KHÔNG chạy.
  không thấy     ↓
crop trên-phải         531ms      ← tầng C lần 1
crop trên-trái         531ms      ← lần 2 (chỉ khi lần 1 trượt)
crop dưới-phải         531ms      ← lần 3
crop dưới-trái         531ms      ← lần 4
                       ─────
tổng tệ nhất           2.19s cho cả quảng cáo 30 giây
```

**Duty cycle** (giả sử quảng cáo mỗi ~2 phút):

| Tầng | Tần suất | Chi phí | % thời gian |
|---|---|---|---|
| Capture | liên tục | 15.9ms | ~19% (1 thread) |
| A | mỗi frame | <5ms | ~6% |
| B (OCR) | watchdog mỗi 2s + 1 lần/ad | 62ms | ~3% |
| **C (Florence-2)** | **≤4 lần/ad** | 531ms | **~1.8%** |

Model nạp một lần rồi giữ trong RAM (416MB fp16, lazy load lần đầu cần) — không
có chi phí nạp lại.

**Vì sao không cho AI xem mọi frame:** vừa chậm (531ms → ~2 FPS), vừa vô ích
(99% frame là màn game, không có gì cho nó làm), vừa **nguy hiểm** — Florence-2
trên cả màn hình đã gán nhãn nút **Install** là "close button" (§0.2).

---

## 2. Công nghệ

| Thành phần | Chọn | Lý do |
|---|---|---|
| Ngôn ngữ | Python **3.11** | torch/transformers ổn định; 3.14 (mặc định máy) chưa hỗ trợ tốt |
| Chụp màn hình | `pyobjc-framework-Quartz` → `CGWindowListCreateImage` | 63 FPS, không con trỏ, point-resolution (không bug Retina) |
| Điều khiển | `pyobjc-framework-Quartz` → `CGEventPost(kCGHIDEventTap)` | đã đo là đường duy nhất iPhone Mirroring nhận |
| Tìm cửa sổ | `CGWindowListCopyWindowInfo` + `NSWorkspace` theo **bundle id** | tên app bị localized |
| Xử lý ảnh | `numpy` + `opencv-python-headless` | headless: không kéo GUI deps |
| OCR | `pyobjc-framework-Vision` (Apple Vision) | 62ms, on-device, tiếng Việt `vi-VT`, không tải model |
| VLM | `transformers` ≥5.16 + `torch` (MPS) — `florence-community/Florence-2-base-ft` | native `Florence2ForConditionalGeneration`, không cần `trust_remote_code` |
| Web server | `fastapi` + `uvicorn` | nhẹ, WebSocket sẵn, không cần build step |
| Frontend | HTML + vanilla JS + CSS thuần (không framework, không npm) | không build step; UI này đơn giản, không cần React |
| Hotkey toàn cục | `pyobjc-framework-Quartz` CGEventTap (listen-only) | không cần thư viện ngoài |
| Config | TOML (`tomllib` stdlib đọc, `tomli-w` ghi) | người đọc được, sửa tay được |
| Log | JSONL + `logging` | dễ grep, dễ replay |
| Test | `pytest` | |

**Không dùng:** PySide6/Tkinter (bot chiếm chuột → UI native trên cùng máy vô dụng), Electron, React/Vue/npm, Docker.

---

## 3. Cấu trúc dự án

```text
path_of_kings_tool/
├── PLAN.md                      ← file này
├── README.md                    hướng dẫn cài + chạy
├── pyproject.toml
├── .venv/                       (đã có, Python 3.11)
│
├── poc/                         ← GIỮ LẠI. Bằng chứng đo lường + script debug
│   ├── README.md                toàn bộ số đo và cạm bẫy
│   └── *.py
│
├── config/
│   ├── app.toml                 cửa sổ đích, FPS, cổng web, hotkey, safety limits
│   ├── game.toml                tầng A: luật chơi game (điều kiện → hành động)
│   └── ads.toml                 tầng C: keyword, blocklist, vùng góc, ngưỡng
│
├── data/                        (gitignore)
│   ├── captures/                ảnh thu thập cho việc phân tích ads
│   ├── sessions/<ts>/           events.jsonl, stats.json, frames/
│   └── debug/                   ảnh before/after khi có lỗi
│
├── src/pok/
│   ├── __main__.py              `python -m pok`
│   ├── cli.py                   subcommand: run / ui / doctor / capture / probe
│   ├── config.py                load/validate/save TOML → dataclass
│   │
│   ├── core/
│   │   ├── window.py            tìm cửa sổ theo bundle id, bounds, activate
│   │   ├── capture.py           CaptureService (thread + ring buffer)
│   │   ├── coords.py            Point/Pixel/Rect, quy đổi window↔screen, scale
│   │   ├── actuator.py          tap / swipe / drag / hold qua CGEventPost HID
│   │   ├── safety.py            SafetyGuard: kill switch, rate limit, vùng cấm
│   │   └── permissions.py       preflight Screen Recording + Accessibility
│   │
│   ├── perception/
│   │   ├── types.py             Detection, ScreenKind, Candidate (dataclass)
│   │   ├── cheap.py             tầng A: color probe, template match, phash, diff
│   │   ├── classify.py          phân loại màn: GAME/AD/PAUSE/HOME/SPOTLIGHT/UNKNOWN
│   │   ├── ocr.py               tầng B: Apple Vision wrapper
│   │   ├── vlm.py               tầng C: Florence-2 wrapper (lazy load, crop góc)
│   │   └── worker.py            PerceptionWorker: thread + queue
│   │
│   ├── engine/
│   │   ├── states.py            enum BotState
│   │   ├── machine.py           StateMachine: transition table + tick()
│   │   ├── rules.py             tầng A rule engine (đọc game.toml)
│   │   ├── ad_closer.py         tầng C pipeline 6 bước
│   │   └── watchdog.py          recovery: pause / jiggle / spotlight / app-left
│   │
│   ├── store/
│   │   ├── state.py             AppState (thread-safe snapshot cho UI)
│   │   ├── events.py            EventBus + JSONL sink
│   │   └── stats.py             đếm ads đã đóng, thời gian, tỉ lệ thất bại
│   │
│   └── ui/
│       ├── server.py            FastAPI app, REST + WS
│       ├── hotkey.py            global hotkey listener
│       └── static/
│           ├── index.html       SPA 7 tab
│           ├── app.js
│           └── style.css
│
└── tests/
    ├── test_coords.py
    ├── test_rules.py
    ├── test_ad_closer.py        dùng ảnh trong data/captures làm fixture
    └── test_safety.py
```

---

## 4. State machine

### 4.1 Các trạng thái

| State | Ý nghĩa | Thoát khi |
|---|---|---|
| `STOPPED` | chưa chạy / đã dừng | user bấm Start |
| `PREFLIGHT` | kiểm tra quyền, tìm cửa sổ, load config | OK → `SYNC` |
| `SYNC` | xác định đang ở đâu (classify màn hình) | phân loại xong |
| `DISCONNECTED` | màn pause "iPhone đang được sử dụng" | watchdog bấm "Kết nối" thành công |
| `HOME_SCREEN` | iPhone ở Home Screen | mở được app game |
| `GAME_PLAY` | trong game, chạy luật tầng A | thấy ad / mất game |
| `REWARD_PROMPT` | thấy nút xem quảng cáo nhận thưởng | đã bấm |
| `AD_WATCHING` | quảng cáo đang chạy, chờ | hết timeout tối thiểu |
| `AD_CLOSING` | đang tìm & bấm nút đóng (pipeline tầng C) | đóng được / hết lượt thử |
| `AD_ESCAPED` | bị đẩy ra App Store / Safari | quay lại được game |
| `STUCK` | không nhận ra màn hình trong N giây | escalate xong |
| `PANIC` | vượt ngưỡng an toàn / user bấm Kill | chỉ user reset |

### 4.2 Sơ đồ chuyển

```text
STOPPED → PREFLIGHT → SYNC
                        │
      ┌─────────────────┼──────────────────┬───────────────┐
      ▼                 ▼                  ▼               ▼
DISCONNECTED      HOME_SCREEN          GAME_PLAY        UNKNOWN
      │  bấm "Kết nối"   │ mở game          │              │ >N giây
      └────────┐         └────────┐         │              ▼
               └──────────────────┴─────────┤            STUCK
                                            │              │ escalate
                                REWARD_PROMPT              │ (safe tap → restart game)
                                            │              │
                                     AD_WATCHING ◀─────────┘
                                            │ hết chờ tối thiểu
                                     AD_CLOSING
                                     │      │ mất app
                                     │      ▼
                                     │   AD_ESCAPED ──┐ quay lại
                                     ▼                │
                                 GAME_PLAY ◀──────────┘

bất kỳ state ──(vượt ngưỡng an toàn / Kill)──▶ PANIC
```

### 4.3 Nguyên tắc

- **Non-blocking.** Không `sleep()` dài trong state. Mỗi state có `entered_at`, tick kiểm tra `now - entered_at`. (Plan cũ dùng `sleep(32)` — sai: ad 5 giây thì mất 27 giây, ad 60 giây thì tỉnh giữa video.)
- Mỗi state có `timeout` riêng; hết timeout → `STUCK`.
- `watchdog` chạy **song song** và có quyền cướp state khi phát hiện pause/jiggle/spotlight.

---

## 5. Tầng A — luật chơi game

Khai báo bằng TOML, không hard-code. Mỗi luật: **điều kiện rẻ** → **hành động**.

```toml
# config/game.toml
[[rule]]
name = "swipe trái khi thấy mũi tên phải"
priority = 10
[rule.when]
kind = "template"                 # template match
template = "arrow_right.png"
region = [0.6, 0.4, 1.0, 0.7]     # tỉ lệ so với cửa sổ
min_score = 0.82
[rule.do]
action = "swipe"
from = [0.80, 0.55]               # toạ độ tỉ lệ
to   = [0.20, 0.55]
duration_ms = 220

[[rule]]
name = "tap nút tiếp tục"
priority = 20
[rule.when]
kind = "color"                    # color probe
at = [0.50, 0.86]
rgb = [52, 199, 89]
tolerance = 28
[rule.do]
action = "tap"
at = [0.50, 0.86]

[[rule]]
name = "tap vùng an toàn khi màn hình không đổi"
priority = 99
[rule.when]
kind = "idle"                     # phash không đổi
seconds = 12
[rule.do]
action = "tap"
at = [0.50, 0.50]
```

Loại điều kiện hỗ trợ: `template`, `color`, `idle` (phash không đổi N giây), `text` (dùng tầng B, chỉ khi cần), `always`.
Loại hành động: `tap`, `swipe`, `hold`, `wait`, `goto_state`.

Ưu điểm: bạn tự thêm luật mới khi game có màn mới, không cần sửa code, không cần train.

---

## 6. Tầng C — pipeline đóng quảng cáo

Đây là phần khó nhất và là 60% công sức. 6 bước, dừng ở bước nào tìm ra thì bấm.

```text
Bước 0  classify == AD?                                        tầng A, <5ms
        │ không → thoát pipeline
        ▼
Bước 1  chờ tối thiểu (mặc định 5s, cấu hình được)             không chặn loop
        │ trong lúc chờ vẫn quét phash để biết ad đã đổi lớp
        ▼
Bước 2  Apple Vision OCR full frame                            62ms
        │ khớp KEYWORD (Skip / Đóng / Continue / Done / No thanks / Bỏ qua …)
        │ ─────────────► LỌC AN TOÀN (xem 6.2) ─────────► tap
        ▼ không thấy
Bước 3  crop 4 góc 130x130, Florence-2-base-ft                 531ms/góc
        │ <OPEN_VOCABULARY_DETECTION> "close button"
        │ thứ tự: trên-phải → trên-trái → dưới-phải → dưới-trái
        │ ─────────────► LỌC AN TOÀN ─────────────────► tap
        ▼ không thấy
Bước 4  quét lại theo chu kỳ 2s, tối đa 45s                    (ca X hiện sau đếm ngược)
        │ ─────────────► tìm ra → tap
        ▼ hết thời gian
Bước 5  blind tap các offset góc quen thuộc (danh sách cấu hình)
        │ mỗi lần tap → kiểm tra màn hình có đổi
        ▼ vẫn không ra
Bước 6  escalate: gesture Home → mở lại game → về GAME_PLAY
```

### 6.2 LỌC AN TOÀN — quan trọng nhất của cả plan

Florence-2 **đã thực sự** gán nhãn nút **Install** màu xanh là "close button" trong test.
Bấm vào đó là mở App Store. Nên mọi candidate phải qua **3 cửa** trước khi được tap:

1. **Cửa hình học.** Tâm candidate phải nằm trong dải **15% mép** cửa sổ, hoặc trong ô góc 130x130. Candidate ở giữa màn hình bị **loại vô điều kiện**. Riêng luật này đã chặn được cả nút Install (205,731) lẫn X giả (205,640) trong test.
2. **Cửa blocklist chữ.** OCR vùng quanh candidate (bán kính 40pt); nếu khớp bất kỳ từ trong blocklist → loại. Blocklist: `Install`, `Cài đặt`, `Get`, `Download`, `Tải`, `Play`, `Chơi`, `Open`, `Mở`, `Subscribe`, `Đăng ký`, `Buy`, `Mua`, `Free trial`, `Dùng thử`.
3. **Cửa kích thước.** Nút đóng thật thường nhỏ. Loại candidate có diện tích > 4% diện tích cửa sổ.

Sau khi tap, **luôn xác nhận**: chụp lại sau 1.2s, nếu `classify` vẫn là `AD` và phash gần như không đổi → coi như tap thất bại, quay lại bước 3 với góc tiếp theo (đừng tap lại cùng chỗ).

### 6.3 Cấu hình

```toml
# config/ads.toml
min_watch_seconds = 5
rescan_interval_s = 2.0
rescan_max_s      = 45
corner_box        = 130
edge_band_pct     = 0.15
max_area_pct      = 0.04

close_keywords = ["skip", "skip ad", "close", "đóng", "continue", "tiếp tục",
                  "done", "xong", "no thanks", "bỏ qua", "×", "x"]
blocklist      = ["install", "cài đặt", "get", "download", "tải", "play",
                  "chơi", "open", "mở", "subscribe", "đăng ký", "buy", "mua"]

[vlm]
model   = "florence-community/Florence-2-base-ft"
device  = "mps"
dtype   = "float16"
beams   = 1
prompts = ["close button", "x button"]

[[blind_tap]]   # bước 5
at = [0.93, 0.05]
[[blind_tap]]
at = [0.07, 0.05]
```

---

## 7. Watchdog & Safety

### 7.1 Watchdog — ba ca đã xảy ra thật trong POC

| Ca | Phát hiện | Khôi phục |
|---|---|---|
| Mirroring pause | OCR thấy "iPhone đang được sử dụng" / "đã kết thúc" | tap nút "Kết nối" (OCR tìm toạ độ), chờ 3s, verify |
| Jiggle mode | OCR thấy "Xong" / "Done" ở dải trên | tap nút đó |
| Spotlight mở ngoài ý muốn | OCR thấy "Gợi ý của Siri" / "Tìm kiếm gần đây" | gesture Home (swipe từ mép dưới lên) |
| Rời khỏi app game | classify == HOME/APPSTORE/SAFARI | gesture Home → tap icon game (OCR tìm nhãn "Path of Kings") |

`poc/restore_home.py` đã có logic 1–3, sẽ port sang `engine/watchdog.py`.

### 7.2 SafetyGuard — chặn cứng, không cấu hình được tắt

| Ràng buộc | Giá trị mặc định | Hành động khi vượt |
|---|---|---|
| Kill switch bàn phím | `⌃⌥⌘K` | → `PANIC` ngay |
| Chuột về góc trên-trái màn hình | pyautogui FAILSAFE tương đương | → `PANIC` |
| Tap ngoài bounds cửa sổ | tuyệt đối không cho | bỏ hành động, log ERROR |
| Số tap / phút | 90 | → `PANIC` |
| Thời gian giữ chuột 1 lần | ≤ 250ms | cắt xuống (tránh jiggle mode) |
| Thời lượng phiên | 4 giờ | dừng sạch |
| Số lần `STUCK` liên tiếp | 5 | dừng sạch |
| Vùng cấm tap | cấu hình được (ví dụ dải chứa nút Install) | bỏ hành động |

---

## 8. UI

### 8.1 Vì sao là web UI, không phải app native

Bot **chiếm chuột vật lý**. Một cửa sổ native trên cùng máy thì bạn không bấm được
trong lúc bot chạy. Web UI giải quyết bằng cách xem/bấm **từ thiết bị khác** (iPad,
điện thoại thứ hai, máy khác trong LAN), cộng global hotkey cho 3 lệnh khẩn.

- Bind mặc định `127.0.0.1:8765`. Có cờ `--lan` để bind `0.0.0.0` (kèm token đơn giản).
- Không login, không account. Đây là tool local.

### 8.2 Bảy màn hình

**① Dashboard** — màn chính
- **Livestream realtime** cửa sổ iPhone, **30 FPS, độ phân giải gốc 410x898** (xem §8.4)
- Overlay: box của detection hiện tại, nhãn, điểm tap vừa thực hiện (chấm đỏ tắt dần)
- Badge state hiện tại + thời gian ở state đó
- Số đo trực tiếp: FPS capture, latency perception, tap/phút
- Nút: Start / Pause / Stop / **Kill** (đỏ, luôn hiển thị)
- Feed log 20 dòng cuối, màu theo mức

**② Game Rules** — tầng A
- Bảng luật: bật/tắt, tên, priority, điều kiện, hành động
- Editor 1 luật: chọn loại điều kiện, **chọn vùng/điểm bằng cách click trực tiếp lên ảnh preview** (rất quan trọng — đỡ phải đoán toạ độ)
- Nút "Test luật này ngay" → chạy 1 lần trên frame hiện tại, báo khớp/không khớp + score
- Quản lý file template: upload, crop từ frame hiện tại, xem score

**③ Ads** — tầng C
- Sửa `close_keywords` / `blocklist` (thêm/bớt từ)
- Cấu hình vùng góc, edge band, max area, thời gian chờ
- Chọn model VLM, device, dtype, beams — kèm **latency đo được** hiển thị ngay
- Danh sách `blind_tap` với marker trên ảnh preview
- Nút "Chạy pipeline trên frame hiện tại" → hiện từng bước, kết quả từng cửa lọc, thời gian từng bước

**④ Capture** — thu dataset ads thật
- Nút chụp thủ công + hotkey
- **Auto-capture**: mỗi khi state = `AD_*`, tự lưu frame
- Gallery ảnh đã thu: xem, gắn tag (`text_button` / `icon_only` / `countdown` / `playable` / `redirect`), xoá
- Thống kê: bao nhiêu ảnh mỗi tag → chính là dữ liệu để trả lời "70% kia có đúng không"
- Export ZIP

**⑤ Sessions & Stats**
- Danh sách phiên đã chạy
- Mỗi phiên: thời lượng, số ad đã đóng, ad đóng ở bước nào (1/2/3/4/5), số lần `STUCK`, số lần watchdog can thiệp
- Biểu đồ đơn giản: ad đóng theo giờ, phân bố bước thành công
- Xem lại `events.jsonl`, filter theo mức/loại

**⑥ Probe** — công cụ debug
- Chụp 1 frame, chạy **cả 3 tầng** rồi hiện cạnh nhau: classify, OCR (mọi vùng chữ + confidence + box), Florence-2 (mỗi góc, mỗi prompt) — kèm ms từng cái
- Vẽ toàn bộ box lên ảnh
- Tap/swipe thử tay: click lên ảnh preview → bot tap đúng chỗ đó (có xác nhận)
- Ring buffer viewer: xem lại 60 frame gần nhất

**⑦ Settings & Doctor**
- Trạng thái quyền: Screen Recording, Accessibility (kèm hướng dẫn nếu thiếu)
- Cửa sổ đích: bundle id, bounds hiện tại, scale factor
- Benchmark lại các backend chụp ngay trong UI
- Hotkey mapping
- Safety limits
- Đường dẫn data, dung lượng, nút dọn

### 8.3 Hotkey toàn cục

| Tổ hợp | Chức năng |
|---|---|
| `⌃⌥⌘S` | Start / Pause toggle |
| `⌃⌥⌘K` | **Kill** — dừng ngay, về PANIC |
| `⌃⌥⌘C` | Chụp frame hiện tại vào `data/captures/` |
| `⌃⌥⌘P` | Chạy Probe trên frame hiện tại, in ra log |

### 8.4 Livestream realtime — thiết kế và số đo

**Có, đây là tính năng trung tâm của Dashboard**, không phải ảnh chụp refresh định kỳ.

Chi phí encode đã đo (`poc/bench_stream.py`, `cv2.imencode` trên frame thật 410x898):

| Kích thước | Quality | ms/frame | KB/frame | @15 FPS | @30 FPS |
|---|---|---|---|---|---|
| **410x898 (gốc)** | **75** | **0.56** | **15.2** | 1.78 Mbps | **3.56 Mbps** |
| 410x898 (gốc) | 60 | 0.57 | 13.3 | 1.56 Mbps | 3.13 Mbps |
| 308x674 | 60 | 0.33 | 9.0 | 1.06 Mbps | 2.12 Mbps |
| 205x449 | 60 | 0.16 | 5.4 | 0.64 Mbps | 1.27 Mbps |

`Pillow` cùng cấu hình mất 1.51ms — **chậm 2.7x** so với `cv2.imencode`. Dùng cv2.

**Ngân sách thời gian:** 1 frame @30 FPS = 33.3ms. Capture 15.9ms + encode 0.56ms
= **16.5ms** → còn dư gần một nửa. Nên 30 FPS ở độ phân giải gốc là an toàn,
không phải cố gắng.

**Bảy quyết định thiết kế:**

1. **WebSocket binary, không base64.** base64 phình +33% vô ích.
2. **Encoder là thread riêng**, đọc frame mới nhất từ ring buffer. Vòng lặp bot
   **không bao giờ** chờ encode hay chờ client. Nếu encoder chậm, nó bỏ frame —
   không xếp hàng.
3. **Backpressure: luôn gửi frame mới nhất, không queue.** Client chậm thì nhận
   ít frame hơn, không bao giờ nhận frame cũ. Đây là stream giám sát, không phải
   video cần liền mạch.
4. **Overlay KHÔNG vẽ vào JPEG.** Frame gửi kèm header binary nhỏ
   (`frame_id` uint32 + `ts` float64), detection gửi riêng bằng JSON có
   `frame_id` tương ứng. Client vẽ lên `<canvas>` phủ trên `<img>`.
   Lợi: encode vẫn rẻ, overlay nét ở mọi zoom, bật/tắt từng lớp được,
   và không tốn thêm ms nào cho việc vẽ.
5. **Adaptive tự động.** Server đo thời gian ack của client; nếu chậm thì hạ
   xuống 0.75 scale + q60 (9 KB/frame, 1.06 Mbps @15 FPS) rồi 0.5 scale.
   Có nút override tay trong UI.
6. **Endpoint MJPEG dự phòng:** `GET /stream.mjpg`
   (`multipart/x-mixed-replace`). Chạy trong `<img src>` trần, không cần JS —
   hữu ích khi xem nhanh từ điện thoại hoặc khi WS bị chặn. Không có overlay.
7. **Stream chỉ chạy khi có client.** Không ai mở Dashboard thì encoder ngủ,
   không tốn CPU.

**Băng thông thực tế:** 3.56 Mbps ở cấu hình mặc định. Localhost không đáng kể;
Wi-Fi LAN thoải mái. Chỉ cần hạ scale nếu xem qua mạng yếu.

**Ring buffer replay:** ngoài stream trực tiếp, màn Probe cho xem lại 60 frame
gần nhất (≈4s ở 15 FPS bot loop) — dùng để soi lại đúng khoảnh khắc bot tap sai.

### 8.5 Overlay hành động — thấy được bot tap/swipe ở đâu

#### Vì sao overlay phải dựng từ lệnh, không phải từ ảnh

`CGWindowListCreateImage` **không vẽ con trỏ chuột vào ảnh** — đã xác nhận trong
POC (chính đặc tính này giúp bắt được dương tính giả ở test hover: tắt con trỏ
thì diff về đúng 0.00%). Nghĩa là **không thể** thấy con trỏ trong stream.

Nên overlay dựng từ chính `ActionEvent` mà `Actuator` phát ra. Tốt hơn hẳn cách
phân tích ảnh:

- Toạ độ **chính xác tuyệt đối** — là con số gửi cho `CGEventPost`, không suy từ pixel
- Biết cả **thời điểm, thời lượng, và lý do** (luật nào / bước nào của pipeline)
- Vẽ được cả hành động **bị chặn**, thứ nhìn ảnh không bao giờ thấy

#### Giao thức

`Actuator` phát `ActionEvent` trước và sau mỗi hành động, gửi qua cùng WS dưới
dạng JSON, gắn `frame_id` đang hiện hành:

```jsonc
{ "type": "action",
  "id": 1482,
  "frame_id": 90311,
  "kind": "swipe",                    // tap | swipe | hold
  "points": [[0.80,0.55], …],         // 18 điểm nội suy THẬT mà cg_swipe phát ra
  "duration_ms": 220,
  "source": "rule",                   // rule | ad_step | watchdog | blind_tap | manual
  "label": "swipe trái khi thấy mũi tên phải",
  "blocked": false,
  "block_reason": null                 // "geometry" | "blocklist" | "size" | "out_of_bounds" | "rate_limit"
}
```

#### Cách vẽ

| Loại | Hiển thị |
|---|---|
| `tap` | vòng tròn lan ra (ripple) tại điểm, mờ dần ~800ms, kèm nhãn |
| `swipe` | polyline qua **đúng 18 điểm nội suy thật** + mũi tên, dashed animation chạy dọc, mờ dần ~1200ms |
| `hold` | vòng tròn giữ nguyên + đồng hồ đếm ms (thấy ngay nếu vượt ngưỡng 250ms chống jiggle) |

Vẽ polyline theo điểm thật, không phải đường thẳng giả định — để sau này làm
swipe cong hoặc có gia tốc thì overlay vẫn phản ánh đúng.

#### Màu theo nguồn phát

| Màu | `source` |
|---|---|
| xanh | `rule` — luật tầng A |
| cam | `ad_step` — pipeline đóng ads (kèm số bước 1–6) |
| tím | `watchdog` — recovery |
| đỏ nhạt | `blind_tap` — bước 5 |
| xanh dương | `manual` — bạn tap tay từ màn Probe |
| **đỏ gạch chéo** | **`blocked: true` — bị SafetyGuard chặn** |

Loại cuối là thứ có giá trị nhất khi debug: **thấy được lọc an toàn đang làm
việc**. Ví dụ Florence-2 trả về nút Install, cửa hình học loại nó → hiện dấu X
đỏ gạch chéo đúng vị trí nút Install, kèm `block_reason: "geometry"`.
Không có nó thì bot chỉ "im lặng không làm gì" và bạn không biết vì sao.

#### Trail mode

Giữ 20 hành động gần nhất, độ mờ theo tuổi. Xem được *pattern* bot vừa làm
trong mấy giây qua, không chỉ hành động hiện tại. Bật/tắt trong Dashboard.

#### Replay khớp frame

`events.jsonl` ghi mọi action kèm `frame_id`, ring buffer giữ 60 frame → màn
Probe tua lại được frame + overlay khớp nhau, soi đúng khoảnh khắc tap sai.

#### Độ trễ cần biết trước

Overlay hiện **ngay lập tức** (dựng từ ý định), còn phản ứng của iPhone xuất hiện
trong stream **trễ ~100–300ms** (đường vòng của mirroring). Marker hiện trước,
hiệu ứng sau.

Đây là tính năng chứ không phải lỗi: marker hiện mà màn hình không đổi → biết
ngay **tap đã bắn nhưng không ăn**, phân biệt được với **bot không tap gì cả**.
Đúng cái ranh giới đã làm mất nhiều thời gian nhất trong POC
(`CGEventPostToPid` bắn ra nhưng iPhone Mirroring không nhận).

---

## 9. Danh sách chức năng (39)

**Core (1–8)**
1. Tìm cửa sổ iPhone Mirroring theo bundle id, độc lập ngôn ngữ
2. Theo dõi bounds cửa sổ, tự cập nhật khi user di chuyển cửa sổ
3. Capture 63 FPS qua `CGWindowListCreateImage`, ring buffer 60 frame
4. Quy đổi toạ độ tỉ lệ ↔ point cửa sổ ↔ point màn hình, có scale factor
5. Tap qua `CGEventPost` HID
6. Swipe/drag qua `CGEventPost` HID, số bước & thời lượng cấu hình được
7. Hold (giữ) có giới hạn thời gian, chống jiggle mode
8. Preflight quyền Screen Recording + Accessibility, hướng dẫn khi thiếu

**Perception (9–17)**
9. Phân loại màn hình: GAME / AD / PAUSE / HOME / SPOTLIGHT / APPSTORE / UNKNOWN
10. Color probe tại điểm
11. Template match trong vùng
12. Perceptual hash + phát hiện "màn hình không đổi N giây"
13. Apple Vision OCR full frame, tiếng Việt + tiếng Anh
14. OCR vùng crop (dùng cho cửa blocklist)
15. Florence-2 open-vocab detection trên crop góc
16. Lazy load model — chỉ load khi lần đầu cần tầng C
17. PerceptionWorker: queue, timeout, không để model nặng chặn UI

**Engine (18–26)**
18. State machine 12 state, non-blocking, mỗi state có timeout
19. Rule engine tầng A đọc từ TOML, có priority
20. Reload luật nóng, không cần restart bot
21. Pipeline đóng ads 6 bước
22. Lọc an toàn 3 cửa (hình học / blocklist chữ / kích thước)
23. Xác nhận sau tap, không tap lại cùng chỗ khi thất bại
24. Watchdog: pause / jiggle / spotlight / rời app — 4 ca recovery
25. Escalate khi STUCK: safe tap → gesture Home → mở lại game
26. Thống kê ad đóng được ở bước nào (để biết tầng nào đang gánh)

**Safety (27–30)**
27. Kill switch hotkey + nút UI luôn hiện
28. Rate limit tap/phút, giới hạn thời lượng phiên
29. Chặn tuyệt đối tap ngoài bounds cửa sổ + vùng cấm cấu hình được
30. Auto-stop sau N lần STUCK liên tiếp

**UI (31–37)**
31. Livestream realtime 30 FPS qua WebSocket binary + overlay vẽ client-side trên canvas
31b. Endpoint MJPEG dự phòng `/stream.mjpg` (xem trong `<img>` trần, không cần JS)
31c. Adaptive scale/quality theo độ trễ client; encoder ngủ khi không có ai xem
31d. Overlay hành động: ripple cho tap, polyline 18 điểm thật cho swipe, đếm ms cho hold
31e. Overlay màu theo nguồn phát; hiển thị cả hành động **bị SafetyGuard chặn** kèm lý do
31f. Trail mode — giữ 20 hành động gần nhất, mờ dần theo tuổi
32. Start/Pause/Stop/Kill
33. Rule editor có chọn vùng bằng click lên ảnh
34. Ads config editor + chạy thử pipeline từng bước
35. Capture & gallery gắn tag cho dataset ads thật
36. Sessions & stats + xem lại events.jsonl
37. Probe: chạy cả 3 tầng cạnh nhau kèm ms, tap/swipe thử tay

**Ops (38–39)**
38. CLI: `run` / `ui` / `doctor` / `capture` / `probe` (chạy được không cần UI)
39. Log JSONL theo phiên + lưu frame khi lỗi vào `data/debug/`

---

## 10. Lộ trình

| Phase | Nội dung | Ước lượng | Điều kiện xong |
|---|---|---|---|
| **P0** | Scaffold: pyproject, cấu trúc package, config loader, CLI `doctor` | 0.5 ngày | `python -m pok doctor` báo đủ quyền + tìm ra cửa sổ |
| **P1** | Core: window, capture, coords, actuator, safety | 0.5 ngày | tap/swipe được vào iPhone từ code mới; test coords pass |
| **P2** | Perception A + B: classify, cheap CV, OCR | 1 ngày | classify đúng 5 màn: game/ad/pause/home/spotlight |
| **P3** | Engine + watchdog: state machine, rule engine, 4 ca recovery | 1 ngày | bot chơi được tầng A liên tục 30 phút không kẹt |
| **P4** | Web UI: Dashboard + Probe + Settings (3 màn quan trọng nhất trước) | 1 ngày | xem live, start/stop, probe được từ iPad |
| **P5** | **Thu 30–50 ảnh ads thật** qua màn Capture, gắn tag | 0.5 ngày (chơi game) | có số liệu phân bố: bao nhiêu % text-button vs icon-only |
| **P6** | Tầng C: pipeline 6 bước + lọc an toàn, tune bằng ảnh thật ở P5 | 1.5 ngày | đóng được ≥80% ảnh trong tập P5 (test offline) |
| **P7** | UI còn lại: Game Rules, Ads, Capture, Sessions | 1 ngày | sửa được luật & keyword không cần chạm code |
| **P8** | Chạy dài, sửa long tail, viết README | 1 ngày | chạy 2 giờ không cần can thiệp |

**Tổng: 8–9 ngày part-time.** P5 là cửa quyết định — nó biến con số 70% thành có cơ sở.

Thứ tự này đặt P5 (thu ảnh thật) **trước** P6 (viết tầng C) có chủ đích: viết pipeline
trước khi biết phân bố quảng cáo thật là đoán mò.

---

## 11. Đánh giá thẳng thắn

### Khả thi

| Định nghĩa "xong" | % |
|---|---|
| Tầng A — chơi game bằng swipe/tap | **95%** |
| Tầng C — đóng được phần lớn ads | **70%** |
| Bot farm được, thỉnh thoảng can thiệp tay | **~80%** |
| Bot chạy qua đêm không người trông | **~45%** |

### Ba thứ có thể phá plan này

1. **Nút X không nằm ở góc.** Cửa hình học 15% mép là thứ chặn được nút Install — nhưng nếu ad đặt X thật ở giữa, chính nó chặn luôn cả X thật. P5 sẽ cho biết tỉ lệ. Nếu tỉ lệ cao, phải đổi sang lọc bằng kích thước + độ tương phản thay vì vị trí.
2. **Playable ad.** Loại tương tác được không có nút X theo nghĩa thường. Plan này sẽ thất bại ở loại đó và rơi xuống bước 6 (mở lại game) — mất phần thưởng nhưng không kẹt.
3. **Độ ổn định iPhone Mirroring qua nhiều giờ.** Chưa đo. Đây là biến số lớn nhất cho con số 45%.

### Điều tôi chưa kiểm chứng

- Toàn bộ đánh giá tầng C dựa trên **một ảnh quảng cáo tôi tự vẽ** (`poc/make_fake_ad.py`). Nó chứng minh failure mode và chứng minh crop-góc sửa được, nhưng **không** đại diện phân phối thật.
- Chưa đo iPhone Mirroring chạy liên tục > 15 phút.
- Chưa biết game Path of Kings có bao nhiêu loại màn cần luật riêng.

### Rủi ro ngoài kỹ thuật (không nằm trong % trên)

- Automation game vi phạm ToS → có khả năng ban account. Input đi từ iPhone thật qua Mirroring nên rất khó detect ở tầng kỹ thuật, nhưng pattern quá đều vẫn có thể bị behavioral analysis gắn cờ.
- Tự động xem quảng cáo nhận thưởng về bản chất là ad fraud với nhà quảng cáo. AppLovin / Unity Ads / IronSource có detection riêng; hệ quả thường là cắt reward hoặc chặn thiết bị.

Hai điều này là quyết định của bạn, tôi nêu để tính vào.
