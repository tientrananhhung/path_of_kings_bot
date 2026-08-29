# POC — Kiểm chứng 2 blocker của `plan_bot.md`

| Script | Câu hỏi | Trạng thái |
|---|---|---|
| `poc2_capture.py` | Chụp được cửa sổ iPhone Mirroring không, API nào, bao nhiêu FPS? | **THÔNG** |
| `poc1c_drag_probe.py` | Synthetic mouse down/drag/up có tới được cửa sổ không? (đo bounds, không so ảnh) | **THÔNG** |
| `poc1_click.py` | Click có được chuyển tiếp xuống iPhone không? (5 method injection) | **chờ mirroring kết nối** |
| `poc1b_hover_probe.py` | Probe hover không side-effect | vô dụng — nút accent macOS không đổi hình khi hover |

## Chuẩn bị (làm 1 lần)

Quyền TCC cấp theo **app cha** của process, và macOS đọc quyền **lúc app khởi động**
— cấp quyền xong phải `Cmd+Q` quit hẳn rồi mở lại, không chỉ đóng cửa sổ.

1. Mở **Terminal.app**.
2. `System Settings > Privacy & Security > Screen & System Audio Recording` → bật cho **Terminal**.
3. `System Settings > Privacy & Security > Accessibility` → bật cho **Terminal**.
4. `Cmd+Q` quit Terminal, mở lại.
5. Mở **iPhone Mirroring**, để iPhone **khoá / không chạm vào** cho mirroring kết nối.

## Chạy

```bash
cd "/Users/tientran/Tong Hop/path_of_kings_tool"
./.venv/bin/python poc/poc2_capture.py 20
./.venv/bin/python poc/poc1c_drag_probe.py
./.venv/bin/python poc/poc1_click.py
```

```bash
./.venv/bin/python poc/poc1_click.py --point 1231 608   # khỏi tương tác
./.venv/bin/python poc/poc1_click.py --only 2           # chỉ method 2 (CGEventPost HID)
./.venv/bin/python poc/poc2_capture.py 10 --force       # chạy bất chấp thiếu quyền
```

`poc/run.command` chạy lệnh trong `poc/out/cmd.txt` dưới TCC identity của
Terminal.app và ghi log ra `poc/out/run.log` — dùng khi cần chạy từ agent/IDE
không có quyền.

## Số đo thật trên máy này (macOS 26.4.1, M1, 2026-08-28)

Cửa sổ tên **"Phản chiếu iPhone"** (localized!), bundle `com.apple.ScreenContinuity`,
`410 x 898` point tại `(1029, 30)`. Màn hình `1440x900` point / `2880x1800` pixel (Retina 2x).

| Backend | ms/frame | FPS | Pixel trả về | Scale | Con trỏ trong ảnh |
|---|---|---|---|---|---|
| `mss.grab` | 15.9 | 63 | 410x898 | 1.00 | **có** |
| `CGWindowListCreateImage` | 15.9 | 63 | 410x898 | 1.00 | không |
| `ScreenCaptureKit` | 36.7 | 27 | 410x898 | 1.00 | không (đã tắt) |
| `screencapture -l` | 120 | 8.3 | 820x1796 | 2.00 | không |
| `screencapture -R` | 117 | 8.6 | 820x1740 | 2.00 | **có** |
| `pyautogui.screenshot` | 112 | 8.9 | 820x1740 | 2.00 | **có** |

→ Dùng **`CGWindowListCreateImage`** (63 FPS, chụp riêng cửa sổ, không con trỏ,
trả về point-resolution nên không có bug toạ độ Retina). `pyautogui.screenshot`
mà plan_bot.md dùng là lựa chọn tệ nhất: chậm 7x, trả 2x gây click lệch, và vẽ
cả con trỏ vào ảnh.

Kéo cửa sổ bằng `CGEventPost` → `kCGHIDEventTap`: **ăn**, delta `(1, 37)`.
Điểm bám được là **mép trái, giữa cửa sổ**; mép trên không kéo được.

