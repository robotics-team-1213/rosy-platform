"""LOG-001: audit events survive a process restart on disk."""

from datetime import datetime, timedelta, timezone

import pytest
from pathlib import Path

from core_events.events.audit import PRUNE_INTERVAL_S, FileAuditLog
from core_events.events.bus import EventBus
from core_common.protocol.schemas import EventMessage, Severity


def _event(seq: int, ts: str, type_: str = "mode.changed") -> EventMessage:
    return EventMessage(
        seq=seq,
        ts=ts,
        robot_id="rosy_01",
        type=type_,
        severity=Severity.INFO,
        source="test",
        data={},
    )


def test_audit_log_survives_a_new_process(tmp_path):
    path = tmp_path / "audit.jsonl"
    FileAuditLog(path).record(_event(1, "2026-09-03T12:00:00+00:00"))
    events = FileAuditLog(path).history()
    assert len(events) == 1
    assert events[0].type == "mode.changed"
    assert events[0].seq == 1


def test_audit_log_drops_records_older_than_retention(tmp_path):
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    log = FileAuditLog(tmp_path / "audit.jsonl", retention_days=30, now=lambda: now)
    log.record(_event(1, (now - timedelta(days=31)).isoformat()))
    log.record(_event(2, (now - timedelta(days=1)).isoformat()))
    types = [e.type for e in log.history()]
    assert [e.seq for e in log.history()] == [2]
    assert types == ["mode.changed"]


def test_audit_log_skips_a_corrupt_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    FileAuditLog(path).record(_event(3, "2026-09-03T12:00:00+00:00"))
    events = FileAuditLog(path).history()
    assert [e.seq for e in events] == [3]


def test_event_bus_can_feed_the_audit_log(tmp_path):
    bus = EventBus("rosy_01")
    log = FileAuditLog(tmp_path / "audit.jsonl")
    bus.subscribe(log.record)
    bus.publish("safety.estop", source="api")
    assert FileAuditLog(tmp_path / "audit.jsonl").history()[0].type == "safety.estop"


# --- 쓰기 비용: 기록은 버스 구독자이고, 버스는 구독자를 동기로 부른다 ----------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_a_write_does_not_rewrite_the_whole_file_every_time(tmp_path, monkeypatch):
    """예전에는 이벤트 하나마다 파일 전체를 읽고 파싱하고 다시 썼다.

    보존 기간이 30 일이라 비용은 계속 자라고, 그 비용은 이벤트를 낸 스레드가
    문다 — 그중 하나가 50 Hz cmd_vel 타이머다.

    벽시계로 재지 않는다(부하 걸린 CI 에서 흔들린다). 대신 정리 시각이 아닌
    기록이 하는 일을 센다: 덧붙이기 핸들 하나를 열 뿐, 파일을 읽지 않는다.
    """
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    for seq in range(2000):
        log.record(_event(seq, "2026-09-03T12:00:00+00:00"))
    assert log.settle()

    opens: list[str] = []
    real_open = Path.open

    def note(self, mode="r", *args, **kwargs):
        opens.append(mode)
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", note)
    log.record(_event(2000, "2026-09-03T12:00:00+00:00"))
    monkeypatch.setattr(Path, "open", real_open)

    assert opens == ["a"], f"a non-due record opened {opens}; it must only append"


def test_the_write_path_prunes_at_most_once_an_hour(tmp_path):
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    clock = Clock()
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now,
                       monotonic=clock, prune_interval_s=3600.0)
    log.record(_event(1, (now - timedelta(days=31)).isoformat()))   # 첫 기록은 정리한다
    assert log.settle()

    log.record(_event(2, (now - timedelta(days=31)).isoformat()))
    clock.advance(60.0)
    log.record(_event(3, now.isoformat()))
    assert log.settle()

    # 아직 한 시간이 지나지 않았으니 오래된 줄이 파일에 남아 있다.
    assert "seq\":2" in path.read_text(encoding="utf-8").replace(" ", "")

    clock.advance(3600.0)
    log.record(_event(4, now.isoformat()))
    assert log.settle()

    assert "seq\":2" not in path.read_text(encoding="utf-8").replace(" ", "")
    assert [event.seq for event in log.history()] == [3, 4]


def test_the_first_write_still_prunes_what_the_last_run_left(tmp_path):
    """재시작 직후 파일에 남아 있는 오래된 줄은 첫 기록에서 정리된다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    first = FileAuditLog(path, now=lambda: now)
    first.record(_event(1, (now - timedelta(days=31)).isoformat()))
    assert first.settle()

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(2, now.isoformat()))
    assert log.settle()

    assert [event.seq for event in FileAuditLog(path, now=lambda: now).history()] == [2]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1, "the stale line is gone"


def test_reading_always_honours_retention(tmp_path):
    """정리를 늦춘 것이지 보존 약속을 늦춘 것이 아니다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    clock = Clock()
    log = FileAuditLog(tmp_path / "audit.jsonl", retention_days=30,
                       now=lambda: now, monotonic=clock)
    log.record(_event(1, now.isoformat()))
    log.record(_event(2, (now - timedelta(days=31)).isoformat()))

    assert [event.seq for event in log.history()] == [1]


def test_pruning_keeps_the_original_line_rather_than_re_serialising(tmp_path):
    """감사 기록이 스키마 왕복으로 조용히 달라지면 안 된다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(1, now.isoformat()))
    kept_line = path.read_text(encoding="utf-8").strip()

    log.record(_event(2, (now - timedelta(days=31)).isoformat()))
    assert log.settle()
    # 정리는 쓰기 경로가 요청한다. 새 인스턴스의 첫 기록이 그 시각이다.
    fresh = FileAuditLog(path, retention_days=30, now=lambda: now)
    fresh.record(_event(3, now.isoformat()))
    assert fresh.settle()

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == kept_line
    assert len(lines) == 2, "the stale line is gone and the two fresh ones are byte-identical"


def test_a_failed_prune_leaves_the_log_intact(tmp_path, monkeypatch):
    """자르는 도중에 죽으면 감사 기록이 사라진다. 바꿔 끼우기로 쓴다."""
    import os as _os

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(1, now.isoformat()))
    log.record(_event(2, (now - timedelta(days=31)).isoformat()))
    assert log.settle()
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr(_os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    fresh = FileAuditLog(path, retention_days=30, now=lambda: now)
    fresh.record(_event(3, now.isoformat()))       # 덧붙이기는 되고 정리만 실패한다
    assert fresh.settle()

    assert path.read_text(encoding="utf-8").startswith(before)
    assert not list(tmp_path.glob("*.tmp")), "the temporary file must not be left behind"


def test_a_failed_prune_is_not_reported_as_an_unwritable_log(tmp_path, monkeypatch):
    """덧붙이기가 성공했으면 그 이벤트는 기록됐다.

    정리 실패를 쓰기 실패로 세면 `/logs/audit` 은 감사 기록이 멀쩡한 로봇을
    두고 "LOG-001 이 꺼졌다"고 답한다 — 운영자가 좇을 곳이 틀린다.
    """
    import os as _os

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    # 지난 실행이 남긴 오래된 줄. `record()` 로 넣으면 그 자리에서 정리돼 버린다.
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    path.write_text(stale + "\n", encoding="utf-8")

    monkeypatch.setattr(_os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(2, now.isoformat()))         # 예외가 밖으로 나오지 않는다
    assert log.settle()

    health = log.health()
    assert health["writable"] is True
    assert health["write_failures"] == 0 and health["write_failures_total"] == 0
    assert health["prune_failures"] == 1
    assert "OSError" in health["last_prune_error"]
    assert health["last_write_error"] is None, "쓰기 채널은 깨끗하다"
    assert [event.seq for event in log.history()] == [2], "the new event is on disk"


def test_a_read_does_not_rewrite_the_file(tmp_path):
    """조회는 파일을 건드리지 않는다.

    예전에는 읽을 때마다 정리를 돌렸다 — 대시보드가 5 초마다 폴링하면 5 초마다
    30 일치 감사 로그를 통째로 재작성하는 것이고, 그 비용은 `record()` 와 같은
    락 안에 있어 50 Hz cmd_vel 스레드가 문다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(1, (now - timedelta(days=31)).isoformat()))
    log.record(_event(2, now.isoformat()))
    assert log.settle()
    before = path.read_bytes()
    inode = path.stat().st_ino

    assert [event.seq for event in log.history()] == [2], "the stale one is filtered out"

    assert path.read_bytes() == before
    # `st_mtime_ns` 는 같은 내용으로 갈아 끼울 때 그대로일 때가 많다(이 파일
    # 시스템에서 200 번 중 76 번). inode 는 `os.replace` 가 반드시 바꾼다.
    assert path.stat().st_ino == inode


