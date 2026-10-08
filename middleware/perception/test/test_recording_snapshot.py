"""D-373 decision 4: snapshot recording, one session per snapshot dump."""

import json
import subprocess
from datetime import datetime, timezone

import pytest

import control.record_session as rs
from control.recording import (
    COMPRESSED_CAMERA_TOPIC,
    DEFAULT_ROOT,
    SIDE_TOPICS,
    SNAPSHOT_CACHE_BYTES,
    SNAPSHOT_FRAME_BUDGET_BYTES,
    SNAPSHOT_FPS,
    SNAPSHOT_SECONDS,
    SNAPSHOT_SIDE_BUDGET_BYTES,
    adopt_snapshot,
    bag_command,
    closed_snapshot_files,
    enforce_quota,
    mark_harvested,
    pending_snapshot_requests,
    record_topics,
    snapshot_bag_command,
    write_snapshot_request,
)

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
META = dict(device="pinky-1", camera_profile_revision="cam1", model_revision="m1")


def _meta(folder):
    return json.loads((folder / "session.json").read_text())


def test_default_root_is_the_camera_state_directory():
    assert DEFAULT_ROOT == "/var/lib/rosy/camera/recordings"
    assert rs.DEFAULT_ROOT == DEFAULT_ROOT  # the CLI default, --root still overrides


def test_cache_size_is_sixty_seconds_of_the_compressed_stream():
    assert SNAPSHOT_SECONDS == 60 and SNAPSHOT_FPS == 8
    assert SNAPSHOT_CACHE_BYTES == (
        (SNAPSHOT_FRAME_BUDGET_BYTES + SNAPSHOT_SIDE_BUDGET_BYTES) * SNAPSHOT_FPS * SNAPSHOT_SECONDS)
    assert 5_000_000 < SNAPSHOT_CACHE_BYTES < 50_000_000  # fits Pi memory next to the stack
    from control.recording import SCAN_TOPIC, SNAPSHOT_SCAN_BUDGET_BYTES
    assert SCAN_TOPIC in SIDE_TOPICS and SNAPSHOT_SIDE_BUDGET_BYTES >= 4_000 + SNAPSHOT_SCAN_BUDGET_BYTES


def test_record_topics_choose_the_camera_stream():
    assert record_topics(COMPRESSED_CAMERA_TOPIC) == (
        COMPRESSED_CAMERA_TOPIC, *SIDE_TOPICS)
    assert "odom" in SIDE_TOPICS
    assert "line/keep_debug" in SIDE_TOPICS
    assert COMPRESSED_CAMERA_TOPIC == "camera/front/compressed"


def test_snapshot_command_records_compressed_not_raw(tmp_path):
    cmd = snapshot_bag_command(tmp_path / ".cache", namespace="rosy_01", node_name="rec_x")
    assert cmd[:3] == ["ros2", "bag", "record"]
    assert "--snapshot-mode" in cmd
    assert cmd[cmd.index("--max-cache-size") + 1] == str(SNAPSHOT_CACHE_BYTES)
    assert cmd[cmd.index("--node-name") + 1] == "rec_x"
    assert cmd[cmd.index("-o") + 1] == str(tmp_path / ".cache")
    assert "/rosy_01/camera/front/compressed" in cmd
    assert "/rosy_01/camera/front" not in cmd
    for t in SIDE_TOPICS:
        assert f"/rosy_01/{t}" in cmd


def test_bag_command_camera_topic_override(tmp_path):
    cmd = bag_command(tmp_path / "s", camera_topic=COMPRESSED_CAMERA_TOPIC)
    assert COMPRESSED_CAMERA_TOPIC in cmd and "camera/front" not in cmd


def test_requests_are_fifo_and_json(tmp_path):
    a = write_snapshot_request(tmp_path, "error_delta", {"error_delta": [0.5]}, now=T0)
    b = write_snapshot_request(tmp_path, "operator", {"note": "x"}, now=T0)
    got = pending_snapshot_requests(tmp_path)
    assert [p for p, _ in got] == [a, b]
    assert got[0][1]["reason"] == "error_delta"
    assert got[0][1]["values"] == {"error_delta": [0.5]}
    assert got[0][1]["requested_at"] == "2026-09-30T12:00:00+00:00"
    assert not list(tmp_path.glob("**/*.tmp"))


