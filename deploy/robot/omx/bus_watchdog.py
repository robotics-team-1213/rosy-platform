"""The motors' own link check (Dynamixel X Bus Watchdog, RAM address 98, 20 ms units): with no instruction packet for
that long, a motor stops its motion by itself. 2026-10-31: the site PC dropped off the network mid-carry; folding and
torque OFF live in the runner on that PC, so with the PC gone nothing would stop a moving arm.

The runner reads or writes every motor each tick, so a running session never trips it. A tripped watchdog (value -1)
refuses new goals until it is written 0, so every session start writes 0 and then the period. safety.bus_watchdog_ms
0 leaves it off: what an X motor does on the trip in position mode is not yet observed on arm S.
"""
from __future__ import annotations

ADDRESS, UNIT_MS = 98, 20


def units(ms: float) -> int:
    """The register value for a period in ms (1..127 units of 20 ms); 0 = off."""
    if ms <= 0:
        return 0
    return max(1, min(127, round(ms / UNIT_MS)))


def arm(bus, ms: float, write=None) -> dict:
    """Clear any trip and set the period on every motor of `bus`; {name: value}. Raises on a failed write so a
    session that asked for the watchdog never starts without it."""
    value = units(ms)
    if value == 0:
        return {}
    write = write or (lambda motor_id, v: bus.packet_handler.write1ByteTxRx(bus.port_handler, motor_id, ADDRESS, v))
    out = {}
    for name, motor in bus.motors.items():
        for v in (0, value):  # 0 first: a tripped watchdog (-1) is cleared only by writing 0
            result, error = write(motor.id, v)[-2:]
            if result != 0 or error != 0:
                raise ValueError(f"{name}: bus watchdog write {v} failed (result {result}, error {error})")
        out[name] = value
    return out
