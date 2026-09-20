import queue
import sys
import threading
import time
from pathlib import Path

print("canvas demo start", flush=True)

out = Path("output") / "_display"
out.mkdir(parents=True, exist_ok=True)


def draw(title: str) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8)
    ax.set_aspect("equal")
    ax.set_facecolor("#102030")
    ax.add_patch(Rectangle((0.4, 0.4), 9.2, 7.2, fill=False, edgecolor="#e8e8e8", lw=2))
    ax.add_patch(Circle((3.2, 4.2), 1.5, color="#e07a7a"))
    ax.add_patch(Circle((6.8, 4.2), 1.5, color="#7aa2f7"))
    ax.text(5, 1.4, title, color="#e8e8e8", ha="center", fontsize=12)
    ax.axis("off")
    plt.show()
    plt.close("all")


try:
    draw("canvas")
    print("canvas -> Display", flush=True)
except Exception as exc:
    print("no matplotlib:", exc, flush=True)

try:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 200), (16, 32, 48))
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 140, 160), fill=(224, 122, 122))
    d.ellipse((180, 40, 280, 160), fill=(122, 162, 247))
    img.show()
    print("pil -> Display", flush=True)
except Exception as exc:
    print("no pil:", exc, flush=True)

inbox = queue.Queue()


def _read() -> None:
    for line in sys.stdin:
        inbox.put(line.rstrip("\n"))


threading.Thread(target=_read, daemon=True).start()
print("Send a label, or Stop", flush=True)

n = 0
while True:
    n += 1
    try:
        got = inbox.get_nowait()
        print(f"got: {got}", flush=True)
        try:
            draw(got or "canvas")
        except Exception:
            pass
    except queue.Empty:
        pass
    if n % 5 == 1:
        print(f"tick {n}", flush=True)
    time.sleep(1)
