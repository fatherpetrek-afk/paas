import queue
import sys
import threading
import time
from pathlib import Path

print("terminal ok", flush=True)

out = Path("output") / "_display"
out.mkdir(parents=True, exist_ok=True)

try:
    import matplotlib.pyplot as plt

    plt.figure()
    plt.plot([0, 1, 2, 3, 4], [0, 1, 0, 1, 0], marker="o")
    plt.title("display test")
    plt.show()
    print("plot -> Display", flush=True)
except Exception as exc:
    (out / "fallback.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08"
        b"\x08\x02\x00\x00\x00K\xd2\x9c\n\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
        b"\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    print("no matplotlib:", exc, flush=True)

inbox = queue.Queue()


def _read() -> None:
    for line in sys.stdin:
        inbox.put(line.rstrip("\n"))


threading.Thread(target=_read, daemon=True).start()
print("Send text here, or Stop", flush=True)

n = 0
while True:
    n += 1
    try:
        got = inbox.get_nowait()
        print(f"got: {got}", flush=True)
        try:
            import matplotlib.pyplot as plt

            plt.figure()
            plt.bar(["a", "b", "c"], [1, 3, 2])
            plt.title(got or "stdin")
            plt.show()
        except Exception:
            pass
    except queue.Empty:
        pass
    if n % 5 == 1:
        print(f"tick {n}", flush=True)
    time.sleep(1)
