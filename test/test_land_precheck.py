"""tools/land_precheck.py: the cheap gates fail in the owner's terminal, before land_async makes a snapshot or ticket."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stop(Exception):
    pass


def fake_land(tmp_path, fail=None, merged=True):
    (tmp_path / "h.py").write_text("")
    calls = []

    def gate(name):
        def run(*args):
            calls.append(name)
            if fail == name:
                raise Stop(name)
        return run
    return calls, SimpleNamespace(
        Stop=Stop, HARNESS="h.py", out=lambda *a: "main-sha", lines=lambda *a: [], safety_review=gate("safety"), size_check=gate("size"),
        step=lambda wt, cmd, log, label: gate("lint")(), secret_scan=gate("secret"),
        git=lambda *a, **k: SimpleNamespace(returncode=0 if merged else 1))


def test_every_cheap_gate_runs_in_order(tmp_path):
    calls, land = fake_land(tmp_path)
    load("land_precheck").precheck(land, tmp_path, "python")
    assert calls == ["safety", "size", "lint", "secret"]


@pytest.mark.parametrize("gate,after", [("safety", []), ("size", ["safety"]), ("lint", ["safety", "size"]),
                                        ("secret", ["safety", "size", "lint"])])
def test_the_first_failing_gate_stops_the_rest(tmp_path, gate, after):
    calls, land = fake_land(tmp_path, fail=gate)
    with pytest.raises(Stop):
        load("land_precheck").precheck(land, tmp_path, "python")
    assert calls == [*after, gate]


def test_lint_before_main_is_merged_is_advisory_only(tmp_path, capsys):
    calls, land = fake_land(tmp_path, fail="lint", merged=False)
    load("land_precheck").precheck(land, tmp_path, "python")
    assert calls[-1] == "secret" and "supervisor re-lints" in capsys.readouterr().out


def test_land_async_stops_before_any_snapshot_when_the_precheck_fails(monkeypatch):
    tool = load("land_async")
    seen = []
    monkeypatch.setattr(tool.subprocess, "call", lambda argv, **k: seen.append(argv) or 1)
    monkeypatch.setattr(tool, "start", lambda *a, **k: pytest.fail("a snapshot was made after a failed precheck"))
    assert tool.main(["--tests", "auto"]) == 1
    assert seen[0][-1] == "--precheck" and seen[0][1].endswith("land.py")


def test_land_async_queues_after_a_passing_precheck(monkeypatch, tmp_path):
    tool = load("land_async")
    monkeypatch.setattr(tool.subprocess, "call", lambda argv, **k: 0)
    monkeypatch.setattr(tool, "start", lambda *a, **k: ("land/x", tmp_path / "x.log"))
    assert tool.main(["--tests", "auto"]) == 0
