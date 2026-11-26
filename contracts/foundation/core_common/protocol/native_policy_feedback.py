"""Validate bounded native B motor telemetry without inferring motion or HOLD authority."""
MAX_AGE_NS = 2_000_000_000
_HEADER = {"arm_id": "arm_b", "basis": "readonly_motor_registers"}
_FIELDS = {"id", "model_number", "position_raw", "torque_enabled", "hardware_error"}


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def native_policy_feedback(value, *, now_ns=None, transit_ns=None):
    """CORE dates the sweep on its host clock; Fleet conservatively adds the whole HTTPS RTT."""
    unavailable = {**_HEADER, "state": "unavailable"}
    stale = {**_HEADER, "state": "stale"}
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in _HEADER.items()):
        return unavailable
    base_keys = set(_HEADER) | {"state"}
    if value.get("state") in ("stale", "unavailable"):
        return stale if set(value) == base_keys and value["state"] == "stale" else unavailable
    keys = base_keys | {"observed_at_monotonic_ns", "observed_at_unix_ns", "motors"}
    if transit_ns is not None:
        keys.add("age_ms")
    if (value.get("state") != "fresh" or set(value) != keys
            or not _integer(value["observed_at_monotonic_ns"], 1, 2**63 - 1)
            or not _integer(value["observed_at_unix_ns"], 1, 2**63 - 1)):
        return unavailable
    if transit_ns is None:
        if not _integer(now_ns, value["observed_at_monotonic_ns"], 2**63 - 1):
            return unavailable
        age = now_ns - value["observed_at_monotonic_ns"]
    else:
        if not _integer(transit_ns, 0, 2**63 - 1) or not _integer(value["age_ms"], 0, MAX_AGE_NS // 1_000_000):
            return unavailable
        age = value["age_ms"] * 1_000_000 + transit_ns
    if age > MAX_AGE_NS:
        return stale
    motors = value["motors"]
    if not isinstance(motors, list) or len(motors) != 6:
        return unavailable
    for motor_id, motor in enumerate(motors, 11):
        if (not isinstance(motor, dict) or set(motor) != _FIELDS or not _integer(motor["id"], motor_id, motor_id)
                or type(motor["model_number"]) is not int or motor["model_number"] not in (1060, 1200)
                or not _integer(motor["position_raw"], -(2**31), 2**31 - 1)
                or not _integer(motor["torque_enabled"], 0, 1)
                or not _integer(motor["hardware_error"], 0, 255)):
            return unavailable
    return {**value, "age_ms": (age + 999_999) // 1_000_000}
