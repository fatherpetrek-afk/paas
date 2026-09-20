from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from shared.authfmt import group_digits, normalize_password, normalize_username, valid_password, valid_username
from worker import identity
from worker.metrics import load_locks, save_locks

CONSOLE_DIR = Path(__file__).resolve().parent / "static"
PORT = int(os.environ.get("PAAS_WORKER_CONSOLE_PORT", "9090"))
LOCK_FILE = Path(os.environ.get("PAAS_LOCK_FILE", Path.cwd() / "data" / "worker-locks.json"))
SESSION_FILE = Path(os.environ.get("PAAS_WORKER_SESSION", Path.cwd() / "data" / "worker-session.json"))
WORKER_NAME = os.environ.get("PAAS_WORKER_NAME", "local-pc")
CONTROL_URL = os.environ.get("PAAS_CONTROL_URL", "http://127.0.0.1:8080").rstrip("/")

_sessions: set[str] = set()


def _login_error_code(raw: str) -> str:
    text = str(raw or "").strip()
    if text in {"platform_off", "label_taken", "timeout", "password_required", "already_logged_in", "unregistered", "bad_password", "bad_username", "bad_pw_format"}:
        return text
    if any(part in text for part in ("尚未激活", "还没激活", "還沒啟動", "未激活")):
        return "platform_off"
    if text in {"重名", "duplicate"}:
        return "label_taken"
    return text


def _control_login(username: str, password: str) -> tuple[int, dict]:
    url = f"{CONTROL_URL}/api/v1/auth/login"
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json={"role": "worker", "username": username, "password": password})
    except httpx.TransportError as exc:
        return 502, {"error": str(exc)}
    try:
        data = resp.json()
    except json.JSONDecodeError:
        data = {"error": resp.text}
    return resp.status_code, data if isinstance(data, dict) else {"data": data}


