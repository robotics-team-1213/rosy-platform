"""Tests for tools/calibration/pinky_loc_pipeline.py: stages, D-1022 judge, confirm, sample, and bind."""

from __future__ import annotations

import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pinky_loc_pipeline as plp  # noqa: E402

YAW = math.radians(28.0)
TX, TY = 0.65, -0.35
ROBOT_PTS = [(-0.8, -0.4), (0.9, -0.3), (0.8, 0.7), (-0.4, 0.6)]


def _to_site(pt):
    c, s = math.cos(YAW), math.sin(YAW)
    return [c * pt[0] - s * pt[1] + TX, s * pt[0] + c * pt[1] + TY]


def _make_pairs(pts=ROBOT_PTS):
    return [{"robot": list(p), "site": _to_site(p)} for p in pts]


def test_classify_robot_all_five_stages():
    offline = plp.classify_robot({"robot_id": "rosy_42", "online": False}, None, None, None)
    assert offline["stage"] == "OFFLINE"

    no_cands = plp.classify_robot(
        {"robot_id": "rosy_45", "online": True, "state": {"localization": {"state": "UNKNOWN"}, "map_grid_id": "g1"}},
        {"candidates": {"candidates": []}},
        {"matches": False, "reason": "MAP_BINDING_REQUIRED"},
        {"state": "UNKNOWN"},
    )
    assert no_cands["stage"] == "NO_CANDIDATES"

    needs_confirm = plp.classify_robot(
        {"robot_id": "rosy_45", "online": True, "state": {"localization": {"state": "CANDIDATES"}, "map_grid_id": "g1"}},
        {"candidates": {"candidates": [{"x": -0.5, "y": 0.2, "yaw": 0.0, "scan_fit": 0.989}]}},
        {"matches": False, "reason": "MAP_BINDING_REQUIRED"},
        {"state": "CONFIRMED", "x": 0.76, "y": -0.19},
    )
    assert needs_confirm["stage"] == "NEEDS_CONFIRM" and needs_confirm["best_scan_fit"] == pytest.approx(0.989)

    needs_bind = plp.classify_robot(
        {"robot_id": "rosy_45", "online": True, "state": {"localization": {"state": "LOCALIZED"}, "map_grid_id": "g1"}},
        {"localization": {"state": "LOCALIZED"}, "candidates": None},
        {"matches": False, "reason": "MAP_BINDING_REQUIRED"},
        {"state": "CONFIRMED", "x": 0.76, "y": -0.19},
    )
    assert needs_bind["stage"] == "NEEDS_MAP_BINDING"

    ready = plp.classify_robot(
        {"robot_id": "rosy_45", "online": True, "state": {"localization": {"state": "LOCALIZED"}, "map_grid_id": "g1"}},
        {"localization": {"state": "LOCALIZED"}, "candidates": None},
        {"matches": True, "slam_camera_gap_m": 0.03},
        {"state": "CONFIRMED", "x": 0.76, "y": -0.19},
    )
    assert ready["stage"] == "READY" and ready["slam_camera_gap_m"] == pytest.approx(0.03)


