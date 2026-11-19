"""Tests for the 24/7 continuous rolling regression engine (D-1052)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import rolling_regression as rr  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _init_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repo"
    (repo / "pkg_a" / "test").mkdir(parents=True)
    (repo / "pkg_b" / "test").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "pkg_a" / "test" / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")
    (repo / "pkg_b" / "test" / "test_b.py").write_text("def test_b(): assert True\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    c1 = _git(repo, "rev-parse", "HEAD")

    (repo / "pkg_b" / "test" / "test_b.py").write_text("def test_b(): assert 1 == 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "touch pkg_b only")
    c2 = _git(repo, "rev-parse", "HEAD")

    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\nminversion = '8.0'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "touch global seam")
    c3 = _git(repo, "rev-parse", "HEAD")
    return repo, c1, c2, c3


def test_shard_key_tracks_target_and_global_seam_and_bypasses_root_test(tmp_path):
    repo, c1, c2, c3 = _init_repo(tmp_path)
    shard_a = {"name": "pkg-a", "ros": "none", "invocations": [["pkg_a/test"]]}
    shard_b = {"name": "pkg-b", "ros": "none", "invocations": [["pkg_b/test"]]}
    root_shard = {"name": "root-test-1of3", "ros": "overlay", "invocations": [["test/test_a.py"]]}

    k_a1 = rr.shard_key(repo, c1, shard_a, use_closure=False)
    k_a2 = rr.shard_key(repo, c2, shard_a, use_closure=False)
    k_a3 = rr.shard_key(repo, c3, shard_a, use_closure=False)
    k_b1 = rr.shard_key(repo, c1, shard_b, use_closure=False)
    k_b2 = rr.shard_key(repo, c2, shard_b, use_closure=False)

    assert k_a1 and k_a1 == k_a2
    assert k_a3 != k_a2
    assert k_b1 != k_b2
    assert rr.shard_key(repo, c1, root_shard, use_closure=False) is None


def test_select_gha_batch_enforces_h5_exclusion_and_core_ttl_watermark(tmp_path):
    repo, c1, _c2, c3 = _init_repo(tmp_path)
    shards = [
        {"name": "pkg-a", "ros": "none", "invocations": [["pkg_a/test"]], "venue": "gha", "ttl_s": rr.CORE_TTL_S},
        {"name": "gz-sim", "ros": "overlay", "invocations": [["integrations/simulation/gazebo/test"]], "venue": "lab", "ttl_s": rr.LAB_TTL_S},
        {"name": "mislabeled-h5", "ros": "none", "invocations": [["ROSY_JOB_ALONE=1", "test/test_platform_g1_timing.py"]], "venue": "gha"},
    ]
    k_a1 = rr.shard_key(repo, c1, shards[0], use_closure=False)
    now = 1_700_000_000.0
    state = {"shards": {"pkg-a": {"recent_keys": [k_a1], "last_real_run_ts": now - 3600.0, "verified_sha": c1}}}

    # Same key within 12h TTL -> satisfied; H5 shards never enter GHA batch.
    assert rr.select_gha_batch(repo, c1, state, limit=4, now=now, shards=shards) == []

    # Past 12h CORE_TTL_S -> forced re-run even with identical shard_key.
    stale_batch = rr.select_gha_batch(repo, c1, state, limit=4, now=now + rr.CORE_TTL_S + 10.0, shards=shards)
    assert [b["name"] for b in stale_batch] == ["pkg-a"]

    # Changed global seam -> immediate key miss selects shard even inside TTL.
    miss_batch = rr.select_gha_batch(repo, c3, state, limit=4, now=now, shards=shards)
    assert [b["name"] for b in miss_batch] == ["pkg-a"]
    wm = rr.watermark(state, shards[:2], repo, c1, now=now)
    assert wm["total"] == 2 and wm["satisfied"] == 1


def test_lab_micro_warm_enforces_batch_one_disk_guard_and_subsecond_preemption(tmp_path):
    repo, c1, _c2, _c3 = _init_repo(tmp_path)
    gc_calls = []
    assert rr.evaluate_disk_budget(24.0, est_gb=2.0, gc_fn=lambda: gc_calls.append(1) or 26.0) == (True, "ok:26.0GB")
    assert gc_calls == [1]
    assert rr.evaluate_disk_budget(19.0, est_gb=16.0)[0] is False  # requires 16 + 5 = 21 GB
    assert rr.evaluate_disk_budget(17.5, est_gb=1.0)[0] is False   # requires max(18, 6) = 18 GB

    shards = [
        {"name": "gz-sim", "ros": "overlay", "invocations": [["integrations/simulation/gazebo/test"]], "venue": "lab", "ttl_s": rr.LAB_TTL_S, "est_gb": 6.0},
        {"name": "omx-adapter-lab", "ros": "overlay", "invocations": [["middleware/devices/omx/adapter/test"]], "venue": "lab", "ttl_s": rr.LAB_TTL_S, "est_gb": 2.0},
    ]
    state = {"shards": {"gz-sim": {"last_real_run_ts": 100.0}, "omx-adapter-lab": {"last_real_run_ts": 50.0}}}
    assert rr.lab_micro_warm(repo, c1, state, shards=shards, queue_check=lambda: True)["status"] == "skipped_queue"
    assert rr.lab_micro_warm(repo, c1, state, shards=shards, queue_check=lambda: False, disk_probe=lambda: 12.0)["ran"] == 0

    ran = []
    res = rr.lab_micro_warm(
        repo, c1, state, shards=shards, queue_check=lambda: False, disk_probe=lambda: 25.0,
        runner=lambda sh, _stop: (ran.append(sh["name"]) or 0, "1 passed in 0.1s", False), now=1000.0,
    )
    assert res["status"] == "warmed" and ran == ["omx-adapter-lab"]  # WARM_BATCH=1, picks stalest shard

    t0 = time.monotonic()
    flip = {"now": False}
    code, _out, preempted = rr.run_preemptible(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        poll_preempt=lambda: flip["now"] or (time.monotonic() - t0 > 0.12 and not flip.__setitem__("now", True)),
        poll_s=0.05, term_grace_s=0.2,
    )
    elapsed = time.monotonic() - t0
    assert preempted is True and code == 130 and elapsed < 1.0


def test_nodeid_retry_and_two_stage_closure_bisect(tmp_path):
    calls = []

    def flaky_then_clean(inv):
        calls.append(inv)
        if inv == ["pkg_a/test"]:
            return 1, "FAILED pkg_a/test/test_a.py::test_flaky - boom\n1 failed in 0.1s\n"
        return 0, "PASSED pkg_a/test/test_a.py::test_flaky\n1 passed in 0.05s\n"

    flaky_res = rr.run_with_nodeid_retry([["pkg_a/test"]], flaky_then_clean, {})
    assert flaky_res["clean"] is True
    assert flaky_res["flaky_cleared"] == ["pkg_a/test/test_a.py::test_flaky"]
    assert calls[1] == ["-v", "pkg_a/test/test_a.py::test_flaky"]

    det_res = rr.run_with_nodeid_retry(
        [["pkg_a/test"]],
        lambda _inv: (1, "____ test_det ____\npkg_a/test/test_a.py:3: AssertionError\nE assert False\nFAILED pkg_a/test/test_a.py::test_det - assert False\n"),
        {},
    )
    assert det_res["clean"] is False and det_res["deterministic_failures"] == ["pkg_a/test/test_a.py::test_det"]
    bisect_calls, state = [], {"shards": {}, "open_culprits": {}}
    rr.record_gha_results(tmp_path, "sha2", state, [{"name": "pkg-a", **det_res}], now=10.0,
                          bisect_fn=lambda sh, n, lg: bisect_calls.append(n) or {"culprit": "sha1", "probes": 2})
    rr.record_gha_results(tmp_path, "sha3", state, [{"name": "pkg-a", **det_res}], now=20.0,
                          bisect_fn=lambda sh, n, lg: bisect_calls.append(n) or {"culprit": "sha1", "probes": 2})
    assert len(bisect_calls) == 1  # deduplicated by (nodeid, fingerprint)

    commits = [f"c{i:02d}" for i in range(1, 21)]
    # Stage 1: culprit c07 sits inside 3-commit closure subset m -> <= 4 single-nodeid probes.
    p1 = []
    b1 = rr.bisect_culprit(
        commits, "pkg_a/test/test_a.py::test_a",
        lambda c, _n: (p1.append(c), int(c[1:]) < 7)[1],
        touched_commits=["c03", "c07", "c12"], base_green="c00",
    )
    assert b1["culprit"] == "c07" and b1["stage"] == "closure" and b1["probes"] <= 4

    # Stage 2: undeclared seam at c15 (all m pass!) -> falls back cleanly across narrowed tail.
    p2 = []
    b2 = rr.bisect_culprit(
        commits, "pkg_a/test/test_a.py::test_a",
        lambda c, _n: (p2.append(c), int(c[1:]) < 15)[1],
        touched_commits=["c03", "c07", "c12"], base_green="c00",
    )
    assert b2["culprit"] == "c15" and b2["stage"] == "full_fallback" and b2["probes"] <= 6


def test_rolling_sweep_workflow_contract():
    wf = yaml.safe_load((ROOT / ".github/workflows/rolling-sweep.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on", wf.get(True))
    assert {"cron": "*/30 * * * *"} in triggers["schedule"]
    assert "workflow_dispatch" in triggers
    assert wf["concurrency"] == {"group": "rosy-rolling-sweep", "cancel-in-progress": False}
    assert "ci-result" not in wf["jobs"]
    assert all(int(job.get("timeout-minutes", 0)) <= 25 for job in wf["jobs"].values())
