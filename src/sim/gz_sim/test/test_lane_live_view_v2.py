"""ROS-free tests for the live viewer v2 wiring in lane_live_view.py: the
read-only guarantee, the extended status/graph payloads, the new
/runs.json and /run/<id>.json endpoints, the CORE poll and --demo."""

import importlib.util
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GRAPH = ROOT.parents[1] / "apps" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"
VIEWER_FILES = ["lane_live_view.py", "live_view_model.py", "live_view_demo.py",
                "lane_live_view.html"]


def _mod():
    spec = importlib.util.spec_from_file_location("lane_live_view", SCRIPTS / "lane_live_view.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _mod()


@pytest.fixture(scope="module")
def raw_graph():
    return yaml.safe_load(GRAPH.read_text(encoding="utf-8"))


@pytest.fixture()
def state(mod, raw_graph):
    return mod.ViewerState.from_raw_graph(raw_graph)


# ---------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------


@pytest.mark.parametrize("name", VIEWER_FILES)
def test_viewer_files_create_no_publishers(name):
    source = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "create_publisher" not in source
    assert "create_client" not in source  # no ROS service calls either


@pytest.mark.parametrize("name", VIEWER_FILES)
def test_viewer_files_use_no_non_get_http_method(name):
    source = (SCRIPTS / name).read_text(encoding="utf-8")
    assert not re.search(r"""method\s*[=:]\s*["'](POST|PUT|PATCH|DELETE)""", source, re.I)
    assert not re.search(r"def do_(POST|PUT|PATCH|DELETE)", source)
    assert "urlopen(" not in source or "data=" not in source


def test_core_requests_are_built_without_a_body_or_method(mod):
    source = (SCRIPTS / "lane_live_view.py").read_text(encoding="utf-8")
    for call in re.findall(r"urllib\.request\.Request\(([^)]*)\)", source):
        assert "method" not in call and "data" not in call


# ---------------------------------------------------------------------
# CORE poll
# ---------------------------------------------------------------------


def test_poll_core_status_gets_line_follow_robot_and_docking(mod):
    seen = []

    def fake_get(url, timeout):
        seen.append(url)
        if url.endswith("/api/v1/line-follow"):
            return {"mode": "CAMERA_LINE", "state": "FOLLOWING"}
        if url.endswith("/api/v1/robot/state"):
            return {"mode": "NAVIGATION", "safety": {"estop": False}}
        if url.endswith("/api/v1/docking/status"):
            return {"state": "UNDOCKED", "supported": True}
        return None

    out = mod.poll_core_status("http://core:8080/", get=fake_get)
    assert sorted(seen) == ["http://core:8080/api/v1/docking/status",
                            "http://core:8080/api/v1/line-follow",
                            "http://core:8080/api/v1/robot/state"]
    assert out["ok"] is True
    assert out["line_follow"]["mode"] == "CAMERA_LINE"
    assert out["robot"]["mode"] == "NAVIGATION"
    assert out["docking"]["state"] == "UNDOCKED"


def test_poll_core_status_unreachable(mod):
    out = mod.poll_core_status("http://core:8080", get=lambda url, timeout: None)
    assert out["ok"] is False


# ---------------------------------------------------------------------
# Graph payload
# ---------------------------------------------------------------------


def test_graph_payload_has_track_parking_marker_and_route(state):
    g = state.graph
    assert "east" in g["segments"] and "NE" in g["nodes"]
    assert g["parking"]["spot"] == [-1.0, 0.0, 0.0]
    assert len(g["parking"]["points"]) > 2
    assert g["marker"] == [-0.78, 0.0]
    assert len(g["route"]["keys"]) == 13
    assert g["route"]["length_m"] == pytest.approx(16.874, abs=0.01)
    json.dumps(g)


# ---------------------------------------------------------------------
# Status payload
# ---------------------------------------------------------------------


def test_status_keeps_the_v1_keys_and_adds_the_v2_panels(state):
    s = state.status(now=1.0)
    for key in ("core", "observation", "odom", "streams", "timestamp"):
        assert key in s
    for key in ("live", "core_api", "mission", "route", "perception", "parking",
                "clock", "trail", "dock_observation", "road_observation", "wall_time"):
        assert key in s
    assert s["live"] is False
    assert s["mission"]["phase"] == "boot"
    assert s["perception"]["tier"] is None
    json.dumps(s)


def test_observation_drives_tier_history_and_run_distribution(state):
    state.set_phase("tour")
    for c in (0.9, 0.9, 0.8, 0.6):
        state.set_observation({"visible": True, "error": 0.01, "confidence": c}, now=5.0)
    p = state.status(now=5.0)["perception"]
    assert p["tier"] == "MEMORY"
    assert p["tier_label"] == "기억"
    assert p["distribution"]["samples"] == 4
    assert p["distribution"]["pct"]["BOTH"] == 50.0
    assert len(p["history"]) == 4


def test_tiers_are_not_counted_outside_the_tour(state):
    state.set_observation({"visible": False, "confidence": 0.0}, now=1.0)
    p = state.status(now=1.0)["perception"]
    assert p["tier"] == "STOP"
    assert p["distribution"]["samples"] == 0


def test_poses_advance_route_progress_and_the_trail(state, raw_graph):
    name, way = state.graph["route"]["keys"][0].split(":")
    pts = raw_graph["segments"][name]["points"]
    pts = pts if way == "f" else pts[::-1]
    start = raw_graph["parking"]["points"][0]
    i0 = min(range(len(pts)), key=lambda i: (pts[i][0] - start[0]) ** 2 + (pts[i][1] - start[1]) ** 2)
    walk = pts[i0:i0 + 21]
    for i, (x, y) in enumerate(walk):
        state.add_pose(x, y, 0.0, now=0.1 * i)
    s = state.status(now=2.0)
    assert len(s["trail"]) == len(walk)
    expected = sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(walk, walk[1:]))
    assert s["route"]["progress_m"] == pytest.approx(expected, abs=0.01)