## Hai cạm bẫy đã sập vào khi làm POC — đừng lặp lại

**1. Thiếu quyền Screen Recording → macOS trả HÌNH NỀN DESKTOP, không phải ảnh đen.**
Ảnh wallpaper có `std ≈ 35`, cao hơn cả màn game tối, nên mọi phép thử kiểu
`std > 0` đều cho dương tính giả. Tệ hơn: với test click, before/after luôn
giống nhau → kết luận sai là "không method nào ăn" → bỏ oan cả plan.
Cách phân biệt đã hiệu chuẩn bằng số thật — năng lượng tần số cao (mật độ cạnh):

| Nội dung | hf |
|---|---|
| màn iPhone thật (kể cả màn pause khá trơn) | 1.67 – 2.04 |
| hình nền desktop khi thiếu quyền | 0.46 |

Ngưỡng 1.0. Xem `high_freq_energy()` trong `poc2_capture.py`.

**2. Con trỏ chuột được vẽ vào ảnh chụp → dương tính giả.**
Probe hover ban đầu báo "ĂN" với 0.69% pixel đổi ở cả 2 event tap. Xem ảnh mới
thấy nút **không** đổi màu — 0.69% đó hoàn toàn là bitmap con trỏ do window
server vẽ, chứng minh *con trỏ đã dịch*, không chứng minh *app nhận được event*.
Tắt con trỏ (`setShowsCursor_(False)`, hoặc dùng backend chụp riêng cửa sổ) →
diff về đúng **0.00%**.

Bài học chung: **so ảnh trước/sau là bằng chứng yếu.** Ưu tiên phép đo khách quan
— `poc1c_drag_probe.py` đo `bounds` cửa sổ qua Quartz, miễn nhiễm với con trỏ,
animation, và việc nút đích đang vô hiệu.

## Việc còn lại

Test click cuối (`poc1_click.py`, 5 method) cần **mirroring đang kết nối thật**.
Lúc chạy POC, iPhone đang được sử dụng nên cửa sổ chỉ hiện màn pause
*"iPhone đang được sử dụng — hãy khoá iPhone của bạn để kết nối"*, nút "Kết nối"
vô hiệu → click cho 0.02% và kết quả âm đó **không đọc được**.

Ghi chú cho state machine sau này: màn pause này là trạng thái có thật, xảy ra
mỗi lần bạn chạm vào iPhone. Bot bắt buộc phải có watchdog nhận diện nó và bấm
"Kết nối" để hồi phục, nếu không sẽ đứng im vô thời hạn.

## Apple Vision OCR — đo thật, liên quan tới lựa chọn Florence-2 vs YOLO

`poc/bench_ocr.py` chạy OCR native của macOS (on-device, Neural Engine, không
tải model, không train) trên đúng ảnh chụp được ở trên:

| Level | ms/frame | FPS | Chất lượng tiếng Việt |
|---|---|---|---|
| `accurate` | 78.5 | 12.7 | hoàn hảo, confidence 1.00 |
| `fast` | 16.6 | 60.2 | mất hết dấu ('Kết nối' → 'K6t n6i') |

Hỗ trợ `vi-VT` + 29 ngôn ngữ khác. Trả về bounding box chuẩn hoá 0..1,
**gốc toạ độ góc dưới-trái, y hướng lên** — phải lật `cy = (1 - y) * H`.

Điểm đáng chú ý: OCR tự tìm ra nút "Kết nối" ở tâm **(206, 576)**. Con số tôi
tự dò bằng cách phân tích pixel thủ công là (202, 578) — lệch 4 point. Nghĩa là
với các nút quảng cáo **có chữ** (Skip / Done / Continue / Đóng / Tiếp tục),
OCR native định vị được mà không cần gán nhãn hay train một tấm ảnh nào.

## Benchmark Florence-2-base — đo thật trên M1 16GB

