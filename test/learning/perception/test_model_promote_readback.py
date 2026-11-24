"""D-773 A3: every pointer change is recorded; --readback compares the node's loaded revision."""
import json

import pytest

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
    runner = RobotRunner(f"{OBJ_ROOT}/det-7", _status("det-7"))
    assert deliver.main(["rollback", "robot", "--task", "object_det", "--slot", "shadow",
                         "--readback", *SSH], runner=runner) == 0
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


def _paint(revision="lane-9", **changes):
    return json.dumps(dict(paint_source_used="learned_drivable", paint_model_revision=revision,
                          stamp=12.5, **changes)) + "\n---\n"


class PaintRunner(FakeRunner):
    def __init__(self, debug, pointers=("lane-9", "lane-9"), echo_rc=0):
        super().__init__()
        self.debug, self.pointers, self.echo_rc = debug, iter(pointers), echo_rc

    def __call__(self, cmd, **kw):
        result = super().__call__(cmd, **kw)
        if cmd[-1].startswith("sudo -n cat -- "):
            result.stdout = next(self.pointers) + "\n"
        elif "ros2 topic echo" in cmd[-1]:
            result.stdout, result.returncode = self.debug, self.echo_rc
        return result


def _read_paint(runner):
    return promote_readback.read_back(["ssh"], "test@consumer", "/var/lib/rosy/models",
                                     "lane_seg", "paint", runner, timeout=10, attempts=1,
                                     sleep=lambda _: None)


def test_paint_readback_matches_consumed_revision():
    runner = PaintRunner(_paint(signed=True))
    result = _read_paint(runner)
    assert result == dict(pointer_revision="lane-9", node_revision="lane-9", signed=None,
                          readback="match")
    assert sum(c[-1].startswith("sudo -n cat -- ") for c in runner.calls) == 2


def test_paint_probe_uses_volatile_debug():
    runner = PaintRunner(_paint())
    _read_paint(runner)
    [command] = [c[-1] for c in runner.calls if "ros2 topic echo" in c[-1]]
    assert '"$NS/line/keep_debug" std_msgs/msg/String' in command
    assert "--qos-durability volatile" in command and "transient_local" not in command
    assert command.index("/etc/rosy/runtime.env") < command.index("${ROSY_NAMESPACE:")


@pytest.mark.parametrize("debug", [
    _paint(None), _paint(7), "not JSON", "[]", _status("lane-9"),
    json.dumps(dict(paint_source_used="denoise", paint_model_revision="lane-9", stamp=12.5)),
    json.dumps(dict(paint_source_used="learned", paint_model_revision="lane-9", stamp=True)),
    json.dumps(dict(paint_source_used="learned", paint_model_revision="lane-9", stamp=float("nan"))),
])
def test_paint_readback_fallback_or_invalid_evidence_is_unavailable(debug):
    result = _read_paint(PaintRunner(debug))
    assert result["readback"] == "unavailable" and result["node_revision"] is None


def test_paint_readback_different_consumed_revision_is_mismatch():
    result = _read_paint(PaintRunner(_paint("lane-8")))
    assert result["readback"] == "mismatch" and result["node_revision"] == "lane-8"


@pytest.mark.parametrize("pointers", [("lane-9", "lane-10"), ("lane-9", "")])
def test_paint_readback_pointer_change_during_probe_is_not_match(pointers):
    assert _read_paint(PaintRunner(_paint(), pointers))["readback"] == "unavailable"


def test_paint_readback_without_frames_is_unavailable():
    assert _read_paint(PaintRunner("", echo_rc=124))["readback"] == "unavailable"


def test_paint_readback_keeps_delivery_exit_and_records_actual_consumer(tmp_path):
    runner = PaintRunner(_paint())
    assert deliver.main(["rollback", "robot", "--slot", "paint", "--readback", *SSH], runner=runner) == 0
    [row] = _records(tmp_path)
    assert (row["slot"], row["readback"], row["node_revision"], row["signed"]) == (
        "paint", "match", "lane-9", None)


