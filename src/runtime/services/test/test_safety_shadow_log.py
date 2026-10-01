"""D-400 shadow verdict log: counters, verdict-keyed events, 1 Hz repeat and 0.2 s rate caps."""

import pytest

from core_features.safety.shadow import ShadowLog, ShadowVerdict


def _v(t, verdict, reason="", eval_ms=1.0, source="navigation"):
    return ShadowVerdict(t=t, source=source, commanded=(0.1, 0.0), output=(0.1, 0.0),
                         verdict=verdict, limited=(0.0, 0.0) if verdict == "stop" else (0.1, 0.0),
                         reason=reason, eval_ms=eval_ms)


def test_counts_every_verdict_and_remembers_the_last_stop():
    log = ShadowLog()
    for v in (_v(1.0, "allow"), _v(1.1, "limit"), _v(1.2, "stop", "pickup"), _v(1.3, "unavailable", "policy_failed")):
        log.record(v)

    snap = log.snapshot()
    assert snap["counts"] == {"allow": 1, "limit": 1, "stop": 1, "unavailable": 1}
    assert snap["last_stop"] == {"t": 1.2, "reason": "pickup", "source": "navigation"}
    assert snap["last_unavailable"] == {"t": 1.3, "reason": "policy_failed", "source": "navigation"}


def test_events_on_transitions_only_and_repeats_at_most_once_per_second():
    log = ShadowLog()
    log.record(_v(0.00, "allow"))
    log.record(_v(0.30, "stop", "pickup"))     # transition -> event
    log.record(_v(0.40, "stop", "pickup"))     # repeat within 1 s -> none
    log.record(_v(1.40, "stop", "pickup"))     # repeat after 1 s -> event
    log.record(_v(1.70, "allow"))              # transition -> event

    events = log.drain()
    assert [e["verdict"] for e in events] == ["allow", "stop", "stop", "allow"]
    assert log.drain() == []                   # drained once


def test_eval_ms_percentiles_use_a_bounded_window():
    log = ShadowLog(window=4)
    for i, ms in enumerate([9.0, 9.0, 1.0, 2.0, 3.0, 4.0]):
        log.record(_v(float(i), "allow", eval_ms=ms))

    snap = log.snapshot()
    assert snap["eval_ms"] == {"p50": 3.0, "p99": 4.0, "n": 4}


def test_event_payload_is_flat_and_rounded():
    log = ShadowLog()
    log.record(ShadowVerdict(t=2.0004, source="manual", commanded=(0.123456, -0.5), output=(0.123456, -0.5),
                             verdict="limit", limited=(0.0123456, -0.5), reason="motion_limited", eval_ms=0.4))

    (event,) = log.drain()
    assert event == {"verdict": "limit", "reason": "motion_limited", "source": "manual", "t": 2.0,
                     "commanded": [0.1235, -0.5], "output": [0.1235, -0.5],
                     "limited": [0.0123, -0.5], "suppressed": 0}


def test_empty_log_snapshot():
    assert ShadowLog().snapshot() == {
        "counts": {"allow": 0, "limit": 0, "stop": 0, "unavailable": 0},
        "last_stop": None,
        "last_unavailable": None,
        "eval_ms": {"p50": None, "p99": None, "n": 0},
        "dropped_events": 0,
        "suppressed_events": 0,
    }


def test_pending_events_are_bounded_and_drop_the_oldest():
    log = ShadowLog()
    for i in range(1000):
        log.record(_v(i * 0.25, "allow" if i % 2 == 0 else "stop", "" if i % 2 == 0 else "pickup"))

    events = log.drain()
    assert len(events) == 64
    assert events[0]["t"] == 936 * 0.25          # oldest dropped
    assert events[-1]["t"] == 999 * 0.25
    assert events[-1]["verdict"] == "stop"
    assert log.snapshot()["dropped_events"] == 1000 - 64


def test_reason_change_within_a_second_is_not_an_event():
    log = ShadowLog()
    log.record(_v(0.0, "stop", "pickup"))
    log.record(_v(0.5, "stop", "cliff"))

    assert [e["reason"] for e in log.drain()] == ["pickup"]
    assert log.snapshot()["last_stop"]["reason"] == "cliff"


def test_repeat_is_measured_from_the_last_emitted_event():
    log = ShadowLog()
    log.record(_v(0.0, "allow"))
    log.record(_v(0.5, "stop", "pickup"))      # event
    log.record(_v(1.2, "stop", "pickup"))      # 0.7 s since last emit -> none
    log.record(_v(1.6, "stop", "pickup"))      # 1.1 s -> event

    assert [e["t"] for e in log.drain()] == [0.0, 0.5, 1.6]


def test_fast_alternation_is_rate_capped_and_accounted():
    log = ShadowLog()
    for i in range(100):                        # 50 Hz for 2 s
        log.record(_v(i * 0.02, "allow" if i % 2 == 0 else "limit"))

    events = log.drain()
    assert 2 <= len(events) <= 11
    total = log.snapshot()["suppressed_events"]
    assert total > 0
    assert sum(e["suppressed"] for e in events) + log._suppressed == total


def test_suppressed_counts_changes_not_records():
    log = ShadowLog()
    log.record(_v(0.00, "allow"))
    log.record(_v(0.10, "stop", "pickup"))     # change, too soon -> suppressed
    log.record(_v(0.15, "allow"))
    log.record(_v(1.00, "allow"))              # repeat after 1 s -> event

    assert [e["suppressed"] for e in log.drain()] == [0, 1]

    held = ShadowLog()
    held.record(_v(0.0, "allow"))
    for i in range(1, 10):                      # one held stop, nine records
        held.record(_v(i * 0.02, "stop", "pickup"))
    assert held.snapshot()["suppressed_events"] == 1


def test_clock_stepping_back_is_treated_as_a_first_record():
    log = ShadowLog()
    log.record(_v(10.0, "allow"))
    log.record(_v(5.0, "stop", "pickup"))

    assert [e["verdict"] for e in log.drain()] == ["allow", "stop"]


def test_suppressed_verdict_still_current_is_emitted_later():
    log = ShadowLog()
    log.record(_v(0.00, "allow"))
    log.record(_v(0.05, "limit"))              # too soon -> suppressed
    assert [e["verdict"] for e in log.drain()] == ["allow"]
    log.record(_v(0.30, "limit"))              # still current, >= 0.2 s -> emitted

    (event,) = log.drain()
    assert (event["verdict"], event["suppressed"]) == ("limit", 1)
    assert log.snapshot()["suppressed_events"] == 1


def test_window_must_be_positive():
    with pytest.raises(ValueError, match="window must be >= 1"):
        ShadowLog(window=0)