def test_a_prune_with_nothing_to_drop_does_not_rewrite(tmp_path):
    """버릴 것이 없으면 쓰지 않는다. 같은 내용으로 갈아 끼우는 동안 원본이
    잠깐 사라지는 창이 생기고, 그것을 매 시각 여는 이유가 없다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    first = FileAuditLog(path, retention_days=30, now=lambda: now)
    first.record(_event(1, now.isoformat()))
    assert first.settle()

    seen = []
    import os as _os
    real = _os.replace
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    try:
        _os.replace = lambda *a, **k: (seen.append(a), real(*a, **k))[1]
        log.record(_event(2, now.isoformat()))     # 첫 기록 = 정리 시각
        assert log.settle()
    finally:
        _os.replace = real

    assert seen == []


# --- LOG-001 이 꺼졌다는 사실은 어딘가에 남아야 한다 ---------------------------


def test_a_write_failure_is_counted_rather_than_lost(tmp_path, monkeypatch):
    """EventBus 는 구독자 예외를 삼킨다.

    그래서 디스크가 찬 로봇은 감사 기록을 남기지 않으면서 아무 말도 하지
    않는다 — 나중에 사고를 조사할 때 비어 있는 로그와 구분되지 않는다.
    """
    log = FileAuditLog(tmp_path / "audit.jsonl")
    assert log.health() == {"writable": True, "write_failures": 0,
                            "write_failures_total": 0, "prune_failures": 0,
                            "prune_skipped": 0, "serialize_failures": 0,
                            "dir_sync_failures": 0,
                            "last_skip_reason": None, "last_write_error": None,
                            "last_prune_error": None, "last_serialize_error": None,
                            "last_dir_sync_error": None}

    def refuse(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "open", refuse)
    for _ in range(3):
        log.record(_event(1, "2026-09-03T12:00:00+00:00"))   # 던지지 않는다 — 센다

    health = log.health()
    assert health["writable"] is False
    assert health["write_failures"] == 3
    assert health["write_failures_total"] == 3
    assert "No space left" in health["last_write_error"]


def test_the_bus_still_swallows_the_failure_so_publishing_keeps_working(tmp_path, monkeypatch):
    """감사 기록이 안 된다고 안전 이벤트 발행이 멈추면 안 된다."""
    bus = EventBus("rosy_01")
    log = FileAuditLog(tmp_path / "audit.jsonl")
    bus.subscribe(log.record)

    def refuse(*args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(Path, "open", refuse)
    bus.publish("safety.estop", source="api")

    assert log.health()["write_failures"] == 1
    assert bus.last_seq == 1


def test_a_recovered_write_clears_the_alarm(tmp_path, monkeypatch):
    """디스크가 비면 다시 정상이다. 한 번 실패한 채로 굳어 있으면 안 된다."""
    log = FileAuditLog(tmp_path / "audit.jsonl")
    real_open = Path.open

    def refuse(*args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(Path, "open", refuse)
    log.record(_event(1, "2026-09-03T12:00:00+00:00"))
    assert log.health()["writable"] is False

    monkeypatch.setattr(Path, "open", real_open)
    log.record(_event(2, "2026-09-03T12:00:00+00:00"))

    health = log.health()
    assert health["writable"] is True and health["write_failures"] == 0
    # 누적 카운터와 마지막 사유는 남는다. 성공 한 번에 지워 버리면 간헐적으로
    # 실패하는 디스크는 운영자가 볼 때마다 늘 깨끗하고, Prometheus 는 카운터가
    # 0 으로 돌아간 것을 재시작으로 읽어 그 실패를 통째로 잃는다.
    assert health["write_failures_total"] == 1
    assert "nope" in health["last_write_error"]



# --- 잘린 꼬리: fsync 하지 않기로 한 것의 대가 --------------------------------

#: 정전이 UTF-8 한 글자 가운데를 자른 줄. `data` 에는 웨이포인트·맵 이름이
#: 실리므로 한글이 들어가고, 그 바이트열이 잘리면 strict 디코드는 예외다.
TORN = b'{"seq":2,"data":{"name":"\xed\x95\n'


def _with_a_torn_line(path: Path, now: datetime) -> str:
    good = _event(1, now.isoformat()).model_dump_json()
    path.write_bytes(good.encode("utf-8") + b"\n" + TORN)
    return good


def test_a_torn_tail_does_not_take_the_audit_log_down(tmp_path):
    """이 상태가 조용하면 `/logs/audit` 은 그 뒤로 영원히 500 이다.

    바이트 몇 개 때문에 30 일치를 통째로 못 읽게 되는 것이고, 그 사실은
    EventBus 가 구독자 예외를 삼키므로 어디에도 남지 않는다. `record()` 안의
    정리도 같은 디코드에서 죽어, 파일은 다시는 정리되지 않는다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _with_a_torn_line(path, now)
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    assert [event.seq for event in log.history()] == [1]

    log.record(_event(3, now.isoformat()))         # 예외가 밖으로 나오지 않는다
    assert log.settle()

    assert [event.seq for event in log.history()] == [1, 3]
    health = log.health()
    assert health["writable"] is True
    assert health["prune_failures"] == 0, "정리는 실패한 것이 아니라 그 줄을 격리한 것이다"


def test_a_torn_tail_is_quarantined_rather_than_kept_forever_or_deleted(tmp_path):
    """스스로 낫는 것이 요점이다. 세어만 두면 파일은 영원히 그 상태다.

    그렇다고 지우지도 않는다 — 감사 로그에서 삭제는 되돌릴 수 없다. 원본
    바이트 그대로 격리 파일로 옮긴다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    good = _with_a_torn_line(path, now)

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(3, now.isoformat()))
    assert log.settle()

    raw = path.read_bytes()
    assert b"\xed\x95" not in raw
    assert raw.decode("utf-8").splitlines()[0] == good
    assert log.quarantine_path.read_bytes() == TORN, "the torn bytes moved, byte for byte"


def test_blank_lines_are_compacted_rather_than_kept_forever(tmp_path):
    """빈 줄을 세지 않으면 `len(kept) == seen` 이 되어 조기 반환에 걸린다 —
    파일이 사는 내내 남는다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    good = _event(1, now.isoformat()).model_dump_json()
    path.write_text("\n\n   \n" + good + "\n", encoding="utf-8")

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(2, now.isoformat()))
    assert log.settle()
    assert not log.quarantine_path.exists(), "a blank line is not a record to keep"

    assert path.read_text(encoding="utf-8").splitlines()[0] == good
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


