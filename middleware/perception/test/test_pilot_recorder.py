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

    def start_recording(self, size=2048):
        """Start, then let the writer open its first file: the session is `recording`."""
        ok, rid = self.rec.start()
        assert ok, rid
        self.write_bag(self.rec._root / rid, size)
        assert self.rec.tick() is None and self.rec.status()["state"] == "recording"
        return rid

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
                      "/rosy_01/scan", "/rosy_01/line/observation", "/rosy_01/teleop/intent",
                      "/rosy_01/line/keep_debug"]


def test_annotated_recording_preserves_raw_and_separates_model_evidence(tmp_path):
    rig = Rig(tmp_path)
    ok, rid = rig.rec.start(preview_mode='annotated')
    assert ok
    topics = rig.cmds[-1][rig.cmds[-1].index('--topics') + 1:]
    assert '/rosy_01/camera/front/compressed' in topics
    assert '/rosy_01/camera/preview/compressed' in topics
    assert '/rosy_01/line/keep_debug' in topics
    assert rig.rec.status()['preview_mode'] == 'annotated'
    meta = _meta(tmp_path / rid)
    assert meta['preview_mode'] == 'annotated'
    assert meta['annotation_origin'] == 'model_unreviewed'
    rig.write_bag(tmp_path / rid)
    rig.rec.tick()
    rig.rec.stop('requested')
    rig.finish()
    assert _manifest(tmp_path / rid).preview_mode == 'annotated'


@pytest.mark.parametrize('preview_mode', ['raw', 'annotated'])
def test_lane_diagnostics_survive_recording_without_annotated_preview(tmp_path, preview_mode):
    rig = Rig(tmp_path)
    ok, rid = rig.rec.start(preview_mode=preview_mode)
    assert ok
    topics = rig.cmds[-1][rig.cmds[-1].index('--topics') + 1:]
    assert topics.count('/rosy_01/line/keep_debug') == 1
    assert 'line/keep_debug' in _meta(tmp_path / rid)['topics']
    if preview_mode == 'raw':
        assert '/rosy_01/camera/preview/compressed' not in topics
        assert _meta(tmp_path / rid)['annotation_origin'] == 'none'


def test_raw_default_and_unknown_recording_options_cannot_add_annotations(tmp_path):
    rig = Rig(tmp_path)
    assert rig.rec.start(preview_mode='human_ground_truth') == (False, 'RECORDING_INVALID_OPTIONS')
    assert not rig.cmds and not list(tmp_path.iterdir())
    ok, rid = rig.rec.start()
    assert ok and rig.rec.status()['preview_mode'] == 'raw'
    assert _meta(tmp_path / rid)['annotation_origin'] == 'none'
    assert '/rosy_01/camera/preview/compressed' not in rig.cmds[-1]


def test_start_stop_finish_writes_a_verifiable_manifest(tmp_path):
    rig = Rig(tmp_path)
    ok, rid = rig.rec.start()
    assert ok and rig.rec.status()["state"] == "starting" and rig.rec.status()["id"] == rid
    folder = tmp_path / rid
    assert (folder / pr.WRITER_PID_NAME).read_text("utf-8").strip() == "4242"
    assert rig.rec.start() == (False, "RECORDING_BUSY")
    rig.write_bag(folder)
    rig.rec.tick()
    assert rig.rec.status()["state"] == "recording"
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
    rig.start_recording()
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
    rid = rig.start_recording()
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


def test_manifest_refuses_a_session_that_has_not_ended(tmp_path):
    folder = new_session(tmp_path, device="rosy_01", camera_profile_revision="", model_revision="",
                         task_id=None, reason="pilot",
                         now=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                         topics=pr.PILOT_TOPICS, extra={"mode": "pilot"})
    with pytest.raises(ValueError):
        pr.write_manifest(folder)
    assert not (folder / MANIFEST_NAME).exists()


def test_live_writer_check_matches_the_exact_bag_argument(tmp_path):
    folder = tmp_path / "20261002T101500Z_rosy_01"
    proc = tmp_path / "proc"
    for pid, argv in ((10, ["ros2", "bag", "record", "-o", str(folder / "bag")]),
                      (11, ["ros2", "bag", "record", "-o", str(folder) + "_2/bag"]),
                      (12, ["ros2", "bag", "record", "-o", str(folder / "bag") + "x"])):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    assert pr._writer_alive(10, folder, proc_root=proc) is True
    assert pr._writer_alive(11, folder, proc_root=proc) is False
    assert pr._writer_alive(12, folder, proc_root=proc) is False
    assert pr._writer_alive(13, folder, proc_root=proc) is False


def test_a_started_writer_is_starting_until_its_first_mcap_file_exists(tmp_path):
    # rosbag2 needs seconds (CLI start, discovery) before it writes: "recording" must mean data.
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    folder = tmp_path / rid
    status = RecorderStatus.model_validate(rig.rec.status())
    assert status.state == "starting" and status.id == rid and status.elapsed_s == 0.0
    (folder / "bag").mkdir()
    (folder / "bag" / "metadata.yaml").write_text("x", "utf-8")   # not the writer's data file
    rig.t += 3
    assert rig.rec.poll_start() is False and rig.rec.status()["state"] == "starting"
    rig.write_bag(folder, size=0)          # rosbag2 opened its first file: subscriptions follow
    rig.wall += timedelta(seconds=4)
    rig.t += 1
    assert rig.rec.poll_start() is True and rig.rec.poll_start() is False
    status = rig.rec.status()
    assert status["state"] == "recording" and status["elapsed_s"] == 0.0
    meta = _meta(folder)
    assert meta["started_at"] == "2026-10-02T10:15:04+00:00"
    assert meta["requested_at"] == "2026-10-02T10:15:00+00:00"
    rig.t += 5
    assert rig.rec.status()["elapsed_s"] == pytest.approx(5.0)


