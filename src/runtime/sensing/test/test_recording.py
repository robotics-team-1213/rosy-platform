"""Recording sessions: session.json, harvest-aware quota, bag command line."""

import json
from datetime import datetime, timezone, timedelta

import pytest

from control.recording import (
    RECORD_TOPICS,
    bag_command,
    can_record,
    enforce_quota,
    finish_session,
    mark_harvested,
    new_session,
)

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


def _mk(root, minutes, device="pinky-1", size=0):
    folder = new_session(
        root, device=device, camera_profile_revision="cam1",
        model_revision="m1", task_id="t1", reason="test",
        now=T0 + timedelta(minutes=minutes))
    if size:
        (folder / "bag").mkdir(exist_ok=True)
        (folder / "bag" / "x.mcap").write_bytes(b"0" * size)
    return folder


def _meta(folder):
    return json.loads((folder / "session.json").read_text())


def test_new_session_fields(tmp_path):
    folder = _mk(tmp_path, 0, device="pinky 1/x")
    assert folder.name == "20260930T120000Z_pinky_1_x"
    meta = _meta(folder)
    assert meta["schema"] == "rosy.recording.session/1"
    assert meta["device"] == "pinky_1_x"
    assert meta["camera_profile_revision"] == "cam1"
    assert meta["model_revision"] == "m1"
    assert meta["task_id"] == "t1"
    assert meta["reason"] == "test"
    assert meta["started_at"] == "2026-09-30T12:00:00+00:00"
    assert meta["ended_at"] is None
    assert meta["harvested"] is False
    assert meta["topics"] == list(RECORD_TOPICS)


@pytest.mark.parametrize("kw", [{"reason": ""}, {"device": ""}])
def test_empty_reason_or_device_rejected(tmp_path, kw):
    args = dict(device="d", camera_profile_revision="c", model_revision="m",
                task_id="t", reason="r", now=T0)
    args.update(kw)
    with pytest.raises(ValueError):
        new_session(tmp_path, **args)


def test_finish_and_harvest(tmp_path):
    folder = _mk(tmp_path, 0)
    finish_session(folder, T0 + timedelta(minutes=1))
    assert _meta(folder)["ended_at"] == "2026-09-30T12:01:00+00:00"
    mark_harvested(folder)
    assert _meta(folder)["harvested"] is True


def test_quota_deletes_oldest_harvested_ended_only(tmp_path):
    a = _mk(tmp_path, 0, size=100)
    b = _mk(tmp_path, 1, size=100)
    c = _mk(tmp_path, 2, size=100)
    d = _mk(tmp_path, 3, size=100)
    for f in (a, b, c):
        finish_session(f, T0 + timedelta(minutes=10))
    mark_harvested(a)
    mark_harvested(c)
    mark_harvested(d)  # harvested but not ended -> protected
    total = sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file())
    deleted = enforce_quota(tmp_path, total - 50)
    assert deleted == [a]
    assert not a.exists() and b.exists() and c.exists() and d.exists()
    deleted = enforce_quota(tmp_path, 1)
    assert deleted == [c]
    assert b.exists() and d.exists()


def test_can_record_false_when_only_unharvested_over_quota(tmp_path):
    f = _mk(tmp_path, 0, size=1000)
    finish_session(f, T0)
    assert can_record(tmp_path, 500) is False
    assert can_record(tmp_path, 10_000) is True
    mark_harvested(f)
    assert can_record(tmp_path, 500) is True
    assert not f.exists()


def test_bag_command(tmp_path):
    cmd = bag_command(tmp_path / "s")
    assert cmd[:3] == ["ros2", "bag", "record"]
    assert "mcap" in cmd and "zstd_fast" in cmd
    assert str(tmp_path / "s" / "bag") in cmd
    for topic in RECORD_TOPICS:
        assert topic in cmd


def test_shadow_topic_matches():
    from control.recording import SHADOW_TOPIC
    from control.sensing.perception.learned.shadow import TOPIC
    assert SHADOW_TOPIC == TOPIC


def test_sessions_skip_bad_metadata(tmp_path):
    good = _mk(tmp_path, 0, size=10)
    finish_session(good, T0)
    mark_harvested(good)
    bad = []
    for name, text in [("a", "{not json"), ("b", "[1]"),
                       ("c", '{"harvested": true, "ended_at": "x"}'),
                       ("d", '{"started_at": null, "harvested": true}')]:
        f = tmp_path / name
        f.mkdir()
        (f / "session.json").write_text(text)
        (f / "big").write_bytes(b"0" * 100)
        bad.append(f)
    assert enforce_quota(tmp_path, 1) == [good]
    assert all(f.exists() for f in bad)


def test_harvested_must_be_true(tmp_path):
    f = _mk(tmp_path, 0, size=10)
    finish_session(f, T0)
    meta = _meta(f)
    meta["harvested"] = "false"
    (f / "session.json").write_text(json.dumps(meta))
    assert enforce_quota(tmp_path, 1) == []


def test_same_second_sessions_get_suffix(tmp_path):
    a = _mk(tmp_path, 0)
    b = _mk(tmp_path, 0)
    c = _mk(tmp_path, 0)
    assert a.name.endswith("_pinky-1")
    assert b.name.endswith("_pinky-1_2")
    assert c.name.endswith("_pinky-1_3")


# ---- main() ----
import subprocess
import control.record_session as rs


