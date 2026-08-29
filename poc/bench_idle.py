"""Kiểm chứng throttle: đo frame_id tăng bao nhiêu/giây khi có và không có người xem."""
import asyncio, json, subprocess, time
import urllib.request
import websockets

BASE = "http://127.0.0.1:8765"


def state():
    with urllib.request.urlopen(BASE + "/api/state", timeout=5) as r:
        return json.loads(r.read())


def cpu(pid):
    out = subprocess.run(["top", "-l", "2", "-pid", str(pid), "-stats", "cpu"],
                         capture_output=True, text=True).stdout
    return out.strip().splitlines()[-1].strip()


def rate(secs=5.0):
    a = state()
    time.sleep(secs)
    b = state()
    return (b["frame_id"] - a["frame_id"]) / secs, b


async def hold(secs):
    async with websockets.connect(BASE.replace("http", "ws") + "/ws", max_size=8 << 20) as ws:
        t = time.time()
        while time.time() - t < secs:
            await ws.recv()


async def main():
    pid = int(subprocess.run(["pgrep", "-f", "m pok ui"], capture_output=True,
                             text=True).stdout.split()[0])
    time.sleep(3)
    r, s = rate()
    print(f"KHÔNG ai xem : {r:>5.1f} frame/s thật · capture_fps báo "
          f"{s['capture_fps']} · idle={s.get('capture_idle')} · CPU {cpu(pid)}%")

    task = asyncio.create_task(hold(18))
    await asyncio.sleep(3)
    r, s = await asyncio.get_running_loop().run_in_executor(None, rate)
    print(f"1 client WS  : {r:>5.1f} frame/s thật · capture_fps báo "
          f"{s['capture_fps']} · idle={s.get('capture_idle')} · "
          f"chụp {s.get('capture_grab_ms')}ms · CPU {cpu(pid)}%")
    await task
    await asyncio.sleep(4)
    r, s = rate()
    print(f"client đã thoát: {r:>5.1f} frame/s thật · idle={s.get('capture_idle')} "
          f"· CPU {cpu(pid)}%")

asyncio.run(main())