def test_judge_pairs_happy_path_and_all_eight_error_codes():
    verdict = plp.judge_pairs(_make_pairs(ROBOT_PTS[:3]), _make_pairs(ROBOT_PTS[3:]))
    assert verdict["yaw"] == pytest.approx(YAW)
    assert verdict["tx"] == pytest.approx(TX)
    assert verdict["ty"] == pytest.approx(TY)
    assert verdict["max_residual_m"] < 1e-9
    assert verdict["holdout_errors_m"][0] < 1e-9

    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(_make_pairs(ROBOT_PTS[:2]), _make_pairs(ROBOT_PTS[3:]))
    assert exc.value.code == "TOO_FEW_PAIRS"

    collinear = [(0.0, 0.0), (0.6, 0.0), (1.2, 0.0)]
    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(_make_pairs(collinear), _make_pairs(ROBOT_PTS[3:]))
    assert exc.value.code == "COLLINEAR"

    mirrored = [{"robot": list(p), "site": [s[0], -s[1]]} for p in ROBOT_PTS[:3] for s in [_to_site(p)]]
    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(mirrored, _make_pairs(ROBOT_PTS[3:]))
    assert exc.value.code == "MIRRORED"

    bad_res = _make_pairs(ROBOT_PTS[:3])
    bad_res[0]["site"][0] += 0.25
    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(bad_res, _make_pairs(ROBOT_PTS[3:]))
    assert exc.value.code == "RESIDUAL"

    cluster = [(0.1, 0.1), (-0.1, -0.1), (0.1, -0.1), (-0.1, 0.1)]
    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(_make_pairs(cluster), _make_pairs([(0.0, 0.0)]), max_residual=0.5, min_span=0.05)
    assert exc.value.code == "AMBIGUOUS_FLIP"

    small_span = [(0.0, 0.0), (0.4, 0.0), (0.0, 0.4)]
    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(_make_pairs(small_span), _make_pairs([(0.4, 0.4)]))
    assert exc.value.code == "SPAN"

    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(_make_pairs(ROBOT_PTS[:3]), ())
    assert exc.value.code == "HOLDOUT_REQUIRED"

    bad_hold = _make_pairs(ROBOT_PTS[3:])
    bad_hold[0]["site"][0] += 0.2
    with pytest.raises(plp.PipelineError) as exc:
        plp.judge_pairs(_make_pairs(ROBOT_PTS[:3]), bad_hold)
    assert exc.value.code == "HOLDOUT"


class _FakeFleet:
    def __init__(self):
        self.loc_state = "CANDIDATES"
        self.pose_frame = "odom"
        self.candidates = [{"x": -0.5, "y": 0.2, "yaw": -0.02, "scan_fit": 0.989}]
        self.velocity = {"linear": 0.0, "angular": 0.0}
        self.pose = {"x": ROBOT_PTS[0][0], "y": ROBOT_PTS[0][1], "yaw": 0.0}
        self.track = {"robot_id": "rosy_45", "state": "CONFIRMED", "x": _to_site(ROBOT_PTS[0])[0],
                      "y": _to_site(ROBOT_PTS[0])[1], "age_s": 0.2, "map_id": "world_261026"}
        self.binding_matches = False
        self.site_version = 394
        self.sightings = []
        self.evidence = {}
        self.next_evidence = None
        self.posts = []


