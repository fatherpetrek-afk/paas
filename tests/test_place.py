from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control.place import pick_env, score_worker


class PlaceTests(unittest.TestCase):
    def test_idle_beats_busy(self) -> None:
        idle = score_worker(idle=True, queued=0, cpu=40, mem=40, sticky=False, has_gpu=False, needs_gpu=False)
        busy = score_worker(idle=False, queued=0, cpu=10, mem=10, sticky=False, has_gpu=False, needs_gpu=False)
        self.assertGreater(idle, busy)

    def test_shorter_queue_wins(self) -> None:
        short = score_worker(idle=False, queued=1, cpu=0, mem=0, sticky=False, has_gpu=False, needs_gpu=False)
        long = score_worker(idle=False, queued=4, cpu=0, mem=0, sticky=False, has_gpu=False, needs_gpu=False)
        self.assertGreater(short, long)

    def test_sticky_breaks_tie(self) -> None:
        a = score_worker(idle=True, queued=0, cpu=0, mem=0, sticky=True, has_gpu=False, needs_gpu=False)
        b = score_worker(idle=True, queued=0, cpu=0, mem=0, sticky=False, has_gpu=False, needs_gpu=False)
        self.assertGreater(a, b)

    def test_gpu_required(self) -> None:
        with_gpu = score_worker(idle=True, queued=0, cpu=0, mem=0, sticky=False, has_gpu=True, needs_gpu=True)
        no_gpu = score_worker(idle=True, queued=0, cpu=0, mem=0, sticky=False, has_gpu=False, needs_gpu=True)
        self.assertGreater(with_gpu, no_gpu)

    def test_pick_python_over_node_for_py(self) -> None:
        env = pick_env(
            [
                {"id": "node", "kind": "node", "pkg_n": 9},
                {"id": "py", "kind": "python", "pkg_n": 2},
            ],
            {"language": "python"},
        )
        self.assertEqual(env["id"], "py")

    def test_pick_richer_python(self) -> None:
        env = pick_env(
            [
                {"id": "slim", "kind": "python", "pkg_n": 3},
                {"id": "full", "kind": "python", "pkg_n": 40},
            ],
            {"language": "python"},
        )
        self.assertEqual(env["id"], "full")

    def test_html_uses_python(self) -> None:
        env = pick_env(
            [{"id": "py", "kind": "python", "pkg_n": 1}, {"id": "node", "kind": "node", "pkg_n": 8}],
            {"language": "html"},
        )
        self.assertEqual(env["id"], "py")


if __name__ == "__main__":
    unittest.main()