# --- 정리는 락을 쥔 채 디코드·파싱하지 않는다 ---------------------------------


def _prune_with(log: FileAuditLog, path: Path, during) -> None:
    """정리의 **파싱 루프 안**에 `during` 을 끼워 넣고 한 번 기록한다.

    디코드와 파싱은 락 밖에서 도는 유일한 구간이다. 그 자리에서 무슨 일이
    벌어질 수 있는지가 이 설계의 대가이므로, 거기에 직접 손을 넣어 본다.
    루프 바깥(예: 디코드 진입점)에 걸면 루프 자체가 락 안으로 되돌아가도
    검사가 통과한다 — 그 350 ms 가 락 밖 파싱의 요점이므로 루프 안에 건다.
    """
    real = FileAuditLog._is_fresh
    fired: list[int] = []

    def once(self, ts, cutoff):
        if not fired:                      # 창 안에서 정확히 한 번만
            fired.append(1)
            during()
        return real(self, ts, cutoff)

    try:
        FileAuditLog._is_fresh = once
        log.record(_event(2, datetime(2026, 9, 3, tzinfo=timezone.utc).isoformat()))
        assert log.settle()
    finally:
        FileAuditLog._is_fresh = real
    assert fired, "the hook never ran; the prune did not reach the parse loop"