def _start_server(state: _FakeFleet):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send(self, code, body):
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/fleet/state":
                evidence = state.evidence
                if state.next_evidence is not None:
                    state.evidence, state.next_evidence = state.next_evidence, None
                return self._send(200, {"robots": [{
                    "robot_id": "rosy_45",
                    "online": True,
                    "state": {
                        "robot_id": "rosy_45",
                        "online": True,
                        "map_grid_id": "occupancy:abc123",
                        "pose": state.pose,
                        "velocity": state.velocity,
                        "evidence": evidence,
                        "localization": {"state": state.loc_state, "pose_frame": state.pose_frame},
                        "diagnostics_summary": {"navigation_readiness": "OK"},
                    },
                }]})
            if self.path == "/api/fleet/tracking/identity":
                return self._send(200, {"robots": [state.track]})
            if self.path == "/api/fleet/sightings":
                return self._send(200, {"sightings": state.sightings})
            if self.path == "/api/fleet/site-map/active":
                return self._send(200, {"version": state.site_version, "map": {"map_id": "world_261026"}})
            if self.path == "/api/fleet/robots/rosy_45/localization":
                return self._send(200, {
                    "robot_id": "rosy_45",
                    "localization": {"state": state.loc_state, "pose_frame": state.pose_frame},
                    "candidates": {"robot_id": "rosy_45", "request_id": "1", "candidates": state.candidates},
                })
            if self.path == "/api/fleet/robots/rosy_45/map-binding":
                return self._send(200, {
                    "matches": state.binding_matches,
                    "reason": None if state.binding_matches else "MAP_BINDING_REQUIRED",
                    "robot_grid_id": "occupancy:abc123",
                    "slam_camera_gap_m": 0.02 if state.binding_matches else None,
                })
            if self.path == "/api/fleet/robots/rosy_45/map-pose":
                return self._send(200, {"robot_id": "rosy_45", "state": "UNKNOWN"})
            self._send(404, {"detail": {"code": "NOT_FOUND", "message": self.path}})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            state.posts.append((self.path, body))
            if self.path == "/api/fleet/robots/rosy_45/localization/confirm":
                state.loc_state = "LOCALIZED"
                state.pose_frame = "map"
                return self._send(200, {"robot_id": "rosy_45", "candidate_index": body["candidate_id"], "core": {"ok": True}})
            if self.path == "/api/fleet/robots/rosy_45/map-binding":
                state.binding_matches = True
                return self._send(200, {"robot_grid_id": "occupancy:abc123"})
            self._send(404, {})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_approved_aruco_is_a_fit_sample_when_identity_is_unknown(tmp_path):
    state = _FakeFleet()
    state.loc_state, state.pose_frame = "LOCALIZED", "map"
    state.track = {"robot_id": "rosy_45", "state": "UNKNOWN"}
    sighting = {"robot_id": "rosy_45", "source_id": "ceiling_north", "map_id": "world_261026",
                "calibration_source": "approved_record", "calibration_revision": "paint-1",
                "processor_revision": "aruco-opencv-4.12", "stale": False, "age_ms": 500,
                "seq": 12, "captured_at": 1234.0, "x": 0.2, "y": 0.3}
    state.sightings = [sighting]
    out = tmp_path / "pairs.json"
    server = _start_server(state)
    try:
        client = plp.FleetClient(f"http://127.0.0.1:{server.server_port}")
        kwargs = dict(robot_id="rosy_45", out_path=out, pair_spec=None, grid_id_override=None,
                      site_map_id_override=None, max_track_age_s=1.0, aruco_source="ceiling_north")
        with pytest.raises(plp.PipelineError, match="must precede"):
            plp.run_sample(client, **kwargs, holdout=False)
        state.evidence = {
            "pose": {"evidence": "fresh", "received_at": "1970-01-01T00:20:34Z"},
            "velocity": {"evidence": "fresh", "sampled_at": "1970-01-01T00:20:34Z"},
        }
        with pytest.raises(plp.PipelineError, match="holdout"):
            plp.run_sample(client, **kwargs, holdout=True)
        with pytest.raises(plp.PipelineError, match="after the ArUco capture"):
            plp.run_sample(client, **kwargs, holdout=False)
        state.next_evidence = {
            "pose": {"evidence": "fresh", "received_at": "1970-01-01T00:20:34.100Z"},
            "velocity": {"evidence": "fresh", "sampled_at": "1970-01-01T00:20:34.100Z"},
        }
        plp.run_sample(client, **kwargs, holdout=False)
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["site_map_version"] == 394
        assert doc["samples"][0]["site"] == [0.2, 0.3]
        assert doc["samples"][0]["source"] == "approved_aruco"
        with pytest.raises(plp.PipelineError, match="already recorded"):
            plp.run_sample(client, **kwargs, holdout=False)
        sighting.update(stale=True, age_ms=1001, seq=13)
        with pytest.raises(plp.PipelineError, match="fresh"):
            plp.run_sample(client, **kwargs, holdout=False)
        with pytest.raises(plp.PipelineError, match="manual holdout"):
            plp.run_bind(client, robot_id="rosy_45", pairs_path=out, approve=True)
        state.site_version += 1
        with pytest.raises(plp.PipelineError, match="different site map revision"):
            plp.run_sample(client, **kwargs, holdout=False)
        assert state.posts == []
    finally:
        server.shutdown()
        server.server_close()


