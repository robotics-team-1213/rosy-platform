"""Host choice: least placed work first, floors and alone rules unchanged, floor metric reported once."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import placement  # noqa: E402
import remote_pytest as rp  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(rp, "HEADROOM", {})
    placement.reset()


def host(nproc=24, load1=1.0, avail_gb=12.0, total_gb=15.0, **kw):
    return {"nproc": nproc, "load1": load1, "avail_gb": avail_gb, "total_gb": total_gb, "pytest": True,
            "sim": False, "busy": False, "lock_cores": 0, "lock_gb": 0, "site": False, **kw}


def test_least_placed_work_goes_first_with_two_hosts():
    roomy, tight = host(avail_gb=14), host(avail_gb=8)
    assert rp.place("pytest", ["a@1", "b@2"], [roomy, tight])[0] == ["a@1", "b@2"]  # no work yet: headroom
    placement.charge("a@1", 300)
    assert rp.place("pytest", ["a@1", "b@2"], [roomy, tight])[0] == ["b@2", "a@1"]


def test_three_hosts_order_and_tie_break_is_list_order():
    probes = [host(), host(), host()]
    hosts = ["a@1", "b@2", "c@3"]
    assert rp.place("pytest", hosts, probes)[0] == hosts
    placement.charge("a@1", 60)
    placement.charge("b@2", 10)
    assert rp.place("pytest", hosts, probes)[0] == ["c@3", "b@2", "a@1"]


def test_a_host_below_the_floor_is_never_chosen_however_idle(capsys):
    chosen, notes = rp.place("pytest", ["busy@1", "low@2"], [host(), host(avail_gb=2)])
    assert chosen == ["busy@1"] and "RAM 2.0 < 4" in notes[1]
    placement.charge("busy@1", 9999)
    assert rp.place("pytest", ["busy@1", "low@2"], [host(), host(avail_gb=2)])[0] == ["busy@1"]
    assert capsys.readouterr().err.count("floor-skip host=low@2") == 1  # once per host per run


def test_floor_event_names_the_failing_metric(capsys):
    rp.place("pytest", ["x@1"], [host(nproc=3, load1=2.5, avail_gb=2)])
    err = capsys.readouterr().err
    assert "floor-skip host=x@1 class=pytest cores=0.5 floor=2 ram=2.0 floor=4" in err


def test_alone_rule_unchanged():
    chosen, notes = rp.place("pytest", ["blocked@1", "free@2"], [host(pytest_blocked=True), host()])
    assert chosen == ["free@2"] and "alone job" in notes[0]
