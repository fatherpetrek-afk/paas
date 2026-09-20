import time
import os

print("sleeper-b start", os.getpid(), flush=True)
time.sleep(3)
print("sleeper-b done", flush=True)
