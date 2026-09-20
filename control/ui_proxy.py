from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from control.store import Store

_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "cookie",
}
_CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=2.0), follow_redirects=False)


def mount_job_ui(app: FastAPI, store: Store) -> None:
    @app.api_route("/jobs/{job_id}/ui", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.api_route("/jobs/{job_id}/ui/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def job_ui_http(job_id: str, request: Request, path: str = "") -> Response:
        del path
        sess = _session(store, request.headers.get("authorization"), request.cookies.get("paas_session"))
        _bind(store, sess, job_id)
        bind = store.job_ui_bind(job_id)
        if bind is None:
            raise HTTPException(404, "app not ready")
        url = _upstream_url(bind[0], job_id, bind[1], request.url.path, request.url.query)
        body = await request.body()
        try:
            upstream = await _CLIENT.request(request.method, url, headers=_fwd_headers(request), content=body)
        except httpx.RequestError:
            return Response(status_code=502)
        out_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in {"content-encoding", "content-length", "transfer-encoding", "connection"}
        }
        return Response(content=upstream.content, status_code=upstream.status_code, headers=out_headers)

    @app.websocket("/jobs/{job_id}/ui")
    @app.websocket("/jobs/{job_id}/ui/{path:path}")
    async def job_ui_ws(websocket: WebSocket, job_id: str, path: str = "") -> None:
        del path
        try:
            sess = _session(
                store,
                websocket.headers.get("authorization"),
                websocket.cookies.get("paas_session"),
            )
            _bind(store, sess, job_id)
            bind = store.job_ui_bind(job_id)
            if bind is None:
                raise HTTPException(404, "app not ready")
        except HTTPException:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        target = _upstream_url(bind[0], job_id, bind[1], websocket.url.path, websocket.url.query).replace(
            "http://", "ws://", 1
        )
        try:
            from websockets.asyncio.client import connect
            from websockets.exceptions import ConnectionClosed
        except Exception:
            await websocket.close(code=1011)
            return
        try:
            async with connect(target, open_timeout=5, close_timeout=2) as upstream:
                async def down() -> None:
                    try:
                        while True:
                            msg = await websocket.receive()
                            if msg.get("type") == "websocket.disconnect":
                                await upstream.close()
                                return
                            if msg.get("text") is not None:
                                await upstream.send(msg["text"])
                            elif msg.get("bytes") is not None:
                                await upstream.send(msg["bytes"])
                    except WebSocketDisconnect:
                        await upstream.close()

                async def up() -> None:
                    try:
                        async for item in upstream:
                            if isinstance(item, bytes):
                                await websocket.send_bytes(item)
                            else:
                                await websocket.send_text(str(item))
                    except (ConnectionClosed, WebSocketDisconnect):
                        try:
                            await websocket.close()
                        except Exception:
                            pass

                await asyncio.gather(down(), up())
        except Exception:
            try:
                await websocket.close(code=1011)
            except Exception:
                pass


def _session(store: Store, authorization: str | None, cookie: str | None) -> dict:
    token = ""
    auth = authorization or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        token = cookie or ""
    info = store.session_info(token)
    if info is None:
        raise HTTPException(401, "login required")
    return info


def _bind(store: Store, sess: dict, job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if sess.get("role") != "admin" and job.get("user_name") != sess.get("name"):
        raise HTTPException(404, "job not found")


def _upstream_url(kind: str, job_id: str, port: int, request_path: str, query: str) -> str:
    path = request_path or "/"
    if kind == "html":
        prefix = f"/jobs/{job_id}/ui"
        if path.startswith(prefix):
            path = path[len(prefix) :] or "/"
        if not path.startswith("/"):
            path = "/" + path
    url = f"http://127.0.0.1:{int(port)}{path}"
    if query:
        url += f"?{query}"
    return url


def _fwd_headers(request: Request) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in _HOP:
            continue
        out[key] = value
    return out