def test_duration_counts_from_when_the_writer_really_records(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.t += 4
    rig.write_bag(tmp_path / rid)
    rig.rec.tick()
    rig.t += 30
    rig.rec.stop("requested")
    assert rig.finish(0) == "requested"
    assert _manifest(tmp_path / rid).duration_s == pytest.approx(30.0)


def test_a_writer_that_never_opens_its_file_is_stopped_as_a_start_timeout(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.t += pr.START_TIMEOUT_S - 0.1
    assert rig.rec.tick() is None and rig.procs[0].signals == []
    rig.t += 0.2
    assert rig.rec.tick() is None
    assert rig.procs[0].signals == [signal.SIGINT] and rig.rec.status()["state"] == "stopping"
    assert any("writer_start_timeout" in line for line in rig.logs)
    assert rig.finish(0) == "writer_start_timeout"
    assert rig.rec.status()["last_stop_reason"] == "writer_start_timeout"
    manifest = _manifest(tmp_path / rid)
    assert manifest.stop_reason == "writer_start_timeout" and manifest.duration_s == 0.0


def test_stop_while_starting_is_a_clean_stop(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    assert rig.rec.stop("requested") == (True, rid)
    assert rig.rec.status()["state"] == "stopping"
    rig.write_bag(tmp_path / rid)          # a late file never turns a stopping session back
    assert rig.rec.poll_start() is False
    assert rig.finish(0) == "requested"
    assert rig.rec.status()["state"] == "idle" and rig.rec.status()["last_stop_reason"] == "requested"
    assert _manifest(tmp_path / rid).duration_s == 0.0


def test_session_json_says_whether_the_writer_ever_recorded(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    assert _meta(tmp_path / rid)["writer_ready"] is False
    rig.write_bag(tmp_path / rid)
    rig.rec.poll_start()
    assert _meta(tmp_path / rid)["writer_ready"] is True


def test_shutdown_during_starting_records_no_duration(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.wall += timedelta(seconds=9)
    rig.procs[0].code = 0
    rig.rec.shutdown()
    assert Rig(tmp_path).rec.recover() == [rid]
    manifest = _manifest(tmp_path / rid)
    assert manifest.stop_reason == "shutdown" and manifest.duration_s == 0.0


def test_recover_of_a_crash_during_starting_records_no_duration(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    again = Rig(tmp_path)          # the node died while rosbag2 was still starting
    again.wall += timedelta(hours=3)
    assert again.rec.recover() == [rid]
    manifest = _manifest(tmp_path / rid)
    assert manifest.stop_reason == "recovered" and manifest.duration_s == 0.0


def test_a_session_from_before_writer_ready_keeps_its_duration():
    # session.json written before this field existed: counted from started_at as before.
    meta = {"started_at": "2026-10-02T10:00:00+00:00", "ended_at": "2026-10-02T10:01:00+00:00"}
    assert pr._duration(meta) == pytest.approx(60.0)
    assert pr._duration({**meta, "writer_ready": False}) == 0.0


def test_recording_device_falls_through_names_that_sanitise_to_nothing():
    assert pr.recording_device("___", "/rosy_03", "PERPROS") == "rosy_03"
    assert pr.recording_device("", "/!!", "PERPROS") == "PERPROS"
    assert pr.recording_device("", "/rosy", "PERPROS") == "rosy"
    assert pr.recording_device("***", "", "@@@") == "rosy"


def test_the_recording_device_is_the_robot_identity(tmp_path):
    assert pr.recording_device("", "/rosy_03", "PERPROS") == "rosy_03"
    assert pr.recording_device("rosy_01", "", "PERPROS") == "rosy_01"
    assert pr.recording_device("rosy_01", "/rosy_03", "PERPROS") == "rosy_01"
    assert pr.recording_device("", "", "PERPROS") == "PERPROS"
    assert pr.recording_device("  ", "/", "") == "rosy"
    long = pr.recording_device("", "", "h" * 80 + "__")
    rig = Rig(tmp_path)
    rig.rec = pr.PilotRecorder(tmp_path, device=long, popen=lambda cmd, **_: Proc(),
                               clock=lambda: rig.t, now=lambda: rig.wall, executor=SyncExecutor(),
                               disk_free=lambda root: 100 * GIB, killpg=None)
    ok, rid = rig.rec.start()
    assert ok and recording_id_ok(rid) and not rid.endswith("_")


def test_status_is_idle_with_quota_when_nothing_runs(tmp_path):
    status = RecorderStatus.model_validate(Rig(tmp_path).rec.status())
    assert status.state == "idle" and status.max_duration_s == 600 and status.quota_free_bytes > 0


def test_every_status_is_sequenced_within_one_boot(tmp_path):
    # CORE drops a status older than the one it already adopted (a late idle after a start).
    rec = Rig(tmp_path).rec
    first, second = rec.status(), rec.status()
    assert first["boot_id"] and first["boot_id"] == second["boot_id"]
    assert 0 < first["seq"] < second["seq"]
    assert Rig(tmp_path / "other").rec.status()["boot_id"] != first["boot_id"]