def test_unreadable_request_is_skipped(tmp_path):
    write_snapshot_request(tmp_path, "operator", {}, now=T0)
    folder = tmp_path / ".snapshot-requests"
    (folder / "0000.json").write_text("{broken")
    assert [r["reason"] for _, r in pending_snapshot_requests(tmp_path)] == ["operator"]


def _cache(tmp_path, *names, size=100):
    cache = tmp_path / ".snapshot-cache-x"
    cache.mkdir(parents=True, exist_ok=True)
    for n in names:
        (cache / n).write_bytes(b"0" * size)
    return cache


def test_closed_files_exclude_the_open_newest(tmp_path):
    cache = _cache(tmp_path, "c_0.mcap", "c_10.mcap", "c_2.mcap")
    assert [p.name for p in closed_snapshot_files(cache)] == ["c_0.mcap", "c_2.mcap"]
    assert closed_snapshot_files(_cache(tmp_path / "one", "c_0.mcap")) == []
    assert closed_snapshot_files(tmp_path / "missing") == []


def test_adopt_makes_one_ended_unharvested_session(tmp_path):
    cache = _cache(tmp_path, "c_0.mcap", "c_1.mcap", size=1234)
    req = {"reason": "visibility_mismatch", "values": {"learned_visible": True},
           "requested_at": "2026-09-30T11:59:59+00:00"}
    folder = adopt_snapshot(tmp_path, cache / "c_0.mcap", req, now=T0, **META)
    assert (folder / "bag" / "c_0.mcap").stat().st_size == 1234
    assert not (cache / "c_0.mcap").exists()
    meta = _meta(folder)
    assert meta["reason"] == "snapshot:visibility_mismatch"
    assert meta["trigger"] == req
    assert meta["mode"] == "snapshot"
    assert meta["topics"][0] == COMPRESSED_CAMERA_TOPIC
    assert meta["ended_at"] is not None and meta["harvested"] is False
    assert meta["device"] == "pinky-1" and meta["model_revision"] == "m1"


def test_adopt_without_request_says_so(tmp_path):
    cache = _cache(tmp_path, "c_0.mcap", "c_1.mcap")
    folder = adopt_snapshot(tmp_path, cache / "c_0.mcap", None, now=T0, **META)
    assert _meta(folder)["reason"] == "snapshot:unrequested"
    assert _meta(folder)["trigger"] == {"reason": "unrequested", "values": {},
                                         "requested_at": None}


def test_quota_never_deletes_unharvested_snapshots_or_the_cache(tmp_path):
    cache = _cache(tmp_path, "c_0.mcap", "c_1.mcap", "c_2.mcap", size=1000)
    old = adopt_snapshot(tmp_path, cache / "c_0.mcap", None, now=T0, **META)
    new = adopt_snapshot(tmp_path, cache / "c_1.mcap", None, now=T0, **META)
    assert enforce_quota(tmp_path, 10) == []
    mark_harvested(old)
    assert enforce_quota(tmp_path, 10) == [old]
    assert new.exists() and (cache / "c_2.mcap").exists()


# ---- record_session --snapshot ----

class SnapProc:
    """Fake `ros2 bag record --snapshot-mode`: each wait() runs the next step."""

    def __init__(self, cmd, steps):
        self.cache = __import__("pathlib").Path(cmd[cmd.index("-o") + 1])
        self.steps = list(steps)
        self.signals = []
        self.killed = False

    def split(self, idx, size=500):
        self.cache.mkdir(parents=True, exist_ok=True)
        stem = self.cache.name
        (self.cache / f"{stem}_{idx}.mcap").write_bytes(b"0" * size)
        (self.cache / f"{stem}_{idx + 1}.mcap").write_bytes(b"")

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(self)
        return step


