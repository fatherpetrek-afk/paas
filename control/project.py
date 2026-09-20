from __future__ import annotations

import ast
import io
import json
import re
import zipfile
from pathlib import Path

from fastapi import HTTPException

from control.scan import (
    c_local_includes,
    js_rel_imports,
    py_relative_imports,
    scan_bytes,
    skip_zip_name,
    _js_imports,
    _local_modules,
    _py_imports,
)
from shared.langs import EXT_LANG, KIND_LANG, language_from_names
from shared.protocol import DEFAULT_TIMEOUT_SEC, JobManifest
from shared.webui import ui_kind_from_imports

_PY_MAIN_RE = re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]""")
_JS_MAIN_RE = re.compile(r"require\.main\s*===?\s*module")
_C_MAIN_RE = re.compile(r"\b(?:int|void)\s+main\s*\(")
_GO_MAIN_RE = re.compile(r"\bfunc\s+main\s*\(")
_RS_MAIN_RE = re.compile(r"\bfn\s+main\s*\(")
_JAVA_MAIN_RE = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(")
_CS_MAIN_RE = re.compile(r"\bstatic\s+(?:async\s+)?(?:void|int|Task)\s+Main\s*\(")

_NAMED_MAINS = {
    "main.py",
    "app.py",
    "run.py",
    "main.js",
    "index.js",
    "main.mjs",
    "index.mjs",
    "main.cjs",
    "index.cjs",
    "main.c",
    "main.cpp",
    "main.cc",
    "main.cxx",
    "main.rs",
    "main.go",
    "Main.java",
    "Program.cs",
}

_KIND_BY_LANG = {lang: kind for kind, lang in KIND_LANG.items()}
_KIND_BY_LANG["javascript"] = "node"
_LINK_EXTS = {
    "c": {".c"},
    "cpp": {".cpp", ".cc", ".cxx"},
    "java": {".java"},
    "go": {".go"},
    "csharp": {".cs"},
}


def build_project(filename: str, raw: bytes, kind: str = "auto") -> dict:
    name = Path(filename or "job.py").name
    lower = name.lower()
    kind = (kind or "auto").lower()
    is_zip = lower.endswith(".zip") or (len(raw) >= 2 and raw[:2] == b"PK")
    if kind == "single":
        if is_zip:
            raise HTTPException(400, "Single file slot does not accept zip")
        return _from_single(name, raw)
    if kind == "zip" or (kind == "auto" and is_zip):
        if not is_zip:
            raise HTTPException(400, "Project slot requires a zip")
        return _from_zip(name, raw)
    if Path(lower).suffix:
        return _from_single(name, raw)
    raise HTTPException(400, "Upload a single source file, or a project zip")


def spec_to_scan(spec: dict) -> dict:
    identity = spec.get("identity") or {}
    tree = spec.get("tree") or []
    exts = list(identity.get("extensions") or [])
    if not exts:
        exts = sorted({Path(item.get("path") or "").suffix.lower() for item in tree if Path(item.get("path") or "").suffix})
    return {
        "language": spec.get("language") or "unknown",
        "extensions": exts,
        "imports": list(spec.get("imports") or []),
        "mutating": list(spec.get("mutating") or []),
        "needs_admin": bool(spec.get("needs_admin")),
        "files": [item.get("path") for item in tree if item.get("path")],
        "mains": [run.get("file") for run in (spec.get("runs") or []) if run.get("file")],
        "ui_kind": spec.get("ui_kind") or ui_kind_from_imports(spec.get("imports") or []),
    }


def manifest_from_spec(spec: dict) -> dict:
    runs = spec.get("runs") or []
    entry = (runs[0].get("entry") if runs else "") or "python main.py"
    return JobManifest(
        name=spec.get("name") or "job",
        runtime=spec.get("runtime") or "python:3.12",
        entry=entry,
        timeout_sec=int(spec.get("timeout_sec") or DEFAULT_TIMEOUT_SEC),
    ).model_dump()


def inject_project(zip_path: Path, spec: dict) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        payload = {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}
        names = [n for n in payload if not skip_zip_name(n)]
        project_name = next((n for n in names if Path(n).name == "project.json"), None)
        manifest_name = next((n for n in names if Path(n).name == "manifest.json"), None)

    folder = _inject_folder(list(payload), spec)
    payload[project_name or _join_zip(folder, "project.json")] = json.dumps(_public_spec(spec), indent=2).encode("utf-8")
    payload[manifest_name or _join_zip(folder, "manifest.json")] = json.dumps(manifest_from_spec(spec), indent=2).encode("utf-8")

    tmp = zip_path.with_suffix(".repack.zip")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payload.items():
            zf.writestr(name, data)
    tmp.replace(zip_path)


def write_single_zip(dest_zip: Path, *, script_name: str, source: bytes, spec: dict) -> None:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, source)
        zf.writestr("project.json", json.dumps(_public_spec(spec), indent=2))
        zf.writestr("manifest.json", json.dumps(manifest_from_spec(spec), indent=2))


def runtime_entry(lang: str, script: str) -> tuple[str, str]:
    if lang == "javascript":
        return "node", f"node {script}"
    if lang == "html":
        return "python:3.12", f"python {script}"
    if lang == "python":
        return "python:3.12", f"python {script}"
    return lang or "auto", f"compile {script}"


def _from_single(name: str, raw: bytes) -> dict:
    scan = scan_bytes(name, raw, "single")
    lang = scan.get("language") or _lang_of(name) or "python"
    runtime, entry = runtime_entry(lang, name)
    return {
        "name": Path(name).stem or "job",
        "language": lang or "unknown",
        "runtime": runtime,
        "identity": _identity(lang, [name]),
        "root": "",
        "tree": [{"path": name, "role": "main", "language": lang or ""}],
        "imports": list(scan.get("imports") or []),
        "mutating": list(scan.get("mutating") or []),
        "needs_admin": bool(scan.get("needs_admin")),
        "deps": {},
        "runs": [{"file": name, "entry": entry}],
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "source": "auto",
        "ui_kind": ui_kind_from_imports(scan.get("imports") or [])
        or ("html" if Path(name).suffix.lower() in {".html", ".htm"} else ""),
    }


def _from_zip(zip_name: str, raw: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "invalid zip") from exc
    with zf:
        ordered = [n.replace("\\", "/") for n in zf.namelist() if not skip_zip_name(n)]
        if not ordered:
            raise HTTPException(400, "zip has no usable files")
        payload = {n: zf.read(n) for n in ordered}
        user_project = _read_named_json(zf, ordered, "project.json")
        user_manifest = _read_named_json(zf, ordered, "manifest.json")

    prefix = _common_root(ordered)
    rel_payload = {_rel(n, prefix): data for n, data in payload.items()}
    texts = {
        path: data.decode("utf-8", errors="replace")
        for path, data in rel_payload.items()
        if Path(path).suffix.lower() in EXT_LANG
    }
    scan = scan_bytes(zip_name, raw, "zip")
    sources = [path for path in _rel_order(ordered, prefix) if path in texts]
    if not sources and not (user_project and (user_project.get("runs") or user_project.get("mains"))):
        raise HTTPException(400, "zip has no recognizable source file")

    spec = _spec_skeleton(zip_name, scan, texts, rel_payload, prefix, sources)
    user_runs = _runs_from_user(user_project, rel_payload) if user_project else []
    if user_runs:
        spec["runs"] = user_runs
        if user_project.get("name"):
            spec["name"] = str(user_project["name"])
        if user_project.get("runtime"):
            spec["runtime"] = str(user_project["runtime"])
        if user_project.get("timeout_sec"):
            spec["timeout_sec"] = int(user_project["timeout_sec"])
        spec["source"] = "project.json"
        return _finish_zip(spec, texts)
    if user_manifest and user_manifest.get("entry"):
        entry = str(user_manifest["entry"]).strip()
        file = _file_from_entry(entry, list(rel_payload))
        spec["runs"] = [{"file": file or "", "entry": entry}]
        if user_manifest.get("name"):
            spec["name"] = str(user_manifest["name"])
        if user_manifest.get("runtime"):
            spec["runtime"] = str(user_manifest["runtime"])
        if user_manifest.get("timeout_sec"):
            spec["timeout_sec"] = int(user_manifest["timeout_sec"])
        spec["source"] = "manifest.json"
        return _finish_zip(spec, texts)

    mains = [path for path in sources if _is_main(path, texts[path])]
    if not mains:
        mains = sources[:1]
    spec["runs"] = [{"file": path, "entry": _run_for(path)["entry"]} for path in mains]
    if mains:
        spec["runtime"] = runtime_entry(_lang_of(mains[0]), mains[0])[0]
    spec["source"] = "auto"
    return _finish_zip(spec, texts)


def _spec_skeleton(
    zip_name: str,
    scan: dict,
    texts: dict[str, str],
    rel_payload: dict[str, bytes],
    prefix: str,
    sources: list[str],
) -> dict:
    lang = scan.get("language") or language_from_names(sources) or "unknown"
    names = _rel_order(scan.get("files") or sources, prefix)
    if not names:
        names = sources
    return {
        "name": Path(zip_name).stem or "job",
        "language": lang,
        "runtime": runtime_entry(lang, sources[0] if sources else "main.py")[0],
        "identity": _identity(lang, names or list(rel_payload)),
        "root": prefix.rstrip("/"),
        "tree": _tree(rel_payload, texts, sources),
        "imports": list(scan.get("imports") or []),
        "mutating": list(scan.get("mutating") or []),
        "needs_admin": bool(scan.get("needs_admin")),
        "deps": _deps(texts, list(rel_payload)),
        "runs": [],
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "source": "auto",
        "ui_kind": ui_kind_from_imports(scan.get("imports") or [])
        or ("html" if any(Path(n).suffix.lower() in {".html", ".htm"} for n in (names or rel_payload)) else ""),
    }


def _tree(rel_payload: dict[str, bytes], texts: dict[str, str], sources: list[str]) -> list[dict]:
    out = []
    for path in rel_payload:
        item = {"path": path, "role": "asset", "language": ""}
        if Path(path).name in {"project.json", "manifest.json"}:
            item["role"] = "spec"
        elif path in texts:
            item["language"] = _lang_of(path)
            item["role"] = "module"
        out.append(item)
    return out


def _finish_zip(spec: dict, texts: dict[str, str]) -> dict:
    _attach_link_units(spec, texts)
    _apply_run_roles(spec)
    return spec


def _attach_link_units(spec: dict, texts: dict[str, str]) -> None:
    by_lang: dict[str, list[str]] = {}
    for path in texts:
        lang = _lang_of(path)
        if Path(path).suffix.lower() in _LINK_EXTS.get(lang, set()):
            by_lang.setdefault(lang, []).append(path)
    runs = spec.get("runs") or []
    for run in runs:
        if run.get("sources"):
            continue
        lang = _lang_of(str(run.get("file") or ""))
        files = by_lang.get(lang) or []
        if not files:
            continue
        mains = {str(item.get("file") or "") for item in runs if _lang_of(str(item.get("file") or "")) == lang}
        chosen = str(run.get("file") or "")
        units = [path for path in files if path not in mains or path == chosen]
        if chosen and chosen not in units:
            units.append(chosen)
        run["sources"] = units


def _apply_run_roles(spec: dict) -> None:
    mains = {run.get("file") for run in spec.get("runs") or [] if run.get("file")}
    for item in spec.get("tree") or []:
        if item.get("path") in mains:
            item["role"] = "main"


def _deps(texts: dict[str, str], all_paths: list[str]) -> dict[str, list[str]]:
    path_set = {p.replace("\\", "/") for p in all_paths}
    local = _local_modules(list(texts.items()))
    by_stem: dict[str, list[str]] = {}
    for path in texts:
        by_stem.setdefault(Path(path).stem, []).append(path)
        if Path(path).name == "__init__.py" and Path(path).parent.name:
            by_stem.setdefault(Path(path).parent.name, []).append(path)

    def pick_mod(name: str, from_path: str) -> str | None:
        hits = by_stem.get(name) or []
        if not hits:
            return None
        here = str(Path(from_path).parent).replace("\\", "/")
        same = [h for h in hits if str(Path(h).parent).replace("\\", "/") == here]
        pool = same or hits
        pool.sort(key=lambda p: (p.count("/"), p))
        return pool[0]

    graph: dict[str, list[str]] = {}
    for path, text in texts.items():
        found: list[str] = []
        suffix = Path(path).suffix.lower()
        if suffix == ".py":
            for name in _py_imports(text):
                if name in local:
                    target = pick_mod(name, path)
                    if target and target != path:
                        found.append(target)
            parent = Path(path).parent
            for level, module in py_relative_imports(text):
                base = parent
                for _ in range(level - 1):
                    base = base.parent
                rel = module.replace(".", "/") if module else ""
                cand = (base / rel).as_posix() if rel else base.as_posix()
                if cand in {".", ""}:
                    continue
                for option in (f"{cand}.py", f"{cand}/__init__.py"):
                    option = option.lstrip("./")
                    if option in path_set and option != path:
                        found.append(option)
                        break
        elif suffix in {".js", ".mjs", ".cjs"}:
            for spec in js_rel_imports(text):
                target = _resolve_js(path, spec, path_set)
                if target:
                    found.append(target)
            for name in _js_imports(text):
                if name in local:
                    target = pick_mod(name, path)
                    if target and target != path:
                        found.append(target)
        elif suffix in {".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh"}:
            here = Path(path).parent
            for inc in c_local_includes(text):
                option = (here / inc).as_posix()
                option = option.replace("\\", "/")
                if option.startswith("./"):
                    option = option[2:]
                if option in path_set:
                    found.append(option)
        uniq = []
        for item in found:
            if item not in uniq:
                uniq.append(item)
        if uniq:
            graph[path] = uniq
    return graph


def _resolve_js(from_path: str, spec: str, path_set: set[str]) -> str | None:
    base = Path(from_path).parent
    raw = spec.split("?")[0]
    cand = (base / raw).as_posix().replace("\\", "/")
    if cand.startswith("./"):
        cand = cand[2:]
    options = [cand]
    if not Path(cand).suffix:
        options.extend([f"{cand}.js", f"{cand}.mjs", f"{cand}.cjs", f"{cand}/index.js"])
    for option in options:
        option = option.lstrip("./")
        if option in path_set and option != from_path:
            return option
    return None


def _is_main(path: str, text: str) -> bool:
    name = Path(path).name
    parent = str(Path(path).parent).replace("\\", "/")
    at_root = parent in {".", ""}
    if name in {"index.js", "index.mjs", "index.cjs"}:
        if at_root:
            return True
    elif name in _NAMED_MAINS:
        return True
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return _py_is_main(text)
    if suffix in {".js", ".mjs", ".cjs"}:
        return bool(_JS_MAIN_RE.search(text))
    if suffix in {".c", ".cpp", ".cc", ".cxx", ".h"}:
        return bool(_C_MAIN_RE.search(text))
    if suffix == ".go":
        return bool(_GO_MAIN_RE.search(text))
    if suffix == ".rs":
        return bool(_RS_MAIN_RE.search(text))
    if suffix == ".java":
        return bool(_JAVA_MAIN_RE.search(text))
    if suffix == ".cs":
        return bool(_CS_MAIN_RE.search(text))
    return False


def _py_is_main(src: str) -> bool:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return bool(_PY_MAIN_RE.search(src))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        left, right = test.left, test.comparators[0]
        if _name_eq_main(left, right) or _name_eq_main(right, left):
            return True
    return False


def _name_eq_main(a: object, b: object) -> bool:
    return (
        isinstance(a, ast.Name)
        and a.id == "__name__"
        and isinstance(b, ast.Constant)
        and b.value == "__main__"
    )


def _run_for(path: str) -> dict:
    lang = _lang_of(path)
    runtime, entry = runtime_entry(lang, path)
    return {"file": path, "entry": entry, "runtime": runtime}


def _runs_from_user(data: dict, rel_payload: dict[str, bytes]) -> list[dict]:
    runs = data.get("runs")
    if isinstance(runs, list) and runs:
        out = []
        for item in runs:
            if not isinstance(item, dict):
                continue
            file = str(item.get("file") or "").replace("\\", "/")
            entry = str(item.get("entry") or "").strip()
            if not entry and file:
                entry = runtime_entry(_lang_of(file), file)[1]
            if not entry:
                continue
            out.append({"file": file, "entry": entry})
        return out
    mains = data.get("mains")
    if isinstance(mains, list) and mains:
        out = []
        for item in mains:
            path = str(item).replace("\\", "/")
            if path not in rel_payload:
                continue
            row = _run_for(path)
            out.append({"file": row["file"], "entry": row["entry"]})
        return out
    return []


def _file_from_entry(entry: str, paths: list[str]) -> str:
    parts = entry.split()
    if not parts:
        return ""
    hint = parts[-1].replace("\\", "/")
    if hint in paths:
        return hint
    base = Path(hint).name
    hits = [p for p in paths if Path(p).name == base]
    return hits[0] if hits else hint


def _identity(lang: str, names: list[str]) -> dict:
    exts = sorted({Path(n).suffix.lower() for n in names if Path(n).suffix})
    kind = _KIND_BY_LANG.get(lang or "", lang or "unknown")
    return {"kind": kind, "language": lang or "unknown", "extensions": exts}


def _lang_of(path: str) -> str:
    return EXT_LANG.get(Path(path).suffix.lower()) or ""


def _common_root(names: list[str]) -> str:
    tops = []
    for name in names:
        parts = name.replace("\\", "/").split("/")
        if len(parts) < 2:
            return ""
        tops.append(parts[0])
    if not tops:
        return ""
    first = tops[0]
    if all(t == first for t in tops):
        return first + "/"
    return ""


def _rel(name: str, prefix: str) -> str:
    n = name.replace("\\", "/")
    if prefix and n.startswith(prefix):
        return n[len(prefix) :]
    return n


def _rel_order(names: list[str], prefix: str) -> list[str]:
    out = []
    seen = set()
    for name in names:
        rel = _rel(str(name), prefix)
        if rel and rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _read_named_json(zf: zipfile.ZipFile, names: list[str], filename: str) -> dict | None:
    hits = [n for n in names if Path(n).name == filename]
    hits.sort(key=lambda n: (n.count("/"), n))
    if not hits:
        return None
    try:
        data = json.loads(zf.read(hits[0]).decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _inject_folder(names: list[str], spec: dict) -> str:
    for n in names:
        if Path(n).name in {"project.json", "manifest.json"} and not skip_zip_name(n):
            parent = str(Path(n).parent).replace("\\", "/")
            return "" if parent in {".", ""} else parent
    root = str(spec.get("root") or "").replace("\\", "/").strip("/")
    return root


def _join_zip(folder: str, name: str) -> str:
    if not folder:
        return name
    return f"{folder}/{name}"


def _public_spec(spec: dict) -> dict:
    out = dict(spec)
    runs = []
    for run in spec.get("runs") or []:
        row = {"file": run.get("file") or "", "entry": run.get("entry") or ""}
        if run.get("sources"):
            row["sources"] = list(run["sources"])
        runs.append(row)
    out["runs"] = runs
    return out
