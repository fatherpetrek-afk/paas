from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import httpx

from shared.authfmt import normalize_password, normalize_username, valid_username
from shared.protocol import (
    EnvironmentInfo,
    HeartbeatIn,
    JobLease,
    JobLogIn,
    JobManifest,
    ResourceLimits,
    WorkerRegisterIn,
)
from worker import identity
from worker.envs import collect_environments
from worker.console import start_console
from worker.executor import collect_output, run_job, unpack
from worker.jobproc import CURRENT
from worker.metrics import (
    collect_gpus,
    cpu_mem,
    docker_available,
    host_arch,
    host_os,
    io_bytes,
    load_locks,
    native_runtimes,
)

CONTROL_URL = os.environ.get("PAAS_CONTROL_URL", "http://127.0.0.1:8080").rstrip("/")
WORKER_NAME = os.environ.get("PAAS_WORKER_NAME", "local-pc")


def _wipe_tree(path: Path, *, children_only: bool = False) -> None:
    targets = list(path.iterdir()) if children_only and path.exists() else [path]
    for item in targets:
        shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
        if item.exists():
            time.sleep(0.25)
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            elif item.exists():
                item.unlink(missing_ok=True)

LOCK_FILE = Path(os.environ.get("PAAS_LOCK_FILE", Path.cwd() / "data" / "worker-locks.json"))
WORK_ROOT = Path(os.environ.get("PAAS_WORKER_DIR", Path.cwd() / "data" / "worker-jobs"))
SHARE_ROOT = Path(os.environ.get("PAAS_WORKER_SHARE", Path.cwd() / "data" / "worker-shared"))
SESSION_FILE = Path(os.environ.get("PAAS_WORKER_SESSION", Path.cwd() / "data" / "worker-session.json"))


class _Runtime:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.headers: dict[str, str] = {}
        self.job_id: str | None = None
        self.stop = threading.Event()
        self.dead = threading.Event()
        self.pause_all = False


def main() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    SHARE_ROOT.mkdir(parents=True, exist_ok=True)
    _wipe_tree(WORK_ROOT, children_only=True)
    start_console()
    has_docker = docker_available()
    gpus, _ = collect_gpus()
    _, _, memory_mb = cpu_mem()
    locks = load_locks(LOCK_FILE)
    env_models = [EnvironmentInfo(**e) for e in collect_environments()]
    body = WorkerRegisterIn(
        name=WORKER_NAME,
        join_token="",
        os=host_os(),
        arch=host_arch(),
        runtimes=native_runtimes(),
        has_docker=has_docker,
        cpu_cores=os.cpu_count() or 1,
        memory_mb=memory_mb,
        gpus=gpus,
        locks=locks,
        environments=env_models,
    )
    rt = _Runtime()
    _resume_session(rt)
    hb_client = httpx.Client(timeout=15.0)
    job_client = httpx.Client(timeout=30.0)
    threading.Thread(
        target=_heartbeat_loop,
        args=(hb_client, body, rt),
        daemon=True,
        name="paas-heartbeat",
    ).start()
    print(f"worker waiting for console password  docker={has_docker} os={host_os()}", flush=True)
    try:
        while not rt.dead.is_set():
            headers = _headers(rt)
            if not headers:
                time.sleep(0.4)
                continue
            if identity.logout_requested():
                rt.stop.set()
                time.sleep(0.2)
                continue
            locks = load_locks(LOCK_FILE)
            if locks.run_open and rt.job_id is None and not rt.pause_all:
                try:
                    leased = job_client.get(f"{CONTROL_URL}/api/v1/workers/me/lease", headers=headers)
                    if leased.status_code == 401:
                        _clear_headers(rt)
                        continue
                    leased.raise_for_status()
                    job_data = leased.json().get("job")
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    print(f"lease failed: {exc}", flush=True)
                    time.sleep(2)
                    continue
                if job_data:
                    lease = JobLease(
                        job_id=job_data["job_id"],
                        manifest=JobManifest(**job_data["manifest"]),
                        artifact_url=job_data["artifact_url"],
                        limits=ResourceLimits(**job_data["limits"]) if job_data.get("limits") else None,
                        python_exe=job_data.get("python_exe"),
                    )
                    rt.stop.clear()
                    with rt.lock:
                        rt.job_id = lease.job_id
                    try:
                        _execute(job_client, headers, lease, has_docker, native_runtimes(), rt.stop)
                    finally:
                        with rt.lock:
                            rt.job_id = None
                        rt.stop.clear()
            time.sleep(0.4)
    finally:
        rt.dead.set()
        headers = _headers(rt)
        if headers:
            try:
                job_client.post(f"{CONTROL_URL}/api/v1/workers/me/leave", headers=headers)
            except httpx.HTTPError:
                pass
        identity.clear()


def _headers(rt: _Runtime) -> dict[str, str]:
    with rt.lock:
        return dict(rt.headers)


def _clear_headers(rt: _Runtime) -> None:
    with rt.lock:
        rt.headers = {}


