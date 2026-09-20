from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from control.project import build_project, inject_project, write_single_zip


def materialize_upload(filename: str, raw: bytes, dest_zip: Path, kind: str = "auto", spec: dict | None = None) -> None:
    name = Path(filename or "job.py").name
    lower = name.lower()
    kind = (kind or "auto").lower()
    is_zip = lower.endswith(".zip") or _looks_like_zip(raw)
    spec = spec or build_project(name, raw, kind)
    if kind == "single":
        if is_zip:
            raise HTTPException(400, "Single file slot does not accept zip")
        if not Path(lower).suffix:
            raise HTTPException(400, "Single file needs an extension so the Worker can match an environment")
        write_single_zip(dest_zip, script_name=name, source=raw, spec=spec)
        return
    if kind == "zip":
        if not is_zip:
            raise HTTPException(400, "Project slot requires a zip")
        dest_zip.write_bytes(raw)
        inject_project(dest_zip, spec)
        return
    if Path(lower).suffix and not is_zip:
        write_single_zip(dest_zip, script_name=name, source=raw, spec=spec)
        return
    if not is_zip:
        raise HTTPException(400, "Upload a single source file, or a project zip")
    dest_zip.write_bytes(raw)
    inject_project(dest_zip, spec)


def _looks_like_zip(raw: bytes) -> bool:
    return raw[:2] == b"PK"
