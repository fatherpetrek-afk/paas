from __future__ import annotations

import json
import os
from pathlib import Path

from shared.keys import user_key, worker_key

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PAAS_DATA_DIR", ROOT / "data"))
ARTIFACT_DIR = DATA_DIR / "artifacts"
SHARED_DIR = DATA_DIR / "shared"
DB_PATH = DATA_DIR / "paas.db"
SHARE_MAX_BYTES = 80 * 1024 * 1024

HOST = os.environ.get("PAAS_HOST", "0.0.0.0")
PORT = int(os.environ.get("PAAS_PORT", "8080"))
PUBLIC_URL = os.environ.get("PAAS_PUBLIC_URL", f"http://127.0.0.1:{PORT}")
TEAM_PASSWORD = user_key()
JOIN_TOKEN = worker_key()
SESSION_SECRET = os.environ.get("PAAS_SESSION_SECRET", "dev-session-change-me")
HEARTBEAT_TTL_SEC = 15
SESSION_TTL_SEC = 8 * 3600
SESSION_LOCK_SEC = 90
WORKER_CONSOLE_PORT = int(os.environ.get("PAAS_WORKER_CONSOLE_PORT", "9090"))


def _admin_from_file() -> tuple[str, str]:
    path = DATA_DIR / "admin.json"
    if not path.is_file():
        return "", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("username") or "").strip(), str(data.get("password") or "").strip()


_file_user, _file_pw = _admin_from_file()
ADMIN_USERNAME = (os.environ.get("PAAS_ADMIN_USERNAME") or _file_user or "").strip()
ADMIN_PASSWORD = (os.environ.get("PAAS_ADMIN_PASSWORD") or _file_pw or "").strip()
