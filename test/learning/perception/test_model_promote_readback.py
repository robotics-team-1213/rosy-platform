"""D-773 A3: every pointer change is recorded; --readback compares the node's loaded revision."""
import json

from test_model_deliver import SSH, FakeRunner, _model, deliver

import promote_readback  # noqa: E402  (test_model_deliver puts its folder on sys.path)

OBJ_ROOT = "/var/lib/rosy/models/object_det"


def _status(revision, signed=True):
    doc = {"schema": promote_readback.STATUS_SCHEMA, "model_revision": revision, "signed": signed}
    return f"'{json.dumps(doc)}'\n---\n"


class RobotRunner(FakeRunner):
    """Answers the pointer read and the status echo; every other step succeeds."""

    def __init__(self, pointer, status, status_rc=0):
        super().__init__()
        self.pointer, self.status, self.status_rc = pointer, status, status_rc

    def __call__(self, cmd, **kw):
        r = super().__call__(cmd, **kw)
        if cmd[-1].startswith("sudo -n cat -- "):
            r.stdout = self.pointer + "\n"
        elif "ros2 topic echo" in cmd[-1]:
            r.returncode, r.stdout = self.status_rc, self.status
        return r


def _records(tmp_path):
    path = tmp_path / "delivery-journal" / promote_readback.RECORD_NAME
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_push_is_recorded_without_any_extra_network_step(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH], runner=runner) == 0
    assert len(runner.calls) == 3  # prepare, scp, install: unchanged
    [row] = _records(tmp_path)
    assert (row["action"], row["slot"], row["pointer_revision"], row["readback"]) == (
        "push", "shadow", rev, "not_run")
    assert row["host"] == "robot" and "operator" in row


def test_promote_readback_matches_the_node_revision(tmp_path):
    runner = RobotRunner(f"{OBJ_ROOT}/det-7", _status("det-7"))
    assert deliver.main(["promote", "robot", "--task", "object_det", "--readback", *SSH], runner=runner) == 0
    echo = [c[-1] for c in runner.calls if "ros2 topic echo" in c[-1]]
    assert len(echo) == 1 and "perception/learned/object_det/status" in echo[0]
    assert "/etc/rosy/runtime.env" in echo[0] and echo[0].startswith("sudo -n bash -c ")
    [row] = _records(tmp_path)
    assert (row["slot"], row["pointer_revision"], row["node_revision"], row["readback"], row["signed"]) == (
        "active", "det-7", "det-7", "match", True)


def test_a_mismatch_is_reported_but_never_changes_the_exit_code(tmp_path, capsys, monkeypatch):
    runner = RobotRunner(f"{OBJ_ROOT}/det-7", _status("det-6"))
    monkeypatch.setattr(promote_readback.time, "sleep", lambda s: None)
    assert deliver.main(["promote", "robot", "--task", "object_det", "--readback", *SSH], runner=runner) == 0
    assert sum("ros2 topic echo" in c[-1] for c in runner.calls) == 3  # waits for the node to swap
    assert "readback mismatch: pointer det-7, node det-6" in capsys.readouterr().err
    assert _records(tmp_path)[0]["readback"] == "mismatch"


def test_an_unreadable_status_is_unavailable(tmp_path, capsys, monkeypatch):
    runner = RobotRunner(f"{OBJ_ROOT}/det-7", "", status_rc=124)
    monkeypatch.setattr(promote_readback.time, "sleep", lambda s: None)
    assert deliver.main(["promote", "robot", "--task", "object_det", "--readback", *SSH], runner=runner) == 0
    assert _records(tmp_path)[0]["readback"] == "unavailable"
    assert "readback unavailable" in capsys.readouterr().err


def test_a_slot_no_node_reads_is_recorded_as_no_node(tmp_path):
    runner = RobotRunner("/var/lib/rosy/models/lane-9", _status("lane-9"))
    assert deliver.main(["rollback", "robot", "--slot", "paint", "--readback", *SSH], runner=runner) == 0
    assert not any("ros2 topic echo" in c[-1] for c in runner.calls)
    assert _records(tmp_path)[0]["readback"] == "no_node"


def test_a_failed_or_read_only_command_records_nothing(tmp_path):
    assert deliver.main(["promote", "robot", "--task", "object_det", *SSH], runner=FakeRunner(returncode=1)) != 0
    assert deliver.main(["status", "robot", *SSH], runner=FakeRunner()) == 0
    assert _records(tmp_path) == []


def test_the_namespace_expands_in_the_root_shell_after_runtime_env():
    command = promote_readback.status_command("perception/learned/object_det/status")
    assert command.startswith("sudo -n bash -c '") and command.endswith("'")
    script = command[len("sudo -n bash -c '"):-1]
    assert script.index(". /etc/rosy/runtime.env") < script.index("${ROSY_NAMESPACE:+/$ROSY_NAMESPACE}")
    assert '"$NS/perception/learned/object_det/status" std_msgs/msg/String' in script
    assert "--full-length" in script and "--qos-durability transient_local" in script


def test_a_readback_that_raises_still_records_the_change(tmp_path):
    def hang(cmd, **kw):
        if "ros2 topic echo" in cmd[-1] or cmd[-1].startswith("sudo -n cat"):
            raise TimeoutError("ssh step timed out")
        return FakeRunner()(cmd, **kw)
    assert deliver.main(["promote", "robot", "--task", "object_det", "--readback", *SSH], runner=hang) == 0
    [row] = _records(tmp_path)
    assert row["readback"] == "unavailable" and row["readback_error"]


def test_status_output_parsing():
    assert promote_readback.parse_status(_status("x"))["model_revision"] == "x"
    assert promote_readback.parse_status("not json\n---\n") is None
    quoted = "'" + json.dumps({"schema": promote_readback.STATUS_SCHEMA, "model_revision": "x",
                               "last_error": "it's gone"}).replace("'", "''") + "'\n---\n"
    assert promote_readback.parse_status(quoted)["last_error"] == "it's gone"
    assert promote_readback.parse_status(json.dumps({"schema": "other"})) is None
    assert promote_readback.revision_of("/var/lib/rosy/models/object_det/det-7/\n") == "det-7"
    assert promote_readback.revision_of("") is None
