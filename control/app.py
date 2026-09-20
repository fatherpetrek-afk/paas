from __future__ import annotations

import io
import mimetypes
import secrets
import shutil
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from control.config import ARTIFACT_DIR, PUBLIC_URL, SESSION_TTL_SEC, SHARE_MAX_BYTES, WORKER_CONSOLE_PORT
from control.netinfo import access_info
from control.packaging import materialize_upload
from control.project import build_project, manifest_from_spec, spec_to_scan
from control.scan import env_match
from control.store import Store
from control.ui_proxy import mount_job_ui
from shared.authfmt import group_digits, normalize_username
from shared.protocol import (
    DEFAULT_TIMEOUT_SEC,
    HeartbeatIn,
    JobLease,
    JobLogIn,
    JobManifest,
    ResourceLimits,
    WorkerRegisterIn,
    WorkerRegisterOut,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
store = Store()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    store.reset_worker_passwords()
    yield
    store.reset_worker_passwords()


app = FastAPI(title="Team PaaS", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:9090", "http://localhost:9090"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def cookie_as_bearer(request, call_next):
    headers = list(request.scope.get("headers") or [])
    if not any(key == b"authorization" for key, _ in headers):
        token = request.cookies.get("paas_session") or ""
        if token:
            request.scope["headers"] = [(b"authorization", f"Bearer {token}".encode("utf-8"))] + headers
    return await call_next(request)


class NoCacheStatic(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


app.mount("/static", NoCacheStatic(directory=STATIC_DIR), name="static")
mount_job_ui(app, store)


def _session_cookie(payload: dict, token: str) -> JSONResponse:
    resp = JSONResponse(payload)
    resp.set_cookie(
        "paas_session",
        token,
        max_age=SESSION_TTL_SEC,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return resp


def _bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def require_session(authorization: str | None = Header(default=None)) -> dict:
    token = _bearer(authorization)
    info = store.session_info(token)
    if info is None:
        raise HTTPException(401, "login required")
    return info


def require_user(authorization: str | None = Header(default=None)) -> dict:
    sess = require_session(authorization)
    if sess["role"] != "user":
        raise HTTPException(403, "user only")
    return sess


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    sess = require_session(authorization)
    if sess["role"] != "admin":
        raise HTTPException(403, "admin only")
    return sess


def require_portal(authorization: str | None = Header(default=None)) -> dict:
    return require_session(authorization)


def require_worker(x_worker_token: str | None = Header(default=None, alias="X-Worker-Token")) -> dict:
    if not x_worker_token:
        raise HTTPException(401, "missing worker token")
    worker = store.worker_by_token(x_worker_token)
    if worker is None:
        raise HTTPException(401, "bad worker token")
    return worker


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""
    key: str | None = None
    role: str = "user"


class RegisterIn(BaseModel):
    username: str = ""
    password: str = ""
    role: str = "user"


class ApproveIn(BaseModel):
    username: str


class AccountStatusIn(BaseModel):
    status: str


class LimitsIn(BaseModel):
    cpu_cores: float | None = None
    memory_mb: int | None = None
    gpu_count: int | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/info")
def info() -> dict:
    data = access_info()
    data["engine"] = "python"
    data["needs_nodejs"] = False
    data["worker_console"] = f"http://127.0.0.1:{WORKER_CONSOLE_PORT}"
    return data


@app.post("/api/v1/auth/register")
def register_user(body: RegisterIn) -> dict:
    role = (body.role or "user").strip().lower()
    if role not in {"user", "worker"}:
        raise HTTPException(400, "bad_username")
    result = store.apply_account(body.username, body.password, kind=role)
    if result == "bad_username":
        raise HTTPException(400, "bad_username")
    if result == "bad_password":
        raise HTTPException(400, "bad_password")
    if result == "taken":
        raise HTTPException(409, "username_taken")
    return {"ok": True, "submitted": True}


@app.post("/api/v1/auth/login")
def login(body: LoginIn) -> dict:
    role = (body.role or "user").strip().lower()
    username = normalize_username(body.username)
    if role == "admin":
        result = store.authenticate_admin(username, body.password)
        if result == "unregistered":
            raise HTTPException(401, "unregistered")
        if result == "bad_password":
            raise HTTPException(401, "bad_password")
        if result == "platform_off":
            raise HTTPException(403, "platform_off")
        try:
            token = store.create_session(username, "admin")
        except ValueError as exc:
            if str(exc) == "already_logged_in":
                raise HTTPException(409, "already_logged_in") from exc
            raise
        return _session_cookie(
            {
                "token": token,
                "role": "admin",
                "user": username,
                "user_display": group_digits(username),
            },
            token,
        )
    if role == "worker":
        result = store.authenticate(username, body.password, kind="worker")
        if result == "unregistered":
            raise HTTPException(401, "unregistered")
        if result == "bad_password":
            raise HTTPException(401, "bad_password")
        return {
            "ok": True,
            "role": "worker",
            "user": username,
            "user_display": group_digits(username),
        }
    if role != "user":
        raise HTTPException(401, "unregistered")
    result = store.authenticate(username, body.password)
    if result == "unregistered":
        raise HTTPException(401, "unregistered")
    if result == "bad_password":
        raise HTTPException(401, "bad_password")
    try:
        token = store.create_session(username, "user")
    except ValueError as exc:
        if str(exc) == "already_logged_in":
            raise HTTPException(409, "already_logged_in") from exc
        raise
    return _session_cookie(
        {
            "token": token,
            "role": "user",
            "user": username,
            "user_display": group_digits(username),
        },
        token,
    )


@app.get("/api/v1/auth/me")
def auth_me(user: dict = Depends(require_session)) -> dict:
    return {
        "role": user["role"],
        "user": user["name"],
        "user_display": group_digits(user["name"]),
    }


@app.post("/api/v1/auth/logout")
def logout_user(user: dict = Depends(require_session)) -> dict:
    if user["role"] == "user":
        store.cancel_jobs(user_name=user["name"], reason="user logout")
        idle = store.wait_jobs_idle(user_name=user["name"], timeout=45)
        if not idle:
            raise HTTPException(409, "still_running")
    store.delete_session(user["token"])
    resp = JSONResponse({"ok": True, "cleaned": True})
    resp.delete_cookie("paas_session", path="/")
    return resp


@app.post("/api/v1/workers/register", response_model=WorkerRegisterOut)
def register(body: WorkerRegisterIn) -> WorkerRegisterOut:
    try:
        worker_id, token, platform = store.register_worker(body)
    except ValueError as exc:
        code = str(exc)
        if code == "duplicate":
            raise HTTPException(409, "duplicate") from exc
        if code == "unregistered":
            raise HTTPException(401, "unregistered") from exc
        if code == "bad_password":
            raise HTTPException(401, "bad_password") from exc
        raise HTTPException(400, code) from exc
    return WorkerRegisterOut(
        worker_id=worker_id,
        worker_token=token,
        is_platform=platform,
        label=worker_id,
    )


@app.post("/api/v1/workers/heartbeat")
def heartbeat(body: HeartbeatIn, worker: dict = Depends(require_worker)) -> dict:
    store.heartbeat(worker["id"], body)
    cancel = False
    stdin: list[str] = []
    if body.current_job_id:
        cancel = store.job_cancel_requested(body.current_job_id) or store.current_job_blocked(
            worker["id"], body.current_job_id
        )
        stdin = store.take_stdin(body.current_job_id)
    plan = store.share_sync_plan(worker["id"])
    pull = [
        {
            **item,
            "url": f"{PUBLIC_URL}/api/v1/workers/me/share/files/{item['id']}",
        }
        for item in plan["pull"]
    ]
    return {
        "ok": True,
        "cancel_job": cancel,
        "stdin": stdin,
        "pause_all": store.pause_all_requested(worker["id"]),
        "share_pull": pull,
        "share_drop": plan["drop"],
    }


@app.get("/api/v1/workers/me/lease")
def lease(worker: dict = Depends(require_worker)) -> dict:
    job = store.lease_job(worker["id"])
    if job is None:
        return {"job": None}
    limits = None
    if worker["security_open"] and job["requested_limits"]:
        limits = ResourceLimits(**job["requested_limits"])
    env = store.worker_environment(worker["id"], job.get("env_id") or "") if job.get("env_id") else None
    lease_body = JobLease(
        job_id=job["id"],
        manifest=JobManifest(**job["manifest"]),
        artifact_url=f"{PUBLIC_URL}/api/v1/jobs/{job['id']}/artifact",
        limits=limits,
        python_exe=(env or {}).get("executable") or None,
    )
    return {"job": lease_body.model_dump()}


@app.get("/api/v1/workers/me/commands")
def commands(worker: dict = Depends(require_worker)) -> dict:
    pending = store.pending_commands(worker["id"])
    items = []
    for c in pending:
        items.append({"id": c["id"], "kind": c["kind"], "payload": c["payload"]})
    return {"commands": items}


@app.post("/api/v1/workers/me/commands/ack")
def ack_commands(ids: list[int], worker: dict = Depends(require_worker)) -> dict:
    store.ack_commands(worker["id"], ids)
    return {"ok": True}


class AnchorIn(BaseModel):
    before_id: str | None = None
    after_id: str | None = None


class ReorderIn(BaseModel):
    job_ids: list[str]


class PauseIn(BaseModel):
    on: bool


class UserNameIn(BaseModel):
    user_name: str


@app.get("/api/v1/workers/me/board")
def worker_board(worker: dict = Depends(require_worker)) -> dict:
    return store.worker_board(worker["id"])


@app.post("/api/v1/workers/me/pause")
def worker_pause(body: PauseIn, worker: dict = Depends(require_worker)) -> dict:
    return store.set_pause_all(worker["id"], body.on)


@app.post("/api/v1/workers/me/anchors")
def worker_anchor(body: AnchorIn, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.insert_anchor(worker["id"], before_id=body.before_id, after_id=body.after_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/workers/me/anchors/{anchor_id}/release")
def worker_release_anchor(anchor_id: str, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.release_anchor(worker["id"], anchor_id)
    except KeyError:
        raise HTTPException(404, "anchor not found") from None


@app.post("/api/v1/workers/me/reorder")
def worker_reorder(body: ReorderIn, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.reorder_after_anchor(worker["id"], body.job_ids)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.delete("/api/v1/workers/me/queue/{job_id}")
def worker_delete_queued(job_id: str, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.worker_delete_queued(worker["id"], job_id)
    except KeyError:
        raise HTTPException(404, "job not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/workers/me/block")
def worker_block(body: UserNameIn, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.block_user(worker["id"], body.user_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/v1/workers/me/unblock")
def worker_unblock(body: UserNameIn, worker: dict = Depends(require_worker)) -> dict:
    return store.unblock_user(worker["id"], body.user_name)


@app.post("/api/v1/workers/me/approve")
def worker_approve(_: ApproveIn, __: dict = Depends(require_worker)) -> dict:
    raise HTTPException(403, "approval moved to Admin")


@app.post("/api/v1/workers/me/leave")
def worker_leave(worker: dict = Depends(require_worker)) -> dict:
    store.release_worker(worker["id"])
    return {"ok": True}


@app.post("/api/v1/workers/me/logout")
def worker_logout(worker: dict = Depends(require_worker)) -> dict:
    store.cancel_jobs(worker_id=worker["id"], reason="worker logout")
    idle = store.wait_jobs_idle(worker_id=worker["id"], timeout=45)
    if not idle:
        raise HTTPException(409, "still_running")
    store.release_worker(worker["id"])
    return {"ok": True, "cleaned": True}


@app.post("/api/v1/workers/me/jobs/{job_id}/stop")
def worker_stop_job(job_id: str, worker: dict = Depends(require_worker)) -> dict:
    job = store.get_job(job_id)
    if job is None or job["worker_id"] != worker["id"]:
        raise HTTPException(404, "job not found")
    try:
        updated = store.request_cancel(job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.append_log(job_id, "system", "stop requested by Worker")
    return {"job": updated}


@app.get("/api/v1/workers")
def list_workers(_: dict = Depends(require_portal)) -> dict:
    return {"workers": store.list_workers()}


def _share_http(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        raise HTTPException(404, str(exc) or "not found") from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(403, str(exc)) from exc
    if str(exc) == "cancelled":
        raise HTTPException(409, "cancelled") from exc
    raise HTTPException(400, str(exc)) from exc


class ShareStartIn(BaseModel):
    worker_id: str = ""
    kind: str = "open"
    name: str = "file"


class ShareSyncIn(BaseModel):
    pulled: list[str] = []
    dropped: list[str] = []


async def _read_share_bytes(artifact: UploadFile, upload_id: str) -> bytes:
    buf = bytearray()
    while True:
        if store.share_upload_is_cancelled(upload_id):
            raise ValueError("cancelled")
        chunk = await artifact.read(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > SHARE_MAX_BYTES:
            raise ValueError("too_large")
    if store.share_upload_is_cancelled(upload_id):
        raise ValueError("cancelled")
    return bytes(buf)


def _share_download(rec: dict) -> FileResponse:
    path = Path(rec["stored_path"])
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=rec["name"], media_type="application/octet-stream")


@app.get("/api/v1/share")
def user_share(worker_id: str = Query(...), user: dict = Depends(require_user)) -> dict:
    if store.get_worker(worker_id) is None:
        raise HTTPException(404, "worker not found")
    return store.share_user_view(worker_id, user["name"])


@app.post("/api/v1/share/apply")
def user_share_apply(worker_id: str = Query(...), user: dict = Depends(require_user)) -> dict:
    try:
        return store.share_apply(worker_id, user["name"])
    except (KeyError, ValueError) as exc:
        _share_http(exc)
        raise


@app.post("/api/v1/share/uploads")
def user_share_start(body: ShareStartIn, user: dict = Depends(require_user)) -> dict:
    try:
        return store.share_upload_start(body.worker_id, user["name"], body.kind, body.name, user["name"], "user")
    except (KeyError, ValueError) as exc:
        _share_http(exc)
        raise


@app.post("/api/v1/share/uploads/{upload_id}")
async def user_share_put(upload_id: str, artifact: UploadFile = File(...), user: dict = Depends(require_user)) -> dict:
    rec = store.share_upload_get(upload_id)
    if rec is None or rec["owner"] != user["name"] or rec["status"] != "uploading":
        raise HTTPException(404, "upload not found")
    try:
        raw = await _read_share_bytes(artifact, upload_id)
        view = store.share_upload(
            rec["worker_id"], rec["owner"], rec["kind"], rec["name"], raw, user["name"], "user"
        )
        store.share_upload_finish(upload_id)
        return view
    except (KeyError, ValueError) as exc:
        store.share_upload_finish(upload_id)
        _share_http(exc)
        raise


@app.post("/api/v1/share/uploads/{upload_id}/cancel")
def user_share_cancel(upload_id: str, user: dict = Depends(require_user)) -> dict:
    try:
        return store.share_cancel_upload(upload_id, user["name"], "user", owner=user["name"])
    except (KeyError, ValueError, PermissionError) as exc:
        _share_http(exc)
        raise


@app.post("/api/v1/share/files")
async def user_share_upload(
    worker_id: str = Form(...),
    kind: str = Form(...),
    artifact: UploadFile = File(...),
    user: dict = Depends(require_user),
) -> dict:
    rec = store.share_upload_start(worker_id, user["name"], kind, artifact.filename or "file", user["name"], "user")
    try:
        raw = await _read_share_bytes(artifact, rec["id"])
        view = store.share_upload(
            worker_id, user["name"], kind, artifact.filename or "file", raw, user["name"], "user"
        )
        store.share_upload_finish(rec["id"])
        return view
    except (KeyError, ValueError) as exc:
        if str(exc) != "cancelled":
            try:
                store.share_cancel_upload(rec["id"], user["name"], "user", owner=user["name"])
            except (KeyError, ValueError, PermissionError):
                pass
        store.share_upload_finish(rec["id"])
        _share_http(exc)
        raise


@app.get("/api/v1/share/files/{file_id}")
def user_share_download(file_id: str, user: dict = Depends(require_user)) -> FileResponse:
    rec = store.share_get(file_id)
    if rec is None or rec["owner"] != user["name"]:
        raise HTTPException(404, "file not found")
    return _share_download(rec)


@app.delete("/api/v1/share/files/{file_id}")
def user_share_delete(file_id: str, user: dict = Depends(require_user)) -> dict:
    try:
        store.share_remove(file_id, user["name"], "user", owner=user["name"])
    except (KeyError, PermissionError) as exc:
        _share_http(exc)
        raise
    return {"ok": True}


@app.get("/api/v1/workers/me/share")
def worker_share(worker: dict = Depends(require_worker)) -> dict:
    return store.share_staff_view(worker["id"])


@app.post("/api/v1/workers/me/share/grants/{username}/approve")
def worker_share_approve(username: str, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.share_set_grant(worker["id"], username, True, worker.get("name") or "worker", "worker")
    except ValueError as exc:
        _share_http(exc)
        raise


@app.post("/api/v1/workers/me/share/grants/{username}/revoke")
def worker_share_revoke(username: str, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.share_set_grant(worker["id"], username, False, worker.get("name") or "worker", "worker")
    except ValueError as exc:
        _share_http(exc)
        raise


@app.get("/api/v1/workers/me/share/files/{file_id}")
def worker_share_download(file_id: str, worker: dict = Depends(require_worker)) -> FileResponse:
    rec = store.share_get(file_id)
    if rec is None or rec["worker_id"] != worker["id"]:
        raise HTTPException(404, "file not found")
    return _share_download(rec)


@app.delete("/api/v1/workers/me/share/files/{file_id}")
def worker_share_delete(file_id: str, worker: dict = Depends(require_worker)) -> dict:
    rec = store.share_get(file_id)
    if rec is None or rec["worker_id"] != worker["id"]:
        raise HTTPException(404, "file not found")
    store.share_remove(file_id, worker.get("name") or "worker", "worker")
    return {"ok": True}


@app.post("/api/v1/workers/me/share/uploads/{upload_id}/cancel")
def worker_share_cancel(upload_id: str, worker: dict = Depends(require_worker)) -> dict:
    try:
        return store.share_cancel_upload(
            upload_id, worker.get("name") or "worker", "worker", worker_id=worker["id"]
        )
    except (KeyError, ValueError, PermissionError) as exc:
        _share_http(exc)
        raise


@app.post("/api/v1/workers/me/share/sync")
def worker_share_sync(body: ShareSyncIn, worker: dict = Depends(require_worker)) -> dict:
    store.share_sync_ack(worker["id"], body.pulled, body.dropped)
    return {"ok": True}


@app.get("/api/v1/admin/workers/{worker_id}/share")
def admin_share(worker_id: str, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    return store.share_staff_view(worker_id)


@app.post("/api/v1/admin/workers/{worker_id}/share/grants/{username}/approve")
def admin_share_approve(worker_id: str, username: str, admin: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.share_set_grant(worker_id, username, True, admin["name"], "admin")
    except ValueError as exc:
        _share_http(exc)
        raise


@app.post("/api/v1/admin/workers/{worker_id}/share/grants/{username}/revoke")
def admin_share_revoke(worker_id: str, username: str, admin: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.share_set_grant(worker_id, username, False, admin["name"], "admin")
    except ValueError as exc:
        _share_http(exc)
        raise


@app.get("/api/v1/admin/workers/{worker_id}/share/files/{file_id}")
def admin_share_download(worker_id: str, file_id: str, _: dict = Depends(require_admin)) -> FileResponse:
    rec = store.share_get(file_id)
    if rec is None or rec["worker_id"] != worker_id:
        raise HTTPException(404, "file not found")
    return _share_download(rec)


@app.delete("/api/v1/admin/workers/{worker_id}/share/files/{file_id}")
def admin_share_delete(worker_id: str, file_id: str, admin: dict = Depends(require_admin)) -> dict:
    rec = store.share_get(file_id)
    if rec is None or rec["worker_id"] != worker_id:
        raise HTTPException(404, "file not found")
    store.share_remove(file_id, admin["name"], "admin")
    return {"ok": True}


@app.post("/api/v1/admin/workers/{worker_id}/share/uploads/{upload_id}/cancel")
def admin_share_cancel(worker_id: str, upload_id: str, admin: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.share_cancel_upload(upload_id, admin["name"], "admin", worker_id=worker_id)
    except (KeyError, ValueError, PermissionError) as exc:
        _share_http(exc)
        raise



@app.get("/api/v1/admin/accounts")
def admin_accounts(_: dict = Depends(require_admin)) -> dict:
    return {
        "accounts": store.list_accounts(kind="user"),
        "workers": store.list_accounts(kind="worker"),
        "history": store.approval_history(),
    }


@app.get("/api/v1/admin/accounts/{username}")
def admin_account_detail(username: str, _: dict = Depends(require_admin)) -> dict:
    detail = store.account_detail(username)
    if detail is None:
        raise HTTPException(404, "account not found")
    return detail


@app.get("/api/v1/admin/approvals")
def admin_approvals(_: dict = Depends(require_admin)) -> dict:
    return {"history": store.approval_history()}


@app.post("/api/v1/admin/accounts/{username}/approve")
def admin_approve(username: str, admin: dict = Depends(require_admin)) -> dict:
    try:
        store.approve_account(username, admin["name"])
    except KeyError:
        raise HTTPException(404, "account not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.post("/api/v1/admin/accounts/{username}/status")
def admin_set_status(username: str, body: AccountStatusIn, admin: dict = Depends(require_admin)) -> dict:
    try:
        store.set_account_status(username, body.status, admin["name"])
    except KeyError:
        raise HTTPException(404, "account not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.delete("/api/v1/admin/accounts/{username}")
def admin_remove_account(username: str, admin: dict = Depends(require_admin)) -> dict:
    try:
        store.remove_account(username, admin["name"])
    except KeyError:
        raise HTTPException(404, "account not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.delete("/api/v1/admin/workers/{worker_id}")
def admin_remove_worker(worker_id: str, admin: dict = Depends(require_admin)) -> dict:
    try:
        store.remove_worker(worker_id, admin["name"])
    except KeyError:
        raise HTTPException(404, "worker not found") from None
    return {"ok": True}


def _admin_worker(worker_id: str) -> dict:
    worker = store.get_worker(worker_id)
    if worker is None:
        raise HTTPException(404, "worker not found")
    return worker


@app.get("/api/v1/admin/workers/{worker_id}/board")
def admin_worker_board(worker_id: str, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.worker_board(worker_id)
    except KeyError:
        raise HTTPException(404, "worker not found") from None


@app.post("/api/v1/admin/workers/{worker_id}/pause")
def admin_worker_pause(worker_id: str, body: PauseIn, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    return store.set_pause_all(worker_id, body.on)


@app.post("/api/v1/admin/workers/{worker_id}/anchors")
def admin_worker_anchor(worker_id: str, body: AnchorIn, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.insert_anchor(worker_id, before_id=body.before_id, after_id=body.after_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/admin/workers/{worker_id}/anchors/{anchor_id}/release")
def admin_release_anchor(worker_id: str, anchor_id: str, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.release_anchor(worker_id, anchor_id)
    except KeyError:
        raise HTTPException(404, "anchor not found") from None


@app.post("/api/v1/admin/workers/{worker_id}/reorder")
def admin_worker_reorder(worker_id: str, body: ReorderIn, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.reorder_after_anchor(worker_id, body.job_ids)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.delete("/api/v1/admin/workers/{worker_id}/queue/{job_id}")
def admin_delete_queued(worker_id: str, job_id: str, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.worker_delete_queued(worker_id, job_id)
    except KeyError:
        raise HTTPException(404, "job not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/admin/workers/{worker_id}/jobs/{job_id}/stop")
def admin_stop_job(worker_id: str, job_id: str, _: dict = Depends(require_admin)) -> dict:
    job = store.get_job(job_id)
    if job is None or job["worker_id"] != worker_id:
        raise HTTPException(404, "job not found")
    try:
        updated = store.request_cancel(job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.append_log(job_id, "system", "stop requested by Admin")
    return {"job": updated}


@app.post("/api/v1/admin/workers/{worker_id}/block")
def admin_block_user(worker_id: str, body: UserNameIn, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    try:
        return store.block_user(worker_id, body.user_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/v1/admin/workers/{worker_id}/unblock")
def admin_unblock_user(worker_id: str, body: UserNameIn, _: dict = Depends(require_admin)) -> dict:
    _admin_worker(worker_id)
    return store.unblock_user(worker_id, body.user_name)


@app.post("/api/v1/workers/{worker_id}/limits")
def set_limits(worker_id: str, body: LimitsIn, _: dict = Depends(require_portal)) -> dict:
    worker = store.get_worker(worker_id)
    if worker is None:
        raise HTTPException(404, "worker not found")
    if not worker["locks"]["security_open"]:
        raise HTTPException(403, "Remote CPU/GPU limits are off on this Worker.")
    cmd_id = store.enqueue_limits(worker_id, ResourceLimits(**body.model_dump()))
    return {"command_id": cmd_id}


async def _job_bytes(
    *,
    user_name: str,
    worker_id: str | None,
    share_file_id: str | None,
    artifact: UploadFile | None,
) -> tuple[str, bytes, str | None]:
    if share_file_id:
        rec = store.share_get(share_file_id)
        if rec is None:
            raise HTTPException(404, "file not found")
        wid = worker_id or rec.get("worker_id")
        if not wid:
            raise HTTPException(400, "Pick a Worker")
        try:
            rec = store.share_read_for_submit(share_file_id, user_name, str(wid))
        except KeyError as exc:
            raise HTTPException(404, str(exc) or "file not found") from exc
        except ValueError as exc:
            _share_http(exc)
            raise
        return rec["name"], Path(rec["stored_path"]).read_bytes(), str(wid)
    if artifact is None:
        raise HTTPException(400, "Choose a single file or a zip")
    raw = await artifact.read()
    return artifact.filename or "job.py", raw, worker_id


@app.post("/api/v1/jobs/scan")
async def scan_upload(
    artifact: UploadFile | None = File(default=None),
    kind: str = Form(default="auto"),
    worker_id: str | None = Form(default=None),
    share_file_id: str | None = Form(default=None),
    place: str = Form(default="manual"),
    user: dict = Depends(require_user),
) -> dict:
    name, raw, share_worker = await _job_bytes(
        user_name=user["name"], worker_id=worker_id, share_file_id=share_file_id, artifact=artifact
    )
    if not raw:
        raise HTTPException(400, "empty upload")
    spec = build_project(name, raw, kind)
    scan = spec_to_scan(spec)
    auto = (place or "").lower() == "auto" or (worker_id or "").lower() == "auto"
    pin = share_worker if share_file_id else (None if auto else worker_id)
    placed = store.placements(user["name"], scan, worker_id=pin)
    if pin:
        verdicts = store.env_verdicts(pin, scan)
    elif placed:
        verdicts = store.env_verdicts(placed[0]["worker_id"], scan)
    else:
        verdicts = []
    return {"scan": scan, "verdicts": verdicts, "placements": placed, "placement": placed[0] if placed else None}


@app.post("/api/v1/jobs")
async def create_job(
    worker_id: str | None = Form(default=None),
    env_id: str | None = Form(default=None),
    cpu_cores: float | None = Form(default=None),
    memory_mb: int | None = Form(default=None),
    gpu_count: int | None = Form(default=None),
    artifact: UploadFile | None = File(default=None),
    share_file_id: str | None = Form(default=None),
    kind: str = Form(default="auto"),
    place: str = Form(default="manual"),
    user: dict = Depends(require_user),
) -> dict:
    name, raw, share_worker = await _job_bytes(
        user_name=user["name"], worker_id=worker_id, share_file_id=share_file_id, artifact=artifact
    )
    if not raw:
        raise HTTPException(400, "empty upload")
    spec = build_project(name, raw, kind)
    scan = spec_to_scan(spec)
    place_auto = (place or "").lower() == "auto" or (worker_id or "").lower() == "auto"
    if (worker_id or "").lower() == "auto":
        worker_id = None
    if place_auto:
        placed = store.placements(user["name"], scan, worker_id=share_worker)
        if not placed:
            raise HTTPException(409, "No Worker can run this")
        worker_id = share_worker or placed[0]["worker_id"]
        if not env_id:
            env_id = placed[0]["env_id"]
    else:
        worker_id = share_worker or worker_id
        if not worker_id:
            raise HTTPException(400, "Pick a Worker")
        if not env_id:
            placed = store.placements(user["name"], scan, worker_id=worker_id)
            if not placed:
                raise HTTPException(409, "No Worker can run this")
            env_id = placed[0]["env_id"]
    if not env_id:
        raise HTTPException(400, "pick an environment that can run this code")
    job_id_dir = ARTIFACT_DIR / secrets.token_hex(8)
    job_id_dir.mkdir(parents=True, exist_ok=True)
    zip_path = job_id_dir / "job.zip"
    materialize_upload(name, raw, zip_path, kind=kind, spec=spec)
    return _submit_zip(zip_path, worker_id, cpu_cores, memory_mb, gpu_count, user["name"], env_id, scan)


@app.get("/api/v1/jobs")
def list_jobs(user: dict = Depends(require_user)) -> dict:
    return {"jobs": store.list_jobs(user_name=user["name"]), "user": user["name"]}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, _: dict = Depends(require_portal)) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {"job": job}


@app.post("/api/v1/jobs/{job_id}/stop")
def stop_job(job_id: str, sess: dict = Depends(require_portal)) -> dict:
    if sess.get("role") not in {"user", "admin"}:
        raise HTTPException(403, "forbidden")
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if sess.get("role") == "user" and job.get("user_name") != sess.get("name"):
        raise HTTPException(403, "forbidden")
    try:
        job = store.request_cancel(job_id)
    except KeyError:
        raise HTTPException(404, "job not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    who = "Admin" if sess.get("role") == "admin" else "User"
    store.append_log(job_id, "system", f"stop requested by {who}")
    return {"job": job}


class StdinIn(BaseModel):
    text: str = ""


@app.post("/api/v1/jobs/{job_id}/stdin")
def job_stdin(job_id: str, body: StdinIn, _: dict = Depends(require_user)) -> dict:
    try:
        store.push_stdin(job_id, body.text)
    except KeyError:
        raise HTTPException(404, "job not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.append_log(job_id, "stdin", body.text)
    return {"ok": True}


@app.delete("/api/v1/jobs/{job_id}")
def delete_job(job_id: str, _: None = Depends(require_user)) -> dict:
    raise HTTPException(403, "User cannot remove a submitted job. A Worker can remove queued jobs after Pause all or an anchor.")


@app.get("/api/v1/jobs/{job_id}/logs")
def get_logs(job_id: str, after: int = 0, _: dict = Depends(require_portal)) -> dict:
    return {"logs": store.job_logs(job_id, after)}


@app.get("/api/v1/jobs/{job_id}/artifact")
def download_artifact(job_id: str, worker: dict = Depends(require_worker)) -> FileResponse:
    job = store.get_job(job_id)
    if job is None or job["worker_id"] != worker["id"]:
        raise HTTPException(404, "artifact not found")
    return FileResponse(job["artifact_path"], filename="job.zip")


@app.post("/api/v1/jobs/{job_id}/logs")
def push_log(job_id: str, body: JobLogIn, worker: dict = Depends(require_worker)) -> dict:
    job = store.get_job(job_id)
    if job is None or job["worker_id"] != worker["id"]:
        raise HTTPException(404, "job not found")
    store.append_log(job_id, body.stream, body.line)
    return {"ok": True}


@app.post("/api/v1/jobs/{job_id}/complete")
async def complete_job(
    job_id: str,
    exit_code: int = Form(...),
    error: str | None = Form(default=None),
    result: UploadFile | None = File(default=None),
    worker: dict = Depends(require_worker),
) -> dict:
    job = store.get_job(job_id)
    if job is None or job["worker_id"] != worker["id"]:
        raise HTTPException(404, "job not found")
    result_path = None
    if result is not None:
        dest = Path(job["artifact_path"]).parent / "result.bin"
        dest.write_bytes(await result.read())
        result_path = str(dest)
    store.complete_job(job_id, exit_code, error, result_path)
    return {"ok": True}


@app.get("/api/v1/jobs/{job_id}/result")
def download_result(job_id: str, _: dict = Depends(require_portal)) -> FileResponse:
    job = store.get_job(job_id)
    if job is None or not job["result_path"]:
        raise HTTPException(404, "no result")
    return FileResponse(job["result_path"], filename="result.bin")


def _live_dir(job: dict) -> Path:
    return Path(job["artifact_path"]).parent / "live"


def _owned_job(job_id: str, user_name: str) -> dict:
    job = store.get_job(job_id)
    if job is None or job.get("user_name") != user_name:
        raise HTTPException(404, "job not found")
    return job


def _job_result_bytes(job: dict) -> tuple[str, bytes]:
    name = f"{job.get('name') or 'job'}-result.zip"
    result = job.get("result_path")
    if result and Path(result).is_file():
        return name, Path(result).read_bytes()
    live = _live_dir(job)
    if live.is_dir():
        buf = io.BytesIO()
        wrote = False
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in live.rglob("*"):
                if not path.is_file():
                    continue
                zf.write(path, path.relative_to(live).as_posix())
                wrote = True
        if wrote:
            return name, buf.getvalue()
    raise HTTPException(404, "no result")


@app.post("/api/v1/jobs/{job_id}/rerun")
def rerun_job(job_id: str, user: dict = Depends(require_user)) -> dict:
    job = _owned_job(job_id, user["name"])
    if job["state"] in {"queued", "running"}:
        raise HTTPException(409, "job still active")
    src = Path(job.get("artifact_path") or "")
    if not src.is_file():
        raise HTTPException(404, "artifact gone")
    env_id = job.get("env_id") or ""
    if not env_id:
        raise HTTPException(400, "pick an environment that can run this code")
    dest_dir = ARTIFACT_DIR / secrets.token_hex(8)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "job.zip"
    shutil.copy2(src, dest)
    spec = build_project("job.zip", dest.read_bytes(), "zip")
    scan = spec_to_scan(spec)
    limits = job.get("requested_limits") or {}
    return _submit_zip(
        dest,
        job["worker_id"],
        limits.get("cpu_cores"),
        limits.get("memory_mb"),
        limits.get("gpu_count"),
        user["name"],
        env_id,
        scan,
    )


@app.post("/api/v1/jobs/{job_id}/store")
def store_job_result(job_id: str, user: dict = Depends(require_user)) -> dict:
    job = _owned_job(job_id, user["name"])
    if job["state"] in {"queued", "running"}:
        raise HTTPException(409, "job still active")
    filename, raw = _job_result_bytes(job)
    if len(raw) > SHARE_MAX_BYTES:
        raise HTTPException(413, "too_large")
    try:
        view = store.share_upload(
            job["worker_id"],
            user["name"],
            "open",
            filename,
            raw,
            user["name"],
            "user",
        )
    except (KeyError, PermissionError, ValueError) as exc:
        _share_http(exc)
    store.append_log(job_id, "system", f"stored {filename} to Open")
    return view


def _safe_rel(name: str) -> Path:
    n = str(name or "").replace("\\", "/").lstrip("/")
    parts = [p for p in n.split("/") if p not in {"", ".", ".."}]
    if not parts:
        raise HTTPException(400, "bad path")
    return Path(*parts)


@app.post("/api/v1/jobs/{job_id}/live-output")
async def live_output(
    job_id: str,
    name: str = Form(...),
    file: UploadFile = File(...),
    worker: dict = Depends(require_worker),
) -> dict:
    job = store.get_job(job_id)
    if job is None or job["worker_id"] != worker["id"]:
        raise HTTPException(404, "job not found")
    rel = _safe_rel(name)
    dest = _live_dir(job) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = await file.read()
    if len(raw) > SHARE_MAX_BYTES:
        raise HTTPException(413, "too_large")
    dest.write_bytes(raw)
    return {"ok": True}


def _live_entries(job: dict) -> dict[str, tuple[int, int]]:
    root = _live_dir(job)
    if not root.is_dir():
        return {}
    out: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            try:
                st = path.stat()
                out[path.relative_to(root).as_posix()] = (int(st.st_size), int(st.st_mtime_ns))
            except OSError:
                continue
    return out


def _zip_entries(job: dict) -> dict[str, tuple[int, int]]:
    path = job.get("result_path")
    if not path or not Path(path).is_file():
        return {}
    try:
        with zipfile.ZipFile(path) as zf:
            return {
                info.filename.replace("\\", "/"): (int(info.file_size), 0)
                for info in zf.infolist()
                if not info.is_dir()
            }
    except zipfile.BadZipFile:
        return {}


@app.get("/api/v1/jobs/{job_id}/output")
def list_output(job_id: str, _: dict = Depends(require_portal)) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    entries = _zip_entries(job)
    entries.update(_live_entries(job))
    files = [
        {"name": name, "size": size, "mtime": mtime}
        for name, (size, mtime) in sorted(entries.items())
    ]
    return {"files": files}


@app.get("/api/v1/jobs/{job_id}/output/{path:path}")
def get_output_file(job_id: str, path: str, _: dict = Depends(require_portal)) -> Response:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    rel = _safe_rel(path)
    live = _live_dir(job) / rel
    if live.is_file():
        ctype, _ = mimetypes.guess_type(rel.name)
        return FileResponse(live, media_type=ctype or "application/octet-stream")
    name = rel.as_posix()
    path_zip = job.get("result_path")
    if not path_zip or not Path(path_zip).is_file():
        raise HTTPException(404, "file not found")
    try:
        with zipfile.ZipFile(path_zip) as zf:
            names = {info.filename.replace("\\", "/"): info.filename for info in zf.infolist() if not info.is_dir()}
            raw_name = names.get(name)
            if raw_name is None:
                raise HTTPException(404, "file not found")
            data = zf.read(raw_name)
    except zipfile.BadZipFile as exc:
        raise HTTPException(404, "file not found") from exc
    ctype, _ = mimetypes.guess_type(name)
    return Response(content=data, media_type=ctype or "application/octet-stream")


@app.get("/api/v1/metrics")
def metrics(worker_id: str | None = None, _: dict = Depends(require_portal)) -> dict:
    return {"samples": store.metrics(worker_id)}


def _submit_zip(
    zip_path: Path,
    worker_id: str,
    cpu_cores: float | None,
    memory_mb: int | None,
    gpu_count: int | None,
    user_name: str,
    env_id: str,
    scan: dict,
) -> dict:
    manifest = _manifest_from_zip(zip_path)
    ok, reason = store.worker_can_run(worker_id, manifest, user_name=user_name)
    if not ok:
        raise HTTPException(409, reason)
    worker = store.get_worker(worker_id)
    env = store.worker_environment(worker_id, env_id)
    if env is None:
        raise HTTPException(409, "pick an environment on this Worker")
    match = env_match(scan, env)
    if not match["ok"]:
        raise HTTPException(409, match["reason"])
    if scan.get("needs_admin") and not (worker and worker["locks"].get("admin_open")):
        raise HTTPException(
            403,
            "Installs & file changes is off. This program would install packages or change Worker files.",
        )
    kind = env.get("kind") or ""
    if kind == "python" and env.get("version"):
        parts = str(env["version"]).split(".")
        runtime = "python:" + ".".join(parts[:2]) if len(parts) >= 2 else "python"
        manifest = manifest.model_copy(update={"runtime": runtime})
    elif kind == "node":
        manifest = manifest.model_copy(update={"runtime": "node"})
    elif kind and kind != "docker":
        manifest = manifest.model_copy(update={"runtime": kind})
    if int(manifest.timeout_sec or 0) == 300:
        manifest = manifest.model_copy(update={"timeout_sec": DEFAULT_TIMEOUT_SEC})
    limits = None
    if worker and worker["locks"]["security_open"]:
        if cpu_cores or memory_mb or gpu_count:
            limits = ResourceLimits(cpu_cores=cpu_cores, memory_mb=memory_mb, gpu_count=gpu_count)
    job = store.create_job(
        manifest=manifest,
        artifact_path=str(zip_path),
        worker_id=worker_id,
        limits=limits,
        user_name=user_name,
        env_id=env_id,
    )
    store.append_log(
        job["id"],
        "system",
        f"queued for {worker['name'] if worker else worker_id} by {user_name} env={env.get('label')}",
    )
    return {"job": job}


def _manifest_from_zip(zip_path: Path) -> JobManifest:
    import json
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        project_name = next(
            (n for n in names if Path(n).name == "project.json" and "__MACOSX" not in n.split("/")),
            None,
        )
        if project_name:
            spec = json.loads(zf.read(project_name))
            try:
                return JobManifest(**manifest_from_spec(spec))
            except Exception as exc:
                raise HTTPException(400, f"bad project.json: {exc}") from exc
        manifest_name = next(
            (n for n in names if Path(n).name == "manifest.json" and n.count("/") <= 1 and "__MACOSX" not in n.split("/")),
            None,
        )
        if manifest_name is None:
            raise HTTPException(400, "zip must contain project.json or manifest.json")
        data = json.loads(zf.read(manifest_name))
    try:
        return JobManifest(**data)
    except Exception as exc:
        raise HTTPException(400, f"bad manifest: {exc}") from exc