def test_read_back_api_models_match_mismatch_stale_and_no_node():
    runner = RobotRunner(f"{OBJ_ROOT}/det-7", "")
    seen_urls = []

    def fake_fetch(url):
        seen_urls.append(url)
        return {"tasks": [
            {"task": "object_det", "slot": "active", "model_revision": "det-7", "signed": True, "stale": False},
            {"task": "lane_seg", "slot": "shadow", "model_revision": "lane-4", "signed": False, "stale": True},
        ]}

    res = promote_readback.read_back_api(
        "https://robot:8080/", "tok", ["ssh"], "rosy@robot", OBJ_ROOT, "object_det", "active",
        runner, timeout=5, attempts=1, fetch_json=fake_fetch)
    assert res == {"pointer_revision": "det-7", "node_revision": "det-7", "signed": True, "readback": "match"}
    assert seen_urls == ["https://robot:8080/api/v1/vision/models"]
    assert not any("ros2 topic echo" in c[-1] for c in runner.calls)

    # Mismatch retries `attempts` times and stays mismatch while exit code stays unchanged.
    sleeps = []
    mismatch = promote_readback.read_back_api(
        "https://robot:8080", "tok", ["ssh"], "rosy@robot", OBJ_ROOT, "object_det", "active",
        RobotRunner(f"{OBJ_ROOT}/det-8", ""), timeout=5, attempts=3, wait_s=1.0,
        sleep=sleeps.append, fetch_json=fake_fetch)
    assert mismatch == {"pointer_revision": "det-8", "node_revision": "det-7", "signed": True, "readback": "mismatch"}
    assert sleeps == [1.0, 1.0]

    stale = promote_readback.read_back_api(
        "https://robot:8080", "tok", ["ssh"], "rosy@robot", "/var/lib/rosy/models", "lane_seg", "shadow",
        RobotRunner("/var/lib/rosy/models/lane-4", ""), timeout=5, attempts=1, fetch_json=fake_fetch)
    assert stale["readback"] == "unavailable" and stale["node_revision"] is None

    no_node = promote_readback.read_back_api(
        "https://robot:8080", "tok", ["ssh"], "rosy@robot", OBJ_ROOT, "object_det", "shadow",
        runner, timeout=5, attempts=1, fetch_json=fake_fetch)
    assert no_node["readback"] == "no_node"


def test_read_back_api_paint_edge_cases():
    assert promote_readback.parse_api_paint({"applied_paint_source": "denoise_fallback", "applied_model_revision": "lane-9"}) is None
    assert promote_readback.parse_api_paint({"applied_paint_source": "learned", "applied_model_revision": ""}) is None
    runner = PaintRunner("", pointers=("lane-9", "lane-10"))
    moved = promote_readback.read_back_api(
        "https://robot:8080", "tok", ["ssh"], "rosy@robot", "/var/lib/rosy/models", "lane_seg", "paint",
        runner, timeout=5, attempts=1,
        fetch_json=lambda _u: {"applied_paint_source": "learned", "applied_model_revision": "lane-9"})
    assert moved["readback"] == "unavailable"


def test_http_get_json_hardening_and_error_handling():
    import http.client
    import io
    import urllib.request

    with pytest.raises(ValueError, match="https://"):
        promote_readback._http_get_json("http://robot:8080/api/v1/vision/models", token="tok")

    assert promote_readback._NoRedirect().redirect_request(None, None, 302, "Found", {}, "") is None

    seen = []

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def ok_opener(*handlers):
        seen.append(handlers)
        class Opener:
            def open(self, req, timeout=None):
                assert req.get_header("Authorization") == "Bearer env-tok"
                return FakeResp(b'{"tasks": []}')
        return Opener()

    doc = promote_readback._http_get_json(
        "HTTPS://robot:8080/api/v1/vision/models", token="env-tok", insecure=True, opener_factory=ok_opener)
    assert doc == {"tasks": []}
    assert isinstance(seen[0][0], urllib.request.ProxyHandler) and seen[0][0].proxies == {}
    assert isinstance(seen[0][2], promote_readback._NoRedirect)

    def err_opener(*_handlers):
        class Opener:
            def open(self, _req, timeout=None):
                raise http.client.RemoteDisconnected("closed")
        return Opener()

    assert promote_readback._http_get_json("https://robot:8080/api/v1/vision/models", opener_factory=err_opener) is None


def test_read_back_api_paint_and_deliver_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_API_TOKEN", "env-secret")
    token_file = tmp_path / "tok"
    token_file.write_text("secret-token\n", encoding="utf-8")
    runner = PaintRunner("")
    calls = []

    def fake_get(url, *, token=None, **_kw):
        calls.append((url, token))
        return {"applied_paint_source": "learned_drivable", "applied_model_revision": "lane-9"}

    monkeypatch.setattr(promote_readback, "_http_get_json", fake_get)
    assert deliver.main([
        "rollback", "robot", "--slot", "paint", "--readback",
        "--core-url", "https://robot:8080", "--token-file", str(token_file),
        "--journal-dir", str(tmp_path / "delivery-journal"), *SSH,
    ], runner=runner) == 0
    assert calls[-1] == ("https://robot:8080/api/v1/line-follow/perception", "secret-token")
    assert not any("ros2 topic echo" in c[-1] for c in runner.calls)
    [row] = _records(tmp_path)
    assert (row["slot"], row["readback"], row["node_revision"]) == ("paint", "match", "lane-9")

    # Omitting --token-file reads ROSY_API_TOKEN; mismatch leaves delivery exit code 0.
    assert deliver.main([
        "promote", "robot", "--task", "object_det", "--readback", "--core-url", "https://robot:8080",
        "--journal-dir", str(tmp_path / "delivery-journal"), *SSH,
    ], runner=RobotRunner(f"{OBJ_ROOT}/det-99", "")) == 0
    assert calls[-1] == ("https://robot:8080/api/v1/vision/models", "env-secret")

    with pytest.raises(SystemExit):
        deliver.main(["promote", "robot", "--ca-file", "/tmp/c", "--insecure", *SSH], runner=runner)
