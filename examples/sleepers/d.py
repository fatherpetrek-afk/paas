import time
import os

print("sleeper-d start", os.getpid(), flush=True)
time.sleep(3)
print("sleeper-d done", flush=True)