class FakePopen:
    def __init__(self, waits, log):
        self.waits = list(waits)
        self.signals = []
        self.killed = False
        self.log = log

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.log.append("wait")
        w = self.waits.pop(0)
        if isinstance(w, BaseException):
            raise w
        return w


def _run(monkeypatch, tmp_path, proc_factory, extra=()):
    log = []
    holder = {}

    def popen(cmd, *a, **k):
        holder["proc"] = proc_factory(log)
        return holder["proc"]

    orig = rs.finish_session

    def fin(folder, now):
        log.append("finish")
        orig(folder, now)

    monkeypatch.setattr(rs.subprocess, "Popen", popen)
    monkeypatch.setattr(rs, "finish_session", fin)
    code = rs.main(["--root", str(tmp_path), "--reason", "r", *extra])
    return code, log, holder.get("proc")


def test_main_quota_full_exit_2(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "can_record", lambda *a: False)
    called = []
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *a, **k: called.append(1))
    assert rs.main(["--root", str(tmp_path), "--reason", "r"]) == 2
    assert not called


def test_main_interrupt_graceful(monkeypatch, tmp_path):
    t = subprocess.TimeoutExpired("x", 2)
    code, log, proc = _run(monkeypatch, tmp_path, lambda lg: FakePopen(
        [KeyboardInterrupt(), t, 0], lg))
    assert proc.signals == [rs.signal.SIGINT]
    assert not proc.killed
    assert log == ["wait", "wait", "wait", "finish"]
    assert code == 0


def test_main_kills_if_no_exit(monkeypatch, tmp_path):
    t = subprocess.TimeoutExpired("x", 30)
    code, log, proc = _run(monkeypatch, tmp_path, lambda lg: FakePopen(
        [KeyboardInterrupt(), t, t, 0], lg))
    assert proc.killed and log[-1] == "finish"


def test_main_nonzero_exit(monkeypatch, tmp_path):
    code, log, _ = _run(monkeypatch, tmp_path, lambda lg: FakePopen([3], lg))
    assert code == 1 and log[-1] == "finish"


def test_main_ros2_missing(monkeypatch, tmp_path):
    def popen(*a, **k):
        raise FileNotFoundError("ros2")
    monkeypatch.setattr(rs.subprocess, "Popen", popen)
    assert rs.main(["--root", str(tmp_path), "--reason", "r"]) == 1
    metas = [json.loads(p.read_text()) for p in tmp_path.glob("*/session.json")]
    assert len(metas) == 1 and metas[0]["ended_at"] is not None


def test_main_quota_exceeded_while_running(monkeypatch, tmp_path):
    t = subprocess.TimeoutExpired("x", 5)
    seq = iter([True, False])
    monkeypatch.setattr(rs, "can_record", lambda *a: next(seq))
    code, log, proc = _run(monkeypatch, tmp_path, lambda lg: FakePopen(
        [t, t, 0], lg))
    assert code == 3
    assert proc.signals == [rs.signal.SIGINT]
    assert log[-1] == "finish"


def test_stop_skips_sigint_if_child_exits_on_its_own(monkeypatch, tmp_path):
    code, log, proc = _run(monkeypatch, tmp_path, lambda lg: FakePopen(
        [KeyboardInterrupt(), 0], lg))
    assert proc.signals == [] and log[-1] == "finish"


def test_stop_ignores_further_signals_and_restores(monkeypatch, tmp_path):
    seen = {}
    t = subprocess.TimeoutExpired("x", 2)

    class P(FakePopen):
        def send_signal(self, sig):
            seen["int"] = rs.signal.getsignal(rs.signal.SIGINT)
            seen["term"] = rs.signal.getsignal(rs.signal.SIGTERM)
            super().send_signal(sig)

    before = rs.signal.getsignal(rs.signal.SIGINT)
    _run(monkeypatch, tmp_path, lambda lg: P([KeyboardInterrupt(), t, 0], lg))
    assert seen == {"int": rs.signal.SIG_IGN, "term": rs.signal.SIG_IGN}
    assert rs.signal.getsignal(rs.signal.SIGINT) == before


def test_sigterm_handler_installed_before_popen(monkeypatch, tmp_path):
    seen = {}

    def popen(*a, **k):
        seen["h"] = rs.signal.getsignal(rs.signal.SIGTERM)
        raise FileNotFoundError
    monkeypatch.setattr(rs.subprocess, "Popen", popen)
    rs.main(["--root", str(tmp_path), "--reason", "r"])
    assert seen["h"] is rs._on_sigterm


def test_quota_check_error_stops_recorder_exit_1(monkeypatch, tmp_path):
    t = subprocess.TimeoutExpired("x", 5)
    calls = iter([True])

    def cr(*a):
        try:
            return next(calls)
        except StopIteration:
            raise RuntimeError("boom")
    monkeypatch.setattr(rs, "can_record", cr)
    code, log, proc = _run(monkeypatch, tmp_path, lambda lg: FakePopen(
        [t, t, 0], lg))
    assert code == 1 and proc.signals == [rs.signal.SIGINT]
    assert log[-1] == "finish"


def test_total_bytes_skips_vanished_files(tmp_path, monkeypatch):
    from pathlib import Path
    import control.recording as rec
    (tmp_path / "a").write_bytes(b"0" * 5)
    (tmp_path / "b").write_bytes(b"0" * 7)
    orig = Path.stat

    def stat(self, *a, **k):
        if self.name == "a":
            raise FileNotFoundError
        return orig(self, *a, **k)
    monkeypatch.setattr(Path, "stat", stat)
    assert rec._total_bytes(tmp_path) == 7