def test_an_event_written_during_a_prune_is_not_lost(tmp_path):
    """스냅샷 길이 뒤를 잘라 새 내용에 붙이지 않으면 그 줄은 `os.replace` 에
    지워진다 — 감사 로그가 조용히 이벤트를 잃는 것이다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    path.write_text(stale + "\n", encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    def another_thread_records():
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_event(99, now.isoformat()).model_dump_json() + "\n")

    _prune_with(log, path, another_thread_records)

    assert sorted(event.seq for event in log.history()) == [2, 99]


def test_the_prune_does_not_hold_the_lock_across_the_parse(tmp_path):
    """10 만 줄이면 디코드·파싱만 350 ms 다. 락을 쥔 채로 하면 그 한 시간에
    처음 기록되는 이벤트가 그것을 문다 — 하필 SAF-002 정지일 수 있다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    path.write_text(_event(1, (now - timedelta(days=31)).isoformat()).model_dump_json() + "\n",
                    encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    held: list[bool] = []

    def note_whether_the_lock_is_held():
        free = log._lock.acquire(blocking=False)
        held.append(not free)
        if free:
            log._lock.release()

    _prune_with(log, path, note_whether_the_lock_is_held)

    assert held == [False], "the lock was held across the decode and parse"


def test_whatever_the_prune_throws_is_counted_rather_than_swallowed(tmp_path):
    """`except OSError` 로는 부족하다.

    `_compact` 가 가장 먼저 하는 일은 I/O 가 아니라 디코드이고, 디코드 실패는
    `ValueError` 다. 그것이 여기를 빠져나가면 EventBus 의 `except Exception:
    pass` 가 삼켜 아무 데도 남지 않는다 — 정리는 영영 멈춘 채, 건강 상태는
    깨끗하다고 답한다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    path.write_text(_event(1, (now - timedelta(days=31)).isoformat()).model_dump_json() + "\n",
                    encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    def explode():
        raise ValueError("not an OSError")

    _prune_with(log, path, explode)                # 예외가 밖으로 나오지 않는다

    health = log.health()
    assert health["prune_failures"] == 1
    assert "ValueError" in health["last_prune_error"]
    assert health["writable"] is True and health["write_failures_total"] == 0
    assert [event.seq for event in log.history()] == [2], "the append still happened"


def test_a_file_that_shrank_under_the_prune_is_left_alone(tmp_path):
    """락 밖에서 파싱하는 대가로 생긴 창이다.

    그 사이 파일이 지워지거나 줄어들면 우리가 든 스냅샷은 더 이상 이 파일의
    앞부분이 아니다. 그대로 이어 붙이면 남의 파일을 우리 옛 내용으로
    덮어쓰게 된다 — 이어 붙이지 않고 이번 시각을 거른다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    survivor = _event(7, now.isoformat()).model_dump_json()
    path.write_text(stale + "\n", encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    def someone_replaces_the_file():
        path.write_text(survivor + "\n", encoding="utf-8")   # 더 짧다

    _prune_with(log, path, someone_replaces_the_file)

    assert path.read_text(encoding="utf-8") == survivor + "\n"


def test_a_deleted_file_is_not_recreated_from_a_stale_snapshot(tmp_path):
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    path.write_text(_event(1, (now - timedelta(days=31)).isoformat()).model_dump_json() + "\n",
                    encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    _prune_with(log, path, lambda: path.unlink())

    assert not path.exists()


# --- 정전이 개행을 남기지 못한 경우 -------------------------------------------

#: 잘린 꼬리 — 개행이 **없다**. 개행은 마지막에 쓰이는 바이트이므로, 글자
#: 가운데가 잘렸다면 그것은 애초에 디스크에 닿지 못했다. 개행으로 끝나는 잘린
#: 꼬리를 픽스처로 쓰면 이 문제 하나만 비껴간다.
UNTERMINATED = b'{"seq":2,"data":{"name":"\xed\x95'


def test_the_next_event_is_not_swallowed_by_an_unterminated_line(tmp_path):
    """그냥 이어 쓰면 새 이벤트가 망가진 줄의 일부가 되어 함께 버려진다.

    정전 직후 처음 기록되는 것이 하필 `safety.estop` 일 수 있다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    good = _event(1, now.isoformat()).model_dump_json()
    path.write_bytes(good.encode("utf-8") + b"\n" + UNTERMINATED)

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(3, now.isoformat(), "safety.estop"))

    seqs = [event.seq for event in log.history()]
    assert 3 in seqs, "the estop was concatenated onto the torn line and pruned away"
    assert seqs == [1, 3]


def test_the_terminator_is_checked_once_not_on_every_record(tmp_path):
    """50 Hz 경로다. 기록마다 stat+seek 을 붙이면 덧붙이기 전용 쓰기가 없앤 비용이 돌아온다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    path.write_bytes(UNTERMINATED)
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    opens: list[str] = []
    real_open = Path.open

    def note(self, *args, **kwargs):
        opens.append(str(args[0]) if args else "r")
        return real_open(self, *args, **kwargs)

    log.record(_event(1, now.isoformat()))          # 첫 기록이 확인한다
    assert log.settle()
    before = len(opens)
    try:
        Path.open = note
        for seq in range(2, 12):
            log.record(_event(seq, now.isoformat()))
    finally:
        Path.open = real_open

    assert [mode for mode in opens if mode.startswith("rb")] == [], (
        "the terminator was re-checked after the first append")
    assert before == 0


# --- 스냅샷 읽기도 세어야 한다 -------------------------------------------------


def test_a_snapshot_read_failure_is_counted_rather_than_swallowed(tmp_path, monkeypatch):
    """이 읽기가 가드 밖에 있으면 열린 핸들 하나(백신·인덱서)가 정리를 영원히
    멈추면서 건강 상태는 깨끗하다고 답한다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    monkeypatch.setattr(FileAuditLog, "_open_snapshot_locked",
                        lambda self: (_ for _ in ()).throw(PermissionError("in use")))

    log.record(_event(1, now.isoformat()))          # 예외가 밖으로 나오지 않는다
    assert log.settle()

    health = log.health()
    assert health["prune_failures"] == 1
    assert "PermissionError" in health["last_prune_error"]
    assert health["writable"] is True and health["write_failures_total"] == 0


def test_a_failing_snapshot_read_is_not_retried_on_every_record(tmp_path, monkeypatch):
    """50 Hz 스레드가 실패하는 읽기를 매 주기 다시 하면 안 된다.

    `_last_prune` 을 읽기 **앞**에서 태우는 것이 그것을 막는다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    log = FileAuditLog(tmp_path / "audit.jsonl", retention_days=30, now=lambda: now)
    attempts: list[int] = []

    def refuse(self):
        attempts.append(1)
        raise PermissionError("in use")

    monkeypatch.setattr(FileAuditLog, "_open_snapshot_locked", refuse)
    for seq in range(6):
        log.record(_event(seq, now.isoformat()))
    assert log.settle()

    assert attempts == [1], "the prune retried on the hot path"


# --- 이어 붙이기의 전제 --------------------------------------------------------


def test_a_file_rewritten_in_place_is_not_spliced(tmp_path):
    """신원((장치, inode))까지 같은 다른 파일. Linux 는 지운 파일의 inode 번호를
    곧바로 다시 주므로 "지우고 다시 만들기"가 이렇게 보인다. 제자리 덮어쓰기는
    어느 OS 에서나 inode 를 유지하므로 같은 상황을 Windows 에서도 재현한다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    path.write_text(stale + "\n", encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    replacement = ("x" * (len(stale) + 400)) + "\n"

    def someone_rewrites_it():
        with path.open("r+b") as handle:          # 같은 inode 그대로
            handle.seek(0)
            handle.write(replacement.encode("utf-8"))
            handle.truncate()

    _prune_with(log, path, someone_rewrites_it)

    assert path.read_text(encoding="utf-8") == replacement
    health = log.health()
    assert health["prune_skipped"] == 1
    assert health["prune_failures"] == 0


def test_a_file_edited_in_place_near_the_start_is_not_spliced(tmp_path):
    """끝 4 KiB 가 같아도 앞부분이 바뀌었으면 이어 붙이지 않는다. 같은 길이로
    제자리 저장하는 편집기는 inode·크기·끝을 모두 그대로 두므로, 앞도 보지
    않으면 우리 옛 스냅샷이 그 편집을 조용히 되돌린다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    fresh = [_event(10 + i, now.isoformat()).model_dump_json() for i in range(80)]
    path.write_text("\n".join([stale, *fresh]) + "\n", encoding="utf-8")
    assert path.stat().st_size > 2 * 4096, "the head and the boundary must not overlap"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    edited = stale.replace('"seq":1,', '"seq":7,')
    assert edited != stale and len(edited) == len(stale)

    def someone_edits_the_first_line():
        with path.open("r+b") as handle:          # 같은 inode, 같은 크기, 같은 끝
            handle.write(edited.encode("utf-8"))

    _prune_with(log, path, someone_edits_the_first_line)

    assert path.read_text(encoding="utf-8").startswith(edited), "the edit was undone"
    health = log.health()
    assert health["prune_skipped"] == 1
    assert health["prune_failures"] == 0


def test_a_file_swapped_for_a_longer_one_is_not_spliced(tmp_path):
    """크기만 보면 같은 길이거나 더 긴 것으로 갈아 끼운 것을 못 잡는다 —
    그러면 남의 내용 한가운데에 우리 옛 스냅샷을 이어 붙인다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    path.write_text(stale + "\n", encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    replacement = ("x" * (len(stale) + 400)) + "\n"

    def someone_swaps_it():
        path.unlink()
        path.write_text(replacement, encoding="utf-8")   # 더 길다

    _prune_with(log, path, someone_swaps_it)

    assert path.read_text(encoding="utf-8") == replacement
    health = log.health()
    assert health["prune_skipped"] == 1
    assert health["prune_failures"] == 0, "전제가 깨진 것이지 실패한 것이 아니다"
    assert "no longer" in health["last_skip_reason"]
    assert health["last_prune_error"] is None, "거른 것을 실패 사유 칸에 적지 않는다"


# --- 회귀 방지: 검사가 없어 조용히 바뀔 수 있던 계약들 -------------------------


def test_a_read_returns_the_newest_not_the_oldest(tmp_path):
    """`/logs/audit` 의 기본 limit 은 500 이다. 오래된 쪽을 돌려주면 운영자는
    사고를 조사하는 동안 한 달 전 사건을 본다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    log = FileAuditLog(tmp_path / "audit.jsonl", retention_days=30, now=lambda: now)
    for seq in range(1, 11):
        log.record(_event(seq, now.isoformat()))

    assert [event.seq for event in log.history(limit=3)] == [8, 9, 10]


def test_a_record_with_an_unreadable_timestamp_is_kept_not_deleted(tmp_path):
    """열려 있는 쪽을 고른 것이다 — 감사 로그에서 삭제는 되돌릴 수 없다.

    대가는 그 줄이 `history()` 에 영원히 남는 것이고, 그것은 알고 하는 거래다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    broken = _event(1, now.isoformat()).model_dump_json().replace(
        now.isoformat(), "not-a-timestamp")
    path.write_text(broken + "\n", encoding="utf-8")

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(2, now.isoformat()))
    assert log.settle()

    assert [event.seq for event in log.history()] == [1, 2]
    assert broken in path.read_text(encoding="utf-8")


def test_corrupt_bytes_are_marked_rather_than_quietly_removed(tmp_path):
    """`errors="ignore"` 는 훼손된 바이트를 지워 그럴듯한 기록을 만든다.

    `"현\xff관"` 이 `"현관"` 이 되면 훼손과 정상 기록을 구분할 방법이 없다.
    `replace` 는 U+FFFD 를 남겨 표시한다.
    """
    assert FileAuditLog._decode(b'{"name":"\xed\x98\x84\xff\xea\xb4\x80"}') == (
        '{"name":"현\ufffd관"}')


def test_a_line_the_decoder_had_to_mangle_is_not_rewritten_mangled(tmp_path):
    """디코드해서 자르고 다시 인코드하면 U+FFFD 가 디스크에 쓰인다 —
    "원본 줄을 그대로 남긴다"가 깨진 줄에 대해서만 조용히 거짓이 된다.

    그러면 운영자는 훼손된 기록과 정말로 U+FFFD 를 실은 기록을 구분할 수 없다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    named = _event(1, now.isoformat())
    named.data = {"name": "현관앞"}
    line = named.model_dump_json().encode("utf-8")
    # 한글 한 글자 가운데 한 바이트만 망가뜨린다 — JSON 으로는 여전히 읽힌다.
    at = line.index("현관앞".encode("utf-8"))
    corrupt = line[:at] + b"\xff" + line[at + 1:]
    stale = _event(2, (now - timedelta(days=31)).isoformat()).model_dump_json()
    path.write_bytes(corrupt + b"\n" + stale.encode("utf-8") + b"\n")

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(3, now.isoformat()))
    assert log.settle()

    raw = path.read_bytes()
    assert stale.encode("utf-8") not in raw, "the prune did run"
    assert corrupt in raw, "the corrupt line was rewritten with the decoder's guesses"
    assert b"\xef\xbf\xbd" not in raw


def test_only_one_record_is_ever_inside_the_compaction_window(tmp_path):
    """직렬화가 `prune_interval_s > 0` 에 기대는 창발적 성질이면 생성자 인자
    하나로 깨진다. 두 정리가 겹치면 나중 것이 앞선 것의 스냅샷을 덮어써,
    그 사이 덧붙은 이벤트가 사라진다.

    간격을 0 으로 두고 창을 넓혀, 겹칠 수 있으면 반드시 겹치게 한다.
    """
    import threading
    import time

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    path.write_text(_event(1, (now - timedelta(days=31)).isoformat()).model_dump_json() + "\n",
                    encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now, prune_interval_s=0.0)

    real = FileAuditLog._is_fresh
    guard = threading.Lock()
    active: list[int] = []
    high_water: list[int] = []

    def note(self, ts, cutoff):
        with guard:
            active.append(threading.get_ident())
            high_water.append(len(set(active)))
        time.sleep(0.05)                   # 창을 넓힌다
        with guard:
            active.remove(threading.get_ident())
        return real(self, ts, cutoff)

    try:
        FileAuditLog._is_fresh = note
        threads = [threading.Thread(target=log.record, args=(_event(seq, now.isoformat()),))
                   for seq in range(20, 24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert log.settle()
    finally:
        FileAuditLog._is_fresh = real

    assert high_water, "no compaction ran; the test proves nothing"
    assert max(high_water) == 1, "two records compacted at once"
    assert sorted(event.seq for event in log.history()) == [20, 21, 22, 23]


def test_a_failed_write_does_not_leave_the_tail_looking_terminated(tmp_path, monkeypatch):
    """캐시는 *쓰려고 한 것* 이 아니라 *쓰인 것* 을 말해야 한다.

    성공한 기록이 캐시를 참으로 만든 뒤 다음 기록이 절반만 나가고 실패하면,
    꼬리는 개행 없이 끝나 있는데 캐시는 여전히 참이다. 그 다음 이벤트는 그
    잘린 줄에 이어 붙어 함께 버려진다 — 디스크가 잠깐 찼다 풀린 로봇에서
    그것이 하필 `safety.estop` 일 수 있다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(1, now.isoformat()))          # 캐시가 참이 된다
    assert log.settle()

    real_open = Path.open

    class HalfWrites:
        """절반만 쓰고 닫으며 실패한다 (ENOSPC 의 모양)."""

        def __init__(self, handle):
            self._handle = handle

        def write(self, text):
            self._handle.write(text[: len(text) // 2])

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self._handle.close()
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "open", lambda self, *a, **k: HalfWrites(real_open(self, *a, **k)))
    log.record(_event(2, now.isoformat()))
    monkeypatch.setattr(Path, "open", real_open)
    assert log.health()["write_failures"] == 1

    assert not path.read_bytes().endswith(b"\n"), "the fixture must leave a torn tail"

    log.record(_event(3, now.isoformat(), "safety.estop"))

    assert [event.seq for event in log.history()] == [1, 3], (
        "the estop was appended onto the half-written line and pruned away")


def test_a_last_byte_we_could_not_read_is_treated_as_unterminated(tmp_path, monkeypatch):
    """두 답의 비용이 다르다. 틀린 `True` 는 이벤트를 삼키고(되돌릴 수 없다),
    틀린 `False` 는 빈 줄 하나를 남기며 그것은 다음 정리가 지운다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    good = _event(1, now.isoformat()).model_dump_json()
    path.write_bytes(good.encode("utf-8") + b"\n" + UNTERMINATED)
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    real_open = Path.open

    def deny_reads(self, mode="r", *args, **kwargs):
        if "b" in mode and "r" in mode:
            raise PermissionError("in use")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_reads)
    log.record(_event(2, now.isoformat(), "safety.estop"))
    assert log.settle()
    monkeypatch.setattr(Path, "open", real_open)

    assert 2 in [event.seq for event in log.history()]


def test_what_record_wrote_is_what_the_prune_keeps(tmp_path):
    """바이트 그대로 남긴다는 약속은 이 모듈 자신의 writer 에 대해서도 참이어야
    한다. `newline=""` 이 없으면 Windows 는 CRLF 로 쓰고, 정리는 그 `\r` 를
    떼고 LF 로 다시 이어 붙인다 — 깨진 줄뿐 아니라 모든 줄이 달라진다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(_event(1, now.isoformat()))
    log.record(_event(2, (now - timedelta(days=31)).isoformat()))
    assert log.settle()
    written = path.read_bytes().split(b"\n")[0]

    fresh = FileAuditLog(path, retention_days=30, now=lambda: now)
    fresh.record(_event(3, now.isoformat()))
    assert fresh.settle()

    assert written in path.read_bytes(), "the line the module itself wrote came back different"


def test_the_reader_and_the_pruner_agree_on_what_a_line_is(tmp_path):
    """`str.splitlines()` 는 U+2028 에서도 자르고 정리는 개행에서만 자른다.

    어긋나 있으면 payload 에 그 글자가 든 기록이 디스크에는 남고 조회에는
    영영 안 보인다 — 감사 로그가 자기가 가진 것을 부인하는 상태다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    event = _event(1, now.isoformat())
    event.data = {"note": "door\u2028open"}
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    log.record(event)

    assert [item.seq for item in log.history()] == [1]
    assert log.history()[0].data == {"note": "door\u2028open"}


def test_the_writer_asks_for_no_newline_translation(tmp_path, monkeypatch):
    """`newline=""` 없이 열면 Windows 는 CRLF 로 쓴다.

    그 결함은 **Linux CI 에서 관측되지 않는다** — 거기서는 `newline=None` 도
    번역을 하지 않으므로 바이트가 같다. 그래서 결과가 아니라 요청을 검사한다:
    이 줄이 지워지면 어느 플랫폼에서든 여기가 빨개진다.
    """
    seen: list[object] = []
    real_open = Path.open

    def note(self, mode="r", *args, **kwargs):
        if "a" in mode:
            seen.append(kwargs.get("newline", "<missing>"))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", note)
    log = FileAuditLog(tmp_path / "audit.jsonl")
    log.record(_event(1, "2026-09-03T12:00:00+00:00"))
    assert log.settle()

    # `== [""]` 로 적으면 정당한 두 번째 append 열기(재시도 등)에도 깨지고,
    # 그때 나오는 메시지는 엉뚱한 곳을 가리킨다.
    assert seen and all(newline == "" for newline in seen), (
        "the append handle must disable newline translation")


def test_a_log_written_by_an_older_crlf_build_upgrades_without_loss(tmp_path):
    """이미 디스크에 있는 파일은 CRLF 로 쓰여 있을 수 있다.

    읽기는 그대로 되어야 하고, 첫 정리가 LF 로 정규화하되 기록은 하나도
    잃지 않아야 한다. 예전 수정은 writer 를 고치고 writer 를 검사했다 —
    이미 있던 파일은 아무도 검사하지 않았다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    fresh = _event(2, now.isoformat()).model_dump_json()
    path.write_bytes(stale.encode("utf-8") + b"\r\n" + fresh.encode("utf-8") + b"\r\n")

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    assert [event.seq for event in log.history()] == [2], "the reader must cope with CRLF"

    log.record(_event(3, now.isoformat()))
    assert log.settle()

    assert [event.seq for event in log.history()] == [2, 3]
    raw = path.read_bytes()
    assert b"\r" not in raw, "the kept line was not normalised to LF"
    assert raw.startswith(fresh.encode("utf-8") + b"\n"), "and otherwise byte-identical"
    assert len(raw.split(b"\n")) == 3, "two lines and the trailing terminator"


@pytest.mark.parametrize("block", [1, 3, 1024 * 1024])
def test_a_line_is_split_on_the_newline_and_nothing_else(monkeypatch, block):
    """`bytes.splitlines()` 는 수직탭·폼피드·파일구분자에서도 자른다.

    이 파일의 줄 구분자는 개행 하나다(JSON Lines). 갈라지면 한 줄이었던
    기록이 두 줄로 보여 둘 다 깨진 JSON 이 된다. 정리는 파일을 조각으로
    읽으므로, 조각 경계에 걸친 줄도 같은 답이어야 한다.
    """
    import io

    import core_events.events.audit as audit

    monkeypatch.setattr(audit, "_COMPACT_BLOCK", block)

    def lines(blob: bytes) -> list[bytes]:
        return list(audit._lines_forward(io.BytesIO(blob), len(blob)))

    assert lines(b'{"a":"x\ry"}') == [b'{"a":"x\ry"}']
    assert lines(b"one\ntwo\n") == [b"one", b"two"]
    assert lines(b"") == []
    assert lines(b"no terminator") == [b"no terminator"]
    assert lines(b"\n\nx\n") == [b"", b"", b"x"]
    # 연 순간의 크기까지만 읽는다 — 그 뒤에 덧붙는 도중의 줄은 보지 않는다.
    assert list(audit._lines_forward(io.BytesIO(b"one\ntwo\npartial"), 8)) == [b"one", b"two"]


@pytest.mark.parametrize("suffix,visible,label", [
    (b"", True, "plain"),
    (b"\r", True, "CRLF 로 쓰인 옛 파일"),
    # 세로탭·폼피드는 `bytes.strip()` 이 떼어내고 JSON 공백에는 없다. 그래서
    # 자르는 순서가 실제로 다른 답을 내는 유일한 바이트들이다 — 이것들이
    # 없으면 아래 검사는 `strip` 을 통째로 지워도 통과한다.
    (b"\x0b", True, "세로탭이 뒤에 붙은 줄"),
    (b"\x0c", True, "폼피드가 뒤에 붙은 줄"),
    # U+2028·NBSP 는 `str.strip()` 만 떼어낸다. 정리는 예전부터 이 줄을
    # 버려 왔으므로 답은 "안 보인다"이고, 조회도 같은 답을 해야 한다.
    ("\u2028".encode("utf-8"), False, "U+2028 이 뒤에 붙은 줄"),
    ("\u00a0".encode("utf-8"), False, "NBSP 가 뒤에 붙은 줄"),
])
def test_what_a_read_returns_is_what_the_prune_keeps(tmp_path, suffix, visible, label):
    """조회와 정리는 한 줄을 **같게** 판정해야 한다.

    나뉘는 규칙만 맞추는 것으로는 부족하다. 자르는 규칙도 같아야 한다 —
    `str.strip()` 의 공백에는 U+2028·NBSP 가 들어 있고 `bytes.strip()` 에는
    없다. 어긋나면 조회가 운영자에게 돌려준 기록을 다음 정리가 지운다.
    되돌릴 수 없는 삭제이고, 이 브랜치가 없애려던 바로 그 종류다.

    각 줄이 보이는지 **여기서 못박는다**. "돌려준 것은 남는다"만 적으면
    아무것도 안 돌려주는 경우에 공허하게 참이 되고, 실제로 그 두 줄이
    그랬다 — 그래서 이 검사가 `strip` 을 지워도 통과했다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    odd = _event(7, now.isoformat()).model_dump_json().encode("utf-8") + suffix
    stale = _event(1, (now - timedelta(days=31)).isoformat()).model_dump_json()
    path.write_bytes(odd + b"\n" + stale.encode("utf-8") + b"\n")

    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    before = {event.seq for event in log.history()}

    assert (7 in before) is visible, f"{label}: the read disagrees with what we pinned"

    log.record(_event(9, now.isoformat()))          # 첫 기록이 정리를 요청한다
    assert log.settle()

    after = {event.seq for event in log.history()}
    assert before - {1} <= after, f"{label}: a record the read returned was pruned away"


# --- 정리와 조회는 이벤트를 낸 스레드를 세우지 않는다 (2026-09-22 리뷰) --------


def _stale_heavy_log(path: Path, now: datetime, lines: int = 3000) -> None:
    """오래된 줄 하나 + 보존 기간 안의 줄 여럿. 정리하면 반드시 다시 쓴다."""
    stale = _event(0, (now - timedelta(days=40)).isoformat()).model_dump_json()
    fresh = _event(1, now.isoformat()).model_dump_json()
    path.write_text(stale + "\n" + (fresh + "\n") * lines, encoding="utf-8")


def test_a_due_prune_is_handed_off_rather_than_done_by_the_caller(tmp_path, monkeypatch):
    """`record()` 는 버스 구독자이고, 버스는 구독자를 동기로 부른다.

    정리를 그 자리에서 하면 10 만 줄 파일에서 첫 기록이 656 ms, 매시 788 ms 를
    이벤트를 낸 스레드 — 50 Hz cmd_vel 타이머일 수 있다 — 가 문다. 정리를 막아
    둔 채로 `record()` 가 돌아오는지, 정리가 **다른 스레드** 에서 도는지 센다.
    """
    import threading

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _stale_heavy_log(path, now)
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    real = FileAuditLog._compact
    release = threading.Event()
    ran_on: list[int] = []

    def blocked(self):
        ran_on.append(threading.get_ident())
        assert release.wait(10), "the test never released the compaction"
        return real(self)

    monkeypatch.setattr(FileAuditLog, "_compact", blocked)
    log.record(_event(2, now.isoformat()))         # 정리가 막혀 있어도 돌아온다
    assert not release.is_set()

    log.record(_event(3, now.isoformat()))         # 정리 도중의 기록도 덧붙이기만 한다
    release.set()
    assert log.settle()

    assert ran_on and threading.get_ident() not in ran_on, "the caller did the prune"
    assert len(ran_on) == 1, "one due prune, one compaction"
    raw = path.read_text(encoding="utf-8")
    assert '"seq":0' not in raw.replace(" ", ""), "the prune still happened"
    assert [event.seq for event in log.history(limit=2)] == [2, 3], (
        "the record appended during the compaction survived the splice")


def test_a_read_does_not_hold_the_write_lock_while_it_parses(tmp_path, monkeypatch):
    """락을 쥔 채 19 MB 를 읽고 파싱하면 그동안 `record()` 가, 즉 50 Hz 타이머가
    멈춘다. 여는 순간만 잡는다 — 정리의 `os.replace` 와 겹치지 않게."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    for seq in (1, 2, 3):
        log.record(_event(seq, now.isoformat()))
    assert log.settle()

    held: list[bool] = []
    real = FileAuditLog._event_from

    def note(raw_line):
        free = log._lock.acquire(blocking=False)
        held.append(not free)
        if free:
            log._lock.release()
        return real(raw_line)

    monkeypatch.setattr(FileAuditLog, "_event_from", staticmethod(note))

    assert [event.seq for event in log.history()] == [1, 2, 3]
    assert held and not any(held), "history() parsed while holding the write lock"


def test_a_small_read_parses_only_the_tail(tmp_path, monkeypatch):
    """대시보드는 페이지를 열 때 `limit=1` 로 묻는다. 30 일치를 모두 파싱해
    하나를 돌려주면 10 만 줄에서 1.4 초다."""
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    line = _event(1, now.isoformat()).model_dump_json()
    path.write_text((line + "\n") * 5000 + _event(2, now.isoformat()).model_dump_json() + "\n",
                    encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    parsed: list[int] = []
    real = FileAuditLog._event_from

    def count(raw_line):
        parsed.append(1)
        return real(raw_line)

    monkeypatch.setattr(FileAuditLog, "_event_from", staticmethod(count))

    assert [event.seq for event in log.history(limit=1)] == [2]
    assert len(parsed) <= 2, f"a limit=1 read parsed {len(parsed)} lines"


@pytest.mark.parametrize("chunk", [1, 7, 64, 4096])
def test_reading_backwards_matches_a_full_parse(tmp_path, monkeypatch, chunk):
    """끝에서부터 조각으로 읽어도 답은 같아야 한다 — 조각 경계에 걸친 줄,
    보존 기간이 지난 줄, 깨진 줄, 빈 줄, `since_seq` 까지."""
    import core_events.events.audit as audit

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    rows = []
    for seq in range(1, 31):
        ts = (now - timedelta(days=40 if seq % 7 == 0 else 1)).isoformat()
        rows.append(_event(seq, ts).model_dump_json().encode("utf-8"))
        if seq % 11 == 0:
            rows.append(b"not-json")
        if seq % 13 == 0:
            rows.append(b"")
    path.write_bytes(b"\n".join(rows) + b"\n")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    expected = [seq for seq in range(1, 31) if seq % 7 != 0]

    monkeypatch.setattr(audit, "_READ_CHUNK", chunk)

    assert [event.seq for event in log.history()] == expected
    assert [event.seq for event in log.history(limit=5)] == expected[-5:]
    assert [event.seq for event in log.history(since_seq=20)] == [s for s in expected if s > 20]
    assert [event.seq for event in log.history(since_seq=20, limit=2)] == expected[-2:]


def test_an_unserialisable_event_is_counted_and_still_recorded(tmp_path):
    """`data` 에 JSON 이 될 수 없는 값이 있으면 `model_dump_json()` 이
    `PydanticSerializationError`(= `ValueError`) 를 던진다.

    그것이 `record()` 밖으로 나가면 EventBus 가 삼키고, 건강 상태는 여전히
    쓸 수 있다고 답한다 — 기록 하나가 소리 없이 사라진 것이다. 세고, 그 값만
    `repr` 로 바꿔 기록은 남긴다.
    """
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    log = FileAuditLog(tmp_path / "audit.jsonl", retention_days=30, now=lambda: now)
    odd = _event(1, now.isoformat(), "safety.estop")
    odd.data = {"reason": object()}

    log.record(odd)                                # 던지지 않는다

    health = log.health()
    assert health["serialize_failures"] == 1
    assert "PydanticSerializationError" in health["last_serialize_error"]
    assert health["writable"] is True and health["write_failures_total"] == 0
    events = log.history()
    assert [event.type for event in events] == ["safety.estop"]
    assert events[0].data["reason"].startswith("<object object")


def test_the_bus_publishes_an_unserialisable_event_without_losing_the_record(tmp_path):
    bus = EventBus("rosy_01")
    log = FileAuditLog(tmp_path / "audit.jsonl")
    bus.subscribe(log.record)

    bus.publish("safety.estop", source="api", data={"cause": object()})

    assert log.health()["serialize_failures"] == 1
    assert [event.type for event in log.history()] == ["safety.estop"]


def test_the_compacted_file_reaches_the_disk_before_it_replaces_the_log(tmp_path, monkeypatch):
    """바꿔 끼우기는 30 일치 전체를 새 파일로 옮기는 일이다. 그 파일이 디스크에
    닿기 전에 이름을 바꾸면, 직후의 정전이 빈 파일을 남길 수 있다.

    덧붙이기는 그대로 fsync 하지 않는다 — 그 비용은 50 Hz 타이머가 문다.
    """
    import os as _os

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _stale_heavy_log(path, now, lines=3)
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    order: list[str] = []
    real_fsync, real_replace = _os.fsync, _os.replace
    monkeypatch.setattr(_os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(_os, "replace",
                        lambda *a, **k: (order.append("replace"), real_replace(*a, **k))[1])

    log.record(_event(2, now.isoformat()))
    assert log.settle()

    assert "replace" in order, "the prune did not rewrite; the test proves nothing"
    assert "fsync" in order[: order.index("replace")], "replaced before the data was synced"

    order.clear()
    for seq in range(3, 8):
        log.record(_event(seq, now.isoformat()))
    assert order == [], "a plain append must not fsync"


def test_a_line_the_schema_rejects_follows_retention_by_its_own_ts(tmp_path):
    """롤백 뒤의 스키마 차이나 비트 하나로 스키마 검증에 실패한 줄을 정리가
    지우면, 감사 로그가 되돌릴 수 없게 기록을 잃는다(`_is_fresh` 의 fail-open 과
    모순이다).

    JSON 으로 읽히고 `ts` 가 있으면 그 `ts` 로 보존 규칙을 따른다: 기간 안이면
    원본 그대로 남고, 지났으면 다른 기록처럼 덜어낸다. 조회에는 나오지 않는다 —
    스키마로 읽을 수 없는 것을 기록이라고 돌려줄 수는 없다.
    """
    import json

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    drifted_fresh = json.dumps({"seq": 5, "ts": now.isoformat(), "kind": "renamed.field"})
    drifted_stale = json.dumps({"seq": 6, "ts": (now - timedelta(days=40)).isoformat(),
                                "kind": "renamed.field"})
    path.write_text(drifted_fresh + "\n" + drifted_stale + "\n", encoding="utf-8")
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    log.record(_event(7, now.isoformat()))
    assert log.settle()

    raw = path.read_text(encoding="utf-8")
    assert drifted_fresh in raw, "a fresh record the schema rejects was deleted"
    assert drifted_stale not in raw, "retention still applies to it"
    assert not log.quarantine_path.exists(), "it had a ts; it is not quarantined"
    assert [event.seq for event in log.history()] == [7]
    assert log.health()["prune_failures"] == 0


# --- 정리 후속: 락 밖 격리, 재시도 중복, 스레드 시작 실패, 디렉터리 fsync ------


class _OwnedLock:
    """누가 쥐고 있는지 아는 락. 락 안에서 fsync 했는지를 시각이 아니라 소유로 본다."""

    def __init__(self) -> None:
        import threading
        self._inner = threading.Lock()
        self.owner = None

    def acquire(self, blocking=True, timeout=-1):
        import threading
        got = self._inner.acquire(blocking, timeout)
        if got:
            self.owner = threading.get_ident()
        return got

    def release(self):
        self.owner = None
        self._inner.release()

    def locked(self):
        return self._inner.locked()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def test_the_quarantine_is_synced_outside_the_lock_and_before_the_replace(tmp_path, monkeypatch):
    """격리 파일의 fsync 는 SD 카드에서 수~수십 ms 다. 그것을 락 안에서 하면
    그동안 `record()` — 곧 이벤트를 낸 스레드 — 가 기다린다.

    그래도 순서는 지킨다: 본 파일에서 빼기 전에 격리 파일이 디스크에 닿는다.
    """
    import os as _os
    import threading

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _with_a_torn_line(path, now)
    log = FileAuditLog(path, retention_days=30, now=lambda: now)
    lock = _OwnedLock()
    log._lock, log._idle = lock, threading.Condition(lock)

    order: list[tuple[str, bool]] = []
    real_fsync, real_replace = _os.fsync, _os.replace

    def fsync(fd):
        synced = _os.fstat(fd)
        is_sink = log.quarantine_path.exists() and _os.path.samestat(
            synced, _os.stat(log.quarantine_path))
        order.append(("quarantine" if is_sink else "fsync",
                      lock.owner == threading.get_ident()))
        return real_fsync(fd)

    monkeypatch.setattr(_os, "fsync", fsync)
    monkeypatch.setattr(_os, "replace",
                        lambda *a, **k: (order.append(("replace", True)), real_replace(*a, **k))[1])

    log.record(_event(3, now.isoformat()))
    assert log.settle()

    names = [name for name, _ in order]
    assert "quarantine" in names and "replace" in names, order
    assert names.index("quarantine") < names.index("replace"), "removed before quarantined"
    assert [name for name, held in order if held and name != "replace"] == [], \
        f"fsync under the lock: {order}"
    assert log.quarantine_path.read_bytes() == TORN


def test_a_retried_compaction_does_not_quarantine_the_same_bytes_twice(tmp_path, monkeypatch):
    """바꿔 끼우기가 실패하면(Windows 의 `PermissionError`) 다음 시각에 같은
    줄을 다시 만난다. 다시 덧붙이면 증거가 두 벌이 되어, 손상이 두 번 난 것처럼
    읽힌다. 그렇다고 지우기 전에 격리한다는 규칙은 그대로다.
    """
    import os as _os

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _with_a_torn_line(path, now)
    clock = Clock()
    log = FileAuditLog(path, retention_days=30, now=lambda: now, monotonic=clock)

    real_replace = _os.replace

    def refuse(*args, **kwargs):
        raise PermissionError("held open")

    monkeypatch.setattr(_os, "replace", refuse)
    for seq in (3, 4):
        log.record(_event(seq, now.isoformat()))
        assert log.settle()
        clock.advance(PRUNE_INTERVAL_S)
    assert log.health()["prune_failures"] == 2
    assert TORN in path.read_bytes(), "a failed replace must leave the original in place"
    assert log.quarantine_path.read_bytes() == TORN, "the retry quarantined the bytes again"

    monkeypatch.setattr(_os, "replace", real_replace)
    log.record(_event(5, now.isoformat()))
    assert log.settle()
    assert TORN not in path.read_bytes()
    assert log.quarantine_path.read_bytes() == TORN
    assert [event.seq for event in log.history()] == [1, 3, 4, 5]


def test_a_new_corrupt_line_after_a_failed_replace_is_still_quarantined(tmp_path, monkeypatch):
    """중복을 막는 표시는 이미 격리한 그 줄만 건너뛴다. 그 사이 새로 생긴 깨진
    줄까지 건너뛰면, 다음 바꿔 끼우기가 격리하지 않은 바이트를 지운다.
    """
    import os as _os

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _with_a_torn_line(path, now)
    clock = Clock()
    log = FileAuditLog(path, retention_days=30, now=lambda: now, monotonic=clock)

    real_replace = _os.replace
    monkeypatch.setattr(_os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("held open")))
    log.record(_event(3, now.isoformat()))
    assert log.settle()

    second = b"not json at all"
    with path.open("ab") as handle:
        handle.write(second + b"\n")
    monkeypatch.setattr(_os, "replace", real_replace)
    clock.advance(PRUNE_INTERVAL_S)
    log.record(_event(4, now.isoformat()))
    assert log.settle()

    assert log.quarantine_path.read_bytes() == TORN + second + b"\n"
    assert second not in path.read_bytes()


def test_a_worker_that_cannot_start_is_counted_and_does_not_wedge_pruning(tmp_path, monkeypatch):
    """`Thread.start()` 는 "can't start new thread" 를 던질 수 있다. 그것이
    `record()` 밖으로 나가면 무던짐 약속이 깨지고, 시작도 안 한 스레드가 칸에
    남으면 정리는 다시는 돌지 않으며 `settle()` 은 끝나지 않는다.
    """
    import threading

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _stale_heavy_log(path, now, lines=3)
    clock = Clock()
    log = FileAuditLog(path, retention_days=30, now=lambda: now, monotonic=clock)

    def refuse(self):
        raise RuntimeError("can't start new thread")

    real_start = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", refuse)
    log.record(_event(2, now.isoformat()))            # 던지지 않는다
    monkeypatch.setattr(threading.Thread, "start", real_start)

    assert log.settle(timeout=0), "a never-started worker is still holding the slot"
    health = log.health()
    assert health["prune_failures"] == 1
    assert health["last_prune_error"].startswith("worker start: RuntimeError")
    assert health["write_failures_total"] == 0, "the event itself was recorded"
    assert 2 in [event.seq for event in log.history()]

    clock.advance(PRUNE_INTERVAL_S)
    log.record(_event(3, now.isoformat()))
    assert log.settle()
    stale = _event(0, (now - timedelta(days=40)).isoformat()).model_dump_json()
    assert stale not in path.read_text(encoding="utf-8"), "pruning never ran again"


def test_a_directory_sync_failure_after_the_replace_is_not_a_prune_failure(tmp_path, monkeypatch):
    """이름 바꾸기가 끝났으면 정리는 된 것이다. 그 뒤 디렉터리 fsync 가 실패했다고
    정리 실패로 세면 운영자는 30 일보다 길게 자라는 파일을 찾아 헤맨다.
    따로 센다.
    """
    import core_events.events.audit as audit

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _stale_heavy_log(path, now, lines=3)
    log = FileAuditLog(path, retention_days=30, now=lambda: now)

    def refuse(directory):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(audit, "_fsync_directory", refuse)
    log.record(_event(2, now.isoformat()))
    assert log.settle()

    health = log.health()
    assert health["prune_failures"] == 0 and health["last_prune_error"] is None
    assert health["dir_sync_failures"] == 1
    assert "Input/output error" in health["last_dir_sync_error"]
    stale = _event(0, (now - timedelta(days=40)).isoformat()).model_dump_json()
    assert stale not in path.read_text(encoding="utf-8"), "the prune itself did happen"


@pytest.mark.parametrize("tamper", ["delete", "truncate", "rewrite"])
def test_a_quarantine_file_removed_before_the_retry_is_written_again(tmp_path, monkeypatch, tamper):
    """중복을 막는 표시는 "그 바이트가 격리 파일에 있다"를 뜻한다. 운영자가 그
    사이 격리 파일을 지우거나 비웠다면 표시는 거짓이 되고, 그것을 믿고 건너뛴
    재시도는 격리하지 않은 증거를 본 파일에서 지운다.
    """
    import os as _os

    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    _with_a_torn_line(path, now)
    clock = Clock()
    log = FileAuditLog(path, retention_days=30, now=lambda: now, monotonic=clock)

    real_replace = _os.replace
    monkeypatch.setattr(_os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("held open")))
    log.record(_event(3, now.isoformat()))
    assert log.settle()
    assert log.quarantine_path.read_bytes() == TORN

    if tamper == "delete":
        log.quarantine_path.unlink()
    elif tamper == "truncate":
        log.quarantine_path.write_bytes(b"")
    else:
        # 같은 inode, 같은 크기, 다른 바이트 — Linux 가 지운 파일의 inode 번호를
        # 새 파일에 다시 줄 때와 신원·크기가 똑같이 보인다.
        log.quarantine_path.write_bytes(b"Z" * len(TORN))
    monkeypatch.setattr(_os, "replace", real_replace)
    clock.advance(PRUNE_INTERVAL_S)
    log.record(_event(4, now.isoformat()))
    assert log.settle()

    assert TORN not in path.read_bytes()
    assert TORN in log.quarantine_path.read_bytes(), "the evidence is in neither file"
