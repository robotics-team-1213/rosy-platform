"""The owner reports bounded trace segments after commands, without publishing trace contents or paths."""
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(ROOT))
from chunk_runner_run import Runner, NAMES  # noqa: E402
from chunk_runner import bind_trace_source  # noqa: E402


class Robot:
    def get_observation(self):
        return {name: 0.0 for name in NAMES}


def _runner(path):
    rows = []
    runner = Runner(Robot(), {"chunks": {}}, fps=30, status=rows.append,
                    operating_context={"session_id": "owner-session"})
    runner.target = [0.0] * 6
    runner.trace_file = path.open("a", encoding="utf-8")
    runner.trace_source = path.name
    runner.trace_cursor = 0
    return runner, rows


def test_owner_status_binds_one_trace_segment_without_exposing_path_or_bytes(tmp_path):
    path = tmp_path / "trace-arm_b-20261113-220000.jsonl"
    runner, rows = _runner(path)
    try:
        sample = b'{"t":1,"present":[0,0,0,0,0,0],"pwm":{}}\n'
        runner.trace_file.write(sample.decode())
        runner.report(command="run lift_pick", ok=True)
        receipt = rows[-1]["trace_receipt"]
        written = path.read_bytes()
        assert receipt["source"] == path.name and receipt["start"] == 0
        assert receipt["end"] == len(written) and receipt["sha256"] == hashlib.sha256(written).hexdigest()
        assert receipt["session_id"] == "owner-session" and receipt["library_sha256"] == rows[-1]["library_sha256"]
        assert receipt["sequence"] == 1 and receipt["command"] == "run lift_pick"
        assert str(tmp_path) not in str(receipt) and "present" not in str(receipt)
        assert len(json.dumps(receipt)) < 512
    finally:
        runner.trace_file.close()


def test_owner_trace_receipt_rejects_rotated_or_truncated_source(tmp_path, monkeypatch):
    path = tmp_path / "trace-arm_b-20261113-220000.jsonl"
    runner, rows = _runner(path)
    try:
        runner.trace_file.write('{"t":1}\n')
        runner.report(command="state", ok=True)
        path.write_text("")
        runner.report(command="state", ok=True)
        assert rows[-1]["trace_receipt"]["status"] == "truncated"
    finally:
        runner.trace_file.close()
    runner, rows = _runner(path)
    try:
        opened = os.fstat(runner.trace_file.fileno())
        original_stat = Path.stat
        def rotated(self, *args, **kwargs):
            return (SimpleNamespace(st_dev=opened.st_dev, st_ino=opened.st_ino + 1)
                    if self == path else original_stat(self, *args, **kwargs))
        with monkeypatch.context() as patch:
            patch.setattr(Path, "stat", rotated)
            runner.report(command="state", ok=True)
        assert rows[-1]["trace_receipt"]["status"] == "rotated"
    finally:
        runner.trace_file.close()


def test_owner_binds_only_trace_beside_its_fifo(tmp_path):
    runner = Runner(Robot(), {"chunks": {}}, fps=30, status=lambda _: None,
                    operating_context={"session_id": "s"})
    outside = tmp_path / "other"
    outside.mkdir()
    with (outside / "trace.jsonl").open("a") as stream:
        assert bind_trace_source(runner, outside / "trace.jsonl", stream, tmp_path / "chunk-io-b") is False
        assert runner.trace_file is None
    with (tmp_path / "trace.jsonl").open("a") as stream:
        assert bind_trace_source(runner, tmp_path / "trace.jsonl", stream, tmp_path / "chunk-io-b") is True
        assert runner.trace_file is stream and runner.trace_source == "trace.jsonl"


def test_fault_and_human_hold_reports_skip_trace_hashing(tmp_path, monkeypatch):
    path = tmp_path / "trace-arm_b.jsonl"
    runner, rows = _runner(path)
    try:
        runner.trace_file.write('{"t":1}\n')
        original_open = Path.open

        def no_reader(self, *args, **kwargs):
            if self == path and args and args[0] == "rb":
                raise AssertionError("fault report read the trace")
            return original_open(self, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", no_reader)
            runner.report(command="run lift_pick", ok=False)
            runner.report(command="human-hold", ok=True)
        assert [row["trace_receipt"]["status"] for row in rows] == ["aborted", "aborted"]
        assert runner.trace_cursor == 0 and runner.trace_sequence == 0
    finally:
        runner.trace_file.close()


def test_owner_receipt_refuses_more_than_one_megabyte(tmp_path):
    path = tmp_path / "trace-arm_b.jsonl"
    runner, rows = _runner(path)
    try:
        runner.trace_file.write("x" * (1024 * 1024 + 1))
        runner.report(command="state", ok=True)
        assert rows[-1]["trace_receipt"]["status"] == "segment_too_large"
        assert runner.trace_cursor == 0 and runner.trace_sequence == 0
    finally:
        runner.trace_file.close()
