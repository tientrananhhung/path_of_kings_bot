#!/bin/bash
# Khởi động pok ui. DOUBLE-CLICK file này trong Finder là chạy được.
#
# macOS cấp Screen Recording + Accessibility theo APP CHA của process và đọc quyền
# lúc app khởi động. Double-click .command → Terminal.app thực thi → đúng TCC identity.
# Chạy từ IDE/agent/launchd sẽ nhận về hình nền desktop thay vì cửa sổ iPhone Mirroring.
#
# Mặc định bind 0.0.0.0 (--lan) để xem được từ máy khác cùng mạng — double-click
# không truyền được tham số nên cờ phải nằm sẵn trong script.
# Muốn khoá về localhost:  ./poc/run_ui.command --local

cd "/Users/tientran/Tong Hop/path_of_kings_tool" || exit 1
mkdir -p poc/out

# Không gọi mạng lên Hugging Face Hub. Checkpoint Florence-2 đã nằm trong
# ~/.cache/huggingface (447MB) nên load hoàn toàn từ đĩa; biến này cắt luôn cú
# kiểm tra revision mỗi lần khởi động, thứ có thể treo prewarm khi mạng chậm.
# ĐỔI model trong config/ads.toml thì phải tải trước khi bật lại cờ này.
export HF_HUB_OFFLINE=1

# --local là cờ của riêng script này, argparse của pok không biết nó → phải lọc ra.
LAN=1
ARGS=()
for a in "$@"; do
  case "$a" in
    --local) LAN=0 ;;
    --lan)   LAN=1 ;;
    *)       ARGS+=("$a") ;;
  esac
done
[[ "$LAN" == "1" ]] && ARGS+=(--lan)

# Dừng instance cũ — 2 process cùng lúc sẽ tranh cửa sổ chụp và cổng 8765.
pkill -9 -f "m pok ui" 2>/dev/null
sleep 1

PORT=$(sed -n 's/^port *= *\([0-9]*\).*/\1/p' config/app.toml | head -1)
PORT=${PORT:-8765}
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

echo "  Local : http://127.0.0.1:$PORT"
if [[ "$LAN" == "1" ]]; then
  echo "  LAN   : http://${IP:-<không lấy được IP>}:$PORT"
  TOKEN=$(sed -n 's/^token *= *"\([^"]*\)".*/\1/p' config/app.toml | head -1)
  [[ -z "$TOKEN" ]] && \
    echo "  ⚠️  token rỗng — ai trong LAN cũng xem màn hình và tap được vào iPhone."
else
  echo "  (chế độ --local: máy khác KHÔNG vào được)"
fi
echo ""

# Mở browser khi cổng đã sẵn sàng (uvicorn chạy foreground nên phải poll ở nền).
(
  for _ in $(seq 1 60); do
    if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
      open "http://127.0.0.1:$PORT"
      exit 0
    fi
    sleep 0.5
  done
  echo "  ⚠️  server chưa mở cổng $PORT sau 30s — xem log phía trên."
) &

# tee: log vẫn ghi ui.log như trước, đồng thời hiện trong cửa sổ Terminal.
./.venv/bin/python -u -m pok ui "${ARGS[@]}" 2>&1 | tee poc/out/ui.log