def _resume_session(rt: _Runtime) -> None:
    if not SESSION_FILE.is_file():
        return
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    token = str(data.get("worker_token") or "")
    label = normalize_username(str(data.get("label") or data.get("worker_id") or ""))
    if not token or not valid_username(label):
        return
    identity.set_label(label)
    with rt.lock:
        rt.headers = {"X-Worker-Token": token}
    identity.mark_joined(True)
    print(f"resumed {label}", flush=True)


def _heartbeat_loop(client: httpx.Client, body: WorkerRegisterIn, rt: _Runtime) -> None:
    while not rt.dead.is_set():
        try:
            headers = _headers(rt)
            label = identity.get_label()
            if headers and identity.joined_label() and label != identity.joined_label():
                try:
                    client.post(f"{CONTROL_URL}/api/v1/workers/me/leave", headers=headers)
                except httpx.HTTPError:
                    pass
                _clear_headers(rt)
                headers = {}
            if not headers:
                user = normalize_username(identity.get_label() or "")
                pw = normalize_password(identity.get_password() or "")
                if not user or not pw:
                    time.sleep(0.4)
                    continue
                payload_body = body.model_copy(
                    update={"name": user, "join_token": user, "username": user, "password": pw}
                )
                reg = client.post(f"{CONTROL_URL}/api/v1/workers/register", json=payload_body.model_dump())
                if reg.status_code == 409:
                    identity.fail("label_taken")
                    time.sleep(0.4)
                    continue
                if reg.status_code == 401:
                    detail = ""
                    try:
                        detail = str(reg.json().get("detail") or "")
                    except Exception:
                        detail = reg.text
                    identity.fail(detail or "unregistered")
                    time.sleep(0.4)
                    continue
                if not reg.is_success:
                    detail = ""
                    try:
                        detail = str(reg.json().get("detail") or "")
                    except Exception:
                        detail = reg.text
                    identity.fail(detail or f"register failed {reg.status_code}")
                    time.sleep(0.8)
                    continue
                payload = reg.json()
                with rt.lock:
                    rt.headers = {"X-Worker-Token": payload["worker_token"]}
                headers = _headers(rt)
                identity.mark_joined(True)
                print(f"registered {user} as {payload['worker_id']}", flush=True)
                SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                SESSION_FILE.write_text(
                    json.dumps(
                        {
                            "control_url": CONTROL_URL,
                            "worker_token": payload["worker_token"],
                            "worker_id": payload["worker_id"],
                            "label": user,
                        }
                    ),
                    encoding="utf-8",
                )

            locks = load_locks(LOCK_FILE)
            gpus, gpu_util = collect_gpus()
            cpu_pct, mem_pct, _ = cpu_mem()
            sent, recv = io_bytes()
            snap = CURRENT.snapshot()
            ui_kind, ui_port = CURRENT.ui()
            with rt.lock:
                job_id = rt.job_id
            hb = HeartbeatIn(
                locks=locks,
                cpu_percent=cpu_pct,
                memory_percent=mem_pct,
                gpu_percent=gpu_util,
                bytes_sent=sent,
                bytes_recv=recv,
                current_job_id=job_id,
                job_cpu_percent=snap.cpu_percent,
                job_proc_count=snap.proc_count,
                environments=[EnvironmentInfo(**e) for e in collect_environments()],
                ui_kind=ui_kind,
                ui_port=ui_port,
            )
            hb_resp = client.post(
                f"{CONTROL_URL}/api/v1/workers/heartbeat",
                json=hb.model_dump(),
                headers=headers,
            )
            if hb_resp.status_code == 401:
                _clear_headers(rt)
                continue
            hb_resp.raise_for_status()
            hb_data = hb_resp.json()
            pause = bool(hb_data.get("pause_all"))
            with rt.lock:
                rt.pause_all = pause
            if pause:
                CURRENT.suspend()
            else:
                CURRENT.resume()
            if hb_data.get("cancel_job"):
                rt.stop.set()
            for line in hb_data.get("stdin") or []:
                CURRENT.push_stdin(str(line))
            _sync_share(client, headers, hb_data)
            _pull_commands(client, headers, locks.security_open)
        except httpx.TransportError as exc:
            print(f"control unreachable, retrying: {exc}", flush=True)
            rt.dead.wait(3)
            continue
        except httpx.HTTPStatusError as exc:
            print(f"heartbeat failed, retrying: {exc}", flush=True)
            if exc.response is not None and exc.response.status_code == 401:
                _clear_headers(rt)
            rt.dead.wait(3)
            continue
        rt.dead.wait(2)


