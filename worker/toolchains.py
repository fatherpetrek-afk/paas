from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

# Recipes for tools we know how to invoke IF they appear on PATH.
# Detection is PATH-driven: install rustc later, the next scan will pick it up.
RECIPES: dict[str, dict] = {
    "g++": {"kind": "cpp", "title": "g++", "exts": [".cpp", ".cc", ".cxx"], "mode": "compile",
            "compile": ["{exe}", "-O2", "-I{dir}", "{srcs}", "-o", "{out}"], "run": ["{out}"]},
    "clang++": {"kind": "cpp", "title": "clang++", "exts": [".cpp", ".cc", ".cxx"], "mode": "compile",
                "compile": ["{exe}", "-O2", "-I{dir}", "{srcs}", "-o", "{out}"], "run": ["{out}"]},
    "cl": {"kind": "cpp", "title": "MSVC cl", "exts": [".cpp", ".cc", ".cxx", ".c"], "mode": "compile",
           "compile": ["{exe}", "/nologo", "/EHsc", "/I{dir}", "{srcs}", "/Fe:{out}"], "run": ["{out}"]},
    "gcc": {"kind": "c", "title": "gcc", "exts": [".c"], "mode": "compile",
            "compile": ["{exe}", "-O2", "-I{dir}", "{srcs}", "-o", "{out}"], "run": ["{out}"]},
    "clang": {"kind": "c", "title": "clang", "exts": [".c"], "mode": "compile",
              "compile": ["{exe}", "-O2", "-I{dir}", "{srcs}", "-o", "{out}"], "run": ["{out}"]},
    "rustc": {"kind": "rust", "title": "rustc", "exts": [".rs"], "mode": "compile",
              "compile": ["{exe}", "{src}", "-o", "{out}"], "run": ["{out}"]},
    "go": {"kind": "go", "title": "go", "exts": [".go"], "mode": "compile",
           "compile": ["{exe}", "build", "-o", "{out}", "{srcs}"], "run": ["{out}"]},
    "javac": {"kind": "java", "title": "javac", "exts": [".java"], "mode": "java",
              "compile": ["{exe}", "{srcs}"], "run": ["java", "-cp", "{dir}", "{stem}"]},
    "dotnet": {"kind": "csharp", "title": "dotnet", "exts": [".cs"], "mode": "run",
               "run": ["{exe}", "run", "--project", "{dir}"]},
    "csc": {"kind": "csharp", "title": "csc", "exts": [".cs"], "mode": "compile",
            "compile": ["{exe}", "{srcs}", "-out:{out}"], "run": ["{out}"]},
    "ruby": {"kind": "ruby", "title": "ruby", "exts": [".rb"], "mode": "run", "run": ["{exe}", "{src}"]},
    "php": {"kind": "php", "title": "php", "exts": [".php"], "mode": "run", "run": ["{exe}", "{src}"]},
    "rscript": {"kind": "r", "title": "Rscript", "exts": [".r", ".R"], "mode": "run", "run": ["{exe}", "{src}"]},
    "julia": {"kind": "julia", "title": "julia", "exts": [".jl"], "mode": "run", "run": ["{exe}", "{src}"]},
    "lua": {"kind": "lua", "title": "lua", "exts": [".lua"], "mode": "run", "run": ["{exe}", "{src}"]},
    "perl": {"kind": "perl", "title": "perl", "exts": [".pl"], "mode": "run", "run": ["{exe}", "{src}"]},
    "zig": {"kind": "zig", "title": "zig", "exts": [".zig"], "mode": "compile",
            "compile": ["{exe}", "build-exe", "{src}", "-femit-bin={out}"], "run": ["{out}"]},
    "nim": {"kind": "nim", "title": "nim", "exts": [".nim"], "mode": "compile",
            "compile": ["{exe}", "c", "-d:release", "-o:{out}", "{src}"], "run": ["{out}"]},
    "dmd": {"kind": "d", "title": "dmd", "exts": [".d"], "mode": "compile",
            "compile": ["{exe}", "-of={out}", "{src}"], "run": ["{out}"]},
    "ghc": {"kind": "haskell", "title": "ghc", "exts": [".hs"], "mode": "compile",
            "compile": ["{exe}", "-O2", "-o", "{out}", "{src}"], "run": ["{out}"]},
    "kotlinc": {"kind": "kotlin", "title": "kotlinc", "exts": [".kt"], "mode": "run",
                "run": ["{exe}", "-script", "{src}"]},
    "swiftc": {"kind": "swift", "title": "swiftc", "exts": [".swift"], "mode": "compile",
               "compile": ["{exe}", "{src}", "-o", "{out}"], "run": ["{out}"]},
    "dart": {"kind": "dart", "title": "dart", "exts": [".dart"], "mode": "run", "run": ["{exe}", "{src}"]},
    "elixir": {"kind": "elixir", "title": "elixir", "exts": [".exs", ".ex"], "mode": "run", "run": ["{exe}", "{src}"]},
    "ocamlopt": {"kind": "ocaml", "title": "ocamlopt", "exts": [".ml"], "mode": "compile",
                 "compile": ["{exe}", "-o", "{out}", "{src}"], "run": ["{out}"]},
    "crystal": {"kind": "crystal", "title": "crystal", "exts": [".cr"], "mode": "compile",
                "compile": ["{exe}", "build", "-o", "{out}", "{src}"], "run": ["{out}"]},
    "v": {"kind": "v", "title": "v", "exts": [".v"], "mode": "compile",
          "compile": ["{exe}", "-o", "{out}", "{src}"], "run": ["{out}"]},
    "odin": {"kind": "odin", "title": "odin", "exts": [".odin"], "mode": "compile",
             "compile": ["{exe}", "build", "{src}", f"-out:{{out}}"], "run": ["{out}"]},
    "bun": {"kind": "node", "title": "bun", "exts": [".js", ".ts"], "mode": "run", "run": ["{exe}", "{src}"]},
    "deno": {"kind": "node", "title": "deno", "exts": [".js", ".ts"], "mode": "run", "run": ["{exe}", "run", "{src}"]},
    "tsc": {"kind": "node", "title": "tsc", "exts": [".ts"], "mode": "run", "run": ["{exe}", "{src}"]},
}