def test_core_poll_result_feeds_core_panel_and_phase(state):
    state.set_core_status({"ok": True,
                           "line_follow": {"mode": "OFF", "state": "OFF", "reason": "mode_off"},
                           "robot": {"mode": "DOCKING", "safety": {"estop": False}},
                           "docking": {"state": "DOCKING", "phase": "approach", "retries": 1}},
                          now=3.0)
    state.tick(now=3.0)
    s = state.status(now=3.2)
    assert s["core_api"]["reachable"] is True
    assert s["core_api"]["mode"] == "DOCKING"
    assert s["core_api"]["estop"] is False
    assert s["core_api"]["docking"]["retries"] == 1
    assert s["mission"]["phase"] == "confirm"
    assert s["mission"]["phase_label"] == "칸 확인"
    assert s["parking"]["active"] is True
    assert s["core"]["mode"] == "OFF"  # v1 key: CORE's line-follow status


def test_parking_panel_reports_tag_and_spot_error(state):
    state.set_odom({"x": -0.99, "y": 0.0, "yaw": 0.0, "speed": 0.0}, now=1.0)
    state.set_dock_observation({"visible": True, "tag_id": 0, "x": 0.24, "y": 0.0,
                                "yaw": 0.01, "range_m": 0.24, "confidence": 0.9}, now=1.0)
    park = state.status(now=1.1)["parking"]
    assert park["active"] is True
    assert park["tag_visible"] is True
    assert park["tag"]["x"] == 0.24
    assert park["spot_error"]["dist_m"] == pytest.approx(0.01, abs=1e-4)
    assert park["spot_error"]["ok"] is True


def test_live_once_a_stream_or_odom_is_fresh(state):
    state.set_odom({"x": 0.0, "y": 0.0, "yaw": 0.0, "speed": 0.0}, now=1.0)
    assert state.status(now=1.5)["live"] is True
    assert state.status(now=30.0)["live"] is False


# ---------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------


@pytest.fixture()
def server(mod, state, tmp_path):
    (tmp_path / "tour_t1").mkdir()
    (tmp_path / "tour_t1" / "results.json").write_text(
        json.dumps({"pass": True, "reason": "reached", "max_centre_dev_m": 0.03}),
        encoding="utf-8")
    (tmp_path / "tour_t1" / "track.json").write_text("[[0,0],[1,1]]", encoding="utf-8")
    state.evidence_dir = tmp_path
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), mod.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=3) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read()


def test_http_index_status_graph_and_query_strings(server):
    status, ctype, body = _get(server + "/")
    assert status == 200 and ctype.startswith("text/html")
    assert b"/runs.json" in body
    status, _, body = _get(server + "/status.json?t=1")
    assert "mission" in json.loads(body)
    status, _, body = _get(server + "/graph.json")
    assert "route" in json.loads(body)


def test_http_runs_and_one_run(server):
    _, ctype, body = _get(server + "/runs.json")
    assert ctype == "application/json"
    runs = json.loads(body)
    assert [r["id"] for r in runs["runs"]] == ["tour_t1"]
    _, _, body = _get(server + "/run/tour_t1.json")
    run = json.loads(body)
    assert run["summary"]["pass"] is True
    assert run["tracks"][0]["points"] == [[0.0, 0.0], [1.0, 1.0]]


@pytest.mark.parametrize("path", ["/run/..%2F..%2Fetc.json", "/run/nope.json", "/nope"])
def test_http_unknown_paths_are_404(server, path):
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(server + path)
    assert err.value.code == 404


def test_http_rejects_post(server):
    req = urllib.request.Request(server + "/status.json", data=b"{}")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=3)
    assert err.value.code == 501


# ---------------------------------------------------------------------
# --demo
# ---------------------------------------------------------------------


def test_demo_walks_every_phase_in_order(mod, state):
    sys.path.insert(0, str(SCRIPTS))
    import live_view_demo

    demo = live_view_demo.DemoSource(state, make_frames=False)
    seen = []
    t = 0.0
    while t < demo.cycle_s:
        demo.step(t)
        phase = state.status(now=t)["mission"]["phase"]
        if not seen or seen[-1] != phase:
            seen.append(phase)
        t += 0.25
    assert seen == ["boot", "confirm", "undock", "tour", "park", "done"]
    s = state.status(now=t)
    assert s["route"]["finished"] is True
    assert s["perception"]["distribution"]["samples"] > 0


def test_cli_has_demo_and_evidence_flags():
    source = (SCRIPTS / "lane_live_view.py").read_text(encoding="utf-8")
    assert '"--demo", action="store_true"' in source
    assert '"--evidence", type=Path, default=DEFAULT_EVIDENCE' in source
    assert "--route" in source


def test_cmake_installs_every_viewer_file_next_to_the_script():
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    for name in ("lane_live_view.py", "live_view_model.py", "live_view_demo.py"):
        assert f"scripts/{name}" in cmake
    assert "install(FILES scripts/lane_live_view.html DESTINATION lib/${PROJECT_NAME})" in cmake
