"""tools/harness/selection_bench.py: reason grouping, weights, dropped tests and flat-package import edges."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import selection_bench as bench  # noqa: E402


def test_kind_groups_reasons_by_first_word():
    assert bench.kind(["changed tools/x.py"]) == "own"
    assert bench.kind(["reverse dependent core", "references a.py"]) == "reverse"
    assert bench.kind(["reads docs/a.md"]) == "references"
    assert bench.kind(["guard set (D-436 1)"]) == "guard"
    assert bench.kind(["selector self-test tier (tools/land.py)"]) == "other"


def test_weight_prefers_path_then_basename_then_one():
    weights = {"a/test_x.py": 5.0, "test_y.py": 2.0}
    assert bench.weight("a/test_x.py", weights) == 5.0
    assert bench.weight("b/test_y.py", weights) == 2.0
    assert bench.weight("b/test_z.py", weights) == 1.0


def test_summarize_counts_and_dropped_tests():
    rows = [{"commit": "c1", "mode": "affected", "tests": {"t/test_a.py": "own", "t/test_b.py": "reverse"}},
            {"commit": "c2", "mode": "full", "tests": {"t/test_a.py": "full"}}]
    baseline = {"rows": [{"commit": "c1", "mode": "affected", "tests": {"t/test_a.py": "own", "t/test_c.py": "own"}},
                         {"commit": "c2", "mode": "affected", "tests": {"t/test_d.py": "own"}}]}
    out = bench.summarize(rows, {"test_b.py": 3.0}, baseline)
    assert out["files_sum"] == 3 and out["full"] == 1
    assert out["seconds_sum"] == 5.0
    assert out["by_kind"] == {"own": 1, "reverse": 1, "full": 1}
    assert out["dropped"] == {"c1": ["t/test_c.py"]}  # a FULL row on either side is never a drop


def test_edges_counts_flat_imports_between_subfolders(tmp_path):
    server = tmp_path / "pkg" / "server"
    (server / "ledger").mkdir(parents=True)
    (server / "missions").mkdir()
    (server / "test").mkdir()
    (server / "app.py").write_text("from pkg.server import charge, mission_service\n", encoding="utf-8")
    (server / "ledger" / "charge.py").write_text("import pkg.server.mission_service\n", encoding="utf-8")
    (server / "missions" / "mission_service.py").write_text("from .charge import x\nimport json\n", encoding="utf-8")
    (server / "test" / "test_app.py").write_text("from pkg.server import app\n", encoding="utf-8")
    edges = bench.edges(tmp_path, "pkg/server")
    assert edges == {"(root)": {"ledger": 1, "missions": 1}, "ledger": {"missions": 1}, "missions": {"ledger": 1}}