TIMEOUT = subprocess.TimeoutExpired("x", 1)


def _snap(monkeypatch, tmp_path, steps, extra=()):
    holder = {}

    def popen(cmd, *a, **k):
        holder["cmd"] = cmd
        holder["proc"] = SnapProc(cmd, steps)
        return holder["proc"]

    monkeypatch.setattr(rs.subprocess, "Popen", popen)
    code = rs.main(["--root", str(tmp_path), "--snapshot", "--device", "pinky-1", *extra])
    return code, holder


def _sessions(root):
    return sorted((p for p in root.iterdir() if (p / "session.json").is_file()),
                  key=lambda p: p.name)


def test_snapshot_mode_needs_no_reason_and_records_compressed(monkeypatch, tmp_path):
    code, h = _snap(monkeypatch, tmp_path, [0])
    assert code == 0
    assert "--snapshot-mode" in h["cmd"] and "camera/front/compressed" in h["cmd"]
    assert "--node-name" in h["cmd"]
    assert h["cmd"][h["cmd"].index("--node-name") + 1] == rs.DEFAULT_SNAPSHOT_NODE


def test_normal_mode_still_requires_reason(tmp_path):
    with pytest.raises(SystemExit):
        rs.main(["--root", str(tmp_path)])


def test_each_dump_becomes_its_own_session_with_the_trigger(monkeypatch, tmp_path):
    def first(p):
        write_snapshot_request(tmp_path, "error_delta", {"error_delta": [0.4, 0.5, 0.6]},
                               now=T0)
        p.split(0)
        raise TIMEOUT

    def second(p):
        write_snapshot_request(tmp_path, "operator", {"note": "tight turn"}, now=T0)
        p.split(1)
        raise TIMEOUT

    code, h = _snap(monkeypatch, tmp_path, [first, second, 0])
    assert code == 0
    sessions = _sessions(tmp_path)
    assert len(sessions) == 2
    metas = [_meta(s) for s in sessions]
    assert [m["trigger"]["reason"] for m in metas] == ["error_delta", "operator"]
    assert metas[0]["trigger"]["values"] == {"error_delta": [0.4, 0.5, 0.6]}
    assert all(len(list((s / "bag").glob("*.mcap"))) == 1 for s in sessions)
    assert pending_snapshot_requests(tmp_path) == []
    # the open (empty) tail file and the cache folder are gone after a clean stop
    assert not list(tmp_path.glob(".snapshot-cache-*"))


def test_dump_seen_only_at_exit_is_still_adopted(monkeypatch, tmp_path):
    def last(p):
        write_snapshot_request(tmp_path, "operator", {}, now=T0)
        p.split(0)
        return 0

    code, _ = _snap(monkeypatch, tmp_path, [last])
    assert code == 0
    assert [_meta(s)["trigger"]["reason"] for s in _sessions(tmp_path)] == ["operator"]


def test_request_left_at_exit_claims_the_tail_file(monkeypatch, tmp_path):
    def died(p):
        p.cache.mkdir(parents=True, exist_ok=True)
        (p.cache / f"{p.cache.name}_0.mcap").write_bytes(b"0" * 300)  # never closed
        write_snapshot_request(tmp_path, "error_delta", {}, now=T0)
        return 1

    code, _ = _snap(monkeypatch, tmp_path, [died])
    assert code == 1
    assert [_meta(s)["trigger"]["reason"] for s in _sessions(tmp_path)] == ["error_delta"]


def test_stale_cache_from_a_crash_is_recovered_not_deleted(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "mcap_message_count", lambda p: None)  # no mcap reader
    stale = tmp_path / ".snapshot-cache-old"
    stale.mkdir()
    (stale / "old_0.mcap").write_bytes(b"0" * 200)
    (stale / "old_1.mcap").write_bytes(b"")
    code, _ = _snap(monkeypatch, tmp_path, [0])
    assert code == 0
    metas = [_meta(s) for s in _sessions(tmp_path)]
    assert [m["trigger"]["reason"] for m in metas] == ["recovered"]
    assert not stale.exists()


