"""Web UI — FastAPI. REST điều khiển + WebSocket stream frame và event.

Vì sao web chứ không native: bot chiếm chuột vật lý, nên UI phải xem/bấm được
từ THIẾT BỊ KHÁC (iPad, máy khác trong LAN).

Stream: WebSocket BINARY. Header 12 byte (frame_id uint32 BE + ts double BE) +
JPEG. Không base64 (phình +33%). Overlay KHÔNG vẽ vào JPEG — detection gửi
riêng bằng JSON có frame_id, client vẽ lên canvas.
Backpressure: luôn gửi frame MỚI NHẤT, không xếp hàng.
"""
from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..config import Config, data_path
from ..core import permissions
from ..core.capture import high_freq_energy
from ..perception import cheap, ocr
from ..perception.classify import classify, keywords_for_classify
from ..perception.yolo import YoloDetector
from ..perception.types import ScreenKind

STATIC = Path(__file__).parent / "static"


class FrameCache:
    """Encode JPEG một lần cho mọi client cùng xem một frame.

    Trước đây mỗi WebSocket client và mỗi tab MJPEG tự encode riêng. Bốn tab
    còn mở = bốn lần encode cùng một frame. Cache theo (frame_id, quality, scale).
    """

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._jpg: bytes = b""
        self._lock = threading.Lock()

    def get(self, frame, quality: int, scale: float) -> bytes:
        key = (frame.id, quality, scale)
        with self._lock:
            if key == self._key:
                return self._jpg
        jpg = cheap.encode_jpeg(frame.bgr, quality, scale)
        with self._lock:
            self._key, self._jpg = key, jpg
        return jpg


class Cached:
    """Bọc một hàm đắt tiền, giữ kết quả trong ttl giây."""

    def __init__(self, fn, ttl: float):
        self.fn, self.ttl = fn, ttl
        self._at = 0.0
        self._val = None

    def __call__(self):
        now = time.time()
        if self._val is None or now - self._at > self.ttl:
            self._val = self.fn()
            self._at = now
        return self._val


def bust_cache(html: str, static_dir: Path) -> str:
    """Gắn ?v=<mtime> vào /static/app.js và /static/style.css.

    `StaticFiles` chỉ gửi `etag` + `last-modified`, KHÔNG gửi `Cache-Control`,
    nên trình duyệt được phép dùng lại bản đã cache mà không hỏi lại server.
    Bug đã gặp thật: sửa xong `app.js`, `index.html` được phục vụ mới (thấy ô
    search) nhưng `app.js` vẫn là bản cũ (gõ vào không lọc gì) -> tưởng tính
    năng hỏng, trong khi code đúng.

    Đổi file -> mtime đổi -> URL đổi -> trình duyệt buộc phải tải lại. Không đổi
    thì vẫn cache như thường.
    """
    for name in ("app.js", "style.css"):
        f = static_dir / name
        if f.exists():
            html = html.replace(f"/static/{name}",
                                f"/static/{name}?v={int(f.stat().st_mtime)}")
    return html