def _sync_share(client: httpx.Client, headers: dict[str, str], hb_data: dict) -> None:
    pulled: list[str] = []
    dropped: list[str] = []
    for item in hb_data.get("share_pull") or []:
        kind = str(item.get("kind") or "")
        owner = Path(str(item.get("owner") or "")).name
        local_name = Path(str(item.get("local_name") or "")).name
        file_id = str(item.get("id") or "")
        url = str(item.get("url") or "")
        if kind not in {"open", "granted"} or not owner or not local_name or not file_id or not url:
            continue
        dest = SHARE_ROOT / kind / owner / local_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            resp = client.get(url, headers=headers, timeout=60.0)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            pulled.append(file_id)
        except (httpx.HTTPError, OSError) as exc:
            print(f"share pull {file_id}: {exc}", flush=True)
    for item in hb_data.get("share_drop") or []:
        kind = str(item.get("kind") or "")
        owner = Path(str(item.get("owner") or "")).name
        local_name = Path(str(item.get("local_name") or "")).name
        file_id = str(item.get("id") or "")
        if kind not in {"open", "granted"} or not owner or not local_name:
            continue
        dest = SHARE_ROOT / kind / owner / local_name
        try:
            dest.unlink(missing_ok=True)
        except OSError as exc:
            print(f"share drop {file_id}: {exc}", flush=True)
        if file_id:
            dropped.append(file_id)
    if pulled or dropped:
        try:
            client.post(
                f"{CONTROL_URL}/api/v1/workers/me/share/sync",
                json={"pulled": pulled, "dropped": dropped},
                headers=headers,
            ).raise_for_status()
        except httpx.HTTPError as exc:
            print(f"share sync ack: {exc}", flush=True)


def _pull_commands(client: httpx.Client, headers: dict[str, str], security_open: bool) -> None:
    resp = client.get(f"{CONTROL_URL}/api/v1/workers/me/commands", headers=headers)
    if resp.status_code != 200:
        return
    commands = resp.json().get("commands") or []
    ids = []
    for cmd in commands:
        ids.append(cmd["id"])
        if not security_open:
            print(f"ignore command {cmd['id']}: security lock closed")
            continue
        print(f"apply limits: {cmd['payload']}")
    if ids:
        client.post(f"{CONTROL_URL}/api/v1/workers/me/commands/ack", json=ids, headers=headers)


def _execute(
    client: httpx.Client,
    headers: dict[str, str],
    lease: JobLease,
    has_docker: bool,
    runtimes: list[str],
    stop: threading.Event,
) -> None:
    post_lock = threading.Lock()

    def log(stream: str, line: str) -> None:
        try:
            with post_lock:
                client.post(
                    f"{CONTROL_URL}/api/v1/jobs/{lease.job_id}/logs",
                    json=JobLogIn(stream=stream, line=line).model_dump(),  # type: ignore[arg-type]
                    headers=headers,
                ).raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            print(f"log push failed: {exc}", flush=True)

    def push_live(rel: str, path: Path) -> None:
        try:
            data = path.read_bytes()
            with post_lock:
                client.post(
                    f"{CONTROL_URL}/api/v1/jobs/{lease.job_id}/live-output",
                    data={"name": rel},
                    files={"file": (Path(rel).name, data)},
                    headers=headers,
                    timeout=30.0,
                ).raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError, OSError) as exc:
            print(f"live output {rel}: {exc}", flush=True)

    work = Path(tempfile.mkdtemp(prefix=lease.job_id[:8] + "-", dir=WORK_ROOT))
    zip_path = work / "job.zip"
    code = 1
    error: str | None = "worker failed before start"
    try:
        art = client.get(lease.artifact_url, headers=headers)
        art.raise_for_status()
        zip_path.write_bytes(art.content)
        job_dir = unpack(zip_path, work / "src")
        log("system", f"unpacked into {job_dir}")
        if stop.is_set():
            code = 137
            error = "stopped"
            log("system", "stop requested before execute; Worker released the workdir")
        else:
            code = run_job(
                workdir=job_dir,
                manifest=lease.manifest,
                has_docker=has_docker,
                native_runtimes=runtimes,
                limits=lease.limits,
                log=log,
                stop_event=stop.is_set,
                job_id=lease.job_id,
                python_exe=lease.python_exe,
                on_output=push_live,
            )
            if stop.is_set() or code == 137:
                error = "stopped"
            else:
                error = None if code == 0 else f"exit {code}"
        result_path = work / "result.zip"
        files = None
        if not stop.is_set() and collect_output(job_dir, result_path):
            files = {"result": ("result.zip", result_path.read_bytes(), "application/zip")}
        post_kw: dict = {
            "data": {"exit_code": str(code), "error": error or ""},
            "headers": headers,
        }
        if files:
            post_kw["files"] = files
        with post_lock:
            client.post(f"{CONTROL_URL}/api/v1/jobs/{lease.job_id}/complete", **post_kw).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        log("system", error)
        try:
            with post_lock:
                client.post(
                    f"{CONTROL_URL}/api/v1/jobs/{lease.job_id}/complete",
                    data={"exit_code": "1", "error": error},
                    headers=headers,
                ).raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as post_exc:
            print(f"complete failed: {post_exc}", flush=True)
    finally:
        _wipe_tree(work)


if __name__ == "__main__":
    main()