`poc/bench_florence.py`. Model `florence-community/Florence-2-base` (bản đã
convert cho native transformers — checkpoint gốc `microsoft/Florence-2-base`
**không load được** với `transformers 5.x`: `RobertaTokenizer has no attribute
image_token`). 231.4M params, 449MB weights, RSS ~1.7GB, load 1.6s.

`transformers 5.16.1` có `Florence2ForConditionalGeneration` **native** → không
cần `trust_remote_code`, không cần patch `flash_attn`.

### Latency (ảnh 410x898, đã warm-up, `do_sample=False`)

| Config | OCR+box (77 tok) | open-vocab (15 tok) | crop 130x130 (9 tok) |
|---|---|---|---|
| CPU fp32, beams=1 | 2617 ms | 1718 ms | 1666 ms |
| MPS fp32, beams=1 | 1742 ms | 757 ms | 668 ms |
| **MPS fp16, beams=1** | **1395 ms** | **622 ms** | **546 ms** |
| MPS fp16, beams=3 | 2040 ms | 649 ms | — |

Khớp gần như tuyệt đối với mô hình tuyến tính **≈ 430ms cố định + 13ms/token**
(MPS fp16). Dự đoán 77 token = 1410ms, đo được 1395ms.

→ Latency do **độ dài output** quyết định, không phải độ phức tạp ảnh.
Muốn nhanh thì hỏi câu cho ra ít token, đừng OCR cả màn hình.
→ `num_beams=3` (mặc định trong doc HF) tốn thêm 46% trên output dài, gần như
vô ích ở output ngắn. Bot nên dùng `num_beams=1`.
→ MPS nhanh hơn CPU 1.9–2.8x. fp16 nhanh hơn fp32 ~1.2x, không thấy sai kết quả.

### Độ chính xác — phần quan trọng hơn latency

Test trên `poc/out/fake_ad.png` (do `make_fake_ad.py` tạo, ground truth đã biết):
X thật nhỏ+mờ ở góc **(380,44)**, X GIẢ to ở giữa **(205,640)**, "Skip Ad" **(335,834)**,
nút Install xanh ở **(205,731)**.

Cho **cả ảnh** vào — Florence-2 sai một cách nguy hiểm:

| Task | Kết quả |
|---|---|
| `<OD>` | "mobile phone" — vô dụng |
| `<CAPTION_TO_PHRASE_GROUNDING>` "close button" | 4 box, có cả nút Install |
| `<OPEN_VOCABULARY_DETECTION>` "close button" | nút **Install** (205,731) + X giả (204,640). **Bỏ sót X thật** |
| `<OPEN_VOCABULARY_DETECTION>` "small x icon" | X giả (205,640) Δ0pt. **Bỏ sót X thật** |
| `<OCR_WITH_REGION>` | X thật (380,45) **Δ1pt** ✓ — nhưng vì đọc dấu × như ký tự text, và tốn 1395ms |

Nút **Install** bị gán nhãn "close button" — đúng cái dark pattern mà bot phải
tránh. Bấm vào là mở App Store.

Cho **crop góc trên-phải 130x130** vào — đảo chiều hoàn toàn:

| Task | ms | Kết quả |
|---|---|---|
| `<OPEN_VOCABULARY_DETECTION>` "close button" | **546** | (380,44) **Δ0pt** ✓ |
| `<OCR_WITH_REGION>` | 582 | (379,44) Δ1pt ✓ |

Lý do: 130→768 phóng nút X lên 5.9x, và crop loại luôn X giả + nút Install khỏi
khung nhìn nên không còn gì để nhầm.

### So với Apple Vision OCR trên cùng ảnh ad giả

| | ms | "Skip Ad" | X giả | **X thật (icon)** |
|---|---|---|---|---|
| Apple Vision (accurate) | **62** | ✓ (325,835) | ✓ conf 0.30 | **bỏ sót** |
| Florence-2 OCR cả ảnh | 1395 | ✓ | ✓ | ✓ Δ1pt |
| Florence-2 open-vocab, crop góc | 546 | — | — | ✓ Δ0pt |

