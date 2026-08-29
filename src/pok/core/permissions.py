"""Kiểm tra 2 quyền TCC bắt buộc.

macOS đọc quyền lúc app khởi động và cấp theo APP CHA của process. Cấp xong
phải Cmd+Q quit hẳn terminal rồi mở lại — đóng cửa sổ không đủ.
"""
from __future__ import annotations

import Quartz


def screen_recording() -> bool:
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def accessibility() -> bool:
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def request_screen_recording() -> None:
    Quartz.CGRequestScreenCaptureAccess()


def check() -> dict:
    sr, ax = screen_recording(), accessibility()
    return {
        "screen_recording": sr,
        "accessibility": ax,
        "ok": sr and ax,
        "hint": (
            "System Settings > Privacy & Security > Screen & System Audio Recording\n"
            "System Settings > Privacy & Security > Accessibility\n"
            "Cấp cho app đang chạy script (Terminal.app), rồi Cmd+Q quit hẳn và mở lại."
        ),
    }