def test_confirm_refusals_and_happy_path():
    fake = _FakeFleet()
    srv = _start_server(fake)
    try:
        client = plp.FleetClient(f"http://127.0.0.1:{srv.server_port}", token="tok")

        fake.candidates.append({"x": 0.5, "y": -0.2, "yaw": 3.12, "scan_fit": 0.91})
        with pytest.raises(plp.PipelineError) as exc:
            plp.run_confirm(client, robot_id="rosy_45", candidate_id=None, min_fit=0.85, wait_s=1.0, sleep=lambda _: None)
        assert exc.value.code == "CANDIDATE_AMBIGUOUS"

        fake.candidates = [{"x": -0.5, "y": 0.2, "yaw": -0.02, "scan_fit": 0.70}]
        with pytest.raises(plp.PipelineError) as exc:
            plp.run_confirm(client, robot_id="rosy_45", candidate_id=None, min_fit=0.85, wait_s=1.0, sleep=lambda _: None)
        assert exc.value.code == "SCAN_FIT_LOW"

        fake.candidates = [{"x": -0.5, "y": 0.2, "yaw": -0.02, "scan_fit": 0.989}]
        rc = plp.run_confirm(client, robot_id="rosy_45", candidate_id=None, min_fit=0.85, wait_s=2.0, sleep=lambda _: None)
        assert rc == 0 and fake.loc_state == "LOCALIZED"
        assert fake.posts[0] == ("/api/fleet/robots/rosy_45/localization/confirm", {"candidate_id": 0})
    finally:
        srv.shutdown()


def test_sample_guards_and_bind_dry_run_vs_approve(tmp_path):
    fake = _FakeFleet()
    srv = _start_server(fake)
    pairs_file = tmp_path / "pairs.json"
    try:
        client = plp.FleetClient(f"http://127.0.0.1:{srv.server_port}", token="tok")

        with pytest.raises(plp.PipelineError) as exc:
            plp.run_sample(client, robot_id="rosy_45", out_path=pairs_file, pair_spec=None,
                           grid_id_override=None, site_map_id_override=None, holdout=False, max_track_age_s=1.0)
        assert exc.value.code == "ROBOT_NOT_LOCALIZED"

        fake.loc_state, fake.pose_frame = "LOCALIZED", "map"
        fake.velocity = {"linear": 0.05, "angular": 0.0}
        with pytest.raises(plp.PipelineError) as exc:
            plp.run_sample(client, robot_id="rosy_45", out_path=pairs_file, pair_spec=None,
                           grid_id_override=None, site_map_id_override=None, holdout=False, max_track_age_s=1.0)
        assert exc.value.code == "ROBOT_MOVING"

        fake.velocity = {"linear": 0.0, "angular": 0.0}
        fake.track["age_s"] = 2.5
        with pytest.raises(plp.PipelineError) as exc:
            plp.run_sample(client, robot_id="rosy_45", out_path=pairs_file, pair_spec=None,
                           grid_id_override=None, site_map_id_override=None, holdout=False, max_track_age_s=1.0)
        assert exc.value.code == "TRACK_STALE"

        fake.track["age_s"] = 0.2
        assert plp.run_sample(client, robot_id="rosy_45", out_path=pairs_file, pair_spec=None,
                              grid_id_override=None, site_map_id_override=None, holdout=False, max_track_age_s=1.0) == 0

        for i, pt in enumerate(ROBOT_PTS[1:]):
            sx, sy = _to_site(pt)
            plp.run_sample(client, robot_id="rosy_45", out_path=pairs_file,
                           pair_spec=f"{pt[0]},{pt[1]}={sx},{sy}", grid_id_override=None,
                           site_map_id_override=None, holdout=(i == 2), max_track_age_s=1.0)

        saved = json.loads(pairs_file.read_text(encoding="utf-8"))
        assert len(saved["samples"]) == 4

        assert plp.run_bind(client, robot_id="rosy_45", pairs_path=pairs_file, approve=False) == 0
        assert fake.posts == []

        assert plp.run_bind(client, robot_id="rosy_45", pairs_path=pairs_file, approve=True) == 0
        assert len(fake.posts) == 1 and fake.posts[0][0] == "/api/fleet/robots/rosy_45/map-binding"
        assert fake.binding_matches is True

        saved["map_grid_id"] = "occupancy:other"
        pairs_file.write_text(json.dumps(saved), encoding="utf-8")
        with pytest.raises(plp.PipelineError) as exc:
            plp.run_sample(client, robot_id="rosy_45", out_path=pairs_file, pair_spec=None,
                           grid_id_override=None, site_map_id_override=None, holdout=False, max_track_age_s=1.0)
        assert exc.value.code == "MAP_BINDING_GRID_CHANGED"
    finally:
        srv.shutdown()



