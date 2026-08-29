"""CLI. Chạy được không cần UI.

  python -m pok doctor     kiểm tra quyền, cửa sổ, scale, FPS
  python -m pok ui         chạy web UI (mặc định)
  python -m pok run        chạy bot không UI
  python -m pok capture    chụp 1 frame ra data/captures/
  python -m pok probe      chạy cả 3 tầng trên frame hiện tại, in ra terminal
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .config import Config, data_path
from .core import permissions
from .core.capture import CaptureService, high_freq_energy
from .core.window import find
from .engine.machine import BotEngine
from .store.events import EventBus


class AppContext:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.bus = EventBus()
        self.capture = CaptureService(
            cfg.get("app.window.bundle_id"),
            target_fps=int(cfg.get("app.capture.target_fps", 30)),
            ring_size=int(cfg.get("app.capture.ring_size", 60)))
        self.engine = BotEngine(cfg, self.bus, self.capture)
        self.hotkey = None
        self.viewers = 0            # số client web đang mở stream
        # Luồng chụp chỉ chạy full FPS khi có người tiêu thụ frame.
        self.capture.demand = lambda: (self.viewers > 0
                                       or self.engine.running)
        self.stream_cfg = {
            "scale": float(cfg.get("app.stream.scale", 1.0)),
            "quality": int(cfg.get("app.stream.quality", 75)),
            "fps": int(cfg.get("app.stream.fps", 30)),
        }


def cmd_doctor(cfg: Config) -> int:
    p = permissions.check()
    print("=" * 68)
    print("POK DOCTOR")
    print("=" * 68)
    print(f"[{'OK' if p['screen_recording'] else 'X '}] Screen Recording")
    print(f"[{'OK' if p['accessibility'] else 'X '}] Accessibility")
    bundle = cfg.get("app.window.bundle_id")
    win = find(bundle)
    if win:
        print(f"[OK] Cửa sổ '{win.name}' id={win.id} pid={win.pid} "
              f"bounds=({win.x},{win.y},{win.w},{win.h}) point")
    else:
        print(f"[X ] Không thấy cửa sổ bundle={bundle} — mở iPhone Mirroring chưa?")
    if not p["ok"]:
        print("\n" + p["hint"])
        return 1
    if not win:
        return 2

    cap = CaptureService(bundle, target_fps=30)
    cap.start()
    time.sleep(1.2)
    f = cap.latest()
    if f is None:
        print(f"[X ] Chưa chụp được frame: {cap.last_error}")
        cap.stop()
        return 3
    hf = high_freq_energy(f.bgr)
    scale = f.bgr.shape[1] / win.w
    print(f"[OK] Frame {f.bgr.shape[1]}x{f.bgr.shape[0]}  scale={scale:.2f}  "
          f"FPS≈{cap.measured_fps:.1f}")
    if hf < 1.0:
        print(f"[X ] hf={hf:.2f} — đây là HÌNH NỀN DESKTOP, không phải màn iPhone.")
        print("     macOS trả hình nền khi thiếu quyền Screen Recording.")
        cap.stop()
        return 4
    print(f"[OK] Nội dung hợp lệ (hf={hf:.2f}, ngưỡng 1.0)")
    cap.stop()
    print("\nSẵn sàng. Chạy:  python -m pok ui")
    return 0


def cmd_capture(cfg: Config) -> int:
    import cv2
    bundle = cfg.get("app.window.bundle_id")
    cap = CaptureService(bundle, target_fps=30)
    cap.start()
    time.sleep(1.0)
    f = cap.latest()
    cap.stop()
    if f is None:
        print("không chụp được:", cap.last_error)
        return 1
    name = time.strftime("%Y%m%d-%H%M%S") + f"-{f.id}.png"
    path = data_path("captures", name)
    cv2.imwrite(str(path), f.bgr)
    print("đã lưu", path)
    return 0


def cmd_probe(cfg: Config) -> int:
    from .perception.classify import classify, keywords_for_classify
    ctx = AppContext(cfg)
    ctx.capture.start()
    time.sleep(1.2)
    f = ctx.capture.latest()
    if f is None:
        print("không có frame:", ctx.capture.last_error)
        return 1
    bgr = f.bgr
    print(f"frame {bgr.shape[1]}x{bgr.shape[0]}  hf={high_freq_energy(bgr):.2f}\n")

    t0 = time.perf_counter()
    res = classify(bgr, ad_keywords=keywords_for_classify(cfg.ads),
                   ad_icon=cfg.ads)
    print(f"classify: {res.kind.value} ({res.reason})  "
          f"{(time.perf_counter()-t0)*1000:.0f}ms")
    print(f"OCR {len(res.texts)} vùng chữ:")
    for t in res.texts[:25]:
        print(f"  {t.conf:.2f} ({t.cx:>6.0f},{t.cy:>6.0f})  {t.text!r}")

    cands = ctx.engine.closer.step_ocr(bgr, res.texts)
    print(f"\nứng viên từ OCR (đã qua 3 cửa lọc): {len(cands)}")
    for c in cands:
        print(f"  {c.label!r} @({c.cx:.0f},{c.cy:.0f}) {c.w:.0f}x{c.h:.0f} "
              f"origin={c.origin}")

    if ctx.engine.vlm.enabled:
        ctx.engine.worker.start()
        for corner in ctx.engine.closer.corners():
            job = ctx.engine.worker.run_sync(
                lambda c=corner: ctx.engine.closer.step_vlm_corner(
                    bgr, res.texts, c), name=corner, timeout=90)
            n = len(job.result or [])
            print(f"\nVLM {corner}: {job.ms:.0f}ms  {n} ứng viên"
                  f"{'  LỖI: ' + job.error if job.error else ''}")
            for c in (job.result or []):
                print(f"  {c.label!r} @({c.cx:.0f},{c.cy:.0f}) "
                      f"{c.w:.0f}x{c.h:.0f}  (diện tích {c.w*c.h:.0f}px²)")

    blocked = [e for e in ctx.bus.recent if e.get("type") == "candidate_blocked"]
    if blocked:
        print(f"\nBỊ LỌC AN TOÀN CHẶN: {len(blocked)}")
        for e in blocked:
            print(f"  {e['reason']:<10} {e['label']!r} @({e['cx']},{e['cy']}) "
                  f"nearby={e['nearby']}")
    ctx.capture.stop()
    return 0


def cmd_run(cfg: Config) -> int:
    ctx = AppContext(cfg)
    ctx.bus.subscribe(lambda e: print(json.dumps(e, ensure_ascii=False)[:200]))
    ctx.capture.start()
    ctx.engine.start()
    print("bot đang chạy. Ctrl+C để dừng.")
    try:
        while ctx.engine.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    ctx.engine.stop()
    ctx.capture.stop()
    return 0


def cmd_ui(cfg: Config, lan: bool) -> int:
    import uvicorn

    from .ui.hotkey import HotkeyListener
    from .ui.server import create_app

    ctx = AppContext(cfg)
    ctx.capture.start()

    if cfg.get("app.hotkey.enabled", True):
        ctx.hotkey = HotkeyListener({
            "s": lambda: (ctx.engine.pause() if ctx.engine.running
                          else ctx.engine.start()),
            "k": ctx.engine.kill,
            "c": lambda: _quick_shot(ctx),
            "p": lambda: ctx.bus.log("info", "probe: mở tab Probe trên web UI"),
        })
        ctx.hotkey.start()

    host = "0.0.0.0" if lan else cfg.get("app.web.host", "127.0.0.1")
    port = int(cfg.get("app.web.port", 8765))
    app = create_app(ctx)
    print(f"\n  Web UI: http://{'<IP máy này>' if lan else host}:{port}")
    print(f"  MJPEG : http://{host}:{port}/stream.mjpg")
    print("  Hotkey: ⌃⌥⌘S start/pause · ⌃⌥⌘K KILL · ⌃⌥⌘C chụp\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    ctx.capture.stop()
    return 0


def _quick_shot(ctx) -> None:
    import cv2
    f = ctx.capture.latest()
    if not f:
        return
    name = time.strftime("%Y%m%d-%H%M%S") + f"-{f.id}.png"
    cv2.imwrite(str(data_path("captures", name)), f.bgr)
    ctx.bus.log("info", f"hotkey chụp {name}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pok", description="Bot Path of Kings")
    ap.add_argument("command", nargs="?", default="ui",
                    choices=["ui", "run", "doctor", "capture", "probe"])
    ap.add_argument("--lan", action="store_true",
                    help="bind 0.0.0.0 để xem từ iPad/máy khác (nên đặt token)")
    args = ap.parse_args(argv)
    cfg = Config()
    if args.command == "doctor":
        return cmd_doctor(cfg)
    if args.command == "capture":
        return cmd_capture(cfg)
    if args.command == "probe":
        return cmd_probe(cfg)
    if args.command == "run":
        return cmd_run(cfg)
    return cmd_ui(cfg, args.lan)


if __name__ == "__main__":
    sys.exit(main())
