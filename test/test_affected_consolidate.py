"""affected_ros.consolidate merges small same-environment PR jobs and never mixes environments or kinds (11-20)."""
import sys
from pathlib import Path, PurePosixPath

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


def test_small_jobs_fill_up_to_the_slowest_job_of_the_run():
    """2026-11-21: 29% of CI runner time was job setup; a run is as long as its slowest job, so fill up to it."""
    costs = {"test_big.py": 3 * affected_ros.JOB_WEIGHT, "test_mid.py": affected_ros.JOB_WEIGHT}
    jobs = [_e("affected-1", "overlay", ["a/test_big.py"]), _e("affected-2", "overlay", ["b/test_mid.py"]),
            _e("affected-3", "overlay", ["c/test_mid.py"]), _e("affected-4", "overlay", ["d/test_mid.py"]),
            _e("affected-5", "overlay", ["e/test_mid.py"])]
    out = affected_ros.consolidate(jobs, costs)
    assert [o["invocations"] for o in out] == [[["a/test_big.py"]], [["b/test_mid.py"], ["c/test_mid.py"], ["d/test_mid.py"]],
                                               [["e/test_mid.py"]]]
    assert len(affected_ros.consolidate(jobs[1:], costs)) == 4, "without a slower job the cap stays JOB_WEIGHT"


def test_heavy_jobs_are_not_merged_past_the_weight_cap():
    heavy = {"test_big.py": affected_ros.JOB_WEIGHT}
    out = affected_ros.consolidate([_e("affected-1", "overlay", ["a/test_big.py"]),
                                    _e("affected-2", "overlay", ["b/test_y.py"])], heavy)
    assert len(out) == 2


def test_measured_seconds_keep_the_slow_selector_suite_off_the_shared_guard_runner():
    """Slow measured suites (>= JOB_WEIGHT) must not share a runner past cap with unrelated small invocations."""
    import affected_ci
    slow = "operations/fleet/test/test_site_map_browser.py"
    assert affected_ci.CI_TEST_SECONDS[PurePosixPath(slow).name] >= affected_ros.JOB_WEIGHT
    assert affected_ci.CI_TEST_SECONDS["test_site_map_browser.py"] == affected_ci.FLEET_TEST_SECONDS["test_site_map_browser.py"]
    jobs = [_e("affected-1", "overlay", ["test/test_a.py", "test/test_b.py"]), _e("affected-2", "overlay", [slow, "test/test_c.py"]),
            _e("affected-3", "overlay", ["test/test_d.py"])]
    out = affected_ros.consolidate(jobs, affected_ci.CI_TEST_SECONDS)
    assert [o["invocations"] for o in out] == [[["test/test_a.py", "test/test_b.py"], ["test/test_d.py"]], [[slow, "test/test_c.py"]]]


def test_ci_keeps_the_coarser_packing_when_measured_weights_would_pass_the_job_limit():
    import affected_ci
    slow = "test/test_affected_tests.py"  # 80 s: two do not fit one JOB_WEIGHT job; with Fleet weights only they all do
    few = [_e(f"affected-{i}", "overlay", [slow]) for i in range(3)]
    assert len(affected_ci.consolidated(few)) == 3
    many = [_e(f"affected-{i}", "overlay", [slow]) for i in range(affected_ci.MAX_CI_JOBS + 1)]
    out = affected_ci.consolidated(many)
    assert len(out) == 1 and out[0]["invocations"] == [[slow]] * len(many)


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

    mixed = ["middleware/media/test", "test/architecture", *(f"test/test_m{i}.py" for i in range(12))]
    shards = affected_ci._shard_py_invocation(mixed, n=3)
    assert len(shards) == 3 and sorted(p for s in shards for p in s) == sorted(mixed)
    assert affected_ci._shard_py_invocation(["a/test", "b/test", *small]) == [["a/test", "b/test", *small]]


