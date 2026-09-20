import math
import queue
import struct
import sys
import threading
import time
from pathlib import Path

W, H = 480, 280
out = Path("output") / "_display"
out.mkdir(parents=True, exist_ok=True)

mode = "wave"
freq = 2.0
amp = 70.0
inbox = queue.Queue()


def write_bmp(path: Path, pixels: list[tuple[int, int, int]]) -> None:
    row = (W * 3 + 3) & ~3
    raw = bytearray(row * H)
    for y in range(H):
        for x in range(W):
            r, g, b = pixels[y * W + x]
            o = (H - 1 - y) * row + x * 3
            raw[o : o + 3] = bytes((b, g, r))
    header = struct.pack(
        "<2sIHHIIiiHHIIiiII",
        b"BM",
        14 + 40 + len(raw),
        0,
        0,
        54,
        40,
        W,
        H,
        1,
        24,
        0,
        len(raw),
        2835,
        2835,
        0,
        0,
    )
    path.write_bytes(header + raw)


def pix(t: float) -> list[tuple[int, int, int]]:
    px = [(16, 24, 40)] * (W * H)
    cx, cy = W // 2, H // 2
    for x in range(W):
        px[(H - 12) * W + x] = (40, 52, 72)
        px[12 * W + x] = (40, 52, 72)
    for y in range(H):
        px[y * W + 12] = (40, 52, 72)
        px[y * W + (W - 13)] = (40, 52, 72)
    if mode == "bars":
        n = 16
        for i in range(n):
            h = int(40 + amp * (0.4 + 0.6 * abs(math.sin(t * 0.8 + i * 0.4))))
            x0 = 30 + i * ((W - 60) // n)
            for y in range(H - 20 - h, H - 20):
                for x in range(x0, x0 + 18):
                    if 0 <= x < W and 0 <= y < H:
                        px[y * W + x] = (70 + i * 8, 140, 220 - i * 6)
    elif mode == "spiral":
        for i in range(900):
            a = i * 0.12 + t
            r = 8 + i * 0.12
            x = int(cx + r * math.cos(a))
            y = int(cy + r * math.sin(a) * 0.72)
            if 0 <= x < W and 0 <= y < H:
                px[y * W + x] = (255, 80 + (i % 120), 90)
    else:
        prev = None
        for x in range(20, W - 20):
            y = int(cy - amp * math.sin((x / 40.0) * freq + t))
            y = max(16, min(H - 16, y))
            if prev is not None:
                x0, y0 = prev
                steps = max(abs(x - x0), abs(y - y0), 1)
                for s in range(steps + 1):
                    xx = x0 + (x - x0) * s // steps
                    yy = y0 + (y - y0) * s // steps
                    for dy in range(-1, 2):
                        for dx in range(-1, 2):
                            px[(yy + dy) * W + (xx + dx)] = (90, 200, 255)
            prev = (x, y)
        r = 18
        x = int(cx + 90 * math.cos(t * 0.7))
        y = int(cy + 40 * math.sin(t * 0.7))
        for yy in range(y - r, y + r):
            for xx in range(x - r, x + r):
                if 0 <= xx < W and 0 <= yy < H and (xx - x) ** 2 + (yy - y) ** 2 <= r * r:
                    px[yy * W + xx] = (255, 120, 90)
    return px


def draw(t: float, note: str) -> None:
    write_bmp(out / "frame.bmp", pix(t))
    print(f"frame {mode} freq={freq:.2f} amp={amp:.1f} {note}", flush=True)


def _read() -> None:
    while True:
        line = sys.stdin.readline()
        if line == "":
            return
        inbox.put(line.rstrip("\n"))


threading.Thread(target=_read, daemon=True).start()
print("draw_py ready. stdin: wave | bars | spiral | freq=2 | amp=70", flush=True)
t0 = time.time()
n = 0
while True:
    n += 1
    try:
        got = inbox.get_nowait()
    except queue.Empty:
        got = ""
    if got:
        low = got.lower()
        if low in {"wave", "bars", "spiral"}:
            mode = low
        elif "=" in got:
            key, val = got.split("=", 1)
            try:
                num = float(val.strip())
            except ValueError:
                num = None
            if num is not None and key.strip().lower() == "freq":
                freq = max(0.2, min(12.0, num))
            elif num is not None and key.strip().lower() == "amp":
                amp = max(8.0, min(120.0, num))
        print(f"got: {got}", flush=True)
        draw(time.time() - t0, "stdin")
    elif n == 1 or n % 4 == 0:
        draw(time.time() - t0, "tick")
    time.sleep(0.25)
