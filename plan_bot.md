# MASTER PLAN: TỰ ĐỘNG HÓA GAME & XỬ LÝ QUẢNG CÁO (PATH OF KINGS)

## I. KIẾN TRÚC HỆ THỐNG (SYSTEM ARCHITECTURE)

Hệ thống hoạt động theo mô hình **Vòng lặp khép kín (Perception-Decision-Action Loop)** chạy dưới nền Python, tương tác trực tiếp với cửa sổ `iPhone Mirroring` trên macOS.

```text  
+-------------------------------------------------------------------+
|                       MACBOOK LOCAL SYSTEM                        |
|                                                                   |
|  [1. Screen Capture] ---> Lấy khung hình cửa sổ iPhone Mirroring  |
|         |                                                         |
|         v                                                         |
|  [2. Perception Engine] -> YOLOv8 Nano (Nhận diện Game/Quảng cáo) |
|         |                  + OpenCV (Kiểm tra Pixel / Trạng thái) |
|         v                                                         |
|  [3. State Machine] -----> Logic quyết định (Đánh quái / Tắt ads) |
|         |                                                         |
|         v                                                         |
|  [4. Action Executor] ---> PyAutoGUI (Điều khiển chuột/Click)     |
+-------------------------------------------------------------------+
```

## **II. CÔNG NGHỆ VÀ THƯ VIỆN SỬ DỤNG (TECH STACK)**

Toàn bộ chạy local trên Python (khuyên dùng Python 3.10 hoặc 3.11):

* **Ngôn ngữ:** Python  
* **Chụp màn hình:** pyautogui hoặc mss (mss tối ưu tốc độ chụp hình nhanh hơn trên macOS).  
* **AI Nhận diện (Đôi mắt):** ultralytics (YOLOv8 Nano \- file export sang định dạng .onnx hoặc chạy trực tiếp PyTorch trên Apple Silicon qua backend MPS).  
* **Xử lý ảnh phụ trợ:** opencv-python (cv2) để crop ảnh, xử lý template matching hoặc check màu sắc thanh máu/thời gian.  
* **Thao tác chuột:** pyautogui (thực hiện click tại tọa độ tính toán).

## **III. CHI TIẾT CÁC MODULE XỬ LÝ (PROCESSING PIPELINE)**

### **1. Module Thu thập & Cố định Khung hình (Capture & Region Locking)**

* **Vấn đề:** Khi mở iPhone Mirroring, cửa sổ app có thể bị dịch chuyển tọa độ trên màn hình Mac.  
* **Giải pháp:**  
  * Sử dụng OpenCV để nhận diện tiêu đề hoặc viền cửa sổ iPhone Mirroring lúc khởi động để cố định tọa độ vùng cần chụp (region \= \[x, y, width, height\]).  
  * Mọi tọa độ AI trả về sẽ được quy đổi tương đối theo góc trên bên trái của khung cửa sổ này.

### **2. Module Nhận diện AI (YOLOv8 Nano Inference)**

* **Dataset cần gán nhãn (Labeling):**  
  * monster: Quái vật trong game.  
  * skill_btn: Các nút kỹ năng phía dưới.  
  * reward_ad_btn: Nút xem quảng cáo nhận thưởng.  
  * close_ad: Các biến thể nút 'X' / 'Skip' của quảng cáo.  
* **Tốc độ:** Chạy trên chip Apple Silicon (M1/M2/M3/M4) qua phần cứng tăng tốc, mất khoảng **5–15ms/frame**.

### **3\. Module Xử lý Trạng thái Thông minh (State Machine Logic)**

Hệ thống phân chia thành 3 trạng thái chính để xử lý các "Dark Patterns" của quảng cáo:

* **Trạng thái 1: CHIẾN ĐẤU (FIGHTING)**  
  * *Điều kiện:* YOLO phát hiện đối tượng monster.  
  * *Hành động:* Lấy tọa độ tâm của quái -> Ra lệnh pyautogui.click() liên tục để tấn công. Kết hợp check điểm màu (OpenCV) nếu máu thấp thì click bình máu.  
* **Trạng thái 2: XEM QUẢNG CÁO & XỬ LÝ NHIỀU LỚP (WATCHING_AD)**  
  * *Điều kiện:* Bấm vào nút reward_ad_btn.  
  * *Hành động:*  
    1. Kích hoạt bộ đếm thời gian (Timeout) chờ video chạy (mặc định 30 giây).  
    2. Sau 30 giây, liên tục quét tìm close_ad.  
    3. *Xử lý quảng cáo nhiều lớp:* Nếu click nút X xong mà màn hình chuyển sang giao diện App Store ảo (có chữ "Done" hoặc icon tải app), hệ thống kích hoạt sub-routine bấm vào "Done" để thoát lớp phụ, sau đó tiếp tục tìm nút X chính để quay lại game.  