def test_snapshot_quota_full_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "can_record", lambda *a: False)
    called = []
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *a, **k: called.append(1))
    assert rs.main(["--root", str(tmp_path), "--snapshot"]) == 2
    assert not called


def test_snapshot_quota_reached_while_running_stops_exit_3(monkeypatch, tmp_path):
    seq = iter([True, False])
    monkeypatch.setattr(rs, "can_record", lambda *a: next(seq))
    code, h = _snap(monkeypatch, tmp_path, [TIMEOUT, TIMEOUT, 0])
    assert code == 3 and h["proc"].signals == [rs.signal.SIGINT]


def test_snapshot_interrupt_is_graceful(monkeypatch, tmp_path):
    code, h = _snap(monkeypatch, tmp_path, [KeyboardInterrupt(), TIMEOUT, 0])
    assert code == 0 and h["proc"].signals == [rs.signal.SIGINT]


def test_snapshot_ros2_missing(monkeypatch, tmp_path):
    def popen(*a, **k):
        raise FileNotFoundError("ros2")
    monkeypatch.setattr(rs.subprocess, "Popen", popen)
    assert rs.main(["--root", str(tmp_path), "--snapshot"]) == 1


# ---- camera stream preference in session mode ----

def _session_cmd(monkeypatch, tmp_path, listed, extra=()):
    cmds = []

    class Done:
        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(rs, "_topic_listed", lambda name: listed)
    monkeypatch.setattr(rs.subprocess, "Popen", lambda cmd, *a, **k: cmds.append(cmd) or Done())
    assert rs.main(["--root", str(tmp_path), "--reason", "r", *extra]) == 0
    return cmds[0]


def test_session_prefers_compressed_when_published(monkeypatch, tmp_path):
    cmd = _session_cmd(monkeypatch, tmp_path, True)
    assert "camera/front/compressed" in cmd and "camera/front" not in cmd
    meta = _meta(_sessions(tmp_path)[0])
    assert meta["topics"][0] == "camera/front/compressed"


def test_session_falls_back_to_raw(monkeypatch, tmp_path):
    cmd = _session_cmd(monkeypatch, tmp_path, False)
    assert "camera/front" in cmd and "camera/front/compressed" not in cmd


def test_raw_camera_flag_forces_raw(monkeypatch, tmp_path):
    cmd = _session_cmd(monkeypatch, tmp_path, True, extra=("--raw-camera",))
    assert "camera/front" in cmd and "camera/front/compressed" not in cmd


def test_topic_listed_handles_missing_ros2(monkeypatch):
    def run(*a, **k):
        raise FileNotFoundError("ros2")
    monkeypatch.setattr(rs.subprocess, "run", run)
    assert rs._topic_listed("/camera/front/compressed") is False


def test_topic_listed_parses_topic_list(monkeypatch):
    out = "/camera/front\n/camera/front/compressed\n"
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout=out, stderr=""))
    assert rs._topic_listed("/camera/front/compressed") is True
    assert rs._topic_listed("/rosy_01/camera/front/compressed") is False


def test_topics_use_the_jazzy_topics_flag(tmp_path):
    """Positional topics are deprecated in Jazzy ros2 bag record."""
    for cmd in (bag_command(tmp_path / "s", namespace="rosy_01"),
                snapshot_bag_command(tmp_path / "c", namespace="rosy_01", node_name="n")):
        i = cmd.index("--topics")
        assert all(t.startswith("/rosy_01/") for t in cmd[i + 1:])
        assert len(cmd[i + 1:]) == 8  # camera, motion and lane evidence, ground status
        assert cmd[i + 1:].count('/rosy_01/camera/calibration/status') == 1



def test_requests_order_by_monotonic_sequence_not_wall_clock(tmp_path):
    """An NTP step backwards must not reorder the FIFO pairing."""
    later_wall = write_snapshot_request(tmp_path, "first", {}, now=T0, seq=100)
    earlier_wall = write_snapshot_request(
        tmp_path, "second", {}, now=T0.replace(hour=11), seq=200)
    assert [r["reason"] for _, r in pending_snapshot_requests(tmp_path)] == ["first", "second"]
    assert later_wall.name < earlier_wall.name


