"""The camera may guide a missing CORE search; it carries no localization decision."""

import math
from datetime import datetime
from types import SimpleNamespace

import pytest

from core_common.protocol.localization import CandidateReport
from fakes import FakeClock, FakeRobot, run
from fleet.localization.map_binding import Fit
from fleet.localization.relative_search_prior import relative_center, short_baseline_center, supports_heading, synchronous_markers
from fleet.server.localization_service import LocalizationService

GRID = "occupancy:123456789012"
FRAME = ("native-grid", GRID)
SITE = "world_261026"
NATIVE_FIX = (.21, -.33, 1.545)
NATIVE_CAMERA_CENTER = (.17127, -.32965, 1.545)
CAMERA_TARGET = (.17127, -.32965, 1.545)
PEERS = ((-.31, -.4, -.1), (-.05, -.85, 2.8))
SHORT_PEERS = ((-.13, -.5, .04), (.12, -.5, 2.9))
PACKET_TIMESTAMP = "2026-11-25T20:20:55.575+00:00"
PACKET_TIME_S = datetime.fromisoformat(PACKET_TIMESTAMP).timestamp()


def report(scan_fit=.95772):
    return CandidateReport.model_validate({
        "robot_id": "r46", "request_id": "r46-3", "stamp": PACKET_TIME_S - .3,
        "candidates": [dict(zip(("x", "y", "yaw", "scan_fit"), (*NATIVE_FIX, scan_fit)))],
    })


def native_state(pose, state="LOCALIZED", grid=GRID):
    coordinates = dict(zip(("x", "y", "yaw"), pose))
    return {"map_id": FRAME[0], "map_grid_id": grid, "map_generation": 1, "mode": "IDLE", "pose_frame": "map",
            "localization": {"state": state, "pose_frame": "map"}, "pose": coordinates,
            "odom_pose": dict(coordinates, epoch=2, stamp=PACKET_TIME_S - .1),
            "velocity": {"linear": 0., "angular": 0.},
            "timestamp": PACKET_TIMESTAMP,
            "evidence": {channel: {"evidence": "fresh", "received_at": "2026-11-25T20:20:55.480+00:00"}
                         for channel in ("pose", "velocity")}}


def frame_rows(clock, *, offset=0., peers=PEERS):
    return [dict(
        robot_id=rid, x=pose[0], y=pose[1], yaw=pose[2], source_id="ceiling_north",
        captured_at=clock() - offset, seq=23, map_id=SITE, calibration_source="approved_record",
        calibration_revision="fit-394", processor_revision="aruco-field",
    ) for rid, pose in zip(("r42", "r45", "r46"), (*peers, CAMERA_TARGET))]


def test_geometry_rejects_wrong_marker_heading_short_baseline_and_scan_mismatch():
    assert relative_center(CAMERA_TARGET, list(zip(PEERS, PEERS))) == pytest.approx(NATIVE_CAMERA_CENTER)
    wrong_yaw = (*PEERS[0][:2], PEERS[0][2] + math.pi / 2)
    assert relative_center(CAMERA_TARGET, ((PEERS[0], wrong_yaw), (PEERS[1], PEERS[1]))) is None
    assert relative_center(CAMERA_TARGET, ((PEERS[0], PEERS[0]), (PEERS[0], PEERS[0]))) is None
    # Field camera-pair estimate and independent best 46 native 3-LiDAR replay candidate.
    field_camera_mean = ((.165009867 + .177528547) / 2, (-.356189201 - .303106775) / 2, 1.545)
    assert supports_heading(field_camera_mean, report())
    assert not supports_heading((*field_camera_mean[:2], 1.545 + math.pi / 2), report())
    assert not supports_heading(field_camera_mean, report(.80))


def test_camera_samples_belong_to_one_current_approved_exposure():
    clock = FakeClock()
    rows = frame_rows(clock)
    assert set(synchronous_markers(rows, "r46", SITE, clock())[1]) == {"r42", "r45", "r46"}
    rows[0]["seq"] += 1
    rows[1]["calibration_source"] = "field_boundary"
    assert set(synchronous_markers(rows, "r46", SITE, clock())[1]) == {"r46"}
    assert synchronous_markers(frame_rows(clock, offset=1), "r46", SITE, clock()) is None


def test_short_baseline_uses_independent_marker_headings_and_scan_yaw():
    refs = list(zip(SHORT_PEERS, SHORT_PEERS))
    assert relative_center(CAMERA_TARGET, refs) is None
    assert short_baseline_center(CAMERA_TARGET, refs, report()) == pytest.approx(NATIVE_CAMERA_CENTER)
    wrong_yaw = (*SHORT_PEERS[1][:2], SHORT_PEERS[1][2] + math.radians(20))
    assert short_baseline_center(CAMERA_TARGET, (refs[0], (SHORT_PEERS[1], wrong_yaw)), report()) is None
    native = report()
    primary = native.candidates[0].model_copy(update={"yaw": NATIVE_FIX[2] + .1})
    native = native.model_copy(update={"candidates": [primary]})
    assert short_baseline_center(CAMERA_TARGET, refs, native)[2] == primary.yaw
    alternate = primary.model_copy(update={"yaw": NATIVE_FIX[2] + math.pi})
    competing = native.model_copy(update={"candidates": [*native.candidates, alternate]})
    assert short_baseline_center(CAMERA_TARGET, refs, competing) is None
    assert short_baseline_center(CAMERA_TARGET, refs, report(.84)) is None


