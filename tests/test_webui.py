from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control.project import build_project, spec_to_scan
from control.scan import env_match
from shared.webui import ui_kind_from_imports, ui_prefix
from worker.webui import ensure_html_index, html_cmd, script_from_parts, streamlit_cmd


class WebUiTests(unittest.TestCase):
    def test_kind_order(self) -> None:
        self.assertEqual(ui_kind_from_imports(["flask", "streamlit"]), "streamlit")
        self.assertEqual(ui_kind_from_imports(["numpy", "gradio"]), "gradio")
        self.assertEqual(ui_kind_from_imports(["flask"]), "flask")
        self.assertEqual(ui_kind_from_imports(["numpy"]), "")

    def test_prefix(self) -> None:
        self.assertEqual(ui_prefix("abc"), "/jobs/abc/ui")

    def test_scan_streamlit(self) -> None:
        spec = build_project("app.py", b"import streamlit as st\nst.write(1)\n", "single")
        self.assertEqual(spec["ui_kind"], "streamlit")
        self.assertEqual(spec_to_scan(spec)["ui_kind"], "streamlit")

    def test_streamlit_cmd(self) -> None:
        cmd = streamlit_cmd("python", "app.py", 1234, "/jobs/x/ui")
        self.assertIn("streamlit", cmd)
        self.assertIn("1234", cmd)
        self.assertIn("jobs/x/ui", cmd)

    def test_script_from_parts(self) -> None:
        here = Path(__file__).resolve().parent
        name = script_from_parts(["python", "-m", "streamlit", "run", "app.py"], here)
        self.assertEqual(name, "app.py")

    def test_html_scan_matches_python_env(self) -> None:
        spec = build_project("draw.html", b"<!doctype html><canvas></canvas>\n", "single")
        self.assertEqual(spec["language"], "html")
        self.assertEqual(spec["ui_kind"], "html")
        scan = spec_to_scan(spec)
        self.assertEqual(scan["ui_kind"], "html")
        hit = env_match(scan, {"kind": "python", "packages": [], "extensions": [".py"]})
        self.assertTrue(hit["ok"])
        miss = env_match(scan, {"kind": "node", "packages": [], "extensions": [".js"]})
        self.assertFalse(miss["ok"])

    def test_stdlib_html_import_is_not_ui(self) -> None:
        spec = build_project("x.py", b"import html\nprint(html.escape('a'))\n", "single")
        self.assertEqual(spec["ui_kind"], "")

    def test_html_index_and_cmd(self) -> None:
        here = Path(tempfile.mkdtemp())
        (here / "draw.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
        path = ensure_html_index(here, "draw.html")
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "index.html")
        cmd = html_cmd("python", 8765)
        self.assertIn("http.server", cmd)
        self.assertIn("8765", cmd)
        self.assertIn("127.0.0.1", cmd)


if __name__ == "__main__":
    unittest.main()
