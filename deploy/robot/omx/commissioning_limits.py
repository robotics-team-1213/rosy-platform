#!/usr/bin/env python3
"""Reduce finite OMX commissioning caps with torque OFF; never enable or move it.

PWM/Current Limit are persistent EEPROM settings. Successful changes remain in
place. An uncertain write stops the procedure without retries or rollback.
This is an exclusive configuration procedure, not an actuator owner/runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from register_probe import open_readonly_port, read_motors, read_packet_allowed, readonly_writer

CAPS = {"pwm_limit_raw": (36, 2, 885), "current_limit_raw": (38, 2, 1750),
        "profile_acceleration_raw": (108, 4, 32767), "profile_velocity_raw": (112, 4, 32767)}
# The resting caps joint_tune.BASELINE and record_session require, plus the 1/1 profiles joint_tune starts from.
BASELINE = {"pwm_limit_raw": 20, "current_limit_raw": 50,
            "profile_acceleration_raw": 1, "profile_velocity_raw": 1}
DYNAMIC = {"position_raw", "velocity_raw", "goal_position_raw", "voltage_raw", "temperature"}


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: expected integer in {low}..{high}")
    return value


def validate_motors(rows):
    if not isinstance(rows, list) or [r.get("id") for r in rows] != list(range(11, 17)):
        raise ValueError("expected ordered follower IDs 11..16")
    for row in rows:
        motor = row["id"]
        if (row.get("model_number") != (1060 if motor < 14 else 1200)
                or type(row.get("torque_enabled")) is not int or row["torque_enabled"] != 0
                or type(row.get("hardware_error")) is not int or row["hardware_error"] != 0
                or row.get("operating_mode") != (4 if motor < 16 else 5)
                or row.get("drive_mode") != 0):
            raise ValueError(f"motor {motor}: identity/mode/torque/error precondition failed")
        integer(row.get("velocity_limit_raw"), 1, 32767, "velocity_limit_raw")
        for field, (_, _, maximum) in CAPS.items():
            if field == "current_limit_raw" and motor < 14:
                if row.get(field) is not None:
                    raise ValueError("XL430 has no Current Limit register")
                continue
            integer(row.get(field), 0 if field.startswith("profile_") else 1, maximum, field)


def plan_limits(rows, limits):
    """Produce only non-increasing cap writes; zero profile means unlimited."""
    validate_motors(rows)
    if not isinstance(limits, dict) or set(limits) != set(CAPS):
        raise ValueError("explicit PWM/current/profile acceleration/profile velocity caps required")
    for field, (_, _, maximum) in CAPS.items():
        integer(limits[field], 1, maximum, field)
    operations = []
    for row in rows:
        for field, (address, size, _) in CAPS.items():
            if field == "current_limit_raw" and row["id"] < 14:
                continue
            old, value = row[field], limits[field]
            if old != 0 and value > old:
                raise ValueError(f"motor {row['id']}: increasing {field} is prohibited")
            if field == "profile_velocity_raw" and value > row["velocity_limit_raw"]:
                raise ValueError("profile velocity must fit the existing velocity limit")
            if old != value:
                operations.append(dict(id=row["id"], field=field, address=address,
                                       size=size, before=old, value=value))
    return operations


def one_write_guard(send, operation, *, deadline=None):
    """Allow existing PING/READ packets and exactly one matching unicast write."""
    motor = integer(operation.get("id"), 11, 16, "write motor")
    allowed = {address: (size, maximum) for address, size, maximum in CAPS.values()}
    address = operation.get("address")
    if type(address) is not int or address not in allowed or (address == 38 and motor < 14):
        raise ValueError("unsupported cap register for this motor")
    size, maximum = allowed[address]
    if type(operation.get("size")) is not int or operation["size"] != size:
        raise ValueError("incorrect cap register width")
    value = integer(operation.get("value"), 1, maximum, "cap write value")
    expected = address.to_bytes(2, "little") + value.to_bytes(size, "little")
    used = False

    def guarded(data):
        nonlocal used
        packet = bytes(data)
        if read_packet_allowed(packet):
            return send(packet)
        if (used or len(packet) != 12 + size or packet[:4] != b"\xff\xff\xfd\x00"
                or packet[4] != motor or packet[7] != 3
                or int.from_bytes(packet[5:7], "little") != len(packet) - 7
                or packet[8:-2] != expected):
            raise ValueError("only one exact planned cap write is permitted")
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError("commissioning deadline exceeded at serial write")
        used = True  # A failed/short transport write is still an uncertain attempt.
        return send(packet)

    return guarded


def sdk_write(port, motor, address, size, value):
    from dynamixel_sdk import PacketHandler
    sdk = PacketHandler(2.0)
    if size == 2:
        return sdk.write2ByteTxRx(port, motor, address, value)
    if size == 4:
        return sdk.write4ByteTxRx(port, motor, address, value)
    raise ValueError("unsupported cap size")


def configure_limits(port, limits, record, *, read=read_motors, write=sdk_write):
    """Call only under exclusive ownership; durable record failure prevents next write."""
    send = port.ser.write if hasattr(port, "ser") else port.writePort
    port.writePort = readonly_writer(send)
    uncertain = None
    verified = []
    deadline = time.monotonic() + 15
    try:
        before = read(port)
        record(dict(event="before", motors=before, limits=limits, motion_admitted=False))
        plan = plan_limits(before, limits)
        expected = {row["id"]: dict(row) for row in before}
        latest = before
        for operation in plan:
            if time.monotonic() >= deadline:
                raise RuntimeError("commissioning deadline exceeded; no further writes")
            validate_motors(latest)
            record(dict(event="write_intent", operation=operation))
            if time.monotonic() >= deadline:
                raise RuntimeError("commissioning deadline exceeded after durable intent")
            uncertain = operation
            port.writePort = one_write_guard(send, operation, deadline=deadline)
            comm, error = write(port, operation["id"], operation["address"],
                                operation["size"], operation["value"])
            port.writePort = readonly_writer(send)
            if comm != 0 or error != 0:
                raise RuntimeError(f"cap write acknowledgment failed: {comm}, {error}")
            latest = read(port)
            validate_motors(latest)
            expected[operation["id"]][operation["field"]] = operation["value"]
            for row in latest:
                for field, value in expected[row["id"]].items():
                    if field not in DYNAMIC and row.get(field) != value:
                        raise RuntimeError(f"unexpected readback: motor {row['id']} {field}")
            record(dict(event="verified", operation=operation, motors=latest))
            verified.append(operation)
            uncertain = None
        receipt = dict(event="complete", configuration_verified=True, verified=verified,
                       uncertain_write=None, before=before, after=latest,
                       scope="torque_off_configuration_not_motion", motion_admitted=False,
                       physical_stop_verified=False, demonstrations=0)
        record(receipt)
        return receipt
    except Exception as error:
        port.writePort = readonly_writer(send)
        after, read_error = None, None
        try:
            after = read(port)
        except Exception as failure:
            read_error = repr(failure)
        record(dict(event="failed", configuration_verified=False, verified=verified,
                    uncertain_write=uncertain, error=repr(error), after=after,
                    after_read_error=read_error, motion_admitted=False))
        raise
    finally:
        port.writePort = readonly_writer(send)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--limits", type=Path)
    source.add_argument("--baseline", action="store_true",
                        help="the resting caps a session left raised must return to (PWM 20, Current 50, profiles 1)")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("run as the unprivileged commissioning device owner")
    if args.baseline:
        raw = json.dumps(BASELINE).encode()
    else:
        raw = args.limits.read_bytes()
        if len(raw) > 4096 or args.limits.resolve().is_relative_to(args.output.resolve()):
            parser.error("bounded external limits input required")
    limits = json.loads(raw, object_pairs_hook=unique_object)
    args.output.mkdir()  # Never overwrite or resume an uncertain procedure.
    (args.output / "limits.json").write_bytes(raw)
    events = []
    failure = None
    with (args.output / "events.jsonl").open("x", encoding="utf-8") as journal:
        def record(event):
            event = dict(event, recorded_ns=time.time_ns())
            journal.write(json.dumps(event, allow_nan=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            events.append(event)

        try:
            with open_readonly_port(args.device) as port:
                configure_limits(port, limits, record)
        except Exception as error:
            failure = repr(error)
    report = dict(device=args.device, motion_admitted=False, demonstrations=0, error=failure,
                  configuration_verified=bool(events and events[-1]["event"] == "complete"),
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  reader_sha256=hashlib.sha256(Path(__file__).with_name("register_probe.py").read_bytes()).hexdigest(),
                  limits_sha256=hashlib.sha256(raw).hexdigest(),
                  journal_sha256=hashlib.sha256((args.output / "events.jsonl").read_bytes()).hexdigest())
    (args.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["configuration_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
