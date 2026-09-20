"""Detect Streamlit / Gradio / Flask jobs and the Control UI prefix."""

from __future__ import annotations

UI_KINDS = ("streamlit", "gradio", "flask", "html")
_IMPORT_KINDS = ("streamlit", "gradio", "flask")


def ui_kind_from_imports(imports: list[str] | None) -> str:
    have = {str(name).split(".")[0].lower() for name in (imports or []) if name}
    for kind in _IMPORT_KINDS:
        if kind in have:
            return kind
    return ""


def ui_prefix(job_id: str) -> str:
    jid = str(job_id or "").strip()
    if not jid:
        return ""
    return f"/jobs/{jid}/ui"
