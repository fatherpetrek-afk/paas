from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_label: str | None = None
_password: str | None = None
_joined_label: str | None = None
_error: str | None = None
_joined = False
_platform = False
_logout = False


def set_credentials(username: str, password: str) -> None:
    global _label, _password, _joined, _joined_label, _error, _logout
    with _lock:
        _label = username
        _password = password
        _joined = False
        _joined_label = None
        _error = None
        _logout = False


def get_password() -> str | None:
    with _lock:
        return _password


def set_label(label: str) -> None:
    global _label, _joined, _error
    with _lock:
        if _joined_label and _joined_label != label:
            _joined = False
        _label = label
        _error = None


def get_label() -> str | None:
    with _lock:
        return _label


def joined_label() -> str | None:
    with _lock:
        return _joined_label


def mark_joined(is_platform: bool) -> None:
    global _joined, _joined_label, _error, _platform
    with _lock:
        _joined = True
        _joined_label = _label
        _platform = bool(is_platform)
        _error = None


def fail(message: str) -> None:
    global _error, _label, _joined, _joined_label, _platform, _password
    with _lock:
        _error = message
        _label = None
        _password = None
        _joined = False
        _joined_label = None
        _platform = False


def request_logout() -> None:
    global _logout
    with _lock:
        _logout = True


def logout_requested() -> bool:
    with _lock:
        return _logout


def clear() -> None:
    global _label, _joined_label, _error, _joined, _platform, _logout, _password
    with _lock:
        _label = None
        _password = None
        _joined_label = None
        _error = None
        _joined = False
        _platform = False
        _logout = False


def status() -> dict:
    with _lock:
        return {
            "label": _label,
            "joined": _joined,
            "error": _error,
            "is_platform": _platform,
        }


def wait_result(timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = status()
        if current["error"] or current["joined"]:
            return current
        time.sleep(0.12)
    current = status()
    if current["error"] or current["joined"]:
        return current
    return {**current, "error": current["error"] or "timeout"}