def test_request_default_sequence_is_monotonic(tmp_path):
    names = [write_snapshot_request(tmp_path, str(i), {}, now=T0).name for i in range(5)]
    assert names == sorted(names)
    assert [r["reason"] for _, r in pending_snapshot_requests(tmp_path)] == list("01234")


def test_snapshot_node_name_is_per_namespace():
    from control.recording import snapshot_node_name
    assert snapshot_node_name("") == "rosy_snapshot_recorder"
    assert snapshot_node_name("/") == "rosy_snapshot_recorder"
    assert snapshot_node_name("/rosy_01") == "rosy_01_snapshot_recorder"
    assert snapshot_node_name("fleet/rosy_02/") == "fleet_rosy_02_snapshot_recorder"


def test_snapshot_cli_node_name_follows_the_namespace(monkeypatch, tmp_path):
    code, h = _snap(monkeypatch, tmp_path, [0], extra=("--namespace", "rosy_01"))
    assert h["cmd"][h["cmd"].index("--node-name") + 1] == "rosy_01_snapshot_recorder"


def test_mcap_message_count_reads_real_files(tmp_path):
    pytest.importorskip("mcap")
    from mcap.writer import Writer
    from control.recording import mcap_message_count

    def write(path, n):
        with open(path, "wb") as fh:
            w = Writer(fh)
            w.start()
            sid = w.register_schema(name="s", encoding="jsonschema", data=b"{}")
            cid = w.register_channel(topic="/t", message_encoding="json", schema_id=sid)
            for i in range(n):
                w.add_message(channel_id=cid, log_time=i, publish_time=i, data=b"{}")
            w.finish()

    write(tmp_path / "a.mcap", 3)
    write(tmp_path / "b.mcap", 0)
    (tmp_path / "c.mcap").write_bytes(b"not an mcap at all")
    assert mcap_message_count(tmp_path / "a.mcap") == 3
    assert mcap_message_count(tmp_path / "b.mcap") == 0
    assert mcap_message_count(tmp_path / "c.mcap") is None


def _stale(tmp_path):
    stale = tmp_path / ".snapshot-cache-old"
    stale.mkdir()
    (stale / "old_0.mcap").write_bytes(b"0" * 200)  # a dump
    (stale / "old_1.mcap").write_bytes(b"1" * 150)  # the empty tail rosbag2 had open
    (stale / "old_2.mcap").write_bytes(b"2" * 120)  # unreadable: count unknown
    return stale


def test_recover_adopts_files_with_messages_and_deletes_our_empty_tail(monkeypatch, tmp_path):
    counts = {"old_0.mcap": 5, "old_1.mcap": 0, "old_2.mcap": None}
    monkeypatch.setattr(rs, "mcap_message_count", lambda p: counts[p.name])
    stale = _stale(tmp_path)
    code, _ = _snap(monkeypatch, tmp_path, [0])
    assert code == 0
    bags = sorted(f.name for s in _sessions(tmp_path) for f in (s / "bag").iterdir())
    # unknown count is kept (never guess data away); zero messages is our own tail
    assert bags == ["old_0.mcap", "old_2.mcap"]
    assert {_meta(s)["trigger"]["reason"] for s in _sessions(tmp_path)} == {"recovered"}
    assert not stale.exists()


def test_recover_never_consumes_a_request_and_drops_stale_ones(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "mcap_message_count", lambda p: 1)
    stale = tmp_path / ".snapshot-cache-old"
    stale.mkdir()
    (stale / "old_0.mcap").write_bytes(b"0" * 200)
    write_snapshot_request(tmp_path, "error_delta", {}, now=T0)  # left by the crashed run
    code, _ = _snap(monkeypatch, tmp_path, [0])
    assert code == 0
    assert [_meta(s)["trigger"]["reason"] for s in _sessions(tmp_path)] == ["recovered"]
    assert pending_snapshot_requests(tmp_path) == []