* **Trạng thái 3: KẸT MÀN HÌNH / SẢNH CHỜ (IDLE)**  
  * *Điều kiện:* Trong vòng 15 giây không thấy quái vật hay quảng cáo.  
  * *Hành động:* Click vào tọa độ "Vùng an toàn" giữa màn hình để tiếp tục trận đấu/vào màn mới.

## **IV. BẢN THẢO MÃ NGUỒN CƠ BẢN (PYTHON SCRIPT TEMPLATE)**

```python
Python  
import time  
import cv2  
import numpy as np  
import pyautogui  
from ultralytics import YOLO

# 1. Load Model YOLO chạy local (có thể dùng file .pt hoặc export sang .onnx)  
model = YOLO("path_of_kings_yolov8n.pt")

# Tọa độ khung cửa sổ iPhone Mirroring trên màn hình Mac (Cần canh chỉnh thực tế)  
# Format: (left, top, width, height)  
WINDOW_REGION = (100, 100, 400, 850) 

def capture_screen():  
    # Dùng pyautogui chụp đúng vùng iPhone Mirroring  
    screenshot = pyautogui.screenshot(region=WINDOW_REGION)  
    frame = np.array(screenshot)  
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

print("Bot Path of Kings đã sẵn sàng. Nhấn Ctrl+C để dừng.")

while True:  
    start_time = time.time()  

    # Bước 1: Chụp màn hình  
    frame = capture_screen()  

    # Bước 2: AI Nhận diện (độ tin cậy > 75%)  
    results = model(frame, conf=0.75, verbose=False)[0]  

    action_taken = False  

    for box in results.boxes:  
        cls_id = int(box.cls[0])  
        label = model.names[cls_id]  

        # Tính tọa độ tâm của đối tượng được khoanh vùng  
        xyxy = box.xyxy[0].tolist()  
        cx = int((xyxy[0] + xyxy[2]) / 2)  
        cy = int((xyxy[1] + xyxy[3]) / 2)  

        # Chuyển đổi tọa độ cục bộ trong khung hình thành tọa độ tuyệt đối trên màn hình Mac  
        absolute_x = WINDOW_REGION[0] + cx  
        absolute_y = WINDOW_REGION[1] + cy  

        # Xử lý theo nhãn (Label)  
        if label == "close_ad":  
            print("-> Phát hiện nút đóng quảng cáo. Đang click...")  
            pyautogui.click(absolute_x, absolute_y)  
            time.sleep(2)  
            action_taken = True  
            break  

        elif label == "reward_ad_btn":  
            print("-> Bấm nhận thưởng quảng cáo. Đang chờ video...")  
            pyautogui.click(absolute_x, absolute_y)  
            time.sleep(32) # Chờ thời lượng quảng cáo trung bình  
            action_taken = True  
            break  

        elif label == "monster":  
            # Click tấn công quái vật  
            pyautogui.click(absolute_x, absolute_y)  
            action_taken = True  
            break

    # Nếu không tìm thấy đối tượng nào ưu tiên, click "Safe Zone" hoặc nút Next mặc định  
    if not action_taken:  
        # Click vào vị trí giữa màn hình dưới để tiếp tục nếu đứng sảnh  
        # pyautogui.click(WINDOW_REGION[0] + 200, WINDOW_REGION[1] + 750)  
        pass

    # Giới hạn tốc độ vòng lặp khoảng 10-15 FPS để nhẹ máy (delay ~0.08s)  
    elapsed = time.time() - start_time  
    if elapsed < 0.08:  
        time.sleep(0.08 - elapsed)
```

## **V. CÁC BƯỚC THỰC THI CHO AI LOCAL**

> 1. **Thu thập dữ liệu:** Chơi game thủ công trên iPhone Mirroring, dùng công cụ chụp màn hình lưu khoảng 150-200 bức ảnh lúc đánh quái và lúc gặp các dạng quảng cáo khác nhau.  
> 2. **Gán nhãn (Labeling):** Đưa ảnh lên Roboflow, vẽ box và đặt tên đúng các nhãn: monster, close_ad, reward_ad_btn.  
> 3. **Train Model:** Train trực tiếp trên Google Colab (chọn YOLOv8 Nano) để nhận về file trọng số (.pt hoặc .onnx).  
> 4. **Cấu hình tọa độ:** Viết script Python nhận diện đúng vị trí cửa sổ iPhone Mirroring trên MacBook của bạn.  
> 5. **Chạy thử & Tinh chỉnh:** Chạy chế độ verbose=True để kiểm tra độ chính xác của AI nhận diện, sau đó điều chỉnh thời gian sleep cho phù hợp với nhịp độ của game.
