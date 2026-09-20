from __future__ import annotations

import json
import re
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from shared.authfmt import (
    group_digits,
    hash_password,
    normalize_password,
    normalize_username,
    valid_password,
    valid_username,
    verify_password,
)
from shared.protocol import (
    GpuInfo,
    HeartbeatIn,
    JobManifest,
    ResourceLimits,
    WorkerLocks,
    WorkerRegisterIn,
    compatible,
)

from control.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    ARTIFACT_DIR,
    DB_PATH,
    HEARTBEAT_TTL_SEC,
    SESSION_LOCK_SEC,
    SESSION_TTL_SEC,
    SHARED_DIR,
    SHARE_MAX_BYTES,
)


def _now() -> float:
    return time.time()


class Store:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _ensure_col(self, table: str, name: str, decl: str) -> None:
        cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in cols:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workers (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              token TEXT NOT NULL,
              os TEXT NOT NULL,
              arch TEXT NOT NULL,
              runtimes TEXT NOT NULL,
              has_docker INTEGER NOT NULL,
              cpu_cores INTEGER NOT NULL,
              memory_mb INTEGER NOT NULL,
              gpus TEXT NOT NULL,
              run_open INTEGER NOT NULL,
              security_open INTEGER NOT NULL,
              cpu_percent REAL DEFAULT 0,
              memory_percent REAL DEFAULT 0,
              gpu_percent TEXT DEFAULT '[]',
              bytes_sent INTEGER DEFAULT 0,
              bytes_recv INTEGER DEFAULT 0,
              current_job_id TEXT,
              last_seen REAL NOT NULL,
              created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              manifest TEXT NOT NULL,
              artifact_path TEXT NOT NULL,
              worker_id TEXT,
              state TEXT NOT NULL,
              requested_limits TEXT,
              exit_code INTEGER,
              error TEXT,
              result_path TEXT,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              ts REAL NOT NULL,
              stream TEXT NOT NULL,
              line TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metrics (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              worker_id TEXT NOT NULL,
              ts REAL NOT NULL,
              cpu_percent REAL NOT NULL,
              memory_percent REAL NOT NULL,
              gpu_percent TEXT NOT NULL,
              bytes_sent INTEGER NOT NULL,
              bytes_recv INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS commands (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              worker_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at REAL NOT NULL,
              acked INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_name TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue_anchors (
              id TEXT PRIMARY KEY,
              worker_id TEXT NOT NULL,
              queue_order REAL NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS worker_blocks (
              worker_id TEXT NOT NULL,
              user_name TEXT NOT NULL,
              created_at REAL NOT NULL,
              PRIMARY KEY (worker_id, user_name)
            );
            CREATE TABLE IF NOT EXISTS accounts (
              username TEXT PRIMARY KEY,
              password_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approval_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL,
              action TEXT NOT NULL,
              actor TEXT,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS share_files (
              id TEXT PRIMARY KEY,
              worker_id TEXT NOT NULL,
              owner TEXT NOT NULL,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              size INTEGER NOT NULL,
              stored_path TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS share_grants (
              worker_id TEXT NOT NULL,
              user_name TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at REAL NOT NULL,
              decided_at REAL,
              PRIMARY KEY (worker_id, user_name)
            );
            CREATE TABLE IF NOT EXISTS share_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              worker_id TEXT NOT NULL,
              owner TEXT NOT NULL,
              actor TEXT NOT NULL,
              actor_role TEXT NOT NULL,
              action TEXT NOT NULL,
              kind TEXT,
              file_name TEXT,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS share_drops (
              id TEXT PRIMARY KEY,
              worker_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              owner TEXT NOT NULL,
              local_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS share_uploads (
              id TEXT PRIMARY KEY,
              worker_id TEXT NOT NULL,
              owner TEXT NOT NULL,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              actor TEXT NOT NULL,
              actor_role TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS job_stdin (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              line TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            """
        )
        self._ensure_col("sessions", "role", "TEXT NOT NULL DEFAULT 'user'")
        self._ensure_col("sessions", "last_seen", "REAL NOT NULL DEFAULT 0")
        self._ensure_col("jobs", "cancel_requested", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_col("jobs", "user_name", "TEXT NOT NULL DEFAULT 'dev'")
        self._ensure_col("jobs", "queue_order", "REAL")
        self._ensure_col("workers", "pause_all", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_col("workers", "job_cpu_percent", "REAL DEFAULT 0")
        self._ensure_col("workers", "job_proc_count", "INTEGER DEFAULT 0")
        self._ensure_col("workers", "admin_open", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_col("workers", "environments", "TEXT DEFAULT '[]'")
        self._ensure_col("workers", "label", "TEXT DEFAULT ''")
        self._ensure_col("workers", "is_platform", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_col("jobs", "env_id", "TEXT")
        self._ensure_col("jobs", "ui_kind", "TEXT NOT NULL DEFAULT ''")
        self._ensure_col("jobs", "ui_port", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_col("share_files", "synced", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_col("share_files", "local_name", "TEXT")
        self._ensure_col("accounts", "kind", "TEXT NOT NULL DEFAULT 'user'")
        self._conn.execute("UPDATE jobs SET queue_order = created_at WHERE queue_order IS NULL")
        claimed = {
            r[0]
            for r in self._conn.execute(
                "SELECT current_job_id FROM workers WHERE current_job_id IS NOT NULL"
            ).fetchall()
            if r[0]
        }
        for row in self._conn.execute("SELECT id FROM jobs WHERE state='assigned'").fetchall():
            nxt = "running" if row["id"] in claimed else "queued"
            self._conn.execute("UPDATE jobs SET state=? WHERE id=?", (nxt, row["id"]))
        self._conn.commit()

    def _row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _online_unlocked(self, last_seen: float) -> bool:
        return (_now() - last_seen) <= HEARTBEAT_TTL_SEC

    def _platform_online_unlocked(self) -> bool:
        rows = self._conn.execute(
            "SELECT last_seen FROM workers WHERE is_platform=1"
        ).fetchall()
        return any(self._online_unlocked(r["last_seen"]) for r in rows)

    def _park_worker_unlocked(self, worker_id: str) -> None:
        self._conn.execute(
            "UPDATE workers SET token=?, last_seen=0 WHERE id=?",
            (secrets.token_hex(16), worker_id),
        )

    def register_worker(self, body: WorkerRegisterIn) -> tuple[str, str, bool]:
        user = normalize_username(body.username or "")
        pw = normalize_password(body.password or "")
        auth = self.authenticate(user, pw, kind="worker")
        if auth == "bad_password":
            raise ValueError("bad_password")
        if auth != "ok":
            raise ValueError("unregistered")
        ts = _now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM workers WHERE id=?", (user,)).fetchone()
            if row and self._online_unlocked(row["last_seen"]):
                raise ValueError("duplicate")
            token = str(uuid.uuid4())
            fields = (
                user,
                token,
                body.os,
                body.arch,
                json.dumps(body.runtimes),
                int(body.has_docker),
                body.cpu_cores,
                body.memory_mb,
                json.dumps([g.model_dump() for g in body.gpus]),
                int(body.locks.run_open),
                int(body.locks.security_open),
                int(body.locks.admin_open),
                json.dumps([e.model_dump() for e in body.environments]),
                user,
                1,
                ts,
            )
            if row:
                self._conn.execute(
                    """
                    UPDATE workers SET
                      name=?, token=?, os=?, arch=?, runtimes=?, has_docker=?,
                      cpu_cores=?, memory_mb=?, gpus=?, run_open=?, security_open=?,
                      admin_open=?, environments=?, label=?, is_platform=?, last_seen=?
                    WHERE id=?
                    """,
                    (*fields, user),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO workers(
                      id, name, token, os, arch, runtimes, has_docker, cpu_cores, memory_mb,
                      gpus, run_open, security_open, admin_open, environments, label, is_platform,
                      last_seen, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (user, *fields, ts),
                )
            self._conn.commit()
        return user, token, True

    def reset_worker_passwords(self) -> None:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM workers").fetchall()
            for row in rows:
                self._park_worker_unlocked(row["id"])
            self._conn.commit()

    def release_worker(self, worker_id: str) -> None:
        with self._lock:
            self._park_worker_unlocked(worker_id)
            self._conn.commit()

    def apply_account(self, username: str, password: str, kind: str = "user") -> str:
        kind = kind if kind in {"user", "worker"} else "user"
        user = normalize_username(username)
        pw = normalize_password(password)
        if not valid_username(user):
            return "bad_username"
        if not valid_password(pw):
            return "bad_password"
        if user == ADMIN_USERNAME:
            return "taken"
        with self._lock:
            exists = self._conn.execute(
                "SELECT username FROM accounts WHERE username=?", (user,)
            ).fetchone()
            if exists:
                return "taken"
            ts = _now()
            self._conn.execute(
                "INSERT INTO accounts(username, password_hash, status, created_at, kind) VALUES (?,?,?,?,?)",
                (user, hash_password(pw), "pending", ts, kind if kind in {"user", "worker"} else "user"),
            )
            self._add_event_unlocked(user, "applied", None, ts)
            self._conn.commit()
        return "ok"

    def authenticate(self, username: str, password: str, kind: str = "user") -> str:
        user = normalize_username(username)
        pw = normalize_password(password)
        if user == ADMIN_USERNAME:
            return "unregistered"
        if not valid_username(user) or not valid_password(pw):
            return "unregistered"
        with self._lock:
            row = self._conn.execute(
                "SELECT password_hash, status, kind FROM accounts WHERE username=?", (user,)
            ).fetchone()
        if row is None or row["status"] != "approved":
            return "unregistered"
        acct_kind = (row["kind"] if "kind" in row.keys() else None) or "user"
        want = kind if kind in {"user", "worker"} else "user"
        if acct_kind != want:
            return "unregistered"
        if not verify_password(pw, row["password_hash"]):
            return "bad_password"
        return "ok"

    def authenticate_admin(self, username: str, password: str) -> str:
        user = normalize_username(username)
        pw = normalize_password(password)
        if user != ADMIN_USERNAME:
            return "unregistered"
        if pw != ADMIN_PASSWORD:
            return "bad_password"
        return "ok"

    def platform_online(self) -> bool:
        with self._lock:
            return self._platform_online_unlocked()

    def _add_event_unlocked(self, username: str, action: str, actor: str | None, ts: float | None = None) -> None:
        self._conn.execute(
            "INSERT INTO approval_events(username, action, actor, created_at) VALUES (?,?,?,?)",
            (username, action, actor, ts if ts is not None else _now()),
        )

    def pending_accounts(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT username, created_at FROM accounts WHERE status='pending' ORDER BY created_at"
            ).fetchall()
        return [{"username": r["username"], "created_at": r["created_at"]} for r in rows]

    def list_accounts(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        ts = _now()
        with self._lock:
            rows = self._conn.execute(
                "SELECT username, status, created_at, kind FROM accounts ORDER BY created_at"
            ).fetchall()
            sessions = self._conn.execute(
                "SELECT user_name, last_seen FROM sessions WHERE role='user'"
            ).fetchall()
            worker_rows = self._conn.execute("SELECT id, last_seen FROM workers").fetchall()
            counts = self._conn.execute(
                "SELECT user_name, state, COUNT(*) AS n FROM jobs GROUP BY user_name, state"
            ).fetchall()
            block_n = self._conn.execute(
                "SELECT user_name, COUNT(*) AS n FROM worker_blocks GROUP BY user_name"
            ).fetchall()
        online = {
            r["user_name"]
            for r in sessions
            if r["last_seen"] and (ts - r["last_seen"]) <= SESSION_LOCK_SEC
        }
        workers_online = {r["id"] for r in worker_rows if self._online_unlocked(r["last_seen"])}
        by_user: dict[str, dict[str, int]] = {}
        for r in counts:
            by_user.setdefault(r["user_name"], {})[r["state"]] = int(r["n"])
        blocked_n = {r["user_name"]: int(r["n"]) for r in block_n}
        out = []
        for r in rows:
            st = by_user.get(r["username"], {})
            acct_kind = (r["kind"] if "kind" in r.keys() else None) or "user"
            if kind and acct_kind != kind:
                continue
            live = r["username"] in (workers_online if acct_kind == "worker" else online)
            out.append(
                {
                    "username": r["username"],
                    "kind": acct_kind,
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "online": live and r["status"] == "approved",
                    "blocked_count": blocked_n.get(r["username"], 0),
                    "jobs": {
                        "queued": st.get("queued", 0),
                        "running": st.get("running", 0),
                        "succeeded": st.get("succeeded", 0),
                        "failed": st.get("failed", 0),
                        "cancelled": st.get("cancelled", 0),
                    },
                }
            )
        return out

    def approval_history(self, limit: int = 80, username: str | None = None) -> list[dict[str, Any]]:
        user = normalize_username(username) if username else None
        with self._lock:
            if user:
                rows = self._conn.execute(
                    """
                    SELECT username, action, actor, created_at
                    FROM approval_events
                    WHERE username=?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (user, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT username, action, actor, created_at
                    FROM approval_events
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def account_detail(self, username: str) -> dict[str, Any] | None:
        user = normalize_username(username)
        accounts = {a["username"]: a for a in self.list_accounts()}
        acc = accounts.get(user)
        if acc is None:
            return None
        return {
            "account": acc,
            "jobs": self.list_jobs(limit=200, user_name=user),
            "history": self.approval_history(username=user),
            "blocked_on": self.blocks_for_user(user),
        }

    def blocks_for_user(self, username: str) -> list[dict[str, Any]]:
        user = normalize_username(username)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT b.worker_id, b.user_name, b.created_at, w.label, w.name
                FROM worker_blocks b
                LEFT JOIN workers w ON w.id = b.worker_id
                WHERE b.user_name=?
                ORDER BY b.created_at
                """,
                (user,),
            ).fetchall()
        return [
            {
                "worker_id": r["worker_id"],
                "worker_name": (r["label"] or r["name"] or r["worker_id"]),
                "user_name": r["user_name"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def approve_account(self, username: str, actor: str | None = None) -> None:
        self.set_account_status(username, "approved", actor)

    def set_account_status(self, username: str, status: str, actor: str | None = None) -> None:
        user = normalize_username(username)
        if status not in {"approved", "pending"}:
            raise ValueError("bad_status")
        if user == ADMIN_USERNAME:
            raise ValueError("reserved")
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM accounts WHERE username=?", (user,)
            ).fetchone()
            if row is None:
                raise KeyError("not found")
            if row["status"] != status:
                self._conn.execute("UPDATE accounts SET status=? WHERE username=?", (status, user))
                if status == "pending":
                    self._conn.execute("DELETE FROM sessions WHERE user_name=?", (user,))
                    self._park_worker_unlocked(user)
                action = "approved" if status == "approved" else "revoked"
                self._add_event_unlocked(user, action, actor)
                self._conn.commit()

    def remove_account(self, username: str, actor: str | None = None) -> None:
        user = normalize_username(username)
        if user == ADMIN_USERNAME:
            raise ValueError("reserved")
        with self._lock:
            row = self._conn.execute(
                "SELECT username, kind FROM accounts WHERE username=?", (user,)
            ).fetchone()
            if row is None:
                raise KeyError("not found")
            kind = (row["kind"] if "kind" in row.keys() else None) or "user"
        if kind == "worker":
            self.remove_worker(user, actor)
            return
        with self._lock:
            self._conn.execute("DELETE FROM accounts WHERE username=?", (user,))
            self._conn.execute("DELETE FROM sessions WHERE user_name=?", (user,))
            self._park_worker_unlocked(user)
            self._add_event_unlocked(user, "removed", actor)
            self._conn.commit()
        self.cancel_jobs(user_name=user, reason="account removed")

    def remove_worker(self, worker_id: str, actor: str | None = None) -> None:
        with self._lock:
            worker = self._conn.execute("SELECT id FROM workers WHERE id=?", (worker_id,)).fetchone()
            acct = self._conn.execute(
                "SELECT username, kind FROM accounts WHERE username=?", (worker_id,)
            ).fetchone()
            kind = (acct["kind"] if acct is not None and "kind" in acct.keys() else None) or "user"
            is_worker_acct = acct is not None and kind == "worker"
            if worker is None and not is_worker_acct:
                raise KeyError("not found")
            ts = _now()
            if worker is not None:
                self._conn.execute(
                    """UPDATE jobs SET state='cancelled', cancel_requested=1, error=?, updated_at=?
                       WHERE worker_id=? AND state IN ('queued','running')""",
                    ("machine removed", ts, worker_id),
                )
                self._purge_worker_unlocked(worker_id)
            if is_worker_acct:
                self._conn.execute("DELETE FROM accounts WHERE username=?", (worker_id,))
                self._conn.execute("DELETE FROM sessions WHERE user_name=?", (worker_id,))
                self._add_event_unlocked(worker_id, "removed", actor)
            self._conn.commit()
        shutil.rmtree(SHARED_DIR / worker_id, ignore_errors=True)

    def _purge_worker_unlocked(self, worker_id: str) -> None:
        self._park_worker_unlocked(worker_id)
        for table in (
            "worker_blocks",
            "queue_anchors",
            "commands",
            "share_files",
            "share_grants",
            "share_events",
            "share_drops",
            "share_uploads",
            "metrics",
        ):
            self._conn.execute(f"DELETE FROM {table} WHERE worker_id=?", (worker_id,))
        self._conn.execute("DELETE FROM workers WHERE id=?", (worker_id,))

    def is_platform_worker(self, worker_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT is_platform, label, last_seen FROM workers WHERE id=?", (worker_id,)
            ).fetchone()
        if row is None or not row["is_platform"] or not row["label"]:
            return False
        return self._online_unlocked(row["last_seen"])

    def worker_by_token(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM workers WHERE token = ?", (token,)).fetchone()
        return self._row(row)

    def heartbeat(self, worker_id: str, body: HeartbeatIn) -> None:
        ts = _now()
        with self._lock:
            self._conn.execute(
                """
                UPDATE workers SET
                  run_open=?, security_open=?, admin_open=?, cpu_percent=?, memory_percent=?,
                  gpu_percent=?, bytes_sent=?, bytes_recv=?, current_job_id=?,
                  job_cpu_percent=?, job_proc_count=?, last_seen=?
                WHERE id=?
                """,
                (
                    int(body.locks.run_open),
                    int(body.locks.security_open),
                    int(body.locks.admin_open),
                    body.cpu_percent,
                    body.memory_percent,
                    json.dumps(body.gpu_percent),
                    body.bytes_sent,
                    body.bytes_recv,
                    body.current_job_id,
                    body.job_cpu_percent,
                    body.job_proc_count,
                    ts,
                    worker_id,
                ),
            )
            if body.environments is not None:
                self._conn.execute(
                    "UPDATE workers SET environments=? WHERE id=?",
                    (json.dumps([e.model_dump() for e in body.environments]), worker_id),
                )
            self._conn.execute(
                """
                INSERT INTO metrics(worker_id, ts, cpu_percent, memory_percent, gpu_percent, bytes_sent, bytes_recv)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    worker_id,
                    ts,
                    body.cpu_percent,
                    body.memory_percent,
                    json.dumps(body.gpu_percent),
                    body.bytes_sent,
                    body.bytes_recv,
                ),
            )
            self._conn.execute("DELETE FROM metrics WHERE ts < ?", (ts - 3600,))
            if body.current_job_id and int(body.ui_port or 0) > 0:
                self._conn.execute(
                    """
                    UPDATE jobs SET ui_kind=?, ui_port=?, updated_at=?
                    WHERE id=? AND worker_id=? AND state='running'
                    """,
                    (str(body.ui_kind or ""), int(body.ui_port), ts, body.current_job_id, worker_id),
                )
            self._conn.commit()

    def list_workers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM workers ORDER BY name").fetchall()
        out = []
        for row in rows:
            data = dict(row)
            if not (data.get("label") or "").strip():
                continue
            if not self._online_unlocked(data["last_seen"]):
                continue
            out.append(self._public_worker(data))
        return out

    def get_worker(self, worker_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
        return self._public_worker(dict(row)) if row else None

    def _public_worker(self, row: dict[str, Any]) -> dict[str, Any]:
        last = row["last_seen"]
        online = (_now() - last) <= HEARTBEAT_TTL_SEC
        wid = str(row.get("id") or "")
        label = str(row.get("label") or "")
        if valid_username(wid):
            shown = group_digits(wid)
        elif valid_username(label):
            shown = group_digits(label)
        else:
            shown = label or str(row.get("name") or wid)
        out = {
            "id": row["id"],
            "name": shown,
            "is_platform": bool(row.get("is_platform")),
            "os": row["os"],
            "arch": row["arch"],
            "runtimes": json.loads(row["runtimes"]),
            "has_docker": bool(row["has_docker"]),
            "cpu_cores": row["cpu_cores"],
            "memory_mb": row["memory_mb"],
            "gpus": json.loads(row["gpus"]),
            "locks": {
                "run_open": bool(row["run_open"]),
                "security_open": bool(row["security_open"]),
                "admin_open": bool(row.get("admin_open")),
            },
            "environments": [
                {k: e.get(k) for k in ("id", "kind", "label", "version", "extensions") if e.get(k) is not None}
                for e in json.loads(row.get("environments") or "[]")
            ],
            "cpu_percent": row["cpu_percent"],
            "memory_percent": row["memory_percent"],
            "gpu_percent": json.loads(row["gpu_percent"] or "[]"),
            "bytes_sent": row["bytes_sent"],
            "bytes_recv": row["bytes_recv"],
            "current_job_id": row["current_job_id"],
            "job_cpu_percent": row.get("job_cpu_percent") or 0,
            "job_proc_count": row.get("job_proc_count") or 0,
            "pause_all": bool(row.get("pause_all")),
            "current_user": None,
            "current_job_name": None,
            "last_seen": last,
            "online": online,
            "accepting": online and bool(row["run_open"]) and not bool(row.get("pause_all")),
            "blocked_count": 0,
        }
        n = self._conn.execute(
            "SELECT COUNT(*) FROM worker_blocks WHERE worker_id=?", (row["id"],)
        ).fetchone()[0]
        out["blocked_count"] = int(n)
        jid = row.get("current_job_id")
        if jid:
            job = self.get_job(jid)
            if job:
                out["current_user"] = job.get("user_name")
                out["current_job_name"] = job.get("name")
        return out

    def create_job(
        self,
        *,
        manifest: JobManifest,
        artifact_path: str,
        worker_id: str,
        limits: ResourceLimits | None,
        user_name: str,
        env_id: str | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        ts = _now()
        with self._lock:
            nxt = self._next_queue_order_unlocked(worker_id)
            self._conn.execute(
                """
                INSERT INTO jobs(id, name, manifest, artifact_path, worker_id, state, requested_limits, created_at, updated_at, user_name, queue_order, env_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    manifest.name,
                    manifest.model_dump_json(),
                    artifact_path,
                    worker_id,
                    "queued",
                    limits.model_dump_json() if limits else None,
                    ts,
                    ts,
                    user_name,
                    nxt,
                    env_id,
                ),
            )
            self._conn.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._job_view(dict(row))

    def _job_view(self, row: dict[str, Any]) -> dict[str, Any]:
        d = dict(row)
        d["manifest"] = json.loads(d["manifest"]) if isinstance(d.get("manifest"), str) else d.get("manifest")
        d["requested_limits"] = json.loads(d["requested_limits"]) if d.get("requested_limits") else None
        kind = str(d.get("ui_kind") or "")
        port = int(d.get("ui_port") or 0)
        d["ui"] = {"kind": kind, "ready": bool(d.get("state") == "running" and kind and port > 0)}
        return d

    def job_ui_bind(self, job_id: str) -> tuple[str, int] | None:
        job = self.get_job(job_id)
        if job is None or job.get("state") != "running":
            return None
        port = int(job.get("ui_port") or 0)
        kind = str(job.get("ui_kind") or "")
        if port <= 0 or not kind:
            return None
        return kind, port

    def list_jobs(self, limit: int = 50, user_name: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if user_name:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE user_name=? ORDER BY created_at DESC LIMIT ?",
                    (user_name, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        out = []
        for row in rows:
            out.append(self._job_view(dict(row)))
        return out

    def lease_job(self, worker_id: str) -> dict[str, Any] | None:
        with self._lock:
            worker = self._conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
            if worker is None or not worker["run_open"] or worker["pause_all"]:
                return None
            blocked = {
                r[0]
                for r in self._conn.execute(
                    "SELECT user_name FROM worker_blocks WHERE worker_id=?",
                    (worker_id,),
                ).fetchall()
            }
            items = self._queue_items_unlocked(worker_id)
            chosen = None
            for item in items:
                if item["kind"] == "anchor":
                    return None
                if item["user_name"] in blocked:
                    continue
                if item.get("cancel_requested"):
                    continue
                chosen = item
                break
            if chosen is None:
                return None
            ts = _now()
            self._conn.execute(
                "UPDATE jobs SET state='running', updated_at=? WHERE id=?",
                (ts, chosen["id"]),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (chosen["id"],)).fetchone()
            d = dict(row)
        d["manifest"] = json.loads(d["manifest"])
        d["requested_limits"] = json.loads(d["requested_limits"]) if d["requested_limits"] else None
        return d

    def append_log(self, job_id: str, stream: str, line: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO job_logs(job_id, ts, stream, line) VALUES (?,?,?,?)",
                (job_id, _now(), stream, line),
            )
            self._conn.commit()

    def job_logs(self, job_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_logs WHERE job_id=? AND id>? ORDER BY id ASC",
                (job_id, after_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_job(self, job_id: str, exit_code: int, error: str | None, result_path: str | None) -> None:
        with self._lock:
            row = self._conn.execute("SELECT state, cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return
            if row["state"] == "cancelled" or row["cancel_requested"]:
                state = "cancelled"
            elif exit_code == 0:
                state = "succeeded"
            else:
                state = "failed"
            self._conn.execute(
                """
                UPDATE jobs SET state=?, exit_code=?, error=?, result_path=?, ui_port=0, updated_at=?
                WHERE id=?
                """,
                (state, exit_code, error, result_path, _now(), job_id),
            )
            self._conn.commit()

    def job_cancel_requested(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return bool(job and job.get("cancel_requested"))

    def push_stdin(self, job_id: str, text: str) -> None:
        line = str(text or "")
        if len(line) > 8000:
            raise ValueError("too_large")
        job = self.get_job(job_id)
        if job is None:
            raise KeyError("job not found")
        if job["state"] != "running":
            raise ValueError("only a running job can take input")
        with self._lock:
            n = self._conn.execute(
                "SELECT COUNT(*) FROM job_stdin WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            if int(n) >= 200:
                raise ValueError("too_large")
            self._conn.execute(
                "INSERT INTO job_stdin(job_id, line, created_at) VALUES (?,?,?)",
                (job_id, line, _now()),
            )
            self._conn.commit()

    def take_stdin(self, job_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, line FROM job_stdin WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            self._conn.execute(
                f"DELETE FROM job_stdin WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
            self._conn.commit()
        return [r["line"] for r in rows]

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError("job not found")
        if job["state"] not in {"running", "queued"}:
            raise ValueError("only a running or queued job can be stopped")
        ts = _now()
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?",
                (ts, job_id),
            )
            claimed = False
            if job["worker_id"]:
                worker = self._conn.execute(
                    "SELECT current_job_id FROM workers WHERE id=?",
                    (job["worker_id"],),
                ).fetchone()
                claimed = bool(worker and worker["current_job_id"] == job_id)
            if not claimed:
                self._conn.execute(
                    """
                    UPDATE jobs SET state='cancelled', error=?, updated_at=?
                    WHERE id=?
                    """,
                    ("stopped", ts, job_id),
                )
            self._conn.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def delete_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError("job not found")
        if job["state"] == "running":
            raise ValueError("stop the running job before deleting its record")
        with self._lock:
            self._conn.execute("DELETE FROM job_logs WHERE job_id=?", (job_id,))
            self._conn.execute("DELETE FROM job_stdin WHERE job_id=?", (job_id,))
            self._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            self._conn.commit()

    def prune_metrics(self, keep_sec: float = 3600) -> None:
        cutoff = _now() - keep_sec
        with self._lock:
            self._conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
            self._conn.commit()

    def enqueue_limits(self, worker_id: str, limits: ResourceLimits) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO commands(worker_id, kind, payload, created_at) VALUES (?,?,?,?)",
                (worker_id, "set_limits", limits.model_dump_json(), _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def pending_commands(self, worker_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM commands WHERE worker_id=? AND acked=0 ORDER BY id ASC",
                (worker_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    def ack_commands(self, worker_id: str, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._conn.executemany(
                "UPDATE commands SET acked=1 WHERE id=? AND worker_id=?",
                [(i, worker_id) for i in ids],
            )
            self._conn.commit()

    def metrics(self, worker_id: str | None = None, since: float | None = None) -> list[dict[str, Any]]:
        since = since or (_now() - 3600)
        with self._lock:
            if worker_id:
                rows = self._conn.execute(
                    "SELECT * FROM metrics WHERE worker_id=? AND ts>=? ORDER BY ts ASC",
                    (worker_id, since),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM metrics WHERE ts>=? ORDER BY ts ASC",
                    (since,),
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["gpu_percent"] = json.loads(d["gpu_percent"])
            out.append(d)
        return out

    def worker_can_run(
        self, worker_id: str, manifest: JobManifest, user_name: str | None = None
    ) -> tuple[bool, str]:
        w = self.get_worker(worker_id)
        if w is None:
            return False, "worker not found"
        if not w["online"]:
            return False, "worker offline"
        if not w["locks"]["run_open"]:
            return False, "This Worker is not accepting jobs"
        if user_name and self.is_blocked(worker_id, user_name):
            return False, "this Worker blocked this User"
        gpus = [GpuInfo(**g) for g in w["gpus"]]
        if not compatible(
            manifest,
            os_name=w["os"],
            runtimes=w["runtimes"],
            has_docker=w["has_docker"],
            gpus=gpus,
        ):
            return False, "worker cannot run this program"
        return True, "ok"

    def delete_session(self, token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._conn.commit()

    def cancel_jobs(
        self,
        *,
        user_name: str | None = None,
        worker_id: str | None = None,
        reason: str = "logout",
    ) -> list[str]:
        running: list[str] = []
        with self._lock:
            q = "SELECT id, state, worker_id FROM jobs WHERE state IN ('queued','running')"
            args: list[Any] = []
            if user_name:
                q += " AND user_name=?"
                args.append(user_name)
            if worker_id:
                q += " AND worker_id=?"
                args.append(worker_id)
            rows = self._conn.execute(q, args).fetchall()
            ts = _now()
            for row in rows:
                if row["state"] == "queued":
                    self._conn.execute(
                        "UPDATE jobs SET state='cancelled', cancel_requested=1, error=?, updated_at=? WHERE id=?",
                        (reason, ts, row["id"]),
                    )
                    continue
                self._conn.execute(
                    "UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?",
                    (ts, row["id"]),
                )
                worker = None
                if row["worker_id"]:
                    worker = self._conn.execute(
                        "SELECT last_seen FROM workers WHERE id=?",
                        (row["worker_id"],),
                    ).fetchone()
                online = bool(worker and self._online_unlocked(worker["last_seen"]))
                if not online:
                    self._conn.execute(
                        "UPDATE jobs SET state='cancelled', error=?, updated_at=? WHERE id=?",
                        (reason, ts, row["id"]),
                    )
                else:
                    running.append(row["id"])
            self._conn.commit()
        return running

    def has_running_jobs(self, *, user_name: str | None = None, worker_id: str | None = None) -> bool:
        with self._lock:
            q = "SELECT 1 FROM jobs WHERE state='running'"
            args: list[Any] = []
            if user_name:
                q += " AND user_name=?"
                args.append(user_name)
            if worker_id:
                q += " AND worker_id=?"
                args.append(worker_id)
            return self._conn.execute(q + " LIMIT 1", args).fetchone() is not None

    def wait_jobs_idle(
        self,
        *,
        user_name: str | None = None,
        worker_id: str | None = None,
        timeout: float = 45,
    ) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.has_running_jobs(user_name=user_name, worker_id=worker_id):
                return True
            time.sleep(0.25)
        return not self.has_running_jobs(user_name=user_name, worker_id=worker_id)

    def create_session(self, user_name: str, role: str = "user") -> str:
        token = str(uuid.uuid4())
        ts = _now()
        with self._lock:
            existing = self._conn.execute(
                "SELECT token, last_seen FROM sessions WHERE user_name=? AND role=?",
                (user_name, role),
            ).fetchone()
            if existing and existing["last_seen"] and (ts - existing["last_seen"]) <= SESSION_LOCK_SEC:
                raise ValueError("already_logged_in")
            self._conn.execute(
                "DELETE FROM sessions WHERE user_name=? AND role=?", (user_name, role)
            )
            self._conn.execute(
                "INSERT INTO sessions(token, user_name, role, created_at, last_seen) VALUES (?,?,?,?,?)",
                (token, user_name, role, ts, ts),
            )
            self._conn.commit()
        return token

    def session_user(self, token: str) -> str | None:
        info = self.session_info(token)
        return info["name"] if info else None

    def session_info(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        ts = _now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
            if row is None:
                return None
            last = row["last_seen"] or 0
            if last and (ts - last) > SESSION_TTL_SEC:
                self._conn.execute("DELETE FROM sessions WHERE token=?", (token,))
                self._conn.commit()
                return None
            self._conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (ts, token))
            self._conn.commit()
            return {
                "name": row["user_name"],
                "role": row["role"] or "user",
                "token": token,
            }

    def is_blocked(self, worker_id: str, user_name: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM worker_blocks WHERE worker_id=? AND user_name=?",
                (worker_id, user_name),
            ).fetchone()
        return row is not None

    def _next_queue_order_unlocked(self, worker_id: str) -> float:
        job_m = self._conn.execute(
            "SELECT MAX(queue_order) FROM jobs WHERE worker_id=?", (worker_id,)
        ).fetchone()[0]
        anc_m = self._conn.execute(
            "SELECT MAX(queue_order) FROM queue_anchors WHERE worker_id=?", (worker_id,)
        ).fetchone()[0]
        vals = [v for v in (job_m, anc_m) if v is not None]
        return (max(vals) + 1) if vals else 1.0

    def _queue_items_unlocked(self, worker_id: str) -> list[dict[str, Any]]:
        jobs = self._conn.execute(
            """
            SELECT id, name, user_name, state, queue_order FROM jobs
            WHERE worker_id=? AND state='queued'
            """,
            (worker_id,),
        ).fetchall()
        anchors = self._conn.execute(
            "SELECT id, queue_order FROM queue_anchors WHERE worker_id=?",
            (worker_id,),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for j in jobs:
            items.append(
                {
                    "kind": "job",
                    "id": j["id"],
                    "name": j["name"],
                    "user_name": j["user_name"],
                    "state": j["state"],
                    "queue_order": j["queue_order"] if j["queue_order"] is not None else j["id"],
                }
            )
        for a in anchors:
            items.append(
                {
                    "kind": "anchor",
                    "id": a["id"],
                    "name": "anchor",
                    "user_name": None,
                    "state": "anchor",
                    "queue_order": a["queue_order"],
                }
            )
        items.sort(key=lambda x: (float(x["queue_order"]), x["id"]))
        return items

    def _freeze_unlocked(self, worker_id: str) -> dict[str, Any]:
        worker = self._conn.execute(
            "SELECT pause_all FROM workers WHERE id=?", (worker_id,)
        ).fetchone()
        pause_all = bool(worker and worker["pause_all"])
        items = self._queue_items_unlocked(worker_id)
        first_anchor = next((i for i in items if i["kind"] == "anchor"), None)
        editable = []
        if first_anchor is not None:
            editable = [
                i["id"]
                for i in items
                if i["kind"] == "job" and float(i["queue_order"]) > float(first_anchor["queue_order"])
            ]
        return {
            "pause_all": pause_all,
            "has_anchor": first_anchor is not None,
            "first_anchor_id": first_anchor["id"] if first_anchor else None,
            "can_reorder": first_anchor is not None and len(editable) >= 1,
            "reorder_job_ids": editable,
            "can_edit_queue": pause_all or first_anchor is not None,
        }

    def worker_board(self, worker_id: str) -> dict[str, Any]:
        public = self.get_worker(worker_id)
        if public is None:
            raise KeyError("worker not found")
        with self._lock:
            blocked = [
                r[0]
                for r in self._conn.execute(
                    "SELECT user_name FROM worker_blocks WHERE worker_id=? ORDER BY user_name",
                    (worker_id,),
                ).fetchall()
            ]
            freeze = self._freeze_unlocked(worker_id)
            items = self._queue_items_unlocked(worker_id)
            running = self._conn.execute(
                """
                SELECT id, name, user_name, state, queue_order FROM jobs
                WHERE worker_id=? AND state='running'
                ORDER BY updated_at DESC
                """,
                (worker_id,),
            ).fetchall()
        occupancy = None
        if running:
            r = running[0]
            occupancy = {
                "user_name": r["user_name"],
                "job_id": r["id"],
                "job_name": r["name"],
                "cpu_percent": public.get("job_cpu_percent") or 0,
                "proc_count": public.get("job_proc_count") or 0,
                "frozen": freeze["pause_all"],
            }
        queue = []
        for r in running:
            queue.append(
                {
                    "kind": "job",
                    "id": r["id"],
                    "name": r["name"],
                    "user_name": r["user_name"],
                    "state": "running",
                    "queue_order": r["queue_order"],
                }
            )
        queue.extend(items)
        users = sorted({q["user_name"] for q in queue if q.get("user_name")})
        with self._lock:
            failed = self._conn.execute(
                """
                SELECT id, name, user_name, state, error FROM jobs
                WHERE worker_id=? AND state IN ('failed','cancelled')
                ORDER BY updated_at DESC LIMIT 8
                """,
                (worker_id,),
            ).fetchall()
        recent = [
            {
                "id": r["id"],
                "name": r["name"],
                "user_name": r["user_name"],
                "state": r["state"],
                "error": r["error"],
            }
            for r in failed
        ]
        return {
            "worker": public,
            "occupancy": occupancy,
            "queue": queue,
            "recent": recent,
            "blocked_users": blocked,
            "users": users,
            **freeze,
        }

    def set_pause_all(self, worker_id: str, on: bool) -> dict[str, Any]:
        with self._lock:
            self._conn.execute(
                "UPDATE workers SET pause_all=? WHERE id=?", (int(on), worker_id)
            )
            self._conn.commit()
        return self.worker_board(worker_id)

    def insert_anchor(self, worker_id: str, *, before_id: str | None, after_id: str | None) -> dict[str, Any]:
        with self._lock:
            items = self._queue_items_unlocked(worker_id)
            running = self._conn.execute(
                """
                SELECT id, queue_order FROM jobs
                WHERE worker_id=? AND state='running'
                """,
                (worker_id,),
            ).fetchall()
            ordered: list[tuple[str, float]] = [
                (r["id"], float(r["queue_order"] or 0)) for r in running
            ]
            ordered += [(i["id"], float(i["queue_order"])) for i in items]
            if not ordered:
                raise ValueError("queue is empty")
            if before_id and after_id:
                raise ValueError("use before_id or after_id, not both")
            target = before_id or after_id
            if target is None:
                raise ValueError("need before_id or after_id")
            idx = next((n for n, (i, _) in enumerate(ordered) if i == target), None)
            if idx is None:
                raise ValueError("queue item not found")
            if before_id:
                left = ordered[idx - 1][1] if idx > 0 else ordered[idx][1] - 1
                right = ordered[idx][1]
            else:
                left = ordered[idx][1]
                right = ordered[idx + 1][1] if idx + 1 < len(ordered) else ordered[idx][1] + 1
            pos = (left + right) / 2
            if pos == left or pos == right:
                pos = left + 0.001
            aid = str(uuid.uuid4())
            self._conn.execute(
                "INSERT INTO queue_anchors(id, worker_id, queue_order, created_at) VALUES (?,?,?,?)",
                (aid, worker_id, pos, _now()),
            )
            self._conn.commit()
        return self.worker_board(worker_id)

    def release_anchor(self, worker_id: str, anchor_id: str) -> dict[str, Any]:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM queue_anchors WHERE id=? AND worker_id=?",
                (anchor_id, worker_id),
            )
            if cur.rowcount == 0:
                raise KeyError("anchor not found")
            self._conn.commit()
        return self.worker_board(worker_id)

    def reorder_after_anchor(self, worker_id: str, job_ids: list[str]) -> dict[str, Any]:
        with self._lock:
            freeze = self._freeze_unlocked(worker_id)
            if not freeze["can_reorder"]:
                raise ValueError("reorder is only allowed after an anchor")
            allowed = freeze["reorder_job_ids"]
            if set(job_ids) != set(allowed):
                raise ValueError("reorder list must be exactly the jobs after the first anchor")
            items = self._queue_items_unlocked(worker_id)
            first = next(i for i in items if i["kind"] == "anchor")
            base = float(first["queue_order"])
            for n, jid in enumerate(job_ids, start=1):
                self._conn.execute(
                    "UPDATE jobs SET queue_order=?, updated_at=? WHERE id=? AND worker_id=? AND state='queued'",
                    (base + n, _now(), jid, worker_id),
                )
            self._conn.commit()
        return self.worker_board(worker_id)

    def worker_delete_queued(self, worker_id: str, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None or job["worker_id"] != worker_id:
            raise KeyError("job not found")
        if job["state"] != "queued":
            raise ValueError("only queued jobs can be removed from the Worker queue")
        with self._lock:
            freeze = self._freeze_unlocked(worker_id)
            if not freeze["can_edit_queue"]:
                raise ValueError("insert an anchor or pause all first")
            self._conn.execute(
                """
                UPDATE jobs SET state='cancelled', cancel_requested=1, error=?, updated_at=?
                WHERE id=?
                """,
                ("removed from queue", _now(), job_id),
            )
            self._conn.commit()
        return self.worker_board(worker_id)

    def block_user(self, worker_id: str, user_name: str) -> dict[str, Any]:
        user = normalize_username(user_name)
        if user == ADMIN_USERNAME:
            raise ValueError("cannot_block_admin")
        if not valid_username(user):
            raise ValueError("bad_username")
        ts = _now()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO worker_blocks(worker_id, user_name, created_at) VALUES (?,?,?)",
                (worker_id, user, ts),
            )
            running = self._conn.execute(
                """
                SELECT id FROM jobs WHERE worker_id=? AND user_name=? AND state='running'
                """,
                (worker_id, user),
            ).fetchall()
            self._conn.commit()
        for row in running:
            try:
                self.request_cancel(row["id"])
            except (KeyError, ValueError):
                pass
        return self.worker_board(worker_id)

    def unblock_user(self, worker_id: str, user_name: str) -> dict[str, Any]:
        user = normalize_username(user_name)
        with self._lock:
            self._conn.execute(
                "DELETE FROM worker_blocks WHERE worker_id=? AND user_name=?",
                (worker_id, user),
            )
            self._conn.commit()
        return self.worker_board(worker_id)

    def pause_all_requested(self, worker_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT pause_all FROM workers WHERE id=?", (worker_id,)
            ).fetchone()
        return bool(row and row["pause_all"])

    def current_job_blocked(self, worker_id: str, job_id: str | None) -> bool:
        if not job_id:
            return False
        job = self.get_job(job_id)
        if job is None:
            return False
        return self.is_blocked(worker_id, job.get("user_name") or "")

    def worker_environments_full(self, worker_id: str) -> list[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT environments FROM workers WHERE id=?", (worker_id,)
            ).fetchone()
        if row is None:
            return []
        try:
            data = json.loads(row["environments"] or "[]")
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def worker_environment(self, worker_id: str, env_id: str) -> dict[str, Any] | None:
        for env in self.worker_environments_full(worker_id):
            if env.get("id") == env_id:
                return env
        return None

    def env_verdicts(self, worker_id: str, scan: dict) -> list[dict[str, Any]]:
        from control.scan import env_match

        worker = self.get_worker(worker_id)
        admin_open = bool(worker and worker.get("locks", {}).get("admin_open"))
        out = []
        for env in self.worker_environments_full(worker_id):
            match = env_match(scan, env)
            ok = bool(match["ok"])
            code = match.get("code") or ("ok" if ok else "other")
            if ok and scan.get("needs_admin") and not admin_open:
                ok = False
                code = "admin"
            out.append(
                {
                    "id": env.get("id"),
                    "kind": env.get("kind"),
                    "label": env.get("label"),
                    "ok": ok,
                    "code": code,
                    "reason": match["reason"],
                    "missing": match.get("missing") or [],
                    "pkg_n": len(env.get("packages") or []),
                }
            )
        return out

    def queue_depth(self, worker_id: str) -> int:
        with self._lock:
            n = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE worker_id=? AND state=?",
                (worker_id, "queued"),
            ).fetchone()[0]
        return int(n)

    def last_worker_for_user(self, user_name: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT worker_id FROM jobs
                WHERE user_name=? AND IFNULL(worker_id,'') != ''
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_name,),
            ).fetchone()
        return str(row["worker_id"]) if row and row["worker_id"] else None

    def placements(
        self, user_name: str, scan: dict, *, worker_id: str | None = None
    ) -> list[dict[str, Any]]:
        from control.place import pick_env, score_worker

        sticky = self.last_worker_for_user(user_name)
        if worker_id:
            one = self.get_worker(worker_id)
            workers = [one] if one else []
        else:
            workers = self.list_workers()
        out: list[dict[str, Any]] = []
        for worker in workers:
            if worker is None:
                continue
            if not worker_id and not worker.get("accepting"):
                continue
            if self.is_blocked(worker["id"], user_name):
                continue
            ready = [v for v in self.env_verdicts(worker["id"], scan) if v.get("ok")]
            if not ready:
                continue
            env = pick_env(ready, scan)
            queued = self.queue_depth(worker["id"])
            needs_gpu = bool(scan.get("needs_gpu"))
            score = score_worker(
                idle=not worker.get("current_job_id"),
                queued=queued,
                cpu=float(worker.get("cpu_percent") or 0),
                mem=float(worker.get("memory_percent") or 0),
                sticky=sticky == worker["id"],
                has_gpu=bool(worker.get("gpus")),
                needs_gpu=needs_gpu,
            )
            out.append(
                {
                    "worker_id": worker["id"],
                    "worker_name": worker["name"],
                    "env_id": env["id"],
                    "env_label": env.get("label") or env["id"],
                    "score": score,
                    "queued": queued,
                    "idle": not worker.get("current_job_id"),
                }
            )
        out.sort(key=lambda item: (-int(item["score"]), int(item["queued"]), str(item["worker_id"])))
        return out

    def _share_event_unlocked(
        self,
        worker_id: str,
        owner: str,
        actor: str,
        actor_role: str,
        action: str,
        kind: str | None = None,
        file_name: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO share_events(worker_id, owner, actor, actor_role, action, kind, file_name, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (worker_id, owner, actor, actor_role, action, kind, file_name, _now()),
        )

    def _share_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "worker_id": row["worker_id"],
            "owner": row["owner"],
            "kind": row["kind"],
            "name": row["name"],
            "size": row["size"],
            "created_at": row["created_at"],
        }

    def _share_local_name(self, file_id: str, filename: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "file").name or "file")[:160] or "file"
        return f"{file_id}_{safe}"

    def _share_upload_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "worker_id": row["worker_id"],
            "owner": row["owner"],
            "kind": row["kind"],
            "name": row["name"],
            "actor": row["actor"],
            "actor_role": row["actor_role"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    def _share_expire_uploads_unlocked(self) -> None:
        self._conn.execute(
            "UPDATE share_uploads SET status='cancelled' WHERE status='uploading' AND created_at < ?",
            (_now() - 1800,),
        )

    def share_grant_status(self, worker_id: str, user_name: str) -> str:
        user = normalize_username(user_name)
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM share_grants WHERE worker_id=? AND user_name=?",
                (worker_id, user),
            ).fetchone()
        return str(row["status"]) if row else ""

    def share_apply(self, worker_id: str, user_name: str) -> dict[str, Any]:
        user = normalize_username(user_name)
        if self.get_worker(worker_id) is None:
            raise KeyError("worker not found")
        if self.is_blocked(worker_id, user):
            raise ValueError("blocked")
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM share_grants WHERE worker_id=? AND user_name=?",
                (worker_id, user),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO share_grants(worker_id, user_name, status, created_at) VALUES (?,?,?,?)",
                    (worker_id, user, "pending", _now()),
                )
                self._share_event_unlocked(worker_id, user, user, "user", "apply", "granted")
                self._conn.commit()
            elif row["status"] != "approved" and row["status"] != "pending":
                self._conn.execute(
                    "UPDATE share_grants SET status='pending', decided_at=NULL WHERE worker_id=? AND user_name=?",
                    (worker_id, user),
                )
                self._share_event_unlocked(worker_id, user, user, "user", "apply", "granted")
                self._conn.commit()
        return self.share_user_view(worker_id, user)

    def share_set_grant(
        self, worker_id: str, user_name: str, approved: bool, actor: str, actor_role: str
    ) -> dict[str, Any]:
        user = normalize_username(user_name)
        if not valid_username(user):
            raise ValueError("bad_username")
        with self._lock:
            if approved:
                self._conn.execute(
                    """
                    INSERT INTO share_grants(worker_id, user_name, status, created_at, decided_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(worker_id, user_name) DO UPDATE SET status='approved', decided_at=excluded.decided_at
                    """,
                    (worker_id, user, "approved", _now(), _now()),
                )
                self._share_event_unlocked(worker_id, user, actor, actor_role, "approve", "granted")
            else:
                self._conn.execute(
                    "DELETE FROM share_grants WHERE worker_id=? AND user_name=?",
                    (worker_id, user),
                )
                self._share_event_unlocked(worker_id, user, actor, actor_role, "revoke", "granted")
            self._conn.commit()
        return self.share_staff_view(worker_id)

    def share_upload(
        self,
        worker_id: str,
        owner: str,
        kind: str,
        filename: str,
        data: bytes,
        actor: str,
        actor_role: str,
    ) -> dict[str, Any]:
        if kind not in {"open", "granted"}:
            raise ValueError("bad_folder")
        if not data:
            raise ValueError("empty")
        if len(data) > SHARE_MAX_BYTES:
            raise ValueError("too_large")
        user = normalize_username(owner)
        if self.get_worker(worker_id) is None:
            raise KeyError("worker not found")
        if actor_role == "user":
            if self.is_blocked(worker_id, user):
                raise ValueError("blocked")
            if kind == "granted" and self.share_grant_status(worker_id, user) != "approved":
                raise ValueError("grant_required")
        name = Path(filename or "file").name or "file"
        file_id = str(uuid.uuid4())
        local_name = self._share_local_name(file_id, name)
        dest = SHARED_DIR / worker_id / kind / user / local_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO share_files(id, worker_id, owner, kind, name, size, stored_path, local_name, synced, created_at)
                VALUES (?,?,?,?,?,?,?,?,0,?)
                """,
                (file_id, worker_id, user, kind, name, len(data), str(dest), local_name, _now()),
            )
            self._share_event_unlocked(worker_id, user, actor, actor_role, "upload", kind, name)
            self._conn.commit()
        return self.share_user_view(worker_id, user) if actor_role == "user" else self.share_staff_view(worker_id)

    def share_upload_start(
        self,
        worker_id: str,
        owner: str,
        kind: str,
        filename: str,
        actor: str,
        actor_role: str,
    ) -> dict[str, Any]:
        if kind not in {"open", "granted"}:
            raise ValueError("bad_folder")
        user = normalize_username(owner)
        if self.get_worker(worker_id) is None:
            raise KeyError("worker not found")
        if actor_role == "user":
            if self.is_blocked(worker_id, user):
                raise ValueError("blocked")
            if kind == "granted" and self.share_grant_status(worker_id, user) != "approved":
                raise ValueError("grant_required")
        name = Path(filename or "file").name or "file"
        upload_id = str(uuid.uuid4())
        with self._lock:
            self._share_expire_uploads_unlocked()
            self._conn.execute(
                """
                INSERT INTO share_uploads(id, worker_id, owner, kind, name, actor, actor_role, status, created_at)
                VALUES (?,?,?,?,?,?,?,'uploading',?)
                """,
                (upload_id, worker_id, user, kind, name, actor, actor_role, _now()),
            )
            self._conn.commit()
        return {
            "id": upload_id,
            "worker_id": worker_id,
            "owner": user,
            "kind": kind,
            "name": name,
            "status": "uploading",
        }

    def share_upload_get(self, upload_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM share_uploads WHERE id=?", (upload_id,)).fetchone()
        return dict(row) if row else None

    def share_upload_is_cancelled(self, upload_id: str) -> bool:
        rec = self.share_upload_get(upload_id)
        return rec is None or rec["status"] == "cancelled"

    def share_upload_finish(self, upload_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM share_uploads WHERE id=?", (upload_id,))
            self._conn.commit()

    def share_cancel_upload(
        self,
        upload_id: str,
        actor: str,
        actor_role: str,
        *,
        owner: str | None = None,
        worker_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM share_uploads WHERE id=?", (upload_id,)).fetchone()
            if row is None:
                raise KeyError("upload not found")
            if row["status"] != "uploading":
                raise ValueError("cancelled")
            if actor_role == "user":
                user = normalize_username(owner or actor)
                if row["owner"] != user and row["actor"] != user:
                    raise PermissionError("not owner")
            elif worker_id and row["worker_id"] != worker_id:
                raise PermissionError("wrong worker")
            self._conn.execute("UPDATE share_uploads SET status='cancelled' WHERE id=?", (upload_id,))
            self._share_event_unlocked(
                row["worker_id"],
                row["owner"],
                actor,
                actor_role,
                "cancel",
                row["kind"],
                row["name"],
            )
            self._conn.commit()
            worker = row["worker_id"]
        return self.share_user_view(worker, owner or actor) if actor_role == "user" else self.share_staff_view(worker)

    def share_sync_plan(self, worker_id: str) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            files = self._conn.execute(
                "SELECT * FROM share_files WHERE worker_id=? AND synced=0",
                (worker_id,),
            ).fetchall()
            drops = self._conn.execute(
                "SELECT * FROM share_drops WHERE worker_id=?",
                (worker_id,),
            ).fetchall()
        pull = []
        for row in files:
            local = row["local_name"] or Path(row["stored_path"]).name
            pull.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "owner": row["owner"],
                    "name": row["name"],
                    "local_name": local,
                }
            )
        return {"pull": pull, "drop": [dict(r) for r in drops]}

    def share_sync_ack(self, worker_id: str, pulled: list[str], dropped: list[str]) -> None:
        with self._lock:
            for file_id in pulled:
                self._conn.execute(
                    "UPDATE share_files SET synced=1 WHERE id=? AND worker_id=?",
                    (file_id, worker_id),
                )
            for file_id in dropped:
                self._conn.execute(
                    "DELETE FROM share_drops WHERE id=? AND worker_id=?",
                    (file_id, worker_id),
                )
            self._conn.commit()

    def _share_active_uploads(self, worker_id: str, owner: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._share_expire_uploads_unlocked()
            if owner:
                rows = self._conn.execute(
                    "SELECT * FROM share_uploads WHERE worker_id=? AND owner=? AND status='uploading' ORDER BY created_at DESC",
                    (worker_id, normalize_username(owner)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM share_uploads WHERE worker_id=? AND status='uploading' ORDER BY created_at DESC",
                    (worker_id,),
                ).fetchall()
            self._conn.commit()
        return [self._share_upload_row(r) for r in rows]

    def share_read_for_submit(self, file_id: str, user_name: str, worker_id: str) -> dict[str, Any]:
        user = normalize_username(user_name)
        rec = self.share_get(file_id)
        if rec is None or rec["owner"] != user or rec["worker_id"] != worker_id:
            raise KeyError("file not found")
        if rec["kind"] == "granted" and self.share_grant_status(worker_id, user) != "approved":
            raise ValueError("grant_required")
        if self.is_blocked(worker_id, user):
            raise ValueError("blocked")
        path = Path(rec["stored_path"])
        if not path.is_file():
            raise KeyError("file not found")
        return rec

    def share_get(self, file_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM share_files WHERE id=?", (file_id,)).fetchone()
        return dict(row) if row else None

    def share_remove(self, file_id: str, actor: str, actor_role: str, *, owner: str | None = None) -> None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM share_files WHERE id=?", (file_id,)).fetchone()
            if row is None:
                raise KeyError("file not found")
            if owner and row["owner"] != normalize_username(owner):
                raise PermissionError("not owner")
            path = row["stored_path"]
            local_name = row["local_name"] or Path(path).name
            self._conn.execute(
                """
                INSERT OR REPLACE INTO share_drops(id, worker_id, kind, owner, local_name)
                VALUES (?,?,?,?,?)
                """,
                (row["id"], row["worker_id"], row["kind"], row["owner"], local_name),
            )
            self._conn.execute("DELETE FROM share_files WHERE id=?", (file_id,))
            self._share_event_unlocked(
                row["worker_id"],
                row["owner"],
                actor,
                actor_role,
                "remove",
                row["kind"],
                row["name"],
            )
            self._conn.commit()
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    def share_user_view(self, worker_id: str, user_name: str) -> dict[str, Any]:
        user = normalize_username(user_name)
        grant = self.share_grant_status(worker_id, user)
        with self._lock:
            files = self._conn.execute(
                "SELECT * FROM share_files WHERE worker_id=? AND owner=? ORDER BY created_at DESC",
                (worker_id, user),
            ).fetchall()
            events = self._conn.execute(
                """
                SELECT * FROM share_events
                WHERE worker_id=? AND owner=? AND action IN ('remove','cancel') AND actor_role IN ('worker','admin')
                ORDER BY id DESC LIMIT 40
                """,
                (worker_id, user),
            ).fetchall()
        return {
            "worker_id": worker_id,
            "grant": grant,
            "files": [self._share_row(r) for r in files],
            "uploads": self._share_active_uploads(worker_id, user),
            "events": [dict(r) for r in events],
        }

    def share_staff_view(self, worker_id: str) -> dict[str, Any]:
        with self._lock:
            files = self._conn.execute(
                "SELECT * FROM share_files WHERE worker_id=? ORDER BY owner, kind, created_at DESC",
                (worker_id,),
            ).fetchall()
            grants = self._conn.execute(
                "SELECT * FROM share_grants WHERE worker_id=? ORDER BY created_at DESC",
                (worker_id,),
            ).fetchall()
            events = self._conn.execute(
                """
                SELECT * FROM share_events WHERE worker_id=?
                AND action IN ('upload','remove','apply','approve','revoke','cancel')
                ORDER BY id DESC LIMIT 60
                """,
                (worker_id,),
            ).fetchall()
        return {
            "worker_id": worker_id,
            "files": [self._share_row(r) for r in files],
            "uploads": self._share_active_uploads(worker_id),
            "grants": [dict(r) for r in grants],
            "events": [dict(r) for r in events],
        }
