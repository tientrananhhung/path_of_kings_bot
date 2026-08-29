"""Chạy bot và ĐO tỉ lệ commit của luật PVP RAID trên nhiều lần gặp thật.

Không đoán bằng mắt: mỗi lần bot swipe, kiểm tra sau 2.5s màn hình còn ở trạng
thái quyết định hay không.
"""
import json, sys, time, urllib.request

BASE = "http://127.0.0.1:8765"
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 90


def post(p, b=None):
    req = urllib.request.Request(BASE + p, data=json.dumps(b or {}).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def get(p):
    with urllib.request.urlopen(BASE + p, timeout=30) as r:
        return json.loads(r.read())


def screen():
    d = post("/api/probe", {"vlm": False})
    t = {x["text"].lower().strip() for x in d["texts"]}
    return {"decide": any("swipe to decide" in s for s in t),
            "raid": any("raid" in s for s in t),
            "section": next((s for s in t if s.startswith("section")), "?")}


post("/api/control/stop")
time.sleep(0.5)
post("/api/control/start")
print(f"bot chạy {SECS:.0f}s — đang theo dõi luật PVP RAID…\n")
sess = None
seen = 0
committed = 0
last_action_id = 0
t0 = time.time()

while time.time() - t0 < SECS:
    st = get("/api/state")
    sess = sess or True
    time.sleep(1.0)
    # đọc event mới
    d = get("/api/sessions")
    name = d["items"][0]["name"] if d["items"] else None
    if not name:
        continue
    ev = get(f"/api/sessions/{name}/events?limit=400")["items"]
    acts = [e for e in ev if e["type"] == "action"
            and e.get("source") == "rule" and not e.get("blocked")
            and e["id"] > last_action_id]
    for a in acts:
        last_action_id = a["id"]
        seen += 1
        before_sec = None
        time.sleep(2.5)
        s = screen()
        ok = not s["decide"]
        committed += ok
        print(f"  #{seen} swipe '{a['label']}' -> "
              f"{'COMMIT ✓' if ok else 'KHÔNG commit ✗'}  (section={s['section']})")

post("/api/control/stop")
print(f"\nKẾT QUẢ: {committed}/{seen} lần commit"
      + (f"  = {committed/seen*100:.0f}%" if seen else "  (chưa gặp màn PVP RAID nào)"))
st = get("/api/state")
print("stats:", json.dumps(st["stats"], ensure_ascii=False)[:250])
