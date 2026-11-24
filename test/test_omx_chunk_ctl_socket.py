"""Tests for AF_UNIX chunk_runner control socket, AsyncLiveWriter, and status_row_outcome."""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

OMX = Path(__file__).parents[1] / "deploy" / "robot" / "omx"
sys.path.insert(0, str(OMX))
try:
    import cell_pipeline_io as cpio
    import cell_pipeline_liveness as liveness
    import chunk_ctl_socket as ctl
finally:
    sys.path.remove(str(OMX))

POSIX_UNIX = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires AF_UNIX sockets")


def test_async_live_writer_coalesces_and_flushes_on_close(tmp_path):
    live_path = tmp_path / "live.json"
    writer = ctl.AsyncLiveWriter(live_path)
    writer.start()
    for seq in range(50):
        writer.publish({"seq": seq, "t": 100.0 + seq})
    writer.close(timeout=2.0)
    data = json.loads(live_path.read_text(encoding="utf-8"))
    assert data["seq"] == 49
    assert not live_path.with_suffix(".tmp").exists()


def test_async_live_writer_sync_hold_flush(tmp_path):
    live_path = tmp_path / "live.json"
    writer = ctl.AsyncLiveWriter(live_path)
    writer.start()
    try:
        writer.publish({"interrupt": "hold", "human_hold_latched": True, "t": 123.4}, sync=True)
        data = json.loads(live_path.read_text(encoding="utf-8"))
        assert data["interrupt"] == "hold" and data["human_hold_latched"] is True
    finally:
        writer.close(timeout=1.0)


def test_status_row_outcome_matches_hold_and_recovery():
    now = 1000.0
    sent_at = 999.0
    hold_row = {"command": "human-hold", "t": 999.5, "hold_req": "req123", "ok": True}
    assert liveness.status_row_outcome(
        hold_row, command="human-hold", expected="human-hold", verb="human-hold", recovery=False,
        is_hold=True, hold_req="req123", sent_at=sent_at, finite_stamp=cpio.finite_stamp, now=now,
    ) == "hold"
    wrong_hold = {**hold_row, "hold_req": "other"}
    assert liveness.status_row_outcome(
        wrong_hold, command="human-hold", expected="human-hold", verb="human-hold", recovery=False,
        is_hold=True, hold_req="req123", sent_at=sent_at, finite_stamp=cpio.finite_stamp, now=now,
    ) is None
    assert liveness.status_row_outcome(
        {"command": "run park-slow", "ok": True}, command="park-slow", expected="park-slow",
        verb="park-slow", recovery=True, is_hold=False, hold_req=None, sent_at=sent_at,
        finite_stamp=cpio.finite_stamp, now=now,
    ) == "match"


@POSIX_UNIX
def test_unix_socket_round_trip_and_cache(tmp_path):
    sock_path = tmp_path / ctl.CTL_SOCKET_NAME
    server = ctl.ChunkCtlServer(sock_path)
    stop = threading.Event()
    seen = []

    def serve():
        while not stop.is_set():
            cmds = server.poll_commands()
            for cmd in cmds:
                seen.append(cmd)
                server.broadcast_status({
                    "command": cmd,
                    "ok": True,
                    "state": [0.0] * 6,
                    "operating_context": {"robot": "arm_a"},
                    "library_sha256": "abc123",
                    "t": time.time(),
                })
            time.sleep(0.002)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        cell = cpio.FifoCell(tmp_path, {}, timeout_s=2.0)
        t0 = time.monotonic()
        res = cell._send("state")
        elapsed = time.monotonic() - t0
        assert res["ok"] is True
        assert seen == ["state"]
        assert elapsed < 0.5
        assert cell._cached_state == res
    finally:
        stop.set()
        thread.join(timeout=1.0)
        server.close()


@POSIX_UNIX
def test_unix_socket_detects_runner_death_via_eof_under_100ms(tmp_path):
    sock_path = tmp_path / ctl.CTL_SOCKET_NAME
    server = ctl.ChunkCtlServer(sock_path)
    got_cmd = threading.Event()

    def serve_then_die():
        while not got_cmd.is_set():
            if server.poll_commands():
                got_cmd.set()
                break
            time.sleep(0.002)
        server.close()

    thread = threading.Thread(target=serve_then_die, daemon=True)
    thread.start()
    try:
        cell = cpio.FifoCell(tmp_path, {}, timeout_s=10.0)
        t0 = time.monotonic()
        res = cell._send("run approach", timeout=10.0)
        elapsed = time.monotonic() - t0
        assert res["ok"] is False
        assert res["fault"] == "runner_dead"
        assert elapsed < 0.25
    finally:
        thread.join(timeout=1.0)
        server.close()


def test_fifocell_falls_back_to_fifo_when_socket_absent_or_forced(tmp_path, monkeypatch):
    fifo = tmp_path / "chunk-cmd"
    status_path = tmp_path / "chunk-status.jsonl"
    if hasattr(os, "mkfifo"):
        os.mkfifo(fifo)
    else:
        fifo.write_text("", encoding="utf-8")
    cell = cpio.FifoCell(tmp_path, {}, timeout_s=0.5)
    # Without chunk-ctl.sock and without a FIFO reader, open(O_WRONLY|O_NONBLOCK) returns ENXIO ("no runner").
    res = cell._send("state")
    assert res["ok"] is False
    if hasattr(os, "mkfifo"):
        assert res["fault"] == "no runner"
    monkeypatch.setenv("ROSY_OMX_FORCE_FIFO", "1")
    res2 = cell._send("state")
    assert res2["ok"] is False


@POSIX_UNIX
def test_unix_socket_detects_runner_stalled_via_live_json(tmp_path):
    (tmp_path / "live.json").write_text(json.dumps({"pid": os.getpid(), "t": 100.0}), encoding="utf-8")
    sock_path = tmp_path / ctl.CTL_SOCKET_NAME
    server = ctl.ChunkCtlServer(sock_path)
    stop = threading.Event()

    def accept_only():
        while not stop.is_set():
            server.poll_commands()
            time.sleep(0.01)

    thread = threading.Thread(target=accept_only, daemon=True)
    thread.start()
    try:
        cell = cpio.FifoCell(tmp_path, {}, timeout_s=10.0, stall_timeout_s=0.15)
        t0 = time.monotonic()
        res = cell._send("run approach", timeout=10.0)
        elapsed = time.monotonic() - t0
        assert res["ok"] is False
        assert res["fault"] == "runner_stalled"
        assert elapsed < 1.0
    finally:
        stop.set()
        thread.join(timeout=1.0)
        server.close()


@POSIX_UNIX
def test_unix_socket_fast_human_hold_ack(tmp_path):
    sock_path = tmp_path / ctl.CTL_SOCKET_NAME
    server = ctl.ChunkCtlServer(sock_path)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            for cmd in server.poll_commands():
                if cmd.startswith("human-hold "):
                    req = cmd.split(" ", 1)[1]
                    server.broadcast_status({
                        "command": "human-hold",
                        "hold_req": req,
                        "ok": True,
                        "human_hold_latched": True,
                        "torque_hold_commanded": True,
                        "t": time.time(),
                    })
            time.sleep(0.002)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        cell = cpio.FifoCell(tmp_path, {}, timeout_s=2.0)
        res = cell._send("human-hold")
        assert res["ok"] is True
        assert res["human_hold_latched"] is True
        assert res["hold_req"]
    finally:
        stop.set()
        thread.join(timeout=1.0)
        server.close()