def test_a_guard_only_runner_never_absorbs_a_job_that_needs_colcon():
    guard = dict(_e("affected-1", "overlay", ["a/test_x.py"]), colcon=False)
    out = affected_ros.consolidate([guard, _e("affected-2", "overlay", ["b/test_y.py"])], {})
    assert [o["name"] for o in out] == ["affected-1", "affected-2"] and out[0]["colcon"] is False


def test_guard_only_runners_skip_colcon_while_non_guard_overlay_keeps_it():
    import affected_ci
    import affected_tests as at

    repo = at.Repo.load(Path(__file__).resolve().parents[1])
    guard_sel = at.Selection("affected", ["docs/adr/D-1.md"], invocations=[[at.GUARD_SET[0]]])
    guard_entry = next(e for e in affected_ci.ci_matrix(repo, guard_sel)["include"] if e["kind"] == "pytest")
    assert guard_entry.get("colcon") is False

    mixed_sel = at.Selection("affected", ["integrations/simulation/gazebo/test/test_launch.py"],
                             invocations=[["integrations/simulation/gazebo/test/test_launch.py"]])
    mixed_entry = next(e for e in affected_ci.ci_matrix(repo, mixed_sel)["include"] if e["kind"] == "pytest")
    assert mixed_entry.get("colcon", True) is True

    root_sel = at.Selection("affected", ["test/test_robot_cd.py"], invocations=[["test/test_robot_cd.py"]])
    root_entry = next(e for e in affected_ci.ci_matrix(repo, root_sel)["include"] if e["kind"] == "pytest")
    assert root_entry["ros"] == "overlay" and root_entry.get("colcon") is False


def test_guard_set_consolidates_onto_one_non_colcon_runner():
    import affected_ci
    import affected_tests as at

    repo = at.Repo.load(Path(__file__).resolve().parents[1])
    include = affected_ci.ci_matrix(repo, at.select(repo, []))["include"]
    out = [e for e in affected_ci.consolidated(include) if e["kind"] == "pytest"]
    assert len(out) == 1
    assert out[0].get("colcon") is False
    assert len(out[0]["invocations"]) <= 2


def test_browser_overlay_entries_skip_colcon(monkeypatch):
    import affected_browser
    import affected_ci
    import affected_tests as at

    monkeypatch.setenv(affected_browser.ENV, "1")
    repo = at.Repo.load(Path(__file__).resolve().parents[1])
    include = affected_ci.ci_matrix(repo, at.select(repo, ["shared/web/surface_shell.js"]))["include"]
    overlay_browsers = [e for e in include if e["name"].startswith("browser-") and e["ros"] == "overlay"]
    assert overlay_browsers and all(e.get("colcon") is False for e in overlay_browsers)


def test_git_history_flag_is_emitted_only_for_history_readers_and_preserved_across_consolidate():
    import affected_ci
    import affected_tests as at

    repo = at.Repo.load(Path(__file__).resolve().parents[1])
    sel = at.Selection("affected", [], invocations=[
        ["operations/fleet/test/test_blocks.py"],
        ["test/test_harness_contracts.py"],
        ["test/architecture/test_module_structure.py"],
        ["test/test_safety_review.py"],
        ["test/test_remote_test_tools.py"],
        ["test/test_remote_fixture_isolation.py"],
        ["test/test_release_boundary_guards.py"],
        ["test/test_ci_image.py"],
    ])
    entries = {tuple(e["invocations"][0]): e for e in affected_ci.ci_matrix(repo, sel)["include"] if e["kind"] == "pytest"}
    assert entries[("test/test_harness_contracts.py",)].get("git_history") is True
    assert entries[("test/architecture/test_module_structure.py",)].get("git_history") is True
    assert entries[("test/test_safety_review.py",)].get("git_history") is True
    assert entries[("test/test_remote_test_tools.py",)].get("git_history") is True
    assert entries[("test/test_remote_fixture_isolation.py",)].get("git_history") is True
    assert entries[("test/test_release_boundary_guards.py",)].get("git_history") is True
    assert "git_history" not in entries[("operations/fleet/test/test_blocks.py",)]
    assert "git_history" not in entries[("test/test_ci_image.py",)]

    assert affected_ci._needs_git_history({
        "invocations": [
            ["test/architecture/test_module_structure.py"],
            ["test", "--ignore=test/architecture/test_module_structure.py"],
        ],
    }) is True
    assert affected_ci._needs_git_history({
        "invocations": [
            ["test", "--ignore=test/test_harness_contracts.py",
             "--ignore=test/architecture/test_module_structure.py",
             "--ignore=test/test_safety_review.py",
             "--ignore=test/test_remote_test_tools.py",
             "--ignore=test/test_remote_fixture_isolation.py",
             "--ignore=test/test_release_boundary_guards.py"],
        ],
    }) is False

    merged = affected_ros.consolidate([
        {"name": "affected-1", "invocations": [["test/test_ci_image.py"]], "ros": "overlay", "kind": "pytest"},
        {"name": "affected-2", "invocations": [["test/test_harness_contracts.py"]], "ros": "overlay",
         "kind": "pytest", "git_history": True},
    ], {})
    assert len(merged) == 1 and merged[0].get("git_history") is True


