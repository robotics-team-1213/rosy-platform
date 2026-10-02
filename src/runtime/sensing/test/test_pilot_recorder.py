"""D-411 A: the Pilot recording state machine (ROS-free)."""

import json
import signal
from datetime import datetime, timedelta, timezone

import pytest

from control import pilot_recording as pr
from core_common.protocol.recording import MANIFEST_NAME, RecorderStatus, RecordingManifest


class Proc:
    def __init__(self):
        self.signals, self.killed, self.code = [], False, None

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True
        self.code = -9

    def poll(self):
        return self.code


class Rig:
    def __init__(self, tmp_path, **kwargs):
        self.t = 100.0
        self.wall = datetime(2026, 10, 2, 10, 15, tzinfo=timezone.utc)
        self.procs, self.cmds = [], []

        def popen(cmd, **_):
            self.cmds.append(cmd)
            proc = Proc()
            self.procs.append(proc)
            return proc

        self.rec = pr.PilotRecorder(tmp_path, device="rosy_01", namespace="rosy_01", popen=popen,
                                    clock=lambda: self.t, now=lambda: self.wall, **kwargs)

    def write_bag(self, folder, size=2048):
        bag = folder / "bag"
        bag.mkdir(exist_ok=True)
        (bag / "bag_0.mcap").write_bytes(b"x" * size)


def test_bag_command_records_the_d411_topics_namespaced():
    cmd = pr.pilot_bag_command("/r/s", "rosy_01")
    assert cmd[:3] == ["ros2", "bag", "record"]
    topics = cmd[cmd.index("--topics") + 1:]
    assert topics == ["/rosy_01/camera/front/compressed", "/rosy_01/cmd_vel", "/rosy_01/odom",
                      "/rosy_01/scan", "/rosy_01/line/observation", "/rosy_01/teleop/intent"]
    assert "camera/front" not in [t.rsplit("/rosy_01/", 1)[-1] for t in topics]


def test_start_stop_finish_writes_a_verifiable_manifest(tmp_path):
    rig = Rig(tmp_path)
    ok, rid = rig.rec.start()
    assert ok and rig.rec.status()["state"] == "recording" and rig.rec.status()["id"] == rid
    assert rig.rec.start() == (False, "RECORDING_BUSY")
    folder = tmp_path / rid
    rig.write_bag(folder)
    rig.t += 30
    assert rig.rec.stop("requested") == (True, rid)
    assert rig.procs[0].signals == [signal.SIGINT]
    assert rig.rec.status()["state"] == "stopping"
    rig.procs[0].code = 0
    assert rig.rec.tick() == "requested"
    status = RecorderStatus.model_validate(rig.rec.status())
    assert status.state == "idle" and status.last_stop_reason == "requested"
    manifest = RecordingManifest.model_validate_json((folder / MANIFEST_NAME).read_text("utf-8"))
    assert {f.path for f in manifest.files} == {"bag/bag_0.mcap", "session.json"}
    assert manifest.duration_s == pytest.approx(30.0)
    assert json.loads((folder / "session.json").read_text("utf-8"))["ended_at"] is not None


def test_max_duration_stops_by_itself(tmp_path):
    rig = Rig(tmp_path)
    rig.rec.start()
    rig.t += 600
    assert rig.rec.tick() is None
    assert rig.procs[0].signals == [signal.SIGINT]
    rig.procs[0].code = 0
    assert rig.rec.tick() == "max_duration"


def test_recorder_exit_is_finished_as_incomplete_reason(tmp_path):
    rig = Rig(tmp_path)
    rig.rec.start()
    rig.procs[0].code = 1
    assert rig.rec.tick() == "recorder_exit"
    assert rig.rec.status()["state"] == "idle"


def test_stuck_recorder_is_killed_after_the_stop_timeout(tmp_path):
    rig = Rig(tmp_path)
    rig.rec.start()
    rig.rec.stop("requested")
    rig.t += pr.STOP_TIMEOUT_S + 0.1
    rig.rec.tick()
    assert rig.procs[0].killed


def test_quota_evicts_only_fetched_finished_sessions(tmp_path):
    rig = Rig(tmp_path, quota_bytes=3000)
    _, first = rig.rec.start()
    rig.write_bag(tmp_path / first, 2500)
    rig.rec.stop("requested"); rig.procs[0].code = 0; rig.rec.tick()
    rig.wall += timedelta(minutes=1)
    assert rig.rec.start() == (False, "RECORDING_QUOTA_FULL")
    assert rig.rec.mark_fetched(first) is True
    ok, second = rig.rec.start()
    assert ok and not (tmp_path / first).exists() and second != first


def test_mark_fetched_refuses_unknown_or_unsafe_ids(tmp_path):
    rig = Rig(tmp_path)
    assert rig.rec.mark_fetched("../etc") is False
    assert rig.rec.mark_fetched("20261002T101500Z_nothere") is False


def test_recover_finishes_an_interrupted_session(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.write_bag(tmp_path / rid)
    again = Rig(tmp_path)          # a restart: the old process is gone
    again.rec.recover()
    manifest = RecordingManifest.model_validate_json((tmp_path / rid / MANIFEST_NAME).read_text("utf-8"))
    assert manifest.stop_reason == "recovered"


def test_status_is_idle_with_quota_when_nothing_runs(tmp_path):
    status = RecorderStatus.model_validate(Rig(tmp_path).rec.status())
    assert status.state == "idle" and status.max_duration_s == 600 and status.quota_free_bytes > 0


def test_shutdown_stops_and_finishes_the_running_session(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.procs[0].code = 0          # rosbag2 exits on the SIGINT
    rig.rec.shutdown()
    assert rig.procs[0].signals == [signal.SIGINT]
    manifest = RecordingManifest.model_validate_json((tmp_path / rid / MANIFEST_NAME).read_text("utf-8"))
    assert manifest.stop_reason == "shutdown" and rig.rec.status()["state"] == "idle"