Hai thứ **bù nhau**, không thay nhau: Vision bắt nút có chữ nhanh gấp 22x nhưng
mù với icon; Florence-2 bắt được icon nhưng chỉ khi được crop.

## CHỐT BLOCKER #1 — `poc1d_live_test.py`, mirroring ĐANG kết nối

Chạy khi iPhone Mirroring live ở Home Screen. Test đúng 2 thao tác bot cần.
Nhiễu nền 0.00%. Backend chụp `CGWindowListCreateImage` (không vẽ con trỏ).

| Method | Thao tác | Đổi màn | Kết luận |
|---|---|---|---|
| `CGEventPost` → HID tap | swipe | 7.87% | **ăn** |
| `CGEventPost` → HID tap | tap | 74.26% | **ăn** |
| `CGEventPost` → Session tap | swipe | 22.09% | **ăn** |
| `pyautogui` drag | swipe | 32.81% | **ăn** |
| `pyautogui.click` | tap | 31.77% | **ăn** |
| `CGEventPostToPid` | swipe | 1.60% | **không ăn** |
| AppleScript System Events click | tap | 0.00% | **không ăn** |

→ **iPhone Mirroring CHUYỂN TIẾP synthetic input xuống iPhone thật.**
Dùng `CGEventPost` với `kCGHIDEventTap`. Cả swipe và tap đều hoạt động.

`CGEventPostToPid` **không** dùng được: nó gửi thẳng vào process nên bỏ qua
window server, mà iPhone Mirroring cần đường HID. Con số 1.60% ban đầu đậu oan
vì sàn ngưỡng 1.5% quá lỏng — ảnh before/after thực ra là **cùng một trang**
Home Screen. Đã nâng sàn lên 5% (swipe/tap thật cho 7–74%).
Bài học lặp lại lần thứ ba trong POC này: đừng tin diff sát ngưỡng, hãy mở ảnh ra xem.

AppleScript `System Events → click at` không ăn — nó đi qua Accessibility API,
không phải HID.

**Tác dụng phụ đã gặp:** giữ chuột lâu trên Home Screen làm iOS vào chế độ
chỉnh sửa icon (jiggle mode). `poc/restore_home.py` trả về trạng thái bình
thường: OCR tìm nút "Xong" rồi tap, hoặc gesture Home nếu đang ở Spotlight.
Bot thật cần đúng loại watchdog này.

## Florence-2-base-ft vs base (MPS fp16, beams=1)

`-ft` **không** sửa được lỗi chính. Latency nhanh hơn chút, RSS 416MB (fp16, một
mình). Ground truth: X thật (380,44), X giả (205,640), Install (205,731).

| Task | base | -ft |
|---|---|---|
| OCR+box, cả ảnh | 1395ms · X Δ1pt | 1283ms · X **Δ0pt** |
| `<OD>` | "mobile phone" | "mobile phone" |
| grounding "close button" | 4 box, **không** có X thật | 4 box, **có** X thật Δ1pt (lẫn 3 box sai) |
| open-vocab "close button", cả ảnh | Install + X giả | **chỉ Install** — tệ hơn |
| open-vocab "small x icon", cả ảnh | X giả | (205,345) vùng GAME ART — tệ hơn |
| **crop góc** open-vocab "close button" | 546ms · **Δ0pt** | 531ms · **Δ0pt** |
| **crop góc** grounding "x" | nhãn rác "the image shows a white background" | nhãn sạch `x` · **Δ0pt** |

→ Trên **cả ảnh**, `-ft` vẫn chọn nút **Install** là "close button". Không có
biến thể nào của Florence-2-base cứu được việc đưa nguyên màn hình vào.
→ Trên **crop góc**, cả hai đều Δ0pt; `-ft` cho nhãn sạch hơn nên **dùng `-ft`**.
→ Chiến lược crop-góc là **bắt buộc**, không phải tối ưu hoá.

## Chi phí encode JPEG để livestream lên web

