"""Immutable native simulation inputs, activation, and one-shot execution."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
SHA = "a" * 40
RUN = SHA + "-" + "b" * 12


def test_capacity_ignores_own_advisory_lock_but_counts_visible_peer_budget(tmp_path, monkeypatch):
    import native_sim_job as job
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / ".native-sim-placement.lock").touch()
    (jobs / "peer.lock").write_text(f"{os.getpid()} sim 6 4\n")
    monkeypatch.setattr(job.os, "sched_getaffinity", lambda _pid: set(range(16)))
    monkeypatch.setattr(job.os, "getloadavg", lambda: (2, 2, 2))
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path == Path("/proc/meminfo"):
            return "MemAvailable: 12582912 kB\nMemTotal: 16777216 kB\n"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    assert job.capacity(jobs) == (10, 12)
    (jobs / "peer.lock").write_text("malformed visible budget\n")
    with pytest.raises(RuntimeError, match="budget"):
        job.capacity(jobs)


def prepared(tmp_path):
    from native_sim_inputs import inventory, write_json
    root = tmp_path / "prepared"
    source, state, dependency = root / "source", root / "state", tmp_path / "sdk"
    for path in (source, state, dependency):
        path.mkdir(parents=True)
    (source / "candidate.py").write_text("print('candidate')\n")
    (dependency / "module.py").write_text("SDK = True\n")
    (state / "environment.sh").write_text("export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST\n")
    (state / "run.sh").write_text("exit 0\n")
    metadata = {"schema": "rosy.omx-native-sim-prepared/1", "revision": SHA,
                "run_id": RUN, "role": "ai", "source": str(source), "state": str(state),
                "source_hashes": inventory(source), "dependency_roots": [str(dependency)],
                "dependency_hashes": inventory(dependency, absolute=True),
                "state_hashes": inventory(state), "sdk_status": "PASS", "runtime": "NOT_RUN"}
    write_json(root / "prepared.json", metadata)
    return root


def activated(tmp_path):
    from native_sim_prepare import activate
    (tmp_path / "managed/releases").mkdir(parents=True)
    (tmp_path / "managed/state").mkdir()
    return Path(activate(prepared(tmp_path), tmp_path / "managed")["state"])


def test_inventory_detects_additions_and_changes(tmp_path):
    from native_sim_inputs import inventory, verify_inventory
    (tmp_path / "a.py").write_text("before")
    expected = inventory(tmp_path)
    verify_inventory(tmp_path, expected)
    (tmp_path / "a.py").write_text("after")
    with pytest.raises(ValueError, match="drift"):
        verify_inventory(tmp_path, expected)
    (tmp_path / "a.py").write_text("before")
    (tmp_path / "extra.py").write_text("extra")
    with pytest.raises(ValueError, match="drift"):
        verify_inventory(tmp_path, expected)


@pytest.mark.parametrize("role", ["site", "fleet", "unknown"])
def test_host_config_refuses_production_roles(tmp_path, role):
    from native_sim_inputs import load_config
    config = tmp_path / "host.json"
    config.write_text(json.dumps({"schema": "rosy.omx-native-sim-host/1", "role": role,
                                  "ros_setup": "/sdk/setup.bash", "overlay": "/sdk/overlay",
                                  "python_site": "/sdk/site"}))
    with pytest.raises(ValueError, match="role"):
        load_config(config)


def test_activation_is_content_addressed_and_survives_staging_removal(tmp_path):
    from native_sim_prepare import activate
    from native_sim_job import validate_state
    staged = prepared(tmp_path)
    (tmp_path / "managed/releases").mkdir(parents=True)
    (tmp_path / "managed/state").mkdir()
    result = activate(staged, tmp_path / "managed")
    assert result["release"] == str(tmp_path / "managed/releases" / SHA)
    assert result["unit"] == "rosy-native-sim-" + RUN
    assert validate_state(Path(result["state"]))["revision"] == SHA
    assert activate(staged, tmp_path / "managed") == result
    (Path(result["release"]) / "candidate.py").write_text("changed")
    with pytest.raises(ValueError, match="drift"):
        activate(staged, tmp_path / "managed")


@pytest.mark.parametrize('experiment,episodes,entry', [
    ('pick-place', 1, 'sim_pick_place_task.py'),
    ('pick-place-demonstrations', 3, 'sim_pick_place_demonstrations.py'),
])
def test_activation_preserves_named_object_task_and_status_accepts_its_outputs(tmp_path, experiment, episodes, entry):
    from native_sim_prepare import activate
    from native_sim_job import status
    staged = prepared(tmp_path)
    document = json.loads((staged / 'prepared.json').read_text())
    document.update(experiment=experiment, episodes=episodes)
    (staged / 'prepared.json').write_text(json.dumps(document))
    (tmp_path / 'managed/releases').mkdir(parents=True)
    (tmp_path / 'managed/state').mkdir()
    state = Path(activate(staged, tmp_path / 'managed')['state'])
    script = (state / 'run.sh').read_text()
    assert entry in script
    if experiment == 'pick-place-demonstrations':
        assert '--episodes 3' in script
    (state / 'pick-place').mkdir()
    result = {'result': 'PASS', 'attempts': 1, 'successes': 1, 'training': 'NOT_RUN', 'full_g2': False}
    (state / 'pick-place/result.json').write_text(json.dumps(result))
    observed = status(state)
    assert observed['pick-place-result'] == result
    assert observed['real_episodes'] == 0


@pytest.mark.parametrize("area", ["release", "state", "dependency"])
def test_validation_rejects_input_drift_before_intent(tmp_path, area):
    from native_sim_job import validate_state
    state = activated(tmp_path)
    candidates = {"release": tmp_path / "managed/releases" / SHA / "candidate.py",
                  "state": state / "environment.sh", "dependency": tmp_path / "sdk/module.py"}
    candidates[area].write_text("tampered")
    with pytest.raises(ValueError, match="drift"):
        validate_state(state)
    assert not (state / "start-intent.json").exists()


def test_reservation_floor_and_site_marker_refuse_without_intent(tmp_path, monkeypatch):
    import native_sim_job as job
    state, jobs = activated(tmp_path), tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(job, "capacity", lambda *_: (5.99, 100))
    with pytest.raises(RuntimeError, match="headroom"):
        job.reserve(state, jobs_root=jobs)
    assert not (state / "start-intent.json").exists()
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 16))
    (jobs / "site").touch()
    with pytest.raises(PermissionError, match="site"):
        job.reserve(state, jobs_root=jobs)
    assert not (state / "start-intent.json").exists()


def test_reservation_has_owned_visible_budget_and_never_replays(tmp_path, monkeypatch):
    import native_sim_job as job
    state, jobs = activated(tmp_path), tmp_path / "jobs"
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 16))
    result = job.reserve(state, jobs_root=jobs)
    link = jobs / ("sim-omx-native-" + RUN + ".resv")
    assert link.is_symlink() and link.resolve() == state / "budget.resv"
    assert result["runtime"] == "NOT_RUN"
    assert (state / "budget.resv").read_text().split()[1:] == ["sim", "4", "4"]
    with pytest.raises(FileExistsError):
        job.reserve(state, jobs_root=jobs)


def test_unreserved_runtime_never_starts_child(tmp_path):
    from native_sim_job import run
    with pytest.raises(PermissionError, match="intent"):
        run(activated(tmp_path), launcher=lambda *_args, **_kwargs: pytest.fail("child started"))


def test_runtime_is_one_shot_and_cleans_only_own_budget(tmp_path, monkeypatch):
    import native_sim_job as job
    state, jobs = activated(tmp_path), tmp_path / "jobs"
    monkeypatch.setattr(job, "__file__", str(state.parent.parent / "releases" / SHA /
                                           "deploy/robot/omx/native_sim_job.py"))
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 16))
    job.reserve(state, jobs_root=jobs)
    (jobs / "other.lock").write_text(str(os.getpid()) + " sim 4 4\n")
    seen = []
    def launch(command, **kwargs):
        seen.append(command)
        assert (state / "budget.lock").read_text().split()[0] == str(os.getpid())
        assert not (state / "budget.resv").exists()
        return subprocess.CompletedProcess(command, 7)
    assert job.run(state, launcher=launch) == 7
    assert len(seen) == 1 and seen[0] == ["/bin/bash", "--noprofile", "--norc", str(state / "run.sh")]
    assert not (state / "budget.lock").exists()
    assert (jobs / "other.lock").exists()
    assert job.status(state)["exit_code"] == 7
    with pytest.raises(FileExistsError):
        job.run(state, launcher=launch)
    assert len(seen) == 1


def test_reservation_does_not_replace_foreign_budget_links(tmp_path, monkeypatch):
    import native_sim_job as job
    state, jobs = activated(tmp_path), tmp_path / "jobs"
    jobs.mkdir()
    foreign = jobs / ("sim-omx-native-" + RUN + ".lock")
    foreign.write_text("foreign")
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 16))
    with pytest.raises(FileExistsError):
        job.reserve(state, jobs_root=jobs)
    assert foreign.read_text() == "foreign"


def test_activation_requires_provisioned_anchors(tmp_path):
    from native_sim_prepare import activate
    with pytest.raises(PermissionError, match="provisioned"):
        activate(prepared(tmp_path), tmp_path / "not-provisioned")
    assert not (tmp_path / "not-provisioned").exists()


def test_runtime_rechecks_site_after_reservation_before_start(tmp_path, monkeypatch):
    import native_sim_job as job
    state, jobs = activated(tmp_path), tmp_path / "jobs"
    monkeypatch.setattr(job, "__file__", str(state.parent.parent / "releases" / SHA /
                                           "deploy/robot/omx/native_sim_job.py"))
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 16))
    job.reserve(state, jobs_root=jobs)
    (jobs / "site").touch()
    with pytest.raises(PermissionError, match="site"):
        job.run(state, launcher=lambda *_args, **_kwargs: pytest.fail("child started"))
    assert not (state / "run-intent.json").exists()


def test_runtime_rechecks_headroom_after_reservation(tmp_path, monkeypatch):
    import native_sim_job as job
    state, jobs = activated(tmp_path), tmp_path / "jobs"
    monkeypatch.setattr(job, "__file__", str(state.parent.parent / "releases" / SHA /
                                           "deploy/robot/omx/native_sim_job.py"))
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 16))
    job.reserve(state, jobs_root=jobs)
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 7.99))
    with pytest.raises(RuntimeError, match="headroom"):
        job.run(state, launcher=lambda *_args, **_kwargs: pytest.fail("child started"))
    assert not (state / "run-intent.json").exists()


def test_activation_reuse_does_not_silently_keep_another_sdk_config(tmp_path):
    from native_sim_inputs import inventory, read_json
    from native_sim_prepare import activate
    staged = prepared(tmp_path)
    (tmp_path / "managed/releases").mkdir(parents=True)
    (tmp_path / "managed/state").mkdir()
    activate(staged, tmp_path / "managed")
    (staged / "state/environment.sh").write_text("export DIFFERENT_SDK=1\n")
    document = read_json(staged / "prepared.json")
    document["state_hashes"] = inventory(staged / "state")
    (staged / "prepared.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="drift"):
        activate(staged, tmp_path / "managed")


def test_capacity_uses_the_existing_placement_formula_without_double_counting(tmp_path, monkeypatch):
    from native_sim_job import capacity
    (tmp_path / "peer.lock").write_text(str(os.getpid()) + " sim 6 4\n")
    real_read = Path.read_text
    def read(path, *args, **kwargs):
        if str(path) == "/proc/meminfo":
            return "MemAvailable: 12582912 kB\nMemTotal: 16777216 kB\n"
        return real_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _: set(range(16)))
    monkeypatch.setattr(os, "getloadavg", lambda: (8, 8, 8))
    assert capacity(tmp_path) == (8, 12)


def test_activation_rejects_state_changed_between_validation_and_copy(tmp_path, monkeypatch):
    import native_sim_prepare as preparation
    staged = prepared(tmp_path)
    (tmp_path / "managed/releases").mkdir(parents=True)
    (tmp_path / "managed/state").mkdir()
    real_copy = preparation.shutil.copytree
    def changed_copy(source, destination, *args, **kwargs):
        result = real_copy(source, destination, *args, **kwargs)
        if Path(source) == staged / "state":
            (Path(destination) / "environment.sh").write_text("CHANGED_AFTER_CHECK=1\n")
        return result
    monkeypatch.setattr(preparation.shutil, "copytree", changed_copy)
    with pytest.raises(ValueError, match="drift"):
        preparation.activate(staged, tmp_path / "managed")
    assert not (tmp_path / "managed/state" / RUN[-12:]).exists()


def test_export_source_reads_commit_and_omits_dirty_or_untracked_files(tmp_path):
    from native_sim_prepare import export_source
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "candidate.py").write_text("COMMITTED = True\n")
    subprocess.run(["git", "-C", str(repo), "add", "candidate.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-m", "fixture"], check=True, capture_output=True)
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    (repo / "candidate.py").write_text("DIRTY = True\n")
    (repo / "untracked.py").write_text("UNTRACKED = True\n")
    export_source(repo, revision, tmp_path / "export")
    assert (tmp_path / "export/candidate.py").read_text() == "COMMITTED = True\n"
    assert not (tmp_path / "export/untracked.py").exists()
    assert not (tmp_path / "export/.git").exists()


def test_compact_state_can_bind_the_canonical_linux_uds_path():
    # Pytest's own long temporary roots cannot stand in for the provisioned host root.
    with tempfile.TemporaryDirectory(prefix="omx-", dir="/tmp") as temporary:
        state = activated(Path(temporary))
        path = state / "g2/uds/omx_cell_sim_01/control.sock"
        path.parent.mkdir(parents=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
        assert state.name == "b" * 12
        deployed = Path("/var/lib/rosy-native-sim/1000/state") / state.name / path.relative_to(state)
        assert len(os.fsencode(deployed)) <= 107


def test_runtime_rejects_a_manifest_for_another_executing_release(tmp_path, monkeypatch):
    import native_sim_job as job
    state, jobs = activated(tmp_path), tmp_path / "jobs"
    monkeypatch.setattr(job, "capacity", lambda *_: (12, 16))
    job.reserve(state, jobs_root=jobs)
    monkeypatch.setattr(job, "__file__", str(state.parent.parent / "releases" / ("c" * 40) /
                                           "deploy/robot/omx/native_sim_job.py"))
    with pytest.raises(PermissionError, match="executing release"):
        job.run(state, launcher=lambda *_args, **_kwargs: pytest.fail("child started"))
    assert not (state / "run-intent.json").exists()


def test_tracked_sdk_template_instantiates_the_actual_host_loader(tmp_path):
    from native_sim_inputs import load_config
    template = Path(__file__).parents[1] / "deploy/robot/omx/native-sim-host.json.example"
    document = json.loads(template.read_text())
    for name in ("ros", "overlay", "dependencies", "python_site"):
        (tmp_path / name).mkdir()
    for name in ("ros", "overlay"):
        (tmp_path / name / "setup.bash").write_text("true\n")
    document.update(ros_setup=str(tmp_path / "ros/setup.bash"), overlay=str(tmp_path / "overlay"),
                    dependency_prefix=str(tmp_path / "dependencies"), python_site=str(tmp_path / "python_site"))
    instantiated = tmp_path / "host.json"
    instantiated.write_text(json.dumps(document))
    config = load_config(instantiated)
    assert config["role"] == "ai"
    assert config["ros_setup"] == str((tmp_path / "ros/setup.bash").resolve())
    document["role"] = "site"
    instantiated.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="role"):
        load_config(instantiated)