def test_pr_job_cap_packs_compatible_affected_jobs_only_and_preserves_invocations():
    import affected_ci

    jobs = [
        *(_e("affected-{}".format(i + 1), "overlay", [f"a/test_o{i}.py"]) for i in range(6)),
        {**_e("affected-7", "overlay", ["test/test_harness_contracts.py"]), "colcon": False, "git_history": True},
        {**_e("affected-8", "overlay", ["test/test_land.py"]), "colcon": False},
        *(_e("affected-{}".format(i + 9), "none", [f"b/test_n{i}.py"]) for i in range(5)),
        _e("browser-overlay-1of2", "overlay", ["operations/fleet/test/test_header_browser.py"]),
        _e("browser-overlay-2of2", "overlay", ["operations/fleet/test/test_cell_app_browser.py"]),
        {"name": "build-smoke", "invocations": [], "ros": "overlay", "kind": "smoke"},
    ]
    costs = {f"test_o{i}.py": affected_ros.JOB_WEIGHT for i in range(6)}
    costs.update({f"test_n{i}.py": affected_ros.JOB_WEIGHT for i in range(5)})
    costs["test_harness_contracts.py"] = affected_ros.JOB_WEIGHT
    costs["test_land.py"] = affected_ros.JOB_WEIGHT
    # Bypass consolidate's cap so we specifically exercise pack_to_limit under mixed ros/colcon/browser jobs.
    packed = affected_ros.pack_to_limit(jobs, costs, affected_ci.PR_JOB_CAP)
    assert len(packed) == affected_ci.PR_JOB_CAP
    assert [e["name"] for e in packed if not e["name"].startswith("affected-")] == [
        "browser-overlay-1of2", "browser-overlay-2of2", "build-smoke",
    ]
    assert sorted(tuple(inv) for e in packed for inv in e["invocations"]) == sorted(
        tuple(inv) for e in jobs for inv in e["invocations"]
    )
    for e in packed:
        if e["name"].startswith("affected-"):
            paths = [p for inv in e["invocations"] for p in inv]
            assert not (any(p.startswith("a/") for p in paths) and any(p.startswith("b/") for p in paths))
            assert not (any(p.startswith("test/") for p in paths) and any(p.startswith("a/") for p in paths))
    assert any(
        e.get("git_history") is True
        and ["test/test_harness_contracts.py"] in e["invocations"]
        and ["test/test_land.py"] in e["invocations"]
        for e in packed
    )
    assert affected_ci.PR_JOB_CAP < affected_ci.MAX_CI_JOBS


