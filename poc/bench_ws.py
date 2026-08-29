"""Đo nhịp stream WS: frame/s, state/s, băng thông, và kiểm tra cache encode."""
import asyncio, json, sys, time
import websockets

async def one(name, secs=8):
    f = e = st = 0
    sizes = []
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=8 << 20) as ws:
        t0 = time.time()
        end = t0 + secs
        while time.time() < end:
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=max(0.05, end - time.time()))
            except asyncio.TimeoutError:
                break
            if isinstance(m, bytes):
                sizes.append(len(m) - 12); f += 1
            else:
                d = json.loads(m)
                st += d["kind"] == "state"
                e += d["kind"] == "event"
    dt = time.time() - t0
    avg = sum(sizes) / max(1, len(sizes))
    print(f"  {name:<10} {f/dt:>5.1f} frame/s  {st/dt:>4.1f} state/s  "
          f"{avg/1024:>5.1f} KB/frame  {avg*8*(f/dt)/1024/1024:>5.2f} Mbps")

async def main():
    print("1 client:")
    await one("solo")
    print("3 client cùng lúc (kiểm tra cache encode):")
    await asyncio.gather(one("A"), one("B"), one("C"))

asyncio.run(main())
