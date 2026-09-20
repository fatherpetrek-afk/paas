import time
import os

print("sleeper-c start", os.getpid(), flush=True)
time.sleep(3)
print("sleeper-c done", flush=True)
