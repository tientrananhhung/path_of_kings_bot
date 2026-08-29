"""Trả iPhone về Home Screen bình thường (thoát edit mode / Spotlight / app)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import Quartz
from common import activate
from state import snapshot
from poc1d_live_test import cg_click, go_home

HID = Quartz.kCGHIDEventTap
DONE = ("xong", "done")
SPOTLIGHT = ("gợi ý của siri", "tìm kiếm gần đây", "siri suggestions", "recent searches")


def texts_of(t):
    return [x[0].strip().lower() for x in t]


for attempt in range(1, 5):
    win, texts, paused, _ = snapshot()
    low = texts_of(texts)
    activate(win["pid"]); time.sleep(0.6)

    hit_done = [t for t in texts if t[0].strip().lower() in DONE]
    in_spotlight = any(s in " | ".join(low) for s in SPOTLIGHT)

    if hit_done:
        txt, _, cx, cy = hit_done[0]
        print(f"[{attempt}] edit mode -> tap '{txt}' ({cx},{cy})")
        cg_click(win["x"] + cx, win["y"] + cy, HID)
    elif in_spotlight:
        print(f"[{attempt}] đang ở Spotlight -> gesture Home")
        go_home(win, HID)
    else:
        print(f"[{attempt}] OK, đã ở Home Screen bình thường.")
        print("    OCR:", [t[0] for t in texts][:10])
        break
    time.sleep(1.5)
else:
    print("Không tự trả về được sau 4 lần thử.")