def create_app(app_ctx) -> FastAPI:
    api = FastAPI(title="POK Bot")
    ctx = app_ctx
    frames = FrameCache()
    # permissions.check() là syscall TCC. Trước đây gọi 30 lần/giây trong vòng
    # lặp WS. Kết quả gần như không đổi -> cache 5s.
    perm_cached = Cached(permissions.check, 5.0)

    def guard_token(req: Request) -> None:
        token = ctx.cfg.get("app.web.token", "") or ""
        if token and req.headers.get("x-token") != token and \
           req.query_params.get("token") != token:
            raise HTTPException(401, "token không đúng")

    # ------------------------------------------------------------ trang
    @api.get("/", response_class=HTMLResponse)
    async def index():
        return bust_cache((STATIC / "index.html").read_text(encoding="utf-8"), STATIC)

    api.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ------------------------------------------------------------ state
    @api.get("/api/state")
    async def state():
        s = ctx.engine.snapshot()
        s["perm"] = perm_cached()
        s["hotkey_error"] = ctx.hotkey.error if ctx.hotkey else None
        s["stream"] = ctx.stream_cfg
        return s

    @api.get("/api/config")
    async def get_config():
        return ctx.cfg.data

    @api.post("/api/config/{section}")
    async def set_config(section: str, req: Request):
        guard_token(req)
        if section not in ("app", "game", "ads"):
            raise HTTPException(400, "section không hợp lệ")
        body = await req.json()
        ctx.cfg.data[section] = body
        ctx.cfg.save(section)
        if section == "game":
            ctx.engine.rules.reload(ctx.cfg.game)      # reload nóng
        if section == "ads":
            ctx.engine.closer.cfg = ctx.cfg.ads
            # đọc config lúc khởi tạo -> phải dựng lại, nếu không đổi đường dẫn
            # model trong web UI xong phải restart mới ăn
            ctx.engine.yolo = YoloDetector(ctx.cfg.ads)
            ctx.engine.closer.yolo = ctx.engine.yolo
        if section == "app":
            # SafetyGuard đọc config lúc khởi tạo -> phải nạp lại, không thì
            # sửa forbidden_zones/rate limit xong vẫn phải restart mới có tác dụng
            ctx.engine.guard.__init__(ctx.cfg.app)
            ctx.stream_cfg.update({
                "scale": float(ctx.cfg.get("app.stream.scale", 1.0)),
                "quality": int(ctx.cfg.get("app.stream.quality", 75)),
                "fps": int(ctx.cfg.get("app.stream.fps", 30)),
            })
        ctx.bus.log("info", f"đã lưu config/{section}.toml")
        return {"ok": True}

    # ---------------------------------------------------------- điều khiển
    @api.post("/api/control/{cmd}")
    async def control(cmd: str, req: Request):
        guard_token(req)
        eng = ctx.engine
        if cmd == "start":
            eng.start()
        elif cmd == "pause":
            eng.pause()
        elif cmd == "stop":
            eng.stop()
        elif cmd == "kill":
            eng.kill()
        elif cmd == "reset":
            eng.guard.reset()
            eng.bus.log("info", "đã reset SafetyGuard")
        else:
            raise HTTPException(400, f"lệnh không hợp lệ: {cmd}")
        return {"ok": True, "state": eng.state.value}

    @api.post("/api/manual/tap")
    def manual_tap(body: dict):
        # confirm bắt buộc: một click lạc trên vùng ảnh KHÔNG được phép tap
        # xuống iPhone. Đã xảy ra thật trong lúc phát triển.
        if not body.get("confirm"):
            raise HTTPException(400, "cần confirm=true")
        f = ctx.capture.latest()
        if not f:
            raise HTTPException(503, "chưa có frame")
        ok = ctx.engine.act.tap((float(body["x"]), float(body["y"])), f.win,
                                source="manual", label="tap tay từ UI",
                                frame_id=f.id)
        return {"ok": ok}

    @api.post("/api/manual/swipe")
    def manual_swipe(b: dict):
        if not b.get("confirm"):
            raise HTTPException(400, "cần confirm=true")
        f = ctx.capture.latest()
        if not f:
            raise HTTPException(503, "chưa có frame")
        ok = ctx.engine.act.swipe((float(b["x0"]), float(b["y0"])),
                                  (float(b["x1"]), float(b["y1"])), f.win,
                                  duration_ms=int(b.get("duration_ms", 220)),
                                  steps=int(b.get("steps", 18)),
                                  hold_end_ms=int(b.get("hold_end_ms", 80)),
                                  source="manual", label="swipe tay từ UI",
                                  frame_id=f.id)
        return {"ok": ok}

    # --------------------------------------------------------------- probe
    @api.post("/api/probe")
    def probe(req_body: dict | None = None):
        """Chạy CẢ 3 TẦNG trên frame hiện tại, trả kết quả + ms từng cái."""
        want_vlm = bool((req_body or {}).get("vlm", True))
        f = ctx.capture.latest()
        if not f:
            raise HTTPException(503, "chưa có frame")
        bgr = f.bgr
        out: dict = {"frame_id": f.id, "size": [bgr.shape[1], bgr.shape[0]]}

        t0 = time.perf_counter()
        out["hf"] = round(high_freq_energy(bgr), 2)
        out["hf_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        t0 = time.perf_counter()
        res = classify(bgr, ad_keywords=keywords_for_classify(ctx.cfg.ads),
                       ad_icon=ctx.cfg.ads)
        out["classify"] = {"kind": res.kind.value, "reason": res.reason}
        out["classify_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["texts"] = [
            {"text": t.text, "conf": round(t.conf, 2),
             "cx": round(t.cx, 1), "cy": round(t.cy, 1),
             "w": round(t.w, 1), "h": round(t.h, 1)}
            for t in res.texts]

        # Mốc để chỉ lấy event `candidate_blocked` do CHÍNH lần probe này sinh
        # ra. Trước đây đọc thẳng `bus.recent[-40:]` nên gộp cả event của những
        # lần bấm trước -> bảng "bị chặn" đếm trùng (4 góc ra 11 dòng).
        seen_before = len(ctx.bus.recent)

        t0 = time.perf_counter()
        cands = ctx.engine.closer.step_ocr(bgr, res.texts)
        out["ocr_candidates"] = [_cand(c, bgr) for c in cands]
        out["ocr_step_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        # Bước 2b — dò dấu ✕ bằng OpenCV, quét CẢ FRAME. Engine chạy bước này
        # (machine.py `_state_ad_closing`) nhưng probe thì trước đây bỏ qua, nên
        # "Chạy thử" báo trắng trong khi engine thật đã tìm ra nút đóng. Probe
        # phải phản ánh đúng pipeline, nếu không nó dẫn người dùng đi sai hướng.
        t0 = time.perf_counter()
        icons = ctx.engine.closer.step_icon(bgr, res.texts)
        out["icon_candidates"] = [_cand(c, bgr) for c in icons]
        out["icon_step_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        t0 = time.perf_counter()
        yolos = ctx.engine.closer.step_yolo(bgr, res.texts)
        out["yolo_candidates"] = [_cand(c, bgr) for c in yolos]
        out["yolo_step_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["yolo"] = ctx.engine.yolo.info()

        out["vlm"] = []
        if want_vlm and ctx.engine.vlm.enabled:
            job = ctx.engine.worker.run_sync(
                lambda: ctx.engine.closer.step_vlm_top(bgr, res.texts),
                name="probe:vlm", timeout=60)
            out["vlm"].append({
                "corner": "dải 25% trên",
                "ms": round(job.ms, 0),
                "error": job.error,
                "candidates": [_cand(c, bgr) for c in (job.result or [])],
            })
        out["blocked"] = [e for e in list(ctx.bus.recent)[seen_before:]
                          if e.get("type") == "candidate_blocked"]
        return out

    def _cand(c, bgr) -> dict:
        h, w = bgr.shape[:2]
        return {"label": c.label, "origin": c.origin,
                "cx": round(c.cx, 1), "cy": round(c.cy, 1),
                "w": round(c.w, 1), "h": round(c.h, 1),
                "rel": [round(c.cx / w, 4), round(c.cy / h, 4)],
                "blocked": c.blocked, "block_reason": c.block_reason,
                "nearby": c.nearby_text}

    # -------------------------------------------------------- test luật khô
    @api.post("/api/rules/test")
    def rules_test():
        """Đánh giá TẤT CẢ luật trên frame hiện tại mà KHÔNG hành động.

        Cách an toàn để kiểm tra toạ độ và điều kiện trước khi cho bot swipe thật.
        """
        f = ctx.capture.latest()
        if not f:
            raise HTTPException(503, "chưa có frame")
        bgr = f.bgr
        res = classify(bgr, ad_keywords=keywords_for_classify(ctx.cfg.ads),
                       ad_icon=ctx.cfg.ads)
        low = " | ".join(t.text.lower() for t in res.texts)
        eng = ctx.engine.rules
        idle = eng.update_idle(bgr)

        out = []
        for rule in eng.rules:
            row = {"name": rule.name, "enabled": rule.enabled,
                   "priority": rule.priority, "kind": rule.when.get("kind"),
                   "cooldown_left": round(eng.cooldown_left(rule), 2),
                   "match": False, "info": {}, "action": rule.do}
            # Đánh giá CẢ luật đang tắt và luật đang trong cooldown — cả quy
            # trình là "viết luật ở trạng thái tắt -> test khô -> mới bật".
            only = [r for r in eng.rules if r is rule]
            keep, eng.rules = eng.rules, only
            try:
                hit = eng.evaluate(bgr, idle, low, texts=res.texts,
                                   ignore_enabled=True,
                                   ignore_cooldown=True)
            finally:
                eng.rules = keep
            if hit:
                row["match"] = True
                row["info"] = hit[1]
            out.append(row)

        winner = next((r for r in sorted(out, key=lambda x: x["priority"])
                       if r["enabled"] and r["match"]), None)
        return {"frame_id": f.id, "size": [bgr.shape[1], bgr.shape[0]],
                "classify": res.kind.value, "idle_seconds": round(idle, 1),
                "ocr_joined": low, "rules": out,
                "would_fire": winner["name"] if winner else None,
                "would_do": winner["action"] if winner else None}

    # ------------------------------------------------------------ capture
    @api.post("/api/capture/shot")
    def shot():
        f = ctx.capture.latest()
        if not f:
            raise HTTPException(503, "chưa có frame")
        name = time.strftime("%Y%m%d-%H%M%S") + f"-{f.id}.png"
        path = data_path("captures", name)
        cv2.imwrite(str(path), f.bgr)
        ctx.bus.log("info", f"đã chụp {name}")
        return {"ok": True, "name": name}

    @api.get("/api/capture/list")
    async def cap_list():
        d = data_path("captures", ".keep").parent
        tags = _load_tags()
        items = []
        for p in sorted(d.glob("*.png"), reverse=True):
            items.append({"name": p.name, "size": p.stat().st_size,
                          "tag": tags.get(p.name, "")})
        return {"items": items, "counts": _tag_counts(items)}

    @api.get("/api/capture/file/{name}")
    async def cap_file(name: str):
        p = data_path("captures", name)
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p)

    @api.post("/api/capture/tag")
    async def cap_tag(req: Request):
        guard_token(req)
        b = await req.json()
        tags = _load_tags()
        tags[b["name"]] = b.get("tag", "")
        data_path("captures", "_tags.json").write_text(
            json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True}

    @api.post("/api/capture/delete")
    async def cap_del(req: Request):
        guard_token(req)
        b = await req.json()
        p = data_path("captures", b["name"])
        if p.exists():
            p.unlink()
        return {"ok": True}

    def _load_tags() -> dict:
        p = data_path("captures", "_tags.json")
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _tag_counts(items) -> dict:
        c: dict[str, int] = {}
        for it in items:
            k = it["tag"] or "(chưa gắn)"
            c[k] = c.get(k, 0) + 1
        return c

    # ----------------------------------------------------------- sessions
    @api.get("/api/sessions")
    async def sessions():
        d = data_path("sessions", ".keep").parent
        out = []
        for p in sorted([x for x in d.iterdir() if x.is_dir()], reverse=True):
            st = p / "stats.json"
            item = {"name": p.name, "has_stats": st.exists()}
            if st.exists():
                try:
                    item["stats"] = json.loads(st.read_text(encoding="utf-8"))
                except Exception:
                    pass
            out.append(item)
        return {"items": out}

    @api.get("/api/sessions/{name}/events")
    async def session_events(name: str, limit: int = 500):
        p = data_path("sessions", name, "events.jsonl")
        if not p.exists():
            raise HTTPException(404)
        lines = p.read_text(encoding="utf-8").strip().splitlines()[-limit:]
        return {"items": [json.loads(x) for x in lines if x.strip()]}

    # ------------------------------------------------------------- doctor
    @api.get("/api/doctor")
    async def doctor():
        from ..core.window import find
        win = find(ctx.cfg.get("app.window.bundle_id"))
        f = ctx.capture.latest()
        scale = None
        if f and win:
            scale = round(f.bgr.shape[1] / win.w, 3)
        return {
            "perm": perm_cached(),
            "window": (dict(id=win.id, pid=win.pid, name=win.name, x=win.x,
                            y=win.y, w=win.w, h=win.h) if win else None),
            "scale": scale,
            "capture_fps": round(ctx.capture.measured_fps, 1),
            "capture_grab_ms": round(ctx.capture.grab_ms, 1),
            "viewers": ctx.viewers,
            "capture_error": ctx.capture.last_error,
            "vlm": ctx.engine.vlm.info(),
            "hotkey_error": ctx.hotkey.error if ctx.hotkey else None,
            "ring": len(ctx.capture.ring),
        }

    @api.post("/api/stream")
    async def set_stream(req: Request):
        b = await req.json()
        for k in ("scale", "quality", "fps"):
            if k in b:
                ctx.stream_cfg[k] = (float(b[k]) if k == "scale" else int(b[k]))
        return ctx.stream_cfg

    # -------------------------------------------------------------- MJPEG
    @api.get("/stream.mjpg")
    async def mjpeg():
        """Dự phòng: chạy trong <img src> trần, không cần JS. Không có overlay."""
        boundary = "pokframe"

        async def gen():
            last = -1
            ctx.viewers += 1
            try:
                async for chunk in _mjpeg_frames(last):
                    yield chunk
            finally:
                ctx.viewers = max(0, ctx.viewers - 1)

        async def _mjpeg_frames(last):
            while True:
                f = ctx.capture.latest()
                if f and f.id != last:
                    last = f.id
                    jpg = frames.get(f, ctx.stream_cfg["quality"],
                                     ctx.stream_cfg["scale"])
                    yield (f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                           f"Content-Length: {len(jpg)}\r\n\r\n").encode() + jpg + b"\r\n"
                await asyncio.sleep(1.0 / max(1, ctx.stream_cfg["fps"]))

        return StreamingResponse(
            gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}")

    # ----------------------------------------------------------- WebSocket
    @api.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        ctx.viewers += 1
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)

        def on_event(ev: dict) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, ev)
            except Exception:
                pass

        unsub = ctx.bus.subscribe(on_event)
        # gửi lịch sử gần nhất để UI không trống trơn
        for ev in list(ctx.bus.recent)[-60:]:
            await sock.send_text(json.dumps({"kind": "event", "event": ev},
                                            ensure_ascii=False))
        last_frame = -1
        last_state = 0.0
        try:
            while True:
                # 1) frame mới nhất (backpressure: bỏ frame cũ, không xếp hàng)
                f = ctx.capture.latest()
                if f and f.id != last_frame:
                    last_frame = f.id
                    jpg = frames.get(f, ctx.stream_cfg["quality"],
                                     ctx.stream_cfg["scale"])
                    head = struct.pack(">Id", f.id & 0xFFFFFFFF, f.ts)
                    await sock.send_bytes(head + jpg)

                # 2) mọi event đang chờ
                drained = 0
                while not queue.empty() and drained < 50:
                    ev = queue.get_nowait()
                    await sock.send_text(json.dumps({"kind": "event", "event": ev},
                                                    ensure_ascii=False))
                    drained += 1

                # 3) state định kỳ
                # 3) state — 4 Hz, KHÔNG theo nhịp frame
                now = time.monotonic()
                if now - last_state >= 0.25:
                    last_state = now
                    snap = ctx.engine.snapshot()
                    snap["stream"] = dict(ctx.stream_cfg)
                    snap["perm"] = perm_cached()
                    await sock.send_text(json.dumps(
                        {"kind": "state", "state": snap},
                        ensure_ascii=False, default=str))
                await asyncio.sleep(1.0 / max(1, ctx.stream_cfg["fps"]))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsub()
            ctx.viewers = max(0, ctx.viewers - 1)

    return api
