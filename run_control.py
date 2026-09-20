import ctypes
import sys

import uvicorn

from control.app import app
from control.config import HOST, PORT

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW("Team PaaS Control")
        except Exception:
            pass
    uvicorn.run(app, host=HOST, port=PORT)