def discover_tool_envs() -> list[dict]:
    present = _path_binaries()
    out: list[dict] = []
    seen: set[str] = set()
    for name, spec in RECIPES.items():
        exe = shutil.which(name) or shutil.which(name + ".exe")
        if not exe and name.lower() not in present:
            continue
        if not exe:
            continue
        key = os.path.normcase(os.path.abspath(exe)) + ":" + spec["kind"]
        if key in seen:
            continue
        seen.add(key)
        ver = _version(exe, name)
        digest = hashlib.sha1(key.encode()).hexdigest()[:10]
        out.append(
            {
                "id": f"{spec['kind']}-{digest}",
                "kind": spec["kind"],
                "label": f"{spec['title']} {ver}".strip(),
                "executable": os.path.abspath(exe),
                "version": ver,
                "packages": [],
                "extensions": list(spec["exts"]),
            }
        )
    return out


def runtime_families() -> list[str]:
    return sorted({e["kind"] for e in discover_tool_envs()})


def recipe_for_exe(executable: str, kind: str = "") -> dict | None:
    stem = Path(executable or "").stem.lower()
    spec = RECIPES.get(stem)
    if spec:
        return spec
    if kind:
        for item in RECIPES.values():
            if item["kind"] == kind:
                return item
    return None


def _path_binaries() -> set[str]:
    names: set[str] = set()
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(raw)
        if not folder.is_dir():
            continue
        try:
            for item in folder.iterdir():
                if item.is_file():
                    names.add(item.stem.lower())
        except OSError:
            continue
    return names


def _version(exe: str, name: str) -> str:
    if name.lower() == "cl":
        return ""
    try:
        raw = subprocess.check_output([exe, "--version"], text=True, timeout=5, stderr=subprocess.STDOUT)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        try:
            raw = subprocess.check_output([exe, "-version"], text=True, timeout=5, stderr=subprocess.STDOUT)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""
    line = (raw or "").splitlines()[0].strip() if raw else ""
    return line[:48]
