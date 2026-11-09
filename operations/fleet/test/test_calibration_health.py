"""D-1006 calibration health: rejected/missing polls count, hysteresis, the optional sighting gate.

Today's incident (2026-11-09) is the anchor case: every Vision fit was rejected (score
0.51-0.60, coverage 0.43-0.59), so the drift watch said nothing while the outline sat on
the chairs. Observation only; the gate is opt-in and never blocks on absence of evidence.
"""

import asyncio
import sqlite3

import pytest

from fleet.server.calibration_health import (
    AGREE, DISAGREE, INCONCLUSIVE, LOW_COVERAGE, MISMATCH, NO_RESPONSE, UNKNOWN_AFTER_S,
    CalibrationHealth, classify,
)
from fleet.server.sightings import SightingError, SightingService
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore
from test_tracking_drift import (
    IDENTITY_I2M, NOW, _body, _Clock, _Fetcher, _record, _source, _translated, _watch,
)

REV = "paint-test"


def _rejected(score=0.55, coverage=0.5, cut=("+x", "-y")):
    return {"accepted": False, "proposal": None, "frame_seq": 5,
            "rejected_fit": {"score": score, "precision": 0.7, "coverage": coverage, "cut_sides": list(cut)},
            "reason": "weak paint match"}


def _agree():
    body = _body(IDENTITY_I2M)
    return body, {"state": "ok", "max_move_m": 0.02, "rotation_deg": 0.1}


def _disagree():
    return _body(_translated(0.5)), {"state": "stale", "max_move_m": 0.5, "rotation_deg": 0.2}


def _feed(health, polls, body, verdict=None, clock=None):
    for _ in range(polls):
        health.observe("ceiling_north", REV, body, verdict)
        if clock is not None:
            clock.now += 60.0


def test_classify_covers_every_poll_outcome():
    assert classify(None, None)[0] == NO_RESPONSE
    assert classify(*_agree())[0] == AGREE
    assert classify(*_disagree())[0] == DISAGREE
    assert classify({"accepted": True, "proposal": {}}, None)[0] == INCONCLUSIVE   # other pixel grid
    assert classify(_rejected(0.55, 0.5), None) == (MISMATCH, {
        "score": 0.55, "coverage": 0.5, "cut_sides": ["+x", "-y"]})                 # the 11-09 incident
    assert classify(_rejected(0.55, 0.1), None)[0] == LOW_COVERAGE
    assert classify({"accepted": False, "rejected_fit": None}, None)[0] == LOW_COVERAGE  # no fit at all
    assert classify(_rejected(0.75, 0.5), None)[0] == INCONCLUSIVE                  # near miss: no claim
    assert classify(_rejected(0.4, 0.3), None)[0] == INCONCLUSIVE                   # some paint, poor match
    assert classify(_rejected(None, 0.5), None)[0] == INCONCLUSIVE
    assert classify({"accepted": False, "rejected_fit": {"score": float("nan"), "coverage": 0.5}}, None)[0] \
        == INCONCLUSIVE


def test_todays_rejected_fits_become_mismatch_only_after_five_polls():
    clock = _Clock()
    health = CalibrationHealth(clock=clock)
    assert health.view("ceiling_north") is None
    _feed(health, 4, _rejected(), clock=clock)
    assert health.view("ceiling_north")["state"] == "unknown"
    _feed(health, 1, _rejected(), clock=clock)
    view = health.view("ceiling_north")
    assert view["state"] == "mismatch" and view["cause"] == "undetermined"
    assert view["streak"] == {"kind": MISMATCH, "polls": 5}
    assert view["last"]["coverage"] == 0.5 and view["blocking"] is False   # gate is off by default


def test_an_interrupting_poll_restarts_the_streak_but_a_missing_one_does_not():
    clock = _Clock()
    health = CalibrationHealth(clock=clock)
    _feed(health, 4, _rejected(), clock=clock)
    _feed(health, 3, None, clock=clock)                      # Vision busy/unreachable: neither counts nor resets
    _feed(health, 1, _rejected(), clock=clock)
    assert health.view("ceiling_north")["state"] == "mismatch"
    health = CalibrationHealth(clock=clock)
    _feed(health, 4, _rejected(), clock=clock)
    _feed(health, 1, _rejected(0.75, 0.5), clock=clock)      # inconclusive in between
    _feed(health, 1, _rejected(), clock=clock)
    assert health.view("ceiling_north")["state"] == "unknown"


def test_drifting_fresh_and_insufficient_coverage_need_three_polls():
    clock = _Clock()
    health = CalibrationHealth(clock=clock)
    _feed(health, 3, *_disagree(), clock=clock)
    assert health.view("ceiling_north")["state"] == "drifting"
    health = CalibrationHealth(clock=clock)
    _feed(health, 3, _rejected(0.6, 0.1), clock=clock)
    assert health.view("ceiling_north")["state"] == "insufficient_coverage"
    _feed(health, 3, *_agree(), clock=clock)
    assert health.view("ceiling_north")["state"] == "fresh"


def test_leaving_a_blocking_state_needs_five_agreeing_polls():
    clock = _Clock()
    health = CalibrationHealth(clock=clock, gate=True)
    _feed(health, 3, *_disagree(), clock=clock)
    assert health.blocks("ceiling_north")
    _feed(health, 4, *_agree(), clock=clock)
    assert health.view("ceiling_north")["state"] == "drifting" and health.blocks("ceiling_north")
    _feed(health, 1, *_agree(), clock=clock)
    assert health.view("ceiling_north")["state"] == "fresh" and not health.blocks("ceiling_north")


