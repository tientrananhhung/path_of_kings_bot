#!/usr/bin/env python
"""In gọn trạng thái bot ra terminal. Thay cho các lệnh curl+python một dòng
(lồng quote trong f-string rất dễ lỗi cú pháp).

  ./.venv/bin/python poc/show.py rules     # test khô: luật nào khớp
  ./.venv/bin/python poc/show.py ocr       # mọi vùng chữ + toạ độ
  ./.venv/bin/python poc/show.py events    # action/state/log của phiên mới nhất
  ./.venv/bin/python poc/show.py stats     # thống kê phiên đang chạy
  ./.venv/bin/python poc/show.py doctor
"""
import json
import pathlib
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def post(path, body=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def cmd_rules():
    d = post("/api/rules/test")
    print(f"frame {d['frame_id']} {d['size']}  classify={d['classify']}  "
          f"idle={d['idle_seconds']}s")
    print(f"OCR: {d['ocr_joined'][:170]}\n")
    for r in d["rules"]:
        mark = "x" if r["enabled"] else " "
        hit = "KHỚP" if r["match"] else "—"
        print(f"  [{mark}] p{r['priority']:<3} {r['kind']:<9} {hit:<5} "
              f"cd={r['cooldown_left']}s  {r['name']}")
        if r["info"]:
            print(f"        info={r['info']}")
    print(f"\nsẽ bắn   : {d['would_fire']}")
    print(f"hành động: {d['would_do']}")


def cmd_ocr():
    d = post("/api/probe", {"vlm": False})
    print(f"frame {d['frame_id']} {d['size']}  hf={d['hf']}  "
          f"classify={d['classify']['kind']} ({d['classify_ms']}ms)")
    print(f"{len(d['texts'])} vùng chữ (local point):")
    for t in sorted(d["texts"], key=lambda x: x["cy"]):
        rx, ry = t["cx"] / d["size"][0], t["cy"] / d["size"][1]
        print(f"  {t['conf']:.2f} ({t['cx']:>5.0f},{t['cy']:>5.0f}) "
              f"rel=({rx:.3f},{ry:.3f}) {t['w']:>5.0f}x{t['h']:>4.0f}  {t['text']!r}")


def cmd_events():
    sess = sorted(pathlib.Path("data/sessions").iterdir())
    if not sess:
        print("chưa có phiên nào")
        return
    path = sess[-1] / "events.jsonl"
    print(f"phiên {sess[-1].name}\n")
    for line in open(path, encoding="utf-8"):
        e = json.loads(line)
        t = e["type"]
        if t == "action":
            p = e["points"]
            blk = f"BỊ CHẶN({e['block_reason']})" if e["blocked"] else "ok"
            extra = f" price={e['price_text']!r}" if e.get("price_text") else ""
            print(f"ACTION {e['kind']:<6} {blk:<22} {e['source']:<10} "
                  f"{p[0]} -> {p[-1]} {e['duration_ms']}ms  {e['label']}{extra}")
        elif t == "state":
            print(f"STATE  {e['from']} -> {e['to']}   {e['reason']}")
        elif t == "log":
            print(f"LOG[{e['level']}] {e['msg'][:120]}")
        elif t == "candidate_blocked":
            print(f"CAND   chặn[{e['reason']}] {e['label']!r} @({e['cx']},{e['cy']})")


def cmd_stats():
    s = get("/api/state")
    st = s["stats"]
    print(f"state={s['state']} ({s['state_seconds']}s)  running={s['running']}")
    print(f"capture {s['capture_fps']} fps · chụp {s.get('capture_grab_ms')}ms"
          + ("  ĐANG NGỦ" if s.get("capture_idle") else ""))
    print(f"ticks {st['ticks']} | taps {st['taps']} | swipes {st['swipes']}")
    print(f"bị chặn {st['blocked']} {st['block_reasons']}")
    print(f"ads thấy/đóng/trượt {st['ads_seen']}/{st['ads_closed']}/{st['ads_failed']}"
          f"  đóng ở bước {st['closed_by_step']}")
    print(f"stuck {st['stuck']} | watchdog {st['watchdog']}")


def cmd_doctor():
    d = get("/api/doctor")
    print(json.dumps(d, ensure_ascii=False, indent=2))


CMDS = {"rules": cmd_rules, "ocr": cmd_ocr, "events": cmd_events,
        "stats": cmd_stats, "doctor": cmd_doctor}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "rules"
    if name not in CMDS:
        print(__doc__)
        raise SystemExit(2)
    CMDS[name]()
