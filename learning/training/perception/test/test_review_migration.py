"""Additive authority migration preserves terminal work and refuses unsafe copies."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from job_state import Job, JobError
import learning_cycle as cycle
from store import Store
import review_migration as migration


def raw(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "store")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_bytes(raw({"schema": "rosy.perception.dataset/1",
        "frames": [{"session": "a", "split": "train"}, {"session": "b", "split": "val"}]}))
    _, digest = store.put_dataset(dataset, "lanes")
    requests = tmp_path / "requests"
    requests.mkdir()
    (requests / "request.json").write_bytes(raw({"dataset": "lanes@" + digest, "purpose": "research"}))
    config = {"trainer": {"store": str(store.root)}, "recipes": [{"base": 8}, {"base": 16}],
              "requests_dir": str(requests), "reviews_dir": str(tmp_path / "reviews"),
              "interval_s": 2, "max_attempts": 2}
    source = tmp_path / "old"
    cycle.run_once(config, source, trainer_fn=lambda *args: {"revision": "original"})
    with Job(source, config) as job:
        job.state["extra"] = {"errors": ["original failure"], "revision": {"generation": 7}}
        job.step("original", lambda _: {"values": {"retained": True}, "files": {}})
    old_config, new_config = tmp_path / "old.json", tmp_path / "new.json"
    old_config.write_bytes(raw(config))
    new = dict(config, authority={"path": str(tmp_path / "current.json"),
                                "workspace_id": "a" * 32, "max_age_s": 90})
    new_config.write_bytes(raw(new))
    return source, old_config, new_config, tmp_path / "new", config, new


def migrate(setup):
    return migration.migrate(*setup[:4])


def test_terminal_cycles_steps_and_all_other_fields_survive_without_training(setup):
    source, old_cfg, new_cfg, target, old, new = setup
    before = (source / "state.json").read_bytes()
    result = migrate(setup)
    state = json.loads((target / "state.json").read_bytes())
    original = json.loads(before)
    assert {k: v for k, v in state.items() if k not in ("inputs", "input_signature")} == {
        k: v for k, v in original.items() if k not in ("inputs", "input_signature")}
    assert (source / "state.json").read_bytes() == before
    assert result["source_state_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["new_config_sha256"] == hashlib.sha256(new_cfg.read_bytes()).hexdigest()
    with Job(target, new) as job:
        assert job.step("original", lambda _: pytest.fail("completed stage must not rerun")) == {"retained": True}
    resumed = cycle.run_once(new, target, trainer_fn=lambda *args: pytest.fail("READY recipes must not train"))
    assert len(resumed["cycles"]) == 2


@pytest.mark.parametrize("change", ["recipe", "interval", "old", "authority_existing", "signature"])
def test_nonadditive_or_wrong_source_config_rejected(setup, change):
    source, old_cfg, new_cfg, target, old, new = setup
    if change == "recipe":
        new["recipes"] = [{"base": 32}]
    elif change == "interval":
        new["interval_s"] = 3
    elif change == "old":
        old["max_attempts"] = 3
        old_cfg.write_bytes(raw(old))
    elif change == "authority_existing":
        old["authority"] = new["authority"]
        old_cfg.write_bytes(raw(old))
    else:
        state = json.loads((source / "state.json").read_bytes())
        state["input_signature"] = "b" * 64
        (source / "state.json").write_bytes(raw(state))
    new_cfg.write_bytes(raw(new))
    with pytest.raises(JobError):
        migrate(setup)
    assert not target.exists()


@pytest.mark.parametrize("authority", [None, {}, {"path": "relative", "workspace_id": "a"*32, "max_age_s": 90},
    {"path": "/current", "workspace_id": "a"*32, "max_age_s": True},
    {"path": "/current", "workspace_id": "unknown", "max_age_s": 90},
    {"endpoint": "http://example.com/api/decisions", "workspace_id": "a"*32}])
def test_authority_is_typed_and_pinned(setup, authority):
    new = setup[-1]
    new["authority"] = authority
    setup[2].write_bytes(raw(new))
    with pytest.raises(JobError):
        migrate(setup)
    assert not setup[3].exists()


def test_source_writer_lock_blocks_migration(setup):
    with Job(setup[0], setup[-2]):
        with pytest.raises(JobError, match="running"):
            migrate(setup)
    assert not setup[3].exists()


def test_existing_target_never_overwritten(setup):
    setup[3].mkdir()
    sentinel = setup[3] / "original"
    sentinel.write_bytes(b"retain")
    with pytest.raises(JobError):
        migrate(setup)
    assert sentinel.read_bytes() == b"retain"


def test_interrupted_copy_never_publishes_job_state(setup, monkeypatch):
    monkeypatch.setattr(migration, "_copy_file", lambda *args: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        migrate(setup)
    assert not setup[3].exists()
    assert json.loads((setup[0] / "state.json").read_bytes())["cycles"]


def test_late_publication_failure_keeps_target_absent(setup, monkeypatch):
    monkeypatch.setattr(migration, "_publish", lambda *args: (_ for _ in ()).throw(OSError("interrupted publish")))
    with pytest.raises(OSError):
        migrate(setup)
    assert not setup[3].exists()


def test_source_files_and_receipt_paths_remain_original(setup):
    source = setup[0]
    output = source / "jobs/original/artifact.json"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"original output")
    with Job(source, setup[-2]) as job:
        job.step("artifact", lambda _: {"values": {}, "files": {
            str(output): hashlib.sha256(output.read_bytes()).hexdigest()}})
    before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    migrate(setup)
    assert all((source / p).read_bytes() == value for p, value in before.items())
    assert (setup[3] / "jobs/original/artifact.json").read_bytes() == b"original output"
    assert not (setup[3] / ".lock").exists()
    assert str(output) in Job(setup[3], setup[-1]).state["steps"]["artifact"]["receipt"]["files"]


def test_empty_job_output_directory_preserved(setup):
    (setup[0] / "jobs/empty").mkdir(parents=True)
    migrate(setup)
    assert (setup[3] / "jobs/empty").is_dir()


@pytest.mark.parametrize("mode", ["state", "config", "new_file"])
def test_source_mutation_during_copy_refused(setup, monkeypatch, mode):
    original = migration._copy_file
    changed = False
    def copy(path, value):
        nonlocal changed
        original(path, value)
        if not changed:
            changed = True
            if mode == "new_file":
                (setup[0] / "late.json").write_bytes(b"late")
            elif mode == "config":
                setup[1].write_bytes(setup[1].read_bytes() + b" ")
            else:
                state = json.loads((setup[0] / "state.json").read_bytes())
                state["outcome"] = "changed"
                (setup[0] / "state.json").write_bytes(raw(state))
    monkeypatch.setattr(migration, "_copy_file", copy)
    with pytest.raises(JobError, match="changed"):
        migrate(setup)
    assert not setup[3].exists()


def test_target_created_by_other_writer_at_publication_is_retained(setup, monkeypatch):
    original = migration._publish
    def publish(stage, target):
        target.mkdir()
        (target / "preserve").write_bytes(b"other writer")
        original(stage, target)
    monkeypatch.setattr(migration, "_publish", publish)
    with pytest.raises(OSError):
        migrate(setup)
    assert (setup[3] / "preserve").read_bytes() == b"other writer"
    assert not (setup[3] / "state.json").exists()


def test_target_inside_source_refused(setup):
    values = list(setup)
    values[3] = setup[0] / "migration"
    with pytest.raises(JobError):
        migrate(values)
    assert not values[3].exists()


@pytest.mark.parametrize("where", ["source_file", "target_parent"])
def test_symlink_paths_refused(setup, where, tmp_path):
    link = setup[0] / "linked" if where == "source_file" else tmp_path / "link"
    try:
        link.symlink_to(setup[0], target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink creation unavailable")
    values = list(setup)
    if where == "target_parent":
        values[3] = link / "destination"
    with pytest.raises(JobError):
        migrate(values)


def test_bridge_config_supported_without_network(tmp_path):
    old = {"source": str(tmp_path / "exports"), "peer": "approved-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 5, "max_attempts": 2}
    new = dict(old, authority={"endpoint": "http://127.0.0.1:8767/api/decisions", "workspace_id": "b"*32})
    source = tmp_path / "old"
    with Job(source, old) as job:
        job.state["exports"] = {"old": {"status": "done", "attempts": 1}}
        job._save()
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_bytes(raw(old)); b.write_bytes(raw(new))
    migration.migrate(source, a, b, tmp_path / "new")
    assert Job(tmp_path / "new", new).state["exports"]["old"]["status"] == "done"
