"""Probe Worker queue: pause, anchors, reorder, block, occupancy."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SLEEP = ROOT / "examples" / "sleepers"
CTRL = "http://127.0.0.1:8080"
USERS = [("alice", "alice-dev"), ("bob", "bob-dev"), ("carol", "carol-dev"), ("dave", "dave-dev")]
FILES = ["a.py", "b.py", "c.py", "d.py"]


def login(client: httpx.Client, key: str) -> str:
    r = client.post(f"{CTRL}/api/v1/auth/login", json={"role": "user", "key": key})
    r.raise_for_status()
    return r.json()["token"]


def submit(client: httpx.Client, token: str, worker_id: str, path: Path) -> dict:
    files = {"artifact": (path.name, path.read_bytes(), "text/x-python")}
    r = client.post(
        f"{CTRL}/api/v1/jobs",
        headers={"Authorization": f"Bearer {token}"},
        data={"worker_id": worker_id, "kind": "single"},
        files=files,
    )
    r.raise_for_status()
    return r.json()["job"]


def board(client: httpx.Client, headers: dict) -> dict:
    r = client.get(f"{CTRL}/api/v1/workers/me/board", headers=headers)
    r.raise_for_status()
    return r.json()


def main() -> int:
    sess_path = ROOT / "data" / "worker-session.json"
    if not sess_path.exists():
        print("worker session missing; start run_worker.py")
        return 1
    sess = json.loads(sess_path.read_text(encoding="utf-8"))
    wh = {"X-Worker-Token": sess["worker_token"]}
    c = httpx.Client(timeout=20.0)

    c.post(f"{CTRL}/api/v1/workers/me/pause", headers=wh, json={"on": True}).raise_for_status()
    print("pause_all on")

    uh = {"Authorization": f"Bearer {login(c, USERS[0][1])}"}
    workers = c.get(f"{CTRL}/api/v1/workers", headers=uh).json()["workers"]
    wid = sess["worker_id"]
    worker = next(w for w in workers if w["id"] == wid)
    print("worker", worker["name"], "run_open", worker["locks"]["run_open"])

    jobs = []
    for (user, key), fname in zip(USERS, FILES, strict=True):
        job = submit(c, login(c, key), wid, SLEEP / fname)
        jobs.append(job)
        print("queued", user, job["name"], job["id"][:8])
        assert job["state"] == "queued" and job["user_name"] == user

    b = board(c, wh)
    queued = [x for x in b["queue"] if x["kind"] == "job"]
    print("can_edit", b["can_edit_queue"], "can_reorder", b["can_reorder"])
    assert len(queued) == 4
    assert b["can_edit_queue"] is True
    assert b["can_reorder"] is False

    anc = c.post(f"{CTRL}/api/v1/workers/me/anchors", headers=wh, json={"before_id": queued[1]["id"]})
    anc.raise_for_status()
    b = anc.json()
    print("anchor before", queued[1]["user_name"], "reorder", [i[:8] for i in b["reorder_job_ids"]])
    assert b["has_anchor"] and b["can_reorder"]
    assert queued[0]["id"] not in b["reorder_job_ids"]

    ids = list(reversed(b["reorder_job_ids"]))
    re = c.post(f"{CTRL}/api/v1/workers/me/reorder", headers=wh, json={"job_ids": ids})
    re.raise_for_status()
    print("reordered", [x[:8] for x in re.json()["reorder_job_ids"]])

    drop = ids[0]
    deleted = c.delete(f"{CTRL}/api/v1/workers/me/queue/{drop}", headers=wh)
    deleted.raise_for_status()
    print("deleted_after_anchor", drop[:8])

    c.post(f"{CTRL}/api/v1/workers/me/pause", headers=wh, json={"on": False}).raise_for_status()
    time.sleep(1.3)
    b = board(c, wh)
    occ = b["occupancy"]
    print("occupancy", occ)
    print("queue", [(x["kind"], x.get("user_name"), x["state"]) for x in b["queue"]])
    assert occ is not None
    assert occ["user_name"] == "alice"

    time.sleep(3.6)
    b = board(c, wh)
    print("after_alice", [(x["kind"], x.get("user_name"), x["state"]) for x in b["queue"]], "occ", b["occupancy"])
    assert b["occupancy"] is None
    assert b["has_anchor"]

    remain = [x["user_name"] for x in b["queue"] if x["kind"] == "job" and x["state"] == "queued"]
    block_user = remain[0]
    c.post(f"{CTRL}/api/v1/workers/me/block", headers=wh, json={"user_name": block_user}).raise_for_status()
    print("blocked", block_user)
    try:
        submit(c, login(c, dict(USERS)[block_user]), wid, SLEEP / "a.py")
        print("FAIL blocked submit succeeded")
        return 1
    except httpx.HTTPStatusError as exc:
        print("blocked_submit", exc.response.status_code)

    c.post(f"{CTRL}/api/v1/workers/me/anchors/{b['first_anchor_id']}/release", headers=wh).raise_for_status()
    time.sleep(1.2)
    b = board(c, wh)
    occ2 = b["occupancy"]
    print("after_release_occ", occ2)
    if occ2:
        assert occ2["user_name"] != block_user
        stop = c.post(f"{CTRL}/api/v1/workers/me/jobs/{occ2['job_id']}/stop", headers=wh)
        print("stop", stop.status_code, stop.json().get("job", {}).get("state"))

    c.post(f"{CTRL}/api/v1/workers/me/unblock", headers=wh, json={"user_name": block_user}).raise_for_status()
    print("unblocked", block_user)
    print("PROBE_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPStatusError as exc:
        print("HTTP", exc.response.status_code, exc.response.text[:500])
        raise SystemExit(1) from exc
