"""D-431: replay benchmarks reject missing or invalid measurements."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))


def test_benchmark_uses_p95_and_refuses_errors_or_no_frames():
    from bench_backends import summarize
    assert summarize([1, 2, 3, 10], errors=0, max_p95_ms=20)["ok"]
    assert not summarize([1, 2, 3, 100], errors=0, max_p95_ms=20)["ok"]
    assert not summarize([1], errors=1, max_p95_ms=20)["ok"]
    assert not summarize([], errors=0, max_p95_ms=20)["ok"]
    assert not summarize([float('nan')], errors=0, max_p95_ms=20)["ok"]


def test_benchmark_refuses_nonsensical_thresholds():
    import pytest
    from bench_backends import summarize
    for cap in (0, -1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            summarize([1], errors=0, max_p95_ms=cap)