`poc/bench_stream.py`, `cv2.imencode` trên frame thật 410x898:

| Kích thước | Q | ms/frame | KB/frame | @15 FPS | @30 FPS |
|---|---|---|---|---|---|
| **410x898 (gốc)** | **75** | **0.56** | **15.2** | 1.78 Mbps | **3.56 Mbps** |
| 410x898 | 60 | 0.57 | 13.3 | 1.56 Mbps | 3.13 Mbps |
| 308x674 | 60 | 0.33 | 9.0 | 1.06 Mbps | 2.12 Mbps |
| 205x449 | 60 | 0.16 | 5.4 | 0.64 Mbps | 1.27 Mbps |

`Pillow` cùng cấu hình: 1.51ms — **chậm 2.7x** so với `cv2.imencode`.

Ngân sách 1 frame @30 FPS = 33.3ms. Capture 15.9ms + encode 0.56ms = **16.5ms**,
còn dư gần một nửa → livestream 30 FPS ở độ phân giải gốc là an toàn.
WebSocket phải dùng **binary**; base64 phình +33% vô ích.

## Băng thông livestream trên nội dung THẬT (không phải màn pause)

Đo qua WebSocket client thật, 6 giây, quality 75, scale 1.0, màn iPhone đang
mở TikTok (nhiều chi tiết):

| | KB/frame | FPS | Mbps |
|---|---|---|---|
| màn pause (ít chi tiết) — `bench_stream.py` | 15.2 | 30 | 3.56 |
| **màn thật, nhiều chi tiết** — đo qua `/ws` | **37.2** | 25 | **7.37** |

Nội dung thật nặng gấp **2.4x** so với frame dùng để benchmark. 7.37 Mbps vẫn
thoải mái trên LAN, nhưng nếu xem qua mạng yếu thì hạ `scale` xuống 0.75
(≈2.2 Mbps) trong tab Settings.

MJPEG cùng thời điểm: 34953 B/frame — khớp.

## Bug thật tìm ra khi chạy code (không phải khi đọc code)

Sáu lỗi dưới đây chỉ lộ ra khi chạy trên thiết bị thật. Đã sửa và có test.

**1. Keyword 1 ký tự phá phân loại màn hình.** `close_keywords` chứa `"x"`;
`"x" in low` khớp chữ *"Dược Xuan"* trên màn TikTok → mọi màn hình bị phân loại
là quảng cáo → bot vào `AD_CLOSING` và tap bừa 4 góc. Sửa: khớp theo biên từ
(`\b`) và bỏ keyword < 3 ký tự khi phân loại. (`test_classify_keywords.py`)

**2. Keyword ở giữa màn vẫn kích hoạt AD.** Sau khi sửa (1), nội dung video
TikTok tuỳ ý vẫn sinh dương tính giả. Nút đóng thật nằm **sát mép**; chữ ở giữa
là nội dung. Sửa: chỉ tính keyword có tâm trong dải mép 18%.
(`test_edge_band.py`)

**3. Cửa kích thước chỉ đúng do may.** Khi không thấy gì trong crop, Florence-2
trả box **phủ gần hết crop**. Với `corner_box=130` box đó (16900px²) tình cờ
vượt ngưỡng tuyệt đối 4%×410×898 = 14727px² nên bị chặn. `corner_box=120`
(14400px²) sẽ **lọt** và bot tap bừa vào góc. Sửa: thêm ngưỡng tương đối
> 50% diện tích crop. Sau khi sửa, cả 4 ứng viên VLM trên màn không-quảng-cáo
đều bị chặn (trước đó 1 cái lọt ở (342,82)). (`test_ad_gates.py`)

**4. Lần gọi VLM đầu tiên chặn 12.3s.** Nạp model + warm-up MPS: lần đầu
12304ms, các lần sau 516–519ms. Nếu không prewarm thì 12s đó rơi đúng vào lúc
gặp quảng cáo đầu tiên và chặn cả vòng lặp bot. Sửa: `vlm.prewarm()` chạy ở nền
lúc engine start.

