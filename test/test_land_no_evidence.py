"""land.py's verdict on a pytest exit that names no failure (2026-10-28: eight landings stopped on it)."""

from __future__ import annotations

import pytest

from test_land import cached, land, repos  # noqa: F401  (land.py's fixtures)


@pytest.mark.parametrize("second", [0, 1])
def test_an_exit_without_failure_evidence_reruns_once(cached, monkeypatch, second):
    """pytest exited 1 with every test passed and no FAILED/ERROR line: one rerun of the same invocation decides."""
    wt, run, calls = cached
    seen = []

    def fake(invs, logs, *a, **k):
        seen.append(k.get("label"))
        for log in logs:
            land.Path(log).parent.mkdir(parents=True, exist_ok=True)
            land.Path(log).write_text("7233 passed, 407 skipped\n", encoding="utf-8")
        return [1] if len(seen) == 1 else [second]
    monkeypatch.setattr(land.remote_pytest, "run", fake)
    if second == 0:
        done = run([["pkg/test"]])
        assert len(seen) == 2 and "ok on one rerun" in done[0]
    else:
        with pytest.raises(land.Stop, match="without usable failure evidence, rerun exit 1"):
            run([["pkg/test"]])
        assert len(seen) == 2  # one rerun only


def test_an_error_line_is_failure_evidence(tmp_path):
    log = tmp_path / "run.txt"
    log.write_text("ERROR operations/fleet/test/test_work_sources.py::test_kinds - boom\n1 error\n", encoding="utf-8")
    assert land.land_cache.unusable(1, log) is None
    log.write_text("7233 passed\n", encoding="utf-8")
    assert land.land_cache.unusable(1, log) == land.land_cache.NO_EVIDENCE
