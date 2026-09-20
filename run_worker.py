import ctypes
import sys

from worker.agent import main

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW("Team PaaS Worker")
        except Exception:
            pass
    main()