**5. `/api/probe` treo vô hạn.** `PerceptionWorker` chỉ được start trong
`engine.start()`. Gọi probe trước khi bấm Start → job nằm mãi trong queue, mỗi
góc chờ hết 60s timeout. Cộng thêm handler `async def` gọi code blocking làm
nghẽn cả event loop nên WS stream đứng theo. Sửa: worker tự start khi submit;
các endpoint blocking chuyển thành `def` (sync) để Starlette chạy trong threadpool.

**6. Click lạc trên vùng ảnh tap thật xuống iPhone.** Trong lúc phát triển, 2
tap `manual` không rõ nguồn đã gửi xuống iPhone (rel 0.190,0.508 và 0.607,0.318).
Sửa: `/api/manual/tap` và `/api/manual/swipe` bắt buộc `confirm: true`.

Bên cạnh đó: `uvicorn` **cần package `websockets`** mới xử lý WebSocket upgrade —
thiếu nó thì `/ws` trả **404** chứ không báo lỗi gì. Và `tomli_w` **xoá hết
comment** khi web UI lưu file TOML.

## Nguyên nhân web lag — 6 thứ, đã sửa

**1. Vòng `requestAnimationFrame` tự nhân bản (nguyên nhân chính).**
`drawOverlay()` tự schedule một rAF gọi lại chính nó, nhưng nó **cũng** được gọi
từ `onFrame` (~25 lần/giây). Mỗi frame sinh một chuỗi rAF vĩnh viễn mới → sau
1 phút có ~1500 chuỗi cùng vẽ canvas mỗi frame. Lag tăng dần không giới hạn.
Sửa: một vòng rAF duy nhất có cờ chặn, và chỉ tiếp tục khi còn hiệu ứng mờ dần.

**2. Rebuild bảng DOM 30 lần/giây.** Server gửi state theo nhịp frame; client
dựng lại 2 bảng bằng `innerHTML` mỗi lần. Sửa: server gửi state **4 Hz** (tách
khỏi nhịp frame), client thêm throttle 250ms.

**3. Cấp phát lại canvas mỗi frame.** `sizeCanvas()` gán `canvas.width/height`
mỗi frame → cấp phát lại backing store 25 lần/giây. Sửa: chỉ gán khi kích thước
thật sự đổi.

**4. Encode JPEG riêng cho từng client.** Mỗi WS client và mỗi tab MJPEG tự
encode → 4 tab = 4 lần encode cùng một frame. Sửa: `FrameCache` theo
`(frame_id, quality, scale)`. Đo được: 3 client cùng lúc chỉ tốn thêm ~2% CPU
(15% → 17%), mỗi client vẫn nhận đủ 27.6 frame/s.

**5. `permissions.check()` gọi 30 lần/giây** — đó là syscall TCC.
Sửa: cache 5 giây.

**6. Luồng chụp chạy full FPS dù không ai xem.** Sửa: `capture.demand()` — hạ
xuống `idle_fps` (mặc định 2) khi engine dừng **và** không có client web nào.
(`test_capture_throttle.py`)

Kèm theo, một **chỉ số sai** đã che mất vấn đề: `measured_fps` chỉ tính thời gian
làm việc, bỏ qua sleep — nên nó báo "47 FPS" ngay cả khi vòng lặp thực sự chạy
2 FPS. Giờ nó đo nhịp thật; `grab_ms` báo riêng thời gian chụp một frame
(~17–19ms). UI hiện thêm nhãn "(ngủ)" khi đang throttle.

### Sau khi sửa

| | trước | sau |
|---|---|---|
| state/s tới client | 30 | **4.0** |
| chuỗi rAF đồng thời | tăng vô hạn | **1** |
| encode cho 3 client | 3x | **1x** |
| CPU server, 3 client | — | 17% (idle 15%) |
| frame/s mỗi client | — | 27.6 · 15.3 KB · 3.28 Mbps |
