#!/usr/bin/env python
"""Tinh chỉnh tham số swipe cho MỘT màn quyết định bất kỳ.

Vấn đề thật đã gặp: swipe "ăn" (card dịch) nhưng KHÔNG COMMIT (animation trả
về). Trên màn PVP RAID của Path of Kings: 260ms và 400ms không commit, 600ms có.
Không có cách nào đoán được — phải đo.

Tiêu chí commit: sau swipe, chữ mốc (--marker) biến mất khỏi màn hình.

Ví dụ:
  ./.venv/bin/python poc/tune_swipe.py --marker "swipe to decide" \
      --from-x 0.50 --y 0.78 --to-x 0.11 0.05 --ms 260 400 600

  # màn NEW GEAR (thẻ ở giữa, y=0.607)
  ./.venv/bin/python poc/tune_swipe.py --marker "new gear found" \
      --from-x 0.50 --y 0.607 --to-x 0.05 --ms 400 600 800
"""
import argparse
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8765"


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def screen(marker: str) -> dict:
    d = post("/api/probe", {"vlm": False})
    texts = [t["text"].lower().strip() for t in d["texts"]]
    joined = " | ".join(texts)
    return {"marker": marker.lower() in joined,
            "n": len(texts),
            "head": " | ".join(texts[:4])[:70]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--marker", required=True,
                    help="chữ nhận biết màn (mất đi = đã commit)")
    ap.add_argument("--from-x", type=float, default=0.50)
    ap.add_argument("--y", type=float, required=True)
    ap.add_argument("--to-x", type=float, nargs="+", default=[0.05])
    ap.add_argument("--ms", type=int, nargs="+", default=[260, 400, 600])
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--hold-end", type=int, default=140)
    ap.add_argument("--settle", type=float, default=2.2,
                    help="chờ bao lâu rồi mới kiểm tra")
    args = ap.parse_args()

    variants = [(tx, ms) for ms in args.ms for tx in args.to_x]
    print(f"mốc nhận biết: {args.marker!r}   "
          f"from=({args.from_x}, {args.y})  {len(variants)} biến thể\n")
    hdr = f"{'to_x':>6}{'ms':>7}{'trước':>9}{'sau':>7}   COMMIT?"
    print(hdr)
    print("-" * (len(hdr) + 4))

    winners = []
    for tx, ms in variants:
        before = screen(args.marker)
        if not before["marker"]:
            print(f"{tx:>6}{ms:>7}   -- màn hình không còn mốc, dừng "
                  f"({before['head']})")
            break
        post("/api/manual/swipe", {
            "x0": args.from_x, "y0": args.y, "x1": tx, "y1": args.y,
            "duration_ms": ms, "steps": args.steps,
            "hold_end_ms": args.hold_end, "confirm": True})
        time.sleep(args.settle)
        after = screen(args.marker)
        ok = not after["marker"]
        if ok:
            winners.append((tx, ms))
        print(f"{tx:>6}{ms:>7}{str(before['marker']):>9}{str(after['marker']):>7}"
              f"   {'CÓ' if ok else 'không'}")
        if ok:
            print("      -> đã commit; các biến thể sau sẽ chạy trên màn khác.")
        time.sleep(2.0)

    print()
    if winners:
        tx, ms = winners[0]
        print(f"DÙNG: to = [{tx}, {args.y}]   duration_ms = {ms}   "
              f"steps = {args.steps}   hold_end_ms = {args.hold_end}")
    else:
        print("Không biến thể nào commit. Thử: tăng --ms (800, 1200), "
              "kéo xa hơn (--to-x 0.02), hoặc --hold-end 300.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
