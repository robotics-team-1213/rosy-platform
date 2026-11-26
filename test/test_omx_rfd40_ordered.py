"""Field producer FIFO, restart boundaries and live inventory evidence."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from rfd40_cell import Reader  # noqa: E402
from rfd40_ordered_outbox import Capture, IntakeReading, drain, open_spool  # noqa: E402

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
HEADER = b"Command:inventory ,Status:OK,EPCId:,RSSI:,TagSeenCount:\r\n"
START = b"Notification:StartOperation\r\n"
STOP = b"Notification:StopOperation\r\n"
ACK = b"Command:abort,Status:OK\r\n"


def capture(db, ticks, seconds):
    return Capture(db, monotonic=iter(ticks).__next__, utc=iter(T + timedelta(seconds=n) for n in seconds).__next__)


def queued(db):
    return [IntakeReading.model_validate_json(body) for body, in db.execute("SELECT payload FROM pending ORDER BY seq")]


def test_offline_read_precedes_closure_after_restart(tmp_path):
    path = tmp_path / "queue"
    with closing(open_spool(path, "reader-1")) as db:
        run = capture(db, [0, 1, 2], [0, 1, 2])
        run.record("432D31", triggered=True, max_interval=30)
        run.record(None, triggered=True, max_interval=30)
        before = queued(db)
        assert [i.state for i in before] == ["read", "closed_through", "unreadable", "closed_through"]
        assert [i.reader_seq for i in before] == [1, 2, 3, 4]
        assert before[-1].coverage_start == T
        link = Mock()
        link.post_intake_reading.side_effect = TimeoutError("ack lost")
        with pytest.raises(TimeoutError):
            drain(db, link, Event())
        link.post_intake_reading.assert_called_once_with(before[0])
    with closing(open_spool(path, "reader-1")) as db:
        run = capture(db, [0, 1], [7, 8])
        run.record(None, triggered=False, max_interval=30)
        all_items = queued(db)
        assert all_items[:4] == before
        assert all_items[-1].coverage_start == T + timedelta(seconds=7)
        link = Mock()
        link.post_intake_reading.return_value = {"observation_ref": "another"}
        with pytest.raises(ValueError, match="original observation"):
            drain(db, link, Event())
        assert queued(db) == all_items
        link.reset_mock()
        link.post_intake_reading.side_effect = lambda i: {"observation_ref": i.observation_ref}
        drain(db, link, Event())
        assert [call.args[0] for call in link.post_intake_reading.call_args_list] == all_items
        assert not queued(db)
    with pytest.raises(ValueError, match="epoch"):
        open_spool(path, "replacement")


def test_clock_rollback_stalls_and_reconnect_never_close_a_gap(tmp_path):
    with closing(open_spool(tmp_path / "fifo", "reader-2")) as db:
        run = capture(db, [0, 5, 6, 12, 13, 80, 82], [0, 5, 0, 6, 7, 74, 76])
        for _ in range(6):
            run.record("432D31", triggered=True, max_interval=30)
        items = [i for i in queued(db) if i.state == "closed_through"]
        assert [(i.coverage_start, i.observed_at) for i in items] == [
            (T, T+timedelta(seconds=5)), (T+timedelta(seconds=6), T+timedelta(seconds=6)),
            (T+timedelta(seconds=6), T+timedelta(seconds=7)),
            (T+timedelta(seconds=76), T+timedelta(seconds=76))]
        assert db.execute("SELECT COUNT(*) FROM clock_quarantine").fetchone() == (2,)
        # Even a process restart cannot backdate a fresh interval across a durable watermark.
        restarted = capture(db, [0, 4], [74, 78])
        restarted.record(None, triggered=False, max_interval=30)
        assert queued(db)[-1].coverage_start == T + timedelta(seconds=78)


@pytest.mark.parametrize(("inventory", "abort"), [
    (HEADER + START, ACK), (HEADER, START + ACK), (HEADER + STOP, ACK),
    (HEADER + START + STOP + START, ACK), (HEADER.replace(b"Status:OK", b"Status:ERR"), ACK),
])
def test_incomplete_or_unhealthy_inventory_cannot_close_coverage(inventory, abort):
    reader = Reader(None)
    reader.exchange = Mock(side_effect=[inventory, abort])
    with pytest.raises(ConnectionError):
        reader.scan(20, require_coverage=True)


def test_acknowledged_armed_idle_versus_completed_empty_trigger():
    reader = Reader(None)
    reader.exchange = Mock(side_effect=[HEADER, ACK, HEADER + START + STOP, ACK])
    assert not reader.scan(20, require_coverage=True)
    assert reader.scan(20, require_coverage=True)
