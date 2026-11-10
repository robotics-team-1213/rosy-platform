"""The NEW ids a landing reruns alone must survive the remote argv (test_land.py is at the D-766 size limit)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_checks  # noqa: E402


def test_a_parameter_id_with_spaces_or_escapes_reruns_the_whole_test_function(tmp_path):
    """2026-11-08: a "[response1-<escaped Korean> ...-index.html]" id did not survive the remote argv and ran nothing."""
    (tmp_path / "pkg/test").mkdir(parents=True)
    (tmp_path / "pkg/test/test_a.py").write_text("def test_a(x): pass\n", encoding="utf-8")
    verdict = ("NEW pkg/test/test_a.py::test_a[response1-\\ube44\\uc0c1 \\uc815-index.html]\n"
               "NEW pkg/test/test_a.py::test_a[response2-\\ube44-other]\n"
               "NEW pkg/test/test_a.py::test_a[response0-plain]\n")
    assert land_checks._ids(tmp_path, verdict) == ["pkg/test/test_a.py::test_a", "pkg/test/test_a.py::test_a[response0-plain]"]
