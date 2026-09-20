from __future__ import annotations

import secrets
import zipfile
from pathlib import Path

from control.config import ROOT


def pack_hello(artifact_dir: Path) -> Path:
    src = ROOT / "examples" / "hello"
    dest_dir = artifact_dir / secrets.token_hex(8)
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "job.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.name)
    return zip_path