@pytest.mark.parametrize("points,expected", [
    ([(0, 0), (0.6, 0), (1.2, 0), (0, 1)], "COLLINEAR"),
    (ROBOT_PTS, None),
])
def test_sample_readiness_matches_binding(tmp_path, capsys, points, expected):
    path = tmp_path / "pairs.json"
    for i, (x, y) in enumerate(points):
        plp.run_sample(None, robot_id="rosy_42", out_path=path,
                       pair_spec=f"{x},{y}={x},{y}", grid_id_override="g",
                       site_map_id_override=None, holdout=i == 3, max_track_age_s=1)
        result = json.loads(capsys.readouterr().out)
    assert result["ready_for_bind"] is (expected is None)
    if expected:
        assert result["binding_refusal"]["code"] == expected
    else:
        assert result["binding_refusal"] is None


@pytest.mark.parametrize("pairs,fit_code,site_span_shortfall", [
    ([
        ([0.415044, -0.410333], [-0.255224, 0.483407]),
        ([0.409060, -0.326061], [-0.237613, 0.375868]),
        ([0.396248, -0.162492], [-0.208315, 0.181937]),
        ([0.394217, -0.082741], [-0.194098, 0.086882]),
    ], "COLLINEAR", 0.599),
    ([(p, p) for p in [(0, 0), (1.2, 0), (0, 0.6)]], None, 0.0),
])
def test_versioned_fit_reports_geometry_without_a_floor_holdout(
        tmp_path, capsys, monkeypatch, pairs, fit_code, site_span_shortfall):
    monkeypatch.setattr(plp, "_active_site", lambda _: ("world_261026", 394))
    path = tmp_path / "pairs.json"
    path.write_text(json.dumps({
        "site_map_version": 394,
        "samples": [{"robot": robot, "site": site, "source": "approved_aruco",
                     "holdout": False} for robot, site in pairs[:-1]],
    }), encoding="utf-8")
    (rx, ry), (sx, sy) = pairs[-1]

    plp.run_sample(None, robot_id="rosy_42", out_path=path,
                   pair_spec=f"{rx},{ry}={sx},{sy}", grid_id_override="g",
                   site_map_id_override=None, holdout=False, max_track_age_s=1)

    result = json.loads(capsys.readouterr().out)
    assert not result["ready_for_bind"]
    assert result["binding_refusal"]["code"] == "HOLDOUT_REQUIRED"
    assert result["manual_holdout_missing"]
    geometry = result["fit_geometry"]
    assert geometry["pairs"] == len(pairs)
    assert geometry["pairs_remaining"] == 0
    assert geometry["site_span_shortfall_m"] == pytest.approx(site_span_shortfall)
    if fit_code:
        assert geometry["refusal"]["code"] == fit_code
        assert geometry["robot_spread_m"] == pytest.approx(0.0012)
        assert geometry["site_spread_m"] == pytest.approx(0.0004)
    else:
        assert geometry["refusal"] is None
    original = path.read_bytes()
    assert plp.main(["--token-file", str(tmp_path / "unused-token"), "inspect", "--pairs", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert path.read_bytes() == original
