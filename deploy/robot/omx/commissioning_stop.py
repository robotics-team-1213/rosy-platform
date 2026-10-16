#!/usr/bin/env python3
"""Exclusive commissioning fallback: write only torque OFF, never goals or ON.

The controller must have released the confirmed device before this runs. This
is a stop-only recovery tool, not an accepted field E-stop or actuator owner.
Readback of Torque Enable=0 does not prove physical standstill or load support.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from register_probe import open_readonly_port, read_motors, read_packet_allowed, readonly_writer


def validate_ids(ids):
    if (not isinstance(ids, (list, tuple)) or not ids
            or any(type(motor) is not int or motor not in range(11, 17) for motor in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("explicit unique confirmed follower IDs 11..16 required")
    return list(ids)


def off_writer(send, motor):
    """Allow existing reads and at most one exact OFF packet for this motor."""
    validate_ids([motor])
    used = False

    def guarded(data):
        nonlocal used
        packet = bytes(data)
        if read_packet_allowed(packet):
            return send(packet)
        if (used or len(packet) != 13 or packet[:4] != b"\xff\xff\xfd\x00"
                or packet[4] != motor or packet[5:8] != b"\x06\x00\x03"
                or packet[8:-2] != b"\x40\x00\x00"):
            raise ValueError("only one exact torque-OFF write is permitted")
        used = True  # A short/failed transmission is uncertain, never retried.
        return send(packet)

    return guarded


def sdk_off(port, motor):
    from dynamixel_sdk import PacketHandler
    return PacketHandler(2.0).write1ByteTxRx(port, motor, 64, 0)


def disable_torque(port, ids, *, read=read_motors, write=sdk_off):
    """Attempt each selected OFF once, then read all motors; no logging before stop."""
    ids = validate_ids(ids)
    send = port.ser.write if hasattr(port, "ser") else port.writePort
    attempts = []
    started = time.monotonic()
    try:
        for motor in ids:
            row = dict(id=motor, address=64, value=0, acknowledged=False)
            port.writePort = off_writer(send, motor)
            try:
                comm, error = write(port, motor)
                row.update(comm=comm, error=error, acknowledged=comm == 0 and error == 0)
            except Exception as failure:
                row["exception"] = repr(failure)
            attempts.append(row)
        port.writePort = readonly_writer(send)
        motors, read_error, off = None, None, False
        try:
            motors = read(port)
            if (not isinstance(motors, list) or [r["id"] for r in motors] != list(range(11, 17))
                    or any(r["model_number"] != (1060 if r["id"] < 14 else 1200) for r in motors)):
                raise ValueError("readback follower identity mismatch")
            off = all(type(r["torque_enabled"]) is int and r["torque_enabled"] == 0
                      and type(r["hardware_error"]) is int and r["hardware_error"] == 0
                      for r in motors if r["id"] in ids)
        except Exception as failure:
            read_error = repr(failure)
        return dict(scope="commissioning_torque_off_only", selected_ids=ids, attempts=attempts,
                    motors=motors, read_error=read_error, torque_off_readback=off,
                    stop_verified=off and all(row["acknowledged"] for row in attempts),
                    elapsed_s=time.monotonic() - started, motion_admitted=False,
                    physical_stop_verified=False, demonstrations=0)
    finally:
        port.writePort = readonly_writer(send)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--expected-device-id", required=True, type=int)
    parser.add_argument("--ids", required=True, type=int, nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("run as the unprivileged commissioning device owner")
    report = dict(scope="commissioning_torque_off_only", stop_verified=False,
                  motion_admitted=False, physical_stop_verified=False, demonstrations=0)
    try:
        ids = validate_ids(args.ids)
        with open_readonly_port(args.device) as port:
            if os.fstat(port.ser.fileno()).st_rdev != args.expected_device_id:
                raise ValueError("opened device identity does not match confirmed device")
            report.update(disable_torque(port, ids))
    except Exception as failure:
        report["error"] = repr(failure)
    # A full/unwritable filesystem must not suppress the electrical stop attempt.
    # Never replace an earlier record, including when OFF could not be verified.
    try:
        args.output.mkdir()
        report.update(source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      reader_sha256=hashlib.sha256(Path(__file__).with_name("register_probe.py").read_bytes()).hexdigest(),
                      recorded_ns=time.time_ns())
        with (args.output / "receipt.json").open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, allow_nan=False, indent=2) + "\n")
            output.flush()
            os.fsync(output.fileno())
    except Exception as failure:
        report["record_error"] = repr(failure)
    print(json.dumps(report, allow_nan=False))
    return 0 if report["stop_verified"] and "record_error" not in report else 2


if __name__ == "__main__":
    raise SystemExit(main())