def test_silence_turns_the_state_unknown_and_unknown_never_blocks():
    clock = _Clock()
    health = CalibrationHealth(clock=clock, gate=True)
    _feed(health, 5, _rejected(), clock=clock)
    assert health.blocks("ceiling_north")
    clock.now += UNKNOWN_AFTER_S + 1                          # Vision down or the view blocked
    view = health.view("ceiling_north")
    assert view["state"] == "unknown" and view["blocking"] is False
    health = CalibrationHealth(clock=clock, gate=True)
    _feed(health, 9, _rejected(0.6, 0.05), clock=clock)       # too little paint in view
    assert health.view("ceiling_north")["state"] == "insufficient_coverage"
    assert not health.blocks("ceiling_north")


def test_a_new_approval_starts_over():
    clock = _Clock()
    health = CalibrationHealth(clock=clock, gate=True)
    _feed(health, 5, _rejected(), clock=clock)
    health.observe("ceiling_north", "paint-new", *_agree())
    view = health.view("ceiling_north")
    assert view["state"] == "unknown" and view["calibration_revision"] == "paint-new"
    health.forget("ceiling_north")
    assert health.view("ceiling_north") is None


def test_the_journal_keeps_every_poll_for_threshold_tuning(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    health = CalibrationHealth(clock=_Clock(), journal_path=path)
    health.observe("ceiling_north", REV, _rejected(), None)
    health.observe("ceiling_north", REV, None, None)
    health.observe("ceiling_north", REV, *_disagree())
    rows = sqlite3.connect(path).execute(
        "SELECT category, score, coverage, cut_sides, move_m, frame_seq FROM calibration_health_log"
        " ORDER BY log_id").fetchall()
    assert rows == [(MISMATCH, 0.55, 0.5, "+x,-y", None, 5), (NO_RESPONSE, None, None, None, None, None),
                    (DISAGREE, None, None, None, 0.5, 77)]


def test_a_malformed_rejected_fit_never_breaks_the_watch_or_the_drift_verdict():
    assert classify({"accepted": False, "rejected_fit": {"score": 0.5, "coverage": 0.5, "cut_sides": 7}}, None)         == (MISMATCH, {"score": 0.5, "coverage": 0.5, "cut_sides": []})
    calibrations = TrackingCalibrationStore()
    calibrations.put(_record())
    watch = _watch(_Fetcher(_body(_translated(0.5))), calibrations)
    watch.health.observe = lambda *args: (_ for _ in ()).throw(TypeError("boom"))
    asyncio.run(watch.poll_once())
    assert watch.verdicts()["ceiling_north"]["state"] == "stale"


def test_a_state_held_for_an_older_revision_does_not_block_after_reapproval():
    clock = _Clock()
    health = CalibrationHealth(clock=clock, gate=True)
    _feed(health, 5, _rejected(), clock=clock)
    assert health.blocks("ceiling_north", REV) and not health.blocks("ceiling_north", "paint-new")


def test_a_locked_or_unwritable_journal_does_not_stop_startup(tmp_path):
    health = CalibrationHealth(clock=_Clock(), journal_path=tmp_path)   # a directory is not a database
    health.observe("ceiling_north", REV, _rejected(), None)
    assert health.view("ceiling_north")["last"]["category"] == MISMATCH


def test_the_watch_feeds_every_poll_including_rejected_ones():
    calibrations = TrackingCalibrationStore()
    calibrations.put(_record())
    watch = _watch(_Fetcher(*[_rejected()] * 5), calibrations)
    for _ in range(5):
        asyncio.run(watch.poll_once())
    assert watch.verdicts() == {}                              # still no drift verdict from rejected fits
    assert watch.health.view("ceiling_north")["state"] == "mismatch"
    calibrations.delete("ceiling_north", principal_id="operator-1", at=NOW)
    asyncio.run(watch.poll_once())
    assert watch.health.view("ceiling_north") is None


@pytest.mark.parametrize("gate", [False, True])
def test_the_gate_stops_approved_record_sightings_only_when_enabled(gate):
    calibrations = TrackingCalibrationStore()
    record = _record()
    calibrations.put(record)
    clock = _Clock()
    health = CalibrationHealth(clock=clock, gate=gate)
    source = _source()
    tracking = TrackingService([source], calibrations=calibrations, clock=clock, health=health)
    sightings = SightingService([source], known_robot_ids=["rosy_01"], clock=clock)
    sightings.approved_revision = tracking.approved_revision
    assert tracking.approved_revision(source) == record.calibration_revision
    _feed(health, 5, _rejected(), clock=clock)
    row = tracking.snapshot()["sources"][0]["calibration_health"]
    assert row["state"] == "mismatch" and row["blocking"] is gate
    assert tracking.approved_revision(source) == (None if gate else record.calibration_revision)
    # the tracking display itself keeps its revision either way (the operator still needs the overlay)
    assert record.calibration_revision in tracking.revisions(source)
    if gate:
        with pytest.raises(SightingError) as caught:
            sightings.accept(f"Bearer {source.token}", _sighting(record.calibration_revision, clock.now))
        assert caught.value.code == "CALIBRATION_MISMATCH"


def test_tracking_rows_have_null_health_without_a_watch():
    tracking = TrackingService([_source()], calibrations=TrackingCalibrationStore(), clock=_Clock())
    assert tracking.snapshot()["sources"][0]["calibration_health"] is None


def _sighting(revision, now):
    from core_common.protocol.sightings import SiteSightingPayload
    return SiteSightingPayload(
        robot_id="rosy_01", x=1.0, y=1.0, yaw=0.0, captured_at=now - 0.1, seq=1, map_id="map_v2_fleet",
        calibration_revision=revision, processor_revision="aruco-map-v1", calibration_source="approved_record")
