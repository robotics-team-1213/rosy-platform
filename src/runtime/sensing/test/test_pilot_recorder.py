"""D-411 A: the Pilot recording state machine (ROS-free)."""

import json
import signal
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone

import pytest

from control import pilot_recording as pr
from control.recording import finish_session, new_session
from core_common.protocol.recording import (
    MANIFEST_NAME, RecorderStatus, RecordingManifest, recording_id_ok)

GIB = 1024 ** 3


class Proc:
    def __init__(self, pid=4242):
        self.pid = pid
        self.signals, self.killed, self.code = [], False, None

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True
        self.code = -9

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code


class SyncExecutor:
    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 - mirrors a worker thread
            future.set_exception(exc)
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class ManualExecutor:
    """Holds the hashing job until the test runs it: the worker is still busy."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args, **kwargs):
        future = Future()
        self.jobs.append((future, fn, args, kwargs))
        return future

    def run(self):
        for future, fn, args, kwargs in self.jobs:
            future.set_result(fn(*args, **kwargs))
        self.jobs.clear()

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class Rig:
    def __init__(self, tmp_path, **kwargs):
        self.t = 100.0
        self.wall = datetime(2026, 10, 2, 10, 15, tzinfo=timezone.utc)
        self.procs, self.cmds, self.sleeps, self.killpgs, self.logs = [], [], [], [], []
        self.free = 100 * GIB

        def popen(cmd, **_):
            self.cmds.append(cmd)
            proc = Proc()
            self.procs.append(proc)
            return proc

        def killpg(pid, sig):
            self.killpgs.append((pid, sig))
            self.procs[-1].kill()

        kwargs.setdefault("popen", popen)
        kwargs.setdefault("executor", SyncExecutor())
        kwargs.setdefault("disk_free", lambda root: self.free)
        kwargs.setdefault("sleep", self.sleeps.append)
        kwargs.setdefault("killpg", killpg)
        kwargs.setdefault("writer_alive", lambda pid, folder: False)
        self.rec = pr.PilotRecorder(tmp_path, device="rosy_01", namespace="rosy_01",
                                    clock=lambda: self.t, now=lambda: self.wall,
                                    log=self.logs.append, **kwargs)

    def write_bag(self, folder, size=2048):
        bag = folder / "bag"
        bag.mkdir(exist_ok=True)
        (bag / "bag_0.mcap").write_bytes(b"x" * size)

    def finish(self, code=0):
        self.procs[-1].code = code
        return self.rec.tick()


def _manifest(folder):
    return RecordingManifest.model_validate_json((folder / MANIFEST_NAME).read_text("utf-8"))


def _meta(folder):
    return json.loads((folder / "session.json").read_text("utf-8"))


def test_bag_command_records_the_d411_topics_namespaced_and_dies_with_its_parent():
    cmd = pr.pilot_bag_command("/r/s", "rosy_01")
    assert cmd[:4] == ["setpriv", "--pdeathsig", "INT", "--"]
    assert cmd[4:7] == ["ros2", "bag", "record"]
    topics = cmd[cmd.index("--topics") + 1:]
    assert topics == ["/rosy_01/camera/front/compressed", "/rosy_01/cmd_vel", "/rosy_01/odom",
                      "/rosy_01/scan", "/rosy_01/line/observation", "/rosy_01/teleop/intent"]


def test_start_stop_finish_writes_a_verifiable_manifest(tmp_path):
    rig = Rig(tmp_path)
    ok, rid = rig.rec.start()
    assert ok and rig.rec.status()["state"] == "recording" and rig.rec.status()["id"] == rid
    folder = tmp_path / rid
    assert (folder / pr.WRITER_PID_NAME).read_text("utf-8").strip() == "4242"
    assert rig.rec.start() == (False, "RECORDING_BUSY")
    rig.write_bag(folder)
    rig.t += 30
    assert rig.rec.stop("requested") == (True, rid)
    assert rig.procs[0].signals == [signal.SIGINT]
    assert rig.rec.status()["state"] == "stopping"
    assert rig.finish(0) == "requested"
    status = RecorderStatus.model_validate(rig.rec.status())
    assert status.state == "idle" and status.last_stop_reason == "requested"
    manifest = _manifest(folder)
    assert {f.path for f in manifest.files} == {"bag/bag_0.mcap", "session.json"}
    assert manifest.duration_s == pytest.approx(30.0)
    assert manifest.stop_reason == "requested"
    assert manifest.bag_returncode == 0 and manifest.writer_killed is False
    assert _meta(folder)["ended_at"] is not None
    assert not (folder / pr.WRITER_PID_NAME).exists()


def test_hashing_runs_off_the_timer_and_the_recorder_stays_busy_meanwhile(tmp_path):
    worker = ManualExecutor()
    rig = Rig(tmp_path, executor=worker)
    _, rid = rig.rec.start()
    rig.rec.stop("requested")
    assert rig.finish(0) is None
    assert rig.rec.status()["state"] == "stopping" and rig.rec.status()["id"] == rid
    assert rig.rec.start() == (False, "RECORDING_BUSY")
    assert not (tmp_path / rid / MANIFEST_NAME).exists()
    worker.run()
    assert rig.rec.tick() == "requested"
    assert rig.rec.status()["state"] == "idle" and (tmp_path / rid / MANIFEST_NAME).is_file()


def test_max_duration_stops_by_itself(tmp_path):
    rig = Rig(tmp_path)
    rig.rec.start()
    rig.t += 600
    assert rig.rec.tick() is None
    assert rig.procs[0].signals == [signal.SIGINT]
    assert rig.finish(0) == "max_duration"


def test_recorder_exit_is_finished_with_its_returncode(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    assert rig.finish(1) == "recorder_exit"
    assert rig.rec.status()["state"] == "idle"
    assert _manifest(tmp_path / rid).bag_returncode == 1


def test_stuck_recorder_is_killed_by_process_group_after_the_stop_timeout(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.rec.stop("requested")
    rig.t += pr.STOP_TIMEOUT_S + 0.1
    rig.rec.tick()
    assert rig.killpgs == [(4242, pr.SIGKILL)] and rig.procs[0].killed
    assert rig.rec.tick() == "requested"
    manifest = _manifest(tmp_path / rid)
    assert manifest.writer_killed is True and manifest.bag_returncode == -9


def test_quota_evicts_only_fetched_finished_sessions(tmp_path):
    rig = Rig(tmp_path, quota_bytes=3000, reserve_bytes=0)
    _, first = rig.rec.start()
    rig.write_bag(tmp_path / first, 2500)
    rig.rec.stop("requested"); rig.finish(0)
    rig.wall += timedelta(minutes=1)
    assert rig.rec.start() == (False, "RECORDING_QUOTA_FULL")
    assert rig.rec.mark_fetched(first) is True
    ok, second = rig.rec.start()
    assert ok and not (tmp_path / first).exists() and second != first


def test_reserve_keeps_headroom_for_the_next_recording(tmp_path):
    rig = Rig(tmp_path, quota_bytes=10_000, reserve_bytes=8_000)
    _, first = rig.rec.start()
    rig.write_bag(tmp_path / first, 2500)
    rig.rec.stop("requested"); rig.finish(0)
    rig.wall += timedelta(minutes=1)
    assert rig.rec.start() == (False, "RECORDING_QUOTA_FULL")


def test_reserve_must_leave_room_inside_the_quota(tmp_path):
    with pytest.raises(ValueError):
        Rig(tmp_path, quota_bytes=1000, reserve_bytes=1000)


def test_quota_tick_evicts_fetched_sessions_before_it_stops(tmp_path):
    rig = Rig(tmp_path, quota_bytes=8000, reserve_bytes=0)
    _, first = rig.rec.start()
    rig.write_bag(tmp_path / first, 3000)
    rig.rec.stop("requested"); rig.finish(0)
    rig.rec.mark_fetched(first)
    rig.wall += timedelta(minutes=1)
    _, second = rig.rec.start()
    rig.write_bag(tmp_path / second, 4000)      # first + second >= quota
    assert rig.rec.tick() is None
    assert not (tmp_path / first).exists() and rig.procs[1].signals == []
    rig.write_bag(tmp_path / second, 9000)      # second alone is over quota
    assert rig.rec.tick() is None
    assert rig.procs[1].signals == [signal.SIGINT]
    assert rig.finish(0) == "quota"


def test_disk_full_refuses_start_and_stops_a_running_session(tmp_path):
    rig = Rig(tmp_path)
    rig.free = pr.DEFAULT_MIN_FREE_BYTES
    assert rig.rec.start() == (False, "RECORDING_DISK_FULL")
    rig.free = 10 * GIB
    _, rid = rig.rec.start()
    rig.free = pr.DEFAULT_MIN_FREE_BYTES - 1
    assert rig.rec.tick() is None
    assert rig.procs[0].signals == [signal.SIGINT]
    assert rig.finish(0) == "disk_full"
    assert _manifest(tmp_path / rid).stop_reason == "disk_full"


def test_popen_failure_leaves_no_session_behind(tmp_path):
    def broken(cmd, **_):
        raise OSError("no ros2")

    rig = Rig(tmp_path, popen=broken)
    assert rig.rec.start() == (False, "RECORDER_UNAVAILABLE")
    assert list(tmp_path.iterdir()) == []
    assert rig.rec.status()["state"] == "idle" and rig.logs


def test_unwritable_or_missing_root_is_unavailable_and_never_created(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    rig = Rig(missing)
    assert rig.rec.start() == (False, "RECORDER_UNAVAILABLE")
    assert not missing.exists()
    assert rig.rec.recover() == []
    monkeypatch.setattr(pr.os, "access", lambda path, mode: False)
    assert Rig(tmp_path).rec.start() == (False, "RECORDER_UNAVAILABLE")


def test_mark_fetched_refuses_unknown_or_unsafe_ids(tmp_path):
    rig = Rig(tmp_path)
    assert rig.rec.mark_fetched("../etc") is False
    assert rig.rec.mark_fetched("20261002T101500Z_nothere") is False


def test_recover_finishes_an_interrupted_session_with_its_real_duration(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.write_bag(tmp_path / rid)
    again = Rig(tmp_path)          # a restart: the old process is gone
    again.wall += timedelta(seconds=45)
    assert again.rec.recover() == [rid]
    manifest = _manifest(tmp_path / rid)
    assert manifest.stop_reason == "recovered" and manifest.duration_s == pytest.approx(45.0)
    assert not (tmp_path / rid / pr.WRITER_PID_NAME).exists()


def test_recover_writes_the_missing_manifest_of_a_finished_session(tmp_path):
    folder = new_session(tmp_path, device="rosy_01", camera_profile_revision="", model_revision="",
                         task_id=None, reason="pilot",
                         now=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                         topics=pr.PILOT_TOPICS, extra={"mode": "pilot"})
    finish_session(folder, datetime(2026, 10, 2, 10, 2, tzinfo=timezone.utc))
    rig = Rig(tmp_path)
    assert rig.rec.recover() == [folder.name]
    assert _manifest(folder).duration_s == pytest.approx(120.0)
    assert rig.rec.recover() == []


def test_recover_stops_a_writer_that_outlived_its_node(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    sent = []
    again = Rig(tmp_path, writer_alive=lambda pid, folder: pid == 4242 and folder.name == rid,
                signal_pid=lambda pid, sig: sent.append((pid, sig)))
    again.rec.recover()
    assert sent == [(4242, signal.SIGINT), (4242, pr.SIGKILL)]
    assert again.sleeps and sum(again.sleeps) == pytest.approx(pr.STOP_TIMEOUT_S)
    assert _manifest(tmp_path / rid).writer_killed is True


def test_shutdown_only_ends_the_session_and_recover_hashes_it_later(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.procs[0].code = 0          # rosbag2 exits on the SIGINT
    rig.rec.shutdown()
    assert rig.procs[0].signals == [signal.SIGINT]
    assert _meta(tmp_path / rid)["ended_at"] is not None
    assert not (tmp_path / rid / MANIFEST_NAME).exists()
    assert rig.rec.status()["state"] == "idle"
    assert Rig(tmp_path).rec.recover() == [rid]
    assert _manifest(tmp_path / rid).stop_reason == "shutdown"


def test_shutdown_kills_a_stuck_writer_inside_the_launch_sigterm_window(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.rec.shutdown()
    assert pr.SHUTDOWN_WAIT_S < 4.0
    assert sum(rig.sleeps) == pytest.approx(pr.SHUTDOWN_WAIT_S)
    assert rig.procs[0].killed
    assert _meta(tmp_path / rid)["writer_killed"] is True


def test_long_device_names_still_make_a_valid_recording_id(tmp_path):
    rig = Rig(tmp_path)
    rig.rec = pr.PilotRecorder(tmp_path, device="a" * 100 + "__", popen=lambda cmd, **_: Proc(),
                               clock=lambda: rig.t, now=lambda: rig.wall, executor=SyncExecutor(),
                               disk_free=lambda root: 100 * GIB, killpg=None)
    ok, rid = rig.rec.start()
    assert ok and recording_id_ok(rid)


def test_status_is_idle_with_quota_when_nothing_runs(tmp_path):
    status = RecorderStatus.model_validate(Rig(tmp_path).rec.status())
    assert status.state == "idle" and status.max_duration_s == 600 and status.quota_free_bytes > 0
