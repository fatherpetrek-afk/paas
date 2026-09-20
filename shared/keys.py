from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PAAS_DATA_DIR", ROOT / "data"))
KEYS_PATH = DATA_DIR / "keys.json"

_DEFAULT_USERS = {
    "alice": "alice-dev",
    "bob": "bob-dev",
    "carol": "carol-dev",
    "dave": "dave-dev",
}


def _read() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KEYS_PATH.exists():
        return json.loads(KEYS_PATH.read_text(encoding="utf-8"))
    data = {
        "users": dict(_DEFAULT_USERS),
        "user_key": _DEFAULT_USERS["alice"],
        "worker_key": os.environ.get("PAAS_WORKER_KEY") or os.environ.get("PAAS_JOIN_TOKEN") or "dev-join",
    }
    _write(data)
    return data


def _write(data: dict) -> None:
    KEYS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_keys() -> dict[str, str]:
    data = _read()
    users = load_users()
    fallback = next(iter(users.values()), "dev")
    return {
        "user_key": str(data.get("user_key") or fallback),
        "worker_key": str(data.get("worker_key") or "dev-join"),
    }


def load_users() -> dict[str, str]:
    data = _read()
    users = data.get("users")
    out: dict[str, str] = {}
    if isinstance(users, dict) and users:
        out = {str(k): str(v) for k, v in users.items()}
    elif data.get("user_key"):
        out = {"dev": str(data["user_key"])}
    changed = False
    if not out:
        out = dict(_DEFAULT_USERS)
        changed = True
    for name, key in _DEFAULT_USERS.items():
        if name not in out:
            out[name] = key
            changed = True
    if data.get("users") != out:
        data["users"] = out
        changed = True
    if changed:
        _write(data)
    return out


def user_by_key(key: str) -> str | None:
    for name, stored in load_users().items():
        if stored == key:
            return name
    return None


def user_key() -> str:
    return load_keys()["user_key"]


def worker_key() -> str:
    return load_keys()["worker_key"]


def new_session_secret() -> str:
    return os.environ.get("PAAS_SESSION_SECRET") or secrets.token_hex(16)
