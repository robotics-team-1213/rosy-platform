"""tools/remote/host_caps.py: a test module's HOST_CAPABILITIES keeps it off hosts that lack the environment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import host_caps  # noqa: E402
import host_probe  # noqa: E402
import remote_pytest as rp  # noqa: E402
import work_queue as wq  # noqa: E402

LEARNER = "test/learning/perception/test_learning_workflow_pipeline_browser.py"
NEED = frozenset({"learner_venv"})


@pytest.fixture(autouse=True)
def _fresh_headroom(monkeypatch):
    monkeypatch.setattr(rp, "HEADROOM", {})


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                       capture_output=True)
    git("init", "-q")
    (tmp_path / "suite").mkdir()
    (tmp_path / "suite" / "test_needs.py").write_text("HOST_CAPABILITIES = ('learner_venv',)\n\ndef test_a(): pass\n")
    (tmp_path / "suite" / "test_plain.py").write_text("def test_b(): pass\n")
    git("add", "-A")
    git("commit", "-q", "-m", "x")
    return tmp_path, subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True,
                                    text=True).stdout.strip()


def test_probe_prints_and_parses_the_capability_line():
    assert 'echo "ROSYCAPS' in host_probe.PROBE and "venv-cpu/bin/python" in host_probe.PROBE
    line = "ROSYPROBE 8 0.5 4194304 8388608 1 0 0 2 6 1 0 0"
    assert host_probe.parse_probe(f"{line}\nROSYCAPS learner_venv\n")["caps"] == NEED
    assert host_probe.parse_probe(f"{line}\nROSYCAPS\n")["caps"] == frozenset()
    assert host_probe.parse_probe(f"{line}\n")["caps"] == frozenset()  # an older probe: no capability


def test_the_pinned_learner_test_declares_its_capability():
    assert host_caps.needs(ROOT, "HEAD", [[LEARNER], [LEARNER + "::test_x"], ["test/test_host_caps.py"]]) == [
        NEED, NEED, frozenset()]


def test_needs_reads_files_and_folders_as_committed(repo):
    path, sha = repo
    assert host_caps.needs(path, sha, [["suite/test_needs.py"], ["suite/test_plain.py"], ["suite"], ["-q", "-k", "x"]]) == [
        NEED, frozenset(), NEED, frozenset()]


def test_route_gives_a_capability_test_only_to_a_host_that_has_it():
    wants = [NEED, frozenset()]
    site, model = {"caps": frozenset()}, {"caps": NEED}
    assert [host_caps.route(None, site, wants)(i) for i in (0, 1)] == [False, True]
    assert [host_caps.route(None, model, wants)(i) for i in (0, 1)] == [True, True]
    assert host_caps.route(lambda i: False, model, wants)(0) is False
    assert not host_caps.served(wants, [site]) and host_caps.served(wants, [site, model]) and host_caps.served(wants, [site]) is False


def test_strand_ends_unservable_work_as_not_run_instead_of_looping():
    work = wq.Work([0, 1])
    host_caps.strand(work, [NEED, frozenset()], [{"caps": frozenset()}])
    assert list(work.todo) == [1] and work.codes == {0: host_caps.LOST_EXIT}
    host_caps.strand(work, [NEED, frozenset()], [])  # no working host at all: left for run()'s own handling
    assert list(work.todo) == [1]


def test_run_waits_for_a_capable_host_then_fails_as_not_run(monkeypatch, repo, tmp_path):
    path, _ = repo
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    rp.HEADROOM["site@1"] = {"caps": frozenset()}
    monkeypatch.setattr(rp, "placed_hosts", lambda cls="pytest", hosts=None, cores=0: ["site@1"])
    monkeypatch.setattr(rp, "run_on", lambda *a, **k: pytest.fail("a host without the capability took the test"))
    now = [0.0]
    with pytest.raises(SystemExit, match="no test host reachable"):
        rp.run([["suite/test_needs.py"]], [tmp_path / "1.txt"], repo=path, wait=60, poll=30,
               sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])


def test_run_takes_the_test_once_a_capable_host_is_placed(monkeypatch, repo, tmp_path):
    path, _ = repo
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    rp.HEADROOM.update({"site@1": {"caps": frozenset()}, "model@1": {"caps": NEED}})
    monkeypatch.setattr(rp, "placed_hosts", lambda cls="pytest", hosts=None, cores=0: ["site@1", "model@1"])
    monkeypatch.setattr(rp, "run_on", lambda host, inv, logs, sha, repo, label, *a, **k: [0] * len(inv))
    assert rp.run([["suite/test_needs.py"]], [tmp_path / "1.txt"], repo=path) == [0]
