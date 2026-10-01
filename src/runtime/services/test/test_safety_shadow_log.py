"""D-400 shadow verdict log: counters, transition events, 1 Hz repeat cap."""

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
    log.record(_v(0.02, "stop", "pickup"))     # transition -> event
    log.record(_v(0.04, "stop", "pickup"))     # repeat within 1 s -> none
    log.record(_v(1.10, "stop", "pickup"))     # repeat after 1 s -> event
    log.record(_v(1.12, "allow"))              # transition -> event

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
    log.record(ShadowVerdict(t=2.0, source="manual", commanded=(0.123456, -0.5), output=(0.123456, -0.5),
                             verdict="limit", limited=(0.0123456, -0.5), reason="motion_limited", eval_ms=0.4))

    (event,) = log.drain()
    assert event == {"verdict": "limit", "reason": "motion_limited", "source": "manual",
                     "commanded": [0.1235, -0.5], "limited": [0.0123, -0.5]}


def test_empty_log_snapshot():
    assert ShadowLog().snapshot() == {
        "counts": {"allow": 0, "limit": 0, "stop": 0, "unavailable": 0},
        "last_stop": None,
        "last_unavailable": None,
        "eval_ms": {"p50": None, "p99": None, "n": 0},
    }


def test_pending_events_are_bounded():
    log = ShadowLog()
    for i in range(1000):
        log.record(_v(i * 0.01, "allow" if i % 2 == 0 else "stop", "" if i % 2 == 0 else "pickup"))

    events = log.drain()
    assert 0 < len(events) <= 64
    assert events[-1]["verdict"] == "stop"     # i = 999 is the most recent
