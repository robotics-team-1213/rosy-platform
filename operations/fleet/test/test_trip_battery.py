"""A trip start needs fresh, non-critical battery evidence (TRIP_BATTERY_UNCONFIRMED, fail closed)."""
import pytest
from types import SimpleNamespace

from fleet.server.trip_admission import battery_refusal
from fleet.server.trip_runner import TripError
from test_trip_runner import _arc, _code, _plan, _setup, run


def reading(age_s=0.0, **battery):
    base = {"evidence": "fresh", "sample_age_s": 1.0, "stale_after_s": 5.0, "level": "ok", "percent": 80.0}
    return {"battery": {**base, **battery}, "age_s": age_s}


@pytest.mark.parametrize("value, why", [
    (reading(), None),
    (reading(level="warning"), None),
    (None, "unreadable"),
    ({"battery": None, "age_s": 0.0}, "unreadable"),
    (reading(evidence="stale"), "evidence_stale"),            # rosy_45: frozen percent 100, evidence stale
    (reading(evidence="stale", percent=100.0), "evidence_stale"),
    (reading(evidence="missing", percent=None), "evidence_missing"),
    (reading(age_s=4.5, sample_age_s=1.0), "evidence_old"),   # sample age + Fleet cache age > stale_after_s
    (reading(age_s=5.5), "evidence_old"),                     # Fleet's own cache older than 5 s
    (reading(age_s=None), "evidence_old"),
    (reading(sample_age_s=None), "evidence_old"),
    (reading(stale_after_s=0.0), "evidence_old"),
    (reading(percent=None), "percent_unreadable"),
    (reading(percent=float("nan")), "percent_unreadable"),
    (reading(level="critical", percent=8.0), "level_critical"),
    (reading(level="deep", percent=4.0), "level_deep"),
    (reading(level="bogus"), "level_bogus"),
])
def test_battery_refusal_reasons(value, why):
    assert battery_refusal(value) == why


def _ready(**config):
    runner, store, ports = _setup(**config)
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "CAMERA_LINE"
    return runner, store, ports


def _refused(runner):
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.status == 422
    return err.value


def test_start_is_refused_when_the_battery_is_stale_missing_critical_or_unreadable():
    runner, store, ports = _ready(period_s=0.01)
    async def stale(_):
        return reading(evidence="stale", percent=100.0)
    async def critical(_):
        return reading(level="critical", percent=8.0)
    async def none(_):
        return None
    async def boom(_):
        raise OSError("no route")
    for source, why in ((stale, "evidence_stale"), (critical, "level_critical"), (none, "unreadable"),
                        (boom, "unreadable"), (None, "no_source")):
        runner._battery = source
        err = _refused(runner)
        assert (err.code, err.detail) == ("TRIP_BATTERY_UNCONFIRMED", {"reason": why})
    assert runner.open_trips() == []


def test_a_fresh_battery_still_starts_and_a_pose_fault_is_still_the_pose_code():
    runner, store, ports = _ready()
    ports.pose = None
    assert _code(runner.start("p1", "bob")) == "TRIP_POSE_UNTRUSTED"   # battery passed, pose refused
    ports.at(_arc(store, "ring_s:fwd"), 0.1)
    assert run(runner.start("p1", "bob"))["trip_id"] == "p1"


def test_a_charge_return_start_skips_the_battery_check_but_a_mission_step_does_not():
    runner, store, ports = _ready(period_s=0.01)
    async def stale(_):
        return reading(evidence="stale", percent=100.0)
    for source in (stale, None):      # a dead ADC (rosy_45) must still be able to go and charge
        runner._battery = source
        runner.lease.jobs["rosy_60"] = SimpleNamespace(view={"owner_kind": "charge_session"})
        run(runner._check_battery("rosy_60"))
        runner.lease.jobs["rosy_60"] = SimpleNamespace(view={"owner_kind": "mission"})
        with pytest.raises(TripError):
            run(runner._check_battery("rosy_60"))


def test_a_transient_miss_is_retried_briefly_and_a_stale_robot_is_still_refused():
    runner, store, ports = _ready(period_s=0.01)
    seen = []
    async def flaky(_):
        seen.append(1)
        return None if len(seen) < 3 else reading()
    runner._battery = flaky
    run(runner._check_battery("rosy_60"))                       # two misses, then a fresh read
    assert len(seen) == 3
    seen.clear()
    async def stale(_):
        seen.append(1)
        return reading(evidence="stale")
    runner._battery = stale
    with pytest.raises(TripError):
        run(runner._check_battery("rosy_60"))
    assert len(seen) == 3                                       # a blip past the limit clears; a frozen robot does not
    seen.clear()
    async def never(_):
        seen.append(1)
        return None
    runner._battery = never
    err = pytest.raises(TripError, lambda: run(runner._check_battery("rosy_60"))).value
    assert err.detail == {"reason": "unreadable"} and len(seen) == 3   # bounded