def _session() -> dict | None:
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _control(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    sess = _session()
    if not sess:
        return 503, {"error": "worker is not registered yet"}
    url = str(sess["control_url"]).rstrip("/") + path
    headers = {"X-Worker-Token": sess["worker_token"]}
    try:
        with httpx.Client(timeout=8.0) as client:
            kw: dict = {"headers": headers}
            if payload is not None:
                kw["json"] = payload
            resp = client.request(method, url, **kw)
    except httpx.TransportError as exc:
        return 502, {"error": str(exc)}
    try:
        data = resp.json()
    except json.JSONDecodeError:
        data = {"error": resp.text}
    return resp.status_code, data if isinstance(data, dict) else {"data": data}


def _cd_filename(header: str) -> str:
    text = header or ""
    star = "filename*="
    i = text.lower().find(star)
    if i >= 0:
        rest = text[i + len(star) :].split(";", 1)[0].strip()
        if "''" in rest:
            return unquote(rest.split("''", 1)[1])
        return unquote(rest.strip('"'))
    key = "filename="
    i = text.lower().find(key)
    if i < 0:
        return ""
    return text[i + len(key) :].split(";", 1)[0].strip().strip('"')


def _control_file(path: str) -> tuple[int, bytes, str, str]:
    sess = _session()
    if not sess:
        return 503, json.dumps({"error": "worker is not registered yet"}).encode("utf-8"), "application/json", ""
    url = str(sess["control_url"]).rstrip("/") + path
    headers = {"X-Worker-Token": sess["worker_token"]}
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(url, headers=headers)
    except httpx.TransportError as exc:
        return 502, json.dumps({"error": str(exc)}).encode("utf-8"), "application/json", ""
    return (
        resp.status_code,
        resp.content,
        resp.headers.get("content-type") or "application/octet-stream",
        _cd_filename(resp.headers.get("content-disposition") or ""),
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _raw(self, code: int, raw: bytes, content_type: str, filename: str = "") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        if filename:
            safe = filename.encode("ascii", "replace").decode("ascii")
            self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _html(self) -> None:
        path = CONSOLE_DIR / "console.html"
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self) -> bool:
        token = self.headers.get("X-Worker-Console", "")
        return token in _sessions

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._html()
            return
        if path == "/api/state":
            if not self._authed():
                self._json(401, {"error": "login required"})
                return
            locks = load_locks(LOCK_FILE)
            code, board = _control("GET", "/api/v1/workers/me/board")
            scode, share = _control("GET", "/api/v1/workers/me/share")
            st = identity.status()
            user = st.get("label") or ""
            payload = {
                "role": "worker",
                "name": group_digits(user) if valid_username(user) else (user or WORKER_NAME),
                "user": user,
                "is_platform": bool(st.get("is_platform")),
                "run_open": locks.run_open,
                "security_open": locks.security_open,
                "admin_open": locks.admin_open,
                "board": board if code == 200 else None,
                "board_error": None if code == 200 else board.get("error") or board.get("detail"),
                "share": share if scode == 200 else None,
            }
            self._json(200, payload)
            return
        if path.startswith("/api/share/files/"):
            if not self._authed():
                self._json(401, {"error": "login required"})
                return
            file_id = path.rsplit("/", 1)[-1]
            if not file_id:
                self._json(400, {"error": "id required"})
                return
            self._raw(*_control_file(f"/api/v1/workers/me/share/files/{file_id}"))
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/login":
            body = self._read_json()
            username = normalize_username(str(body.get("username") or ""))
            password = normalize_password(str(body.get("password") or ""))
            if not valid_username(username):
                self._json(400, {"error": "bad_username"})
                return
            if not valid_password(password):
                self._json(400, {"error": "bad_pw_format"})
                return
            code, auth = _control_login(username, password)
            if code != 200:
                err = auth.get("detail") or auth.get("error") or "unregistered"
                if isinstance(err, list):
                    err = "unregistered"
                self._json(401, {"error": _login_error_code(str(err))})
                return
            identity.set_credentials(username, password)
            result = identity.wait_result(10.0)
            if result.get("error"):
                self._json(409, {"error": _login_error_code(result["error"])})
                return
            if not result.get("joined"):
                self._json(503, {"error": "worker is not registered yet"})
                return
            token = secrets.token_hex(16)
            _sessions.add(token)
            self._json(200, {"token": token, "role": "worker", "is_platform": bool(result.get("is_platform")), "label": username})
            return
        if not self._authed():
            self._json(401, {"error": "login required"})
            return
        if path == "/api/logout-safe":
            identity.request_logout()
            sess = _session()
            if not sess:
                identity.clear()
                token = self.headers.get("X-Worker-Console", "")
                _sessions.discard(token)
                self._json(200, {"ok": True})
                return
            url = str(sess["control_url"]).rstrip("/") + "/api/v1/workers/me/logout"
            try:
                with httpx.Client(timeout=50.0) as client:
                    resp = client.post(url, headers={"X-Worker-Token": sess["worker_token"]}, json={})
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    data = {"error": resp.text}
                if resp.status_code >= 400:
                    self._json(resp.status_code, data if isinstance(data, dict) else {"error": str(data)})
                    return
            except httpx.TransportError as exc:
                self._json(502, {"error": str(exc)})
                return
            identity.clear()
            token = self.headers.get("X-Worker-Console", "")
            _sessions.discard(token)
            self._json(200, {"ok": True, "cleaned": True})
            return
        body = self._read_json()
        if path == "/api/locks":
            locks = load_locks(LOCK_FILE)
            which = body.get("toggle")
            if which == "run":
                locks = WorkerLocks(
                    run_open=not locks.run_open,
                    security_open=locks.security_open,
                    admin_open=locks.admin_open,
                )
            elif which == "security":
                locks = WorkerLocks(
                    run_open=locks.run_open,
                    security_open=not locks.security_open,
                    admin_open=locks.admin_open,
                )
            elif which == "admin":
                locks = WorkerLocks(
                    run_open=locks.run_open,
                    security_open=locks.security_open,
                    admin_open=not locks.admin_open,
                )
            else:
                self._json(400, {"error": "toggle run or security"})
                return
            save_locks(LOCK_FILE, locks)
            self._json(200, {"run_open": locks.run_open, "security_open": locks.security_open})
            return
        routes = {
            "/api/pause": ("POST", "/api/v1/workers/me/pause", body),
            "/api/anchor": ("POST", "/api/v1/workers/me/anchors", body),
            "/api/reorder": ("POST", "/api/v1/workers/me/reorder", body),
            "/api/block": ("POST", "/api/v1/workers/me/block", body),
            "/api/unblock": ("POST", "/api/v1/workers/me/unblock", body),
        }
        if path in routes:
            method, target, payload = routes[path]
            self._json(*_control(method, target, payload))
            return
        if path == "/api/anchor/release":
            aid = body.get("id")
            if not aid:
                self._json(400, {"error": "id required"})
                return
            self._json(*_control("POST", f"/api/v1/workers/me/anchors/{aid}/release", {}))
            return
        if path == "/api/queue/delete":
            jid = body.get("id")
            if not jid:
                self._json(400, {"error": "id required"})
                return
            self._json(*_control("DELETE", f"/api/v1/workers/me/queue/{jid}"))
            return
        if path == "/api/stop":
            jid = body.get("id")
            if not jid:
                self._json(400, {"error": "id required"})
                return
            self._json(*_control("POST", f"/api/v1/workers/me/jobs/{jid}/stop", {}))
            return
        if path == "/api/share/approve":
            user = str(body.get("username") or "").strip()
            if not user:
                self._json(400, {"error": "username required"})
                return
            self._json(*_control("POST", f"/api/v1/workers/me/share/grants/{user}/approve", {}))
            return
        if path == "/api/share/revoke":
            user = str(body.get("username") or "").strip()
            if not user:
                self._json(400, {"error": "username required"})
                return
            self._json(*_control("POST", f"/api/v1/workers/me/share/grants/{user}/revoke", {}))
            return
        if path == "/api/share/delete":
            fid = body.get("id")
            if not fid:
                self._json(400, {"error": "id required"})
                return
            self._json(*_control("DELETE", f"/api/v1/workers/me/share/files/{fid}"))
            return
        if path == "/api/share/cancel":
            uid = body.get("id")
            if not uid:
                self._json(400, {"error": "id required"})
                return
            self._json(*_control("POST", f"/api/v1/workers/me/share/uploads/{uid}/cancel", {}))
            return
        self._json(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        self._json(404, {"error": "not found"})


def start_console() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Worker console http://127.0.0.1:{PORT} (this PC only)", flush=True)
