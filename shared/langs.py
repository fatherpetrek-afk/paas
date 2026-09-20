from __future__ import annotations

from pathlib import Path

EXT_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".c": "c",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".r": "r",
    ".jl": "julia",
    ".lua": "lua",
    ".pl": "perl",
    ".html": "html",
    ".htm": "html",
}

SINGLE_EXTS = tuple(ext for ext in EXT_LANG if ext not in {".hpp", ".hh"})
SOURCE_EXTS = set(EXT_LANG) | {".py", ".js"}

KIND_LANG = {
    "python": "python",
    "node": "javascript",
    "cpp": "cpp",
    "c": "c",
    "rust": "rust",
    "go": "go",
    "java": "java",
    "csharp": "csharp",
    "ruby": "ruby",
    "php": "php",
    "r": "r",
    "julia": "julia",
    "lua": "lua",
    "perl": "perl",
    "html": "html",
}

COMPILED_KINDS = {"cpp", "c", "rust", "go", "java", "csharp"}
INTERPRETED_KINDS = {"ruby", "php", "r", "julia", "lua", "perl", "python", "node"}


def language_from_names(names: list[str]) -> str:
    scores: dict[str, int] = {}
    preferred = {"main", "app", "run", "program"}
    for name in names:
        ext = Path(name).suffix.lower()
        lang = EXT_LANG.get(ext) or ext.lstrip(".")
        if not lang:
            continue
        stem = Path(name).stem.lower()
        scores[lang] = scores.get(lang, 0) + (4 if stem in preferred else 1)
    if not scores:
        return "unknown"
    return max(scores, key=scores.get)