def test_consolidated_enforces_pr_job_cap_while_preserving_special_entries():
    import affected_ci

    include = [
        *(_e(f"affected-{i + 1}", "overlay", [f"a/test_o{i}.py"]) for i in range(6)),
        {**_e("affected-7", "overlay", ["test/test_harness_contracts.py"]), "colcon": False, "git_history": True},
        {**_e("affected-8", "overlay", ["test/test_land.py"]), "colcon": False},
        *(_e(f"affected-{i + 9}", "none", [f"b/test_n{i}.py"]) for i in range(6)),
        _e("omx-act-cpu", "none", ["learning/training/omx/test/test_act_inference_native.py"]),
        _e("g1-timing-exclusive", "overlay", ["test/test_platform_g1_timing.py"]),
        _e("browser-overlay-1of1", "overlay", ["operations/fleet/test/test_header_browser.py"]),
        {"name": "build-smoke", "invocations": [], "ros": "overlay", "kind": "smoke"},
    ]
    out = affected_ci.consolidated(include)
    assert len(out) <= affected_ci.PR_JOB_CAP
    assert [e["name"] for e in out if not e["name"].startswith("affected-")] == [
        "omx-act-cpu", "g1-timing-exclusive", "browser-overlay-1of1", "build-smoke",
    ]
    assert sorted(tuple(inv) for e in out for inv in e["invocations"]) == sorted(
        tuple(inv) for e in include for inv in e["invocations"]
    )


def test_build_smoke_skips_pure_contract_version_pin_but_keeps_code_edits():
    import affected_ci
    import affected_narrow
    import affected_tests as at
    from types import SimpleNamespace

    repo = at.Repo.load(Path(__file__).resolve().parents[1])
    pin_sel = at.Selection("affected", [affected_narrow.CONTRACT_VERSION_FILE])
    assert not affected_ci.buildable(repo, pin_sel)

    repo._texts[affected_narrow.CONTRACT_VERSION_FILE] = 'CONTRACT = "v1.1"\n\ndef helper():\n    return 1\n'
    assert affected_ci.buildable(repo, pin_sel)
    assert affected_ci.buildable(SimpleNamespace(parts={"colcon_roots": ["middleware/core"]}), pin_sel)


def test_pack_to_limit_respects_max_weight_so_heavy_shards_do_not_time_out():
    import affected_ci

    costs = {f"test_fleet_{i}.py": 480 for i in range(8)}
    fleet_shards = [_e(f"affected-{i + 1}", "none", [f"operations/fleet/test/test_fleet_{i}.py"]) for i in range(8)]
    special = [_e(f"browser-overlay-{i + 1}of9", "overlay", [f"test/test_b{i}_browser.py"]) for i in range(9)]
    packed = affected_ros.pack_to_limit([*fleet_shards, *special], costs, affected_ci.PR_JOB_CAP)

    affected_jobs = [e for e in packed if e["name"].startswith("affected-")]
    assert len(packed) == 13
    assert len(affected_jobs) == 4
    assert all(affected_ros._entry_weight(e, costs) == 960 <= affected_ros.MAX_PACKED_WEIGHT for e in affected_jobs)
    assert sorted(tuple(inv) for e in packed for inv in e["invocations"]) == sorted(
        tuple(inv) for e in [*fleet_shards, *special] for inv in e["invocations"]
    )


def test_pack_to_limit_respects_max_files_for_unmeasured_root_shards():
    import affected_ci

    root_shards = [
        {**_e(f"affected-{i + 1}", "overlay", [f"test/test_r{i}_{j}.py" for j in range(395)]), "colcon": False}
        for i in range(3)
    ]
    special = [_e(f"browser-overlay-{i + 1}of10", "overlay", [f"test/test_b{i}_browser.py"]) for i in range(10)]
    packed = affected_ros.pack_to_limit([*root_shards, *special], {}, affected_ci.PR_JOB_CAP)

    assert len(packed) == 13
    assert [len(e["invocations"]) for e in packed if e["name"].startswith("affected-")] == [1, 1, 1]
    assert sorted(tuple(inv) for e in packed for inv in e["invocations"]) == sorted(
        tuple(inv) for e in [*root_shards, *special] for inv in e["invocations"]
    )
