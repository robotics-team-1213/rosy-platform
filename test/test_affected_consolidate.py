"""affected_ros.consolidate merges small same-environment PR jobs and never mixes environments or kinds (11-20)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "harness"))
import affected_ros  # noqa: E402


def _e(name, ros, paths, kind="pytest"):
    return {"name": name, "invocations": [paths], "ros": ros, "kind": kind}


def test_small_same_environment_jobs_merge_and_keep_every_invocation():
    out = affected_ros.consolidate([_e("affected-1", "overlay", ["a/test_x.py"]),
                                    _e("affected-2", "overlay", ["b/test_y.py"])], {})
    assert len(out) == 1 and out[0]["invocations"] == [["a/test_x.py"], ["b/test_y.py"]]


def test_environments_kinds_and_non_affected_jobs_stay_apart():
    out = affected_ros.consolidate([_e("affected-1", "overlay", ["a/test_x.py"]),
                                    _e("affected-2", "full", ["b/test_y.py"]),
                                    _e("build-smoke", "overlay", [], kind="smoke")], {})
    assert [o["name"] for o in out] == ["affected-1", "affected-2", "build-smoke"]


def test_heavy_jobs_are_not_merged_past_the_weight_cap():
    heavy = {"test_big.py": affected_ros.JOB_WEIGHT}
    out = affected_ros.consolidate([_e("affected-1", "overlay", ["a/test_big.py"]),
                                    _e("affected-2", "overlay", ["b/test_y.py"])], heavy)
    assert len(out) == 2


def test_build_smoke_skips_only_outside_colcon_roots_workflows_and_deploy():
    import affected_ci
    from types import SimpleNamespace
    repo = SimpleNamespace(parts={"colcon_roots": ["middleware/core"]})
    sel = lambda *paths: SimpleNamespace(mode="affected", escalations=[], changed=list(paths))  # noqa: E731
    assert not affected_ci.buildable(repo, sel("tools/land_room.py", "test/test_x.py"))
    assert affected_ci.buildable(repo, sel("middleware/core/x.py"))
    assert affected_ci.buildable(repo, sel(".github/workflows/ci.yml"))
    assert affected_ci.buildable(repo, sel("deploy/site/x.yaml"))
    assert affected_ci.buildable(repo, sel("tools/harness/platform_parts.yaml"))
    assert affected_ci.buildable(SimpleNamespace(parts={}), sel("tools/land_room.py"))  # unknown roots keep the job


def test_shard_py_invocation_balances_heavy_root_tests_and_preserves_small():
    import affected_ci

    small = [f"test/test_s{i}.py" for i in range(5)]
    assert affected_ci._shard_py_invocation(small) == [small]

    heavy = list(affected_ci._HEAVY_ROOT_TESTS[:4]) + [f"test/test_extra_{i}.py" for i in range(10)] + ["--ignore=x.py"]
    shards = affected_ci._shard_py_invocation(heavy, n=3)
    assert len(shards) == 3
    # Heavy root tests must not pile onto the same runner
    for h in affected_ci._HEAVY_ROOT_TESTS[:3]:
        assert sum(h in s for s in shards) == 1
    assert len({next(i for i, s in enumerate(shards) if h in s) for h in affected_ci._HEAVY_ROOT_TESTS[:3]}) == 3
    assert sorted(p for s in shards for p in s if not p.startswith("-")) == sorted(
        p for p in heavy if not p.startswith("-")
    )
    assert all(s[-1] == "--ignore=x.py" for s in shards)
