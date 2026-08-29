#!/bin/bash
# Tạo lại lối tắt khởi động. Chạy lại khi đổi đường dẫn dự án hoặc khi lối tắt bị xoá.
#
#   ~/Desktop/POK Bot.command   — double-click là chạy (cách dùng chính)
#   ~/Applications/POK Bot.app  — cho Spotlight (⌘Space) và Dock
#
# Vì sao app phải là AppleScript chứ không phải LaunchAgent / Automator:
# macOS đọc quyền Screen Recording theo app cha lúc process khởi động. App này
# KHÔNG tự chạy python — nó nhờ Terminal.app chạy poc/run_ui.command, nên python
# là con của Terminal và thừa hưởng đúng TCC identity đã được cấp quyền.

set -e
ROOT="/Users/tientran/Tong Hop/path_of_kings_tool"
SCRIPT="$ROOT/poc/run_ui.command"
APPS="$HOME/Applications"
mkdir -p "$APPS"

cat > "$HOME/Desktop/POK Bot.command" <<EOF
#!/bin/bash
# Double-click để khởi động bot Path of Kings (web UI, chế độ LAN).
# Chỉ là lối tắt — logic thật nằm trong repo:
exec "$SCRIPT"
EOF
chmod +x "$HOME/Desktop/POK Bot.command"
echo "  ✓ ~/Desktop/POK Bot.command"

SRC=$(mktemp /tmp/pok_launcher.XXXXXX.applescript)
cat > "$SRC" <<EOF
tell application "Terminal"
	activate
	do script "clear; '$SCRIPT'"
end tell
EOF
rm -rf "$APPS/POK Bot.app"
osacompile -o "$APPS/POK Bot.app" "$SRC"
rm -f "$SRC"
echo "  ✓ $APPS/POK Bot.app"

mdimport "$APPS" 2>/dev/null   # để Spotlight tìm thấy ngay
echo ""
echo "Xong. Double-click \"POK Bot\" trên Desktop, hoặc ⌘Space → \"POK Bot\"."
