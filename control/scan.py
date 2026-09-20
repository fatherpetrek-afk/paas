from __future__ import annotations

import ast
import io
import re
import zipfile
from pathlib import Path

from shared.langs import KIND_LANG, SOURCE_EXTS, language_from_names

# Top-level import name -> common dist name when they differ.
_ALIAS = {
    "cv2": "opencv-python",
    "pil": "pillow",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "serial": "pyserial",
    "usb": "pyusb",
    "jwt": "pyjwt",
    "attr": "attrs",
    "crypto": "pycryptodome",
    "wx": "wxpython",
    "gi": "pygobject",
    "mysqldb": "mysqlclient",
    "psycopg2": "psycopg2-binary",
    "toml": "toml",
    "tomli": "tomli",
}

_MUTATE_RE = re.compile(
    r"""
    (?:
        \bpip(?:3)?\s+install\b
        |\bpython\s+-m\s+pip\b
        |\bconda\s+(?:install|env|create|remove)\b
        |\bnpm\s+(?:i|install|uninstall)\b
        |\byarn\s+add\b
        |\bpoetry\s+add\b
        |\buv\s+(?:add|pip\s+install)\b
        |\beasy_install\b
        |\bsetup\.py\s+install\b
        |\bapt(?:-get)?\s+install\b
        |\bchoco\s+install\b
        |\bwinget\s+install\b
        |\bpip\._internal\b
        |\bsubprocess\.[a-z]+\([^)]*(?:pip|conda|npm|poetry)
        |\bos\.system\([^)]*(?:pip|conda|npm)
        |\bopen\(\s*['\"](?:[A-Za-z]:[\\/]|/)
        |\bPath\(\s*['\"](?:[A-Za-z]:[\\/]|/)
        |worker-locks\.json
        |keys\.json
        |paas\.db
        |worker-session\.json
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_JS_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_JS_FROM = re.compile(r"""from\s+['"]([^'"]+)['"]""")
_JS_IMPORT = re.compile(r"""import\s+['"]([^'"]+)['"]""")
_JS_REL = re.compile(
    r"""(?:require\(\s*|from\s+|import\s+)['"](\.[^'"]+)['"]"""
)
_C_INCLUDE_LOCAL = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.MULTILINE)

_SKIP_ZIP_PARTS = {
    "__macosx",
    "__pycache__",
    "node_modules",
    ".git",
    "venv",
    ".venv",
    "site-packages",
}
_SKIP_ZIP_NAMES = {".ds_store", "thumbs.db"}
_SKIP_SOURCE_EXTS = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".zip",
    ".pyc",
    ".class",
    ".o",
    ".obj",
    ".a",
}


def skip_zip_name(name: str) -> bool:
    n = name.replace("\\", "/")
    if not n or n.endswith("/"):
        return True
    parts = [p.lower() for p in n.split("/")]
    if any(p in _SKIP_ZIP_PARTS for p in parts):
        return True
    return Path(n).name.lower() in _SKIP_ZIP_NAMES


def scan_bytes(filename: str, raw: bytes, kind: str = "auto") -> dict:
    files = _files(filename, raw, kind)
    language = language_from_names([n for n, _ in files]) or _language(files)
    local = _local_modules(files)
    imports: set[str] = set()
    mutating: list[str] = []
    for name, text in files:
        mutating.extend(_mutate_hits(name, text))
        if name.lower().endswith(".py"):
            imports |= _py_imports(text) - local
        elif name.lower().endswith((".js", ".mjs", ".cjs")):
            imports |= _js_imports(text) - local
    names = [n for n, _ in files]
    exts = sorted({Path(n).suffix.lower() for n in names if Path(n).suffix})
    return {
        "language": language,
        "extensions": exts,
        "imports": sorted(imports),
        "mutating": mutating[:12],
        "needs_admin": bool(mutating),
        "files": names,
    }


def env_match(scan: dict, env: dict) -> dict:
    kind = env.get("kind")
    lang = scan.get("language")
    expect = KIND_LANG.get(kind or "")
    if kind == "docker":
        return {"ok": False, "missing": [], "reason": "Docker does not pre-check third-party modules", "code": "docker"}
    if lang == "html" and kind == "python":
        return {"ok": True, "missing": [], "reason": "ok", "code": "ok"}
    scan_exts = {e.lower() if str(e).startswith(".") else f".{e}" for e in (scan.get("extensions") or [])}
    env_exts = {str(e).lower() for e in (env.get("extensions") or [])}
    if env_exts and scan_exts:
        if not (env_exts & scan_exts):
            return {"ok": False, "missing": [], "reason": "language does not match this environment", "code": "lang"}
    elif expect and lang and lang != expect and lang != "unknown":
        return {"ok": False, "missing": [], "reason": "language does not match this environment", "code": "lang"}
    if kind not in {"python", "node"}:
        return {"ok": True, "missing": [], "reason": "ok", "code": "ok"}
    have = {p.lower() for p in env.get("packages") or []}
    missing = []
    for name in scan.get("imports") or []:
        if not _covered(name, have):
            missing.append(name)
    if missing:
        return {
            "ok": False,
            "missing": missing,
            "reason": "missing modules: " + ", ".join(missing),
            "code": "missing",
        }
    return {"ok": True, "missing": [], "reason": "ok", "code": "ok"}


def _covered(name: str, have: set[str]) -> bool:
    low = name.lower()
    alias = _ALIAS.get(low, low)
    variants = {
        low,
        alias,
        alias.replace("-", "_"),
        alias.replace("_", "-"),
        low.replace("_", "-"),
    }
    return any(v in have for v in variants)


def _files(filename: str, raw: bytes, kind: str) -> list[tuple[str, str]]:
    name = Path(filename or "job.py").name
    lower = name.lower()
    kind = (kind or "auto").lower()
    if kind == "single" or (Path(lower).suffix and not lower.endswith(".zip")):
        return [(name, raw.decode("utf-8", errors="replace"))]
    out: list[tuple[str, str]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return []
    with zf:
        for n in zf.namelist():
            if skip_zip_name(n):
                continue
            if Path(n).suffix.lower() in _SKIP_SOURCE_EXTS or not Path(n).suffix:
                continue
            out.append((n, zf.read(n).decode("utf-8", errors="replace")))
    return out


def _language(files: list[tuple[str, str]]) -> str:
    py = any(n.lower().endswith(".py") for n, _ in files)
    js = any(n.lower().endswith(".js") for n, _ in files)
    if py and not js:
        return "python"
    if js and not py:
        return "javascript"
    if py:
        return "python"
    return "unknown"


def _local_modules(files: list[tuple[str, str]]) -> set[str]:
    local: set[str] = set()
    for name, _ in files:
        p = Path(name)
        if p.suffix.lower() in {".py", ".js", ".mjs", ".cjs"}:
            local.add(p.stem)
        if p.name == "__init__.py":
            local.add(p.parent.name)
    return {x for x in local if x and x != "__init__"}


def py_relative_imports(src: str) -> list[tuple[int, str | None]]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[tuple[int, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            out.append((node.level, node.module))
    return out


def js_rel_imports(src: str) -> list[str]:
    return [m.group(1) for m in _JS_REL.finditer(src)]


def c_local_includes(src: str) -> list[str]:
    return _C_INCLUDE_LOCAL.findall(src)


def _py_imports(src: str) -> set[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                continue
            if node.module:
                names.add(node.module.split(".")[0])
    return {n for n in names if n and not n.startswith("_")}


def _js_imports(src: str) -> set[str]:
    names: set[str] = set()
    for rx in (_JS_REQUIRE, _JS_FROM, _JS_IMPORT):
        for m in rx.finditer(src):
            spec = m.group(1)
            if spec.startswith(".") or spec.startswith("/"):
                continue
            names.add(spec.split("/")[0])
    return names


def _mutate_hits(name: str, text: str) -> list[str]:
    hits = []
    for m in _MUTATE_RE.finditer(text):
        snippet = " ".join(m.group(0).split())
        hits.append(f"{name}: {snippet[:80]}")
    return hits
