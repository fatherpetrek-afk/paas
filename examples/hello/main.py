from pathlib import Path

out = Path("output")
out.mkdir(exist_ok=True)
message = "hello from worker"
print(message)
(out / "result.txt").write_text(message + "\n", encoding="utf-8")
