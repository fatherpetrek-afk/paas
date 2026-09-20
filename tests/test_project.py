from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control.packaging import materialize_upload
from control.project import build_project, spec_to_scan
from control.scan import env_match
from shared.protocol import JobManifest
from worker.executor import run_job, unpack

MAIN = 'if __name__ == "__main__":\n    print("X")\n'


def _zip_bytes(files: list[tuple[str, str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files:
            zf.writestr(name, text)
    return buf.getvalue()


class ProjectJsonTests(unittest.TestCase):
    def test_zip_order_two_mains(self) -> None:
        raw = _zip_bytes(
            [
                ("b.py", 'if __name__ == "__main__":\n    print("B")\n'),
                ("lib.py", "VALUE = 1\n"),
                ("a.py", 'if __name__ == "__main__":\n    print("A")\n'),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        self.assertEqual([r["file"] for r in spec["runs"]], ["b.py", "a.py"])
        self.assertEqual(spec["source"], "auto")
        scan = spec_to_scan(spec)
        self.assertEqual(scan["mains"], ["b.py", "a.py"])
        self.assertEqual(scan["language"], "python")

    def test_local_dep_from_header(self) -> None:
        raw = _zip_bytes(
            [
                ("lib.py", "VALUE = 1\n"),
                ("a.py", 'import lib\n\nif __name__ == "__main__":\n    print(lib.VALUE)\n'),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        self.assertEqual(spec["runs"][0]["file"], "a.py")
        self.assertIn("lib.py", spec["deps"].get("a.py", []))
        self.assertNotIn("lib", spec["imports"])

    def test_project_json_overrides_order(self) -> None:
        raw = _zip_bytes(
            [
                ("a.py", MAIN.replace("X", "A")),
                ("b.py", MAIN.replace("X", "B")),
                (
                    "project.json",
                    json.dumps({"mains": ["b.py", "a.py"]}),
                ),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        self.assertEqual([r["file"] for r in spec["runs"]], ["b.py", "a.py"])
        self.assertEqual(spec["source"], "project.json")

    def test_manifest_is_special(self) -> None:
        raw = _zip_bytes(
            [
                ("a.py", MAIN.replace("X", "A")),
                ("b.py", MAIN.replace("X", "B")),
                (
                    "manifest.json",
                    json.dumps({"name": "one", "runtime": "python:3.12", "entry": "python b.py"}),
                ),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        self.assertEqual(len(spec["runs"]), 1)
        self.assertEqual(spec["runs"][0]["file"], "b.py")
        self.assertEqual(spec["source"], "manifest.json")

    def test_nested_index_js_not_auto_main(self) -> None:
        raw = _zip_bytes(
            [
                ("src/index.js", "export const x = 1;\n"),
                ("main.js", "require.main === module;\nconsole.log('ok');\n"),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        self.assertEqual([r["file"] for r in spec["runs"]], ["main.js"])

    def test_common_root_stripped(self) -> None:
        raw = _zip_bytes(
            [
                ("proj/lib.py", "VALUE = 2\n"),
                ("proj/main.py", "import lib\nprint(lib.VALUE)\n"),
            ]
        )
        spec = build_project("proj.zip", raw, "zip")
        self.assertEqual(spec["root"], "proj")
        self.assertEqual(spec["runs"][0]["file"], "main.py")
        self.assertTrue(any(item["path"] == "lib.py" for item in spec["tree"]))

    def test_inject_and_env_match(self) -> None:
        raw = _zip_bytes(
            [
                ("b.py", MAIN.replace("X", "B")),
                ("a.py", 'import numpy\n\nif __name__ == "__main__":\n    print("A")\n'),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        scan = spec_to_scan(spec)
        self.assertIn("numpy", scan["imports"])
        miss = env_match(scan, {"kind": "python", "packages": ["numpy"], "extensions": [".py"]})
        self.assertTrue(miss["ok"])
        miss = env_match(scan, {"kind": "python", "packages": [], "extensions": [".py"]})
        self.assertFalse(miss["ok"])
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "job.zip"
            materialize_upload("demo.zip", raw, dest, kind="zip", spec=spec)
            with zipfile.ZipFile(dest) as zf:
                names = zf.namelist()
                self.assertIn("project.json", names)
                self.assertIn("manifest.json", names)
                data = json.loads(zf.read("project.json"))
            self.assertEqual([r["file"] for r in data["runs"]], ["b.py", "a.py"])

    def test_mains_only_project_json_written_as_runs(self) -> None:
        raw = _zip_bytes(
            [
                ("a.py", MAIN.replace("X", "A")),
                ("b.py", MAIN.replace("X", "B")),
                ("project.json", json.dumps({"mains": ["b.py", "a.py"]})),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "job.zip"
            materialize_upload("demo.zip", raw, dest, kind="zip", spec=spec)
            with zipfile.ZipFile(dest) as zf:
                data = json.loads(zf.read("project.json"))
                self.assertIn("manifest.json", zf.namelist())
            self.assertEqual([r["file"] for r in data["runs"]], ["b.py", "a.py"])

    def test_sequential_native_runs(self) -> None:
        raw = _zip_bytes(
            [
                ("first.py", 'if __name__ == "__main__":\n    print("first")\n'),
                ("second.py", 'if __name__ == "__main__":\n    print("second")\n'),
            ]
        )
        spec = build_project("demo.zip", raw, "zip")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zpath = root / "job.zip"
            materialize_upload("demo.zip", raw, zpath, kind="zip", spec=spec)
            workdir = unpack(zpath, root / "src")
            lines: list[tuple[str, str]] = []
            code = run_job(
                workdir=workdir,
                manifest=JobManifest(**{"name": "demo", "runtime": "python:3.12", "entry": "python first.py"}),
                has_docker=False,
                native_runtimes=["python"],
                limits=None,
                log=lambda stream, line: lines.append((stream, line)),
                python_exe=sys.executable,
            )
            self.assertEqual(code, 0)
            stdout = [line for stream, line in lines if stream == "stdout"]
            self.assertEqual(stdout, ["first", "second"])
            system = [line for stream, line in lines if stream == "system"]
            self.assertTrue(any("run 1/2: first.py" in line for line in system))
            self.assertTrue(any("run 2/2: second.py" in line for line in system))


    def test_cpp_zip_links_all_units(self) -> None:
        raw = _zip_bytes(
            [
                (
                    "lib.cpp",
                    '#include "lib.h"\nint answer() { return 7; }\n',
                ),
                (
                    "lib.h",
                    "#pragma once\nint answer();\n",
                ),
                (
                    "main.cpp",
                    '#include "lib.h"\n#include <stdio.h>\nint main() { printf("%d\\n", answer()); return 0; }\n',
                ),
            ]
        )
        spec = build_project("hw.zip", raw, "zip")
        self.assertEqual([r["file"] for r in spec["runs"]], ["main.cpp"])
        sources = spec["runs"][0]["sources"]
        self.assertEqual(sources, ["lib.cpp", "main.cpp"])

    def test_homework_zip_links_public_tests(self) -> None:
        path = ROOT / "data" / "artifacts" / "9f97855a09c22d17" / "job.zip"
        if not path.is_file():
            self.skipTest("homework artifact missing")
        spec = build_project("2012hwexample.zip", path.read_bytes(), "zip")
        self.assertEqual(spec["runs"][0]["file"], "Course.cpp")
        sources = spec["runs"][0].get("sources") or []
        self.assertIn("Course.cpp", sources)
        self.assertIn("CourseOffering.cpp", sources)
        self.assertIn("PublicTests.cpp", sources)
        self.assertIn("Student.cpp", sources)
        self.assertIn("PartnerMatcher.cpp", sources)
