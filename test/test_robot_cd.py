"""Robot CD refuses failed CI, PRs, forks and mismatched artifacts before signing."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import hashlib

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "ab" * 20


def module():
    spec = importlib.util.spec_from_file_location("robot_cd", ROOT / "tools/release/robot_cd.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(**changes):
    value = {"id": 11, "workflow_id": 9, "head_sha": SHA, "head_branch": "main",
             "event": "push", "status": "completed", "conclusion": "success",
             "repository": {"id": 7}, "head_repository": {"id": 7}}
    value.update(changes)
    return value


@pytest.mark.parametrize("changes", [
    {"event": "pull_request"}, {"head_branch": "topic"}, {"head_sha": "cd" * 20},
    {"conclusion": "failure"}, {"status": "in_progress"}, {"workflow_id": 10},
    {"repository": {"id": 8}}, {"head_repository": {"id": 8}},
])
def test_untrusted_or_failed_ci_is_refused(changes):
    assert not module().approved_run(run(**changes), sha=SHA, repo_id=7, workflow_id=9, event="push")


def test_exact_main_success_is_approved():
    assert module().approved_run(run(), sha=SHA, repo_id=7, workflow_id=9, event="push")


def test_release_ids_include_reservations_and_device_versions():
    assert module().next_release_id("2026.10.06", ["payload-2026.10.05-043",
        "payload-reserved-2026.10.05-045", "2026.10.05-044"]) == "2026.10.06-046"


def artifact(path, sha=SHA, link=False):
    with tarfile.open(path, "w:gz") as bundle:
        for name, content in [("source-revision.txt", sha + "\n"),
                              ("manifest.json", json.dumps({"source_revision": sha}))]:
            item = tarfile.TarInfo(name)
            if link and name == "source-revision.txt":
                item.type = tarfile.SYMTYPE
                item.linkname = "/tmp/other"
                bundle.addfile(item)
            else:
                data = content.encode()
                item.size = len(data)
                bundle.addfile(item, io.BytesIO(data))


@pytest.mark.parametrize("sha,link", [("cd" * 20, False), (SHA, True)])
def test_artifact_mismatch_and_link_refused_before_signing(tmp_path, sha, link):
    path = tmp_path / "candidate.tar.gz"
    artifact(path, sha, link)
    with pytest.raises(ValueError):
        module().verify_source(path, SHA)


def test_exact_artifact_is_accepted(tmp_path):
    path = tmp_path / "candidate.tar.gz"
    artifact(path)
    module().verify_source(path, SHA)


def test_failed_main_does_not_dispatch_or_sign(tmp_path):
    tool = module()
    calls = []

    def github(*args):
        calls.append(args)
        if "git/ref/heads/main" in args[1]:
            return json.dumps({"object": {"sha": SHA}})
        if "/workflows/" in args[1] and "/runs" not in args[1]:
            return json.dumps({"id": 9})
        if "/runs?" in args[1]:
            return json.dumps({"workflow_runs": [run(conclusion="failure")]})
        raise AssertionError(args)

    config = {"repo": "team/robots", "repo_id": 7, "state_dir": tmp_path,
              "robots": ["robot-a"], "canary": "robot-a", "key_name": "release-key"}
    assert tool.Coordinator(config, gh=github).tick() == "waiting_ci"
    assert all("workflow" != call[0] for call in calls)


def test_snapshot_rejects_changed_executable_code(tmp_path):
    tool = module()
    (tmp_path / "tool.py").write_text("approved")
    tool.write_snapshot(tmp_path, ["tool.py"], SHA)
    tool.verify_snapshot(tmp_path)
    (tmp_path / "tool.py").write_text("changed")
    with pytest.raises(ValueError):
        tool.verify_snapshot(tmp_path)


def test_dispatch_source_race_is_refused(tmp_path):
    tool = module()
    config = {"repo": "team/robots", "repo_id": 7, "state_dir": tmp_path,
              "robots": ["robot-a"], "canary": "robot-a", "key_name": "release-key"}
    tool.write_json(tmp_path / "state.json", {"sha": SHA, "phase": "building",
                                             "release_id": "2026.10.06-046"})

    def github(*args):
        path = args[1]
        if "git/ref/heads/main" in path:
            return json.dumps({"object": {"sha": SHA}})
        if "compare/" in path:
            return json.dumps({"status": "identical"})
        if "/runs?" in path:
            if "ci.yml" in path:
                return json.dumps({"workflow_runs": [run()]})
            return json.dumps({"workflow_runs": [run(event="workflow_dispatch", head_sha="cd" * 20,
                                 display_title="Pinky payload 2026.10.06-046")]})
        return json.dumps({"id": 9})

    assert tool.Coordinator(config, gh=github).tick() == "build_refused"
    assert json.loads((tmp_path / "state.json").read_text())["phase"] == "failed"


def test_pending_commit_removed_from_main_is_refused(tmp_path):
    tool = module()
    config = {"repo": "team/robots", "repo_id": 7, "state_dir": tmp_path,
              "robots": ["robot-a"], "canary": "robot-a", "key_name": "release-key"}
    tool.write_json(tmp_path / "state.json", {"sha": SHA, "phase": "building",
                                             "release_id": "2026.10.06-046"})

    def github(*args):
        path = args[1]
        if "git/ref/heads/main" in path:
            return json.dumps({"object": {"sha": "cd" * 20}})
        if "compare/" in path:
            return json.dumps({"status": "diverged"})
        if "/runs?" in path:
            return json.dumps({"workflow_runs": [run()]})
        return json.dumps({"id": 9})

    with pytest.raises(ValueError, match="no longer on main"):
        tool.Coordinator(config, gh=github).tick()


@pytest.mark.parametrize("field,value", [
    ("source_revision", "cd" * 20), ("tarball_sha256", "cd" * 32),
    ("release_id", "2026.10.06-047"), ("canary", ["different-robot"]),
])
def test_resumed_rollout_must_match_this_transaction(field, value):
    tool = module()
    state = {"sha": SHA, "tarball_sha256": "ab" * 32, "release_id": "2026.10.06-046",
             "canary_name": "robot-a"}
    remote = {"source_revision": SHA, "tarball_sha256": "ab" * 32,
              "release_id": state["release_id"], "canary": ["robot-a"]}
    remote[field] = value
    with pytest.raises(ValueError):
        tool.check_resume_identity(remote, state)


def test_crashed_preparation_preserves_old_attempt(tmp_path):
    tool = module()
    old = tmp_path / "attempt-1"
    (old / "x/release").mkdir(parents=True)
    state = {"attempt": 1, "work_dir": str(old)}
    assert tool.preparation_folder(tmp_path, state, "release") == tmp_path / "attempt-2"
    assert (old / "x/release").is_dir()


def test_dispatch_registration_wait_is_bounded():
    tool = module()
    assert tool.dispatch_expired("2026-10-05T12:00:00+00:00",
                                 tool.datetime.fromisoformat("2026-10-05T12:30:00+00:00"))
    assert not tool.dispatch_expired("2026-10-05T12:00:00+00:00",
                                     tool.datetime.fromisoformat("2026-10-05T12:01:00+00:00"))


def test_transient_publish_failure_keeps_verified_transaction_pending(tmp_path, monkeypatch):
    tool = module()
    monkeypatch.syspath_prepend(str(ROOT / "tools/release"))
    import publish_payload_release as publish
    work = tmp_path / "attempt-1"
    work.mkdir()
    signed = work / "2026.10.06-046.tar.gz"
    artifact(signed)
    state = {"sha": SHA, "phase": "publishing", "release_id": "2026.10.06-046",
             "work_dir": str(work), "tarball_sha256": hashlib.sha256(signed.read_bytes()).hexdigest(),
             "canary_name": "robot-a"}
    tool.write_json(tmp_path / "state.json", state)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    remote = {"release_id": state["release_id"], "source_revision": SHA,
              "tarball_sha256": state["tarball_sha256"], "canary": ["robot-a"], "withdrawn": False}
    monkeypatch.setattr(publish.Publisher, "download", lambda self: (remote, b"verified"))
    monkeypatch.setattr(publish, "main", lambda *args, **kwargs: 1)

    def github(*args):
        path = args[1]
        if "git/ref/heads/main" in path:
            return json.dumps({"object": {"sha": SHA}})
        if "compare/" in path:
            return json.dumps({"status": "identical"})
        if "/runs?" in path:
            return json.dumps({"workflow_runs": [run()]})
        if "matching-refs" in path:
            return json.dumps([{"ref": "exists"}])
        return json.dumps({"id": 9})

    config = {"repo": "team/robots", "repo_id": 7, "state_dir": tmp_path,
              "robots": ["robot-a"], "canary": "robot-a", "key_name": "release-key"}
    assert tool.Coordinator(config, gh=github).tick() == "rollout_pending"
    assert json.loads((tmp_path / "state.json").read_text())["phase"] == "publishing"


def test_next_release_has_independent_attempt_and_canary_state(tmp_path, monkeypatch):
    tool = module()
    monkeypatch.syspath_prepend(str(ROOT / "tools/release"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    tool.write_json(tmp_path / "state.json", {
        "sha": "cd" * 20, "phase": "done", "attempt": 3, "work_dir": str(tmp_path / "old"),
        "canary_name": "old-canary", "publisher_pid": 123, "tarball_sha256": "cd" * 32,
    })

    def github(*args):
        if args[0] == "workflow" or "--method" in args:
            return "{}"
        path = args[1]
        if "git/ref/heads/main" in path:
            return json.dumps({"object": {"sha": SHA}})
        if "/runs?" in path:
            return json.dumps({"workflow_runs": [run()]})
        if "releases?" in path or "matching-refs" in path:
            return "[]"
        return json.dumps({"id": 9})

    config = {"repo": "team/robots", "repo_id": 7, "state_dir": tmp_path,
              "robots": ["robot-a"], "canary": "robot-a", "key_name": "release-key"}
    coordinator = tool.Coordinator(config, gh=github)
    monkeypatch.setattr(coordinator, "ssh", lambda *args: (0, "/opt/rosy/releases/2026.10.05-043\n", ""))
    assert coordinator.tick() == "build_dispatched"
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["sha"] == SHA and state["phase"] == "building"
    assert not {"attempt", "work_dir", "canary_name", "publisher_pid", "tarball_sha256"} & state.keys()
    assert "old-canary" in (tmp_path / "audit.jsonl").read_text()