@pytest.mark.parametrize("bad", [None, "approved-binding", "wrong-grid", "old-reference", "no-capability",
                                   "global-report", "mixed-frame", "map-restarted", "unanchored",
                                   "stale-peer-velocity", "stale-target-velocity", "moving-peer", "short-baseline",
                                   "stale-native-scan", "candidate-request-changed", "odom-restarted", "stale-target-odom",
                                   "calibration-revoked", "binding-revoked"])
def test_service_sends_search_only_for_empty_native_candidates_with_fresh_peers(bad):
    clock = FakeClock()
    geometry = SHORT_PEERS if bad == "short-baseline" else PEERS
    peers = {rid: FakeRobot(rid, state=native_state(pose)) for rid, pose in zip(("r42", "r45"), geometry)}
    r46 = FakeRobot("r46", state=native_state(NATIVE_FIX, "CANDIDATES"))
    posted = []
    approved_revision = "fit-394"
    active_binding = Fit(0., 0., 0., ())
    r46.candidates = report()
    if bad == "stale-native-scan":
        r46.candidates = r46.candidates.model_copy(update={"stamp": PACKET_TIME_S - 60})
    r46._state["localization"]["request_id"] = (
        "r46-4" if bad == "candidate-request-changed" else r46.candidates.request_id)

    async def caps():
        nonlocal approved_revision, active_binding
        if bad == "calibration-revoked":
            approved_revision = "fit-395"
        if bad == "binding-revoked":
            active_binding = None
        return {"localization": {"search_window": bad != "no-capability"}}

    async def search(grid, center):
        posted.append((grid, center))
        return {"accepted": True}

    async def read_robot(rid):
        robot = r46 if rid == "r46" else peers[rid]
        state = robot._state
        if bad == "wrong-grid" and rid == "r42":
            state = {**state, "map_grid_id": "occupancy:ffffffffffff"}
        if (bad, rid) in {("stale-peer-velocity", "r42"), ("stale-target-velocity", "r46")}:
            state = {**state, "evidence": {**state["evidence"], "velocity": {
                "evidence": "fresh", "received_at": "2026-11-25T20:20:54.990+00:00",
            }}}
        if bad == "moving-peer" and rid == "r42":
            state = {**state, "velocity": {"linear": .1, "angular": 0.}}
        if rid == "r46" and bad in ("odom-restarted", "stale-target-odom"):
            odom_update = {"epoch": 3} if bad == "odom-restarted" else {"stamp": PACKET_TIME_S - 10}
            state = {**state, "odom_pose": {**state["odom_pose"], **odom_update}}
        age = .8 if bad == "old-reference" else 0.
        return SimpleNamespace(state=state, started_mono=clock() - age)

    r46.capabilities, r46.localization_search_window = caps, search
    rows = frame_rows(clock, peers=geometry)
    if bad == "mixed-frame":
        rows[0]["seq"] += 1
    sightings = SimpleNamespace(snapshot=lambda: {"sightings": rows},
                                approved_sighting_revision=lambda *_: approved_revision)
    svc = LocalizationService(lambda: {**peers, "r46": r46}, sightings=sightings,
                              clock=clock, wall=clock)
    svc.set_active_map_id(lambda: SITE)
    svc.set_search_reference_reader(read_robot)
    for rid, pose in zip(peers, geometry):
        if bad == "unanchored" and rid == "r42":
            # A locally trusted or transitively anchored claim is insufficient.
            svc._pending[rid] = (FRAME, pose)
        else:
            svc._operator_pending[rid] = (FRAME, (rid, pose, True, clock()))
    if bad in ("approved-binding", "binding-revoked"):
        svc._binding_fit_for_state = lambda *_args, **_kwargs: active_binding
        rows[:] = [rows[-1]]  # an approved fit does not depend on the camera peers
    run(svc.tick())
    if bad == "map-restarted":
        r46._state["map_generation"] = 2
    r46._state["localization"]["state"] = "SUSPECT"
    r46.candidates = report() if bad == "global-report" else None
    run(svc.tick())
    run(svc.tick())
    if bad in (None, "approved-binding", "short-baseline"):
        assert len(posted) == 1 and posted[0][0] == GRID
        assert posted[0][1] == pytest.approx(NATIVE_CAMERA_CENTER)
        clock.advance(2.1)
        rows[:] = frame_rows(clock, peers=geometry)
        r46._state["localization"]["state"] = "CANDIDATES"
        r46.candidates = report().model_copy(update={"stamp": PACKET_TIME_S - .2})
        run(svc.tick())
        r46._state["localization"]["state"] = "SUSPECT"
        r46.candidates = None
        run(svc.tick())
        assert len(posted) == 1  # report churn in the same recovery cannot submit another accepted window
    else:
        assert posted == []
    assert r46.decisions == []
