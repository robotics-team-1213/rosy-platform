"""Calibration screen server (D-1004): read-only without Account, session and capability gates, `by` from the session."""
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "applications/calibration"))
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import calibration_web as web  # noqa: E402
import cell_calibration_view  # noqa: E402
import cell_requests as cr  # noqa: E402

REQUEST = dict(id="belt-end-1", kind="measure", item="belt", question="axis to belt end", how=["tape"],
               candidates=dict(sim=156, camera=215), unit="mm", tolerance=20, means=dict(sim="design", camera="camera"))
ORIGIN = "https://cal.test"


class Account:
    callback = ORIGIN + "/api/account/callback"
    resource = "site:one"
    profile_url = "https://account.test/console/profile"

    def __init__(self):
        self.operate = True

    def resolve(self, cookie):
        if cookie != "valid":
            return None
        return SimpleNamespace(sub="acct-1", sid="family", rev=1, aud="site:one", grants=[],
                               permits=lambda resource, cap: resource == "site:one" and (cap == "calibration.operate") and self.operate)

    def profile(self, cookie):
        return {"account_id": "acct-1", "login": "kim", "display_name": "Kim"}

    def retry_revocations(self):
        pass


def call(url, path, *, cookie="", origin="", body=None, method=None):
    headers = {k: v for k, v in (("Cookie", f"{web.SESSION_COOKIE}={cookie}" if cookie else ""), ("Origin", origin)) if v}
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(url + path, data=data, headers=headers, method=method), timeout=5) as r:
            return r.status, r.read()
    except HTTPError as error:
        return error.code, error.read()


@pytest.fixture
def store(tmp_path):
    (tmp_path / "pic.png").write_bytes(b"\x89PNG-bytes")
    cr.open_request(REQUEST, tmp_path / "pic.png", root=tmp_path / "store")
    (tmp_path / "secret.png").write_bytes(b"secret")
    return tmp_path / "store"


def serve(store, account):
    server = web.make_server(store, 0, account)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def open_screen(store):
    server, url = serve(store, None)
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture
def account_screen(store):
    account = Account()
    server, url = serve(store, account)
    yield url, account
    server.shutdown()
    server.server_close()


def test_without_account_it_lists_and_shows_but_never_answers(open_screen, store):
    status, body = call(open_screen, web.API)
    rows = json.loads(body)
    assert status == 200 and rows["can_operate"] is False and rows["requests"][0]["id"] == "belt-end-1"
    assert json.loads(call(open_screen, web.API + "/belt-end-1")[1])["candidates"] == REQUEST["candidates"]
    assert call(open_screen, web.API + "/belt-end-1/image")[1] == b"\x89PNG-bytes"
    assert json.loads(call(open_screen, "/api/account/session")[1])["enabled"] is False
    status, _ = call(open_screen, web.API + "/belt-end-1/answer", origin=ORIGIN, body={"value": 160})
    assert status == 403 and cr.load("belt-end-1", store)["status"] == "open"
    assert call(open_screen, "/")[0] == 200 and call(open_screen, "/common/tokens.css")[0] == 200


def test_page_and_assets_are_served_but_not_arbitrary_files(open_screen):
    assert call(open_screen, "/app.js")[0] == 200
    for path in ("/common/../calibration_web.py", "/common/AGENTS.md", "/../calibration_web.py", "/.git"):
        assert call(open_screen, path)[0] == 404


def test_host_header_must_be_local(open_screen):
    request = Request(open_screen + web.API, headers={"Host": "evil.test"})
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 403


def test_with_account_reading_needs_a_session(account_screen):
    url, _ = account_screen
    assert call(url, web.API)[0] == 401 and call(url, web.API + "/belt-end-1")[0] == 401
    assert call(url, web.API + "/belt-end-1/image")[0] == 401
    assert call(url, web.API, cookie="valid")[0] == 200


def test_answer_needs_session_origin_and_capability(account_screen, store):
    url, account = account_screen
    path, body = web.API + "/belt-end-1/answer", {"value": 212}
    assert call(url, path, origin=ORIGIN, body=body)[0] == 401
    assert call(url, path, cookie="valid", origin="https://evil.test", body=body)[0] == 403
    assert call(url, path, cookie="valid", body=body)[0] == 403
    account.operate = False
    status, text = call(url, path, cookie="valid", origin=ORIGIN, body=body)
    assert status == 403 and "calibration.operate" in json.loads(text)["error"]
    assert json.loads(call(url, web.API, cookie="valid")[1])["can_operate"] is False
    assert cr.load("belt-end-1", store)["status"] == "open"


def test_answer_is_recorded_by_the_engine_with_the_session_name(account_screen, store):
    url, _ = account_screen
    path = web.API + "/belt-end-1/answer"
    # a typed `by` is ignored: the name comes from the session
    status, text = call(url, path, cookie="valid", origin=ORIGIN, body={"value": 212, "note": "tape", "by": "someone else"})
    done = json.loads(text)
    assert status == 200 and done["answer"]["verdict"] == "camera" and done["answer"]["by"] == "Kim (acct-1)"
    assert cr.load("belt-end-1", store)["answer"]["note"] == "tape"
    status, text = call(url, path, cookie="valid", origin=ORIGIN, body={"value": 160})
    assert status == 409 and "already" in json.loads(text)["error"]
    assert cr.load("belt-end-1", store)["answer"]["value"] == 212.0


@pytest.mark.parametrize("body", [{}, {"value": "x"}, {"value": True}, {"value": 1, "note": "n" * 301}, {"result": "pass"},
                                  {"value": 1 << 4000}, {"value": 1e300}])  # a huge int once overflowed float() in the engine
def test_bad_answers_are_422_and_leave_the_request_open(account_screen, store, body):
    url, _ = account_screen
    assert call(url, web.API + "/belt-end-1/answer", cookie="valid", origin=ORIGIN, body=body)[0] == 422
    assert cr.load("belt-end-1", store)["status"] == "open"


def test_unknown_or_hostile_ids_and_images_are_refused(open_screen, store):
    for rid in ("nope", "..%2Fsecret", "a.b", "%2e%2e"):
        assert call(open_screen, f"{web.API}/{rid}")[0] == 404
    # a request whose stored image names a path outside the store gets no file
    data = cr.load("belt-end-1", store)
    data["image"] = "../secret.png"
    (store / "belt-end-1.json").write_text(json.dumps(data), encoding="utf-8")
    assert call(open_screen, web.API + "/belt-end-1/image")[0] == 404
    data["image"] = "belt-end-1.json"
    (store / "belt-end-1.json").write_text(json.dumps(data), encoding="utf-8")
    assert call(open_screen, web.API + "/belt-end-1/image")[0] == 404


def test_check_request_takes_pass_or_fail(account_screen, store):
    url, _ = account_screen
    cr.open_request(dict(id="pose-1", kind="check", item="pose", question="q", how=["h"], steps=["look"]), root=store)
    status, text = call(url, web.API + "/pose-1/answer", cookie="valid", origin=ORIGIN, body={"result": "fail"})
    assert status == 200 and json.loads(text)["answer"]["result"] == "fail"
    rows = {r["id"]: r for r in json.loads(call(url, web.API, cookie="valid")[1])["requests"]}
    assert rows["pose-1"]["verdict"] == "fail" and rows["belt-end-1"]["status"] == "open"


def _write_test_profile(tmp_path: Path, live_url: str, *, include_tcp_x: bool = False) -> Path:
    arm_dir = tmp_path / "arm_test"
    arm_dir.mkdir(parents=True, exist_ok=True)
    ref_img = arm_dir / "ref.jpg"
    ref_img.write_bytes(b"\xff\xd8\xff\xd9")
    cfg = {
        "arm_id": "arm_a",
        "work_dir": "w1",
        "calibration_path": str(arm_dir / "calibration.json"),
        "cameras": {"top": {"url": live_url, "height_m": 0.6, "center_px": [320, 240]}},
        "preflight": {"reference_top": str(ref_img)},
        "calibrate": {"map_sites": ["pallet"], "map_points": [[0.10, 0.08], [0.12, 0.08], [0.12, 0.12], [0.10, 0.12]]},
        "sites": {"pallet": {"surface_z": -0.01, "start": [0.15, 0.03], "place": [0.15, 0.115]}},
    }
    if include_tcp_x:
        cfg["tcp_x_m"] = 0.074
    (arm_dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    cal_data = {
        "schema": "rosy.omx-cell-calibration.v1",
        "sites": {
            "pallet": {
                "z_view": 0.14,
                "homography": [[0.0, -0.001, 0.3], [0.001, 0.0, -0.1], [0.0, 0.0, 1.0]],
                "loo_error_mm": {"max": 3.1, "mean": 1.8},
                "points": [
                    {"pixel": [220, 200], "arm_m": [0.10, 0.08]},
                    {"pixel": [220, 180], "arm_m": [0.12, 0.08]},
                    {"pixel": [180, 180], "arm_m": [0.12, 0.12]},
                    {"pixel": [180, 200], "arm_m": [0.10, 0.12]},
                ],
            }
        },
    }
    (arm_dir / "calibration.json").write_text(json.dumps(cal_data), encoding="utf-8")
    (arm_dir / "live.json").write_text(json.dumps({"t": 1.0, "state": [0.0, -0.5, 0.8, 0.4, 0.0]}), encoding="utf-8")
    reg = tmp_path / "profiles.json"
    reg.write_text(json.dumps([{"id": "arm_a", "config_path": str(arm_dir / "config.json"),
                                "live_path": str(arm_dir / "live.json")}]), encoding="utf-8")
    return reg


def test_unconfigured_profiles_serves_static_grid_assets(open_screen):
    assert call(open_screen, "/grid.js")[0] == 200 and call(open_screen, "/requests.js")[0] == 200
    status, body = call(open_screen, web.PROFILES_API)
    data = json.loads(body)
    assert status == 200 and data["configured"] is False and data["profiles"] == []


def test_profiles_endpoint_is_account_gated_and_survives_missing_tcp_x(store, tmp_path, monkeypatch):
    reg = _write_test_profile(tmp_path, "http://127.0.0.1:1/unreachable.jpg", include_tcp_x=False)
    monkeypatch.setattr(web.cell_calibration_view.cell_pivot, "joints_tcp", lambda *a: (_ for _ in ()).throw(SystemExit(2)))
    account = Account()
    server = web.make_server(store, 0, account, profiles_path=reg)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        assert call(url, web.PROFILES_API)[0] == 401
        assert call(url, web.PROFILES_API + "/arm_a/frame/reference")[0] == 401
        status, body = call(url, web.PROFILES_API, cookie="valid")
        assert status == 200
        prof = json.loads(body)["profiles"][0]
        assert prof["id"] == "arm_a" and prof["sites"]["pallet"]["map"]["inlier_count"] == 4
        assert prof["robot_status"]["live"]["present"] is True and prof["robot_status"]["live"]["tcp"] is None
        assert call(url, web.PROFILES_API, cookie="valid", origin=ORIGIN, body={})[0] == 405
        assert call(url, web.PROFILES_API + "/arm_a/frame/reference", cookie="valid") == (200, b"\xff\xd8\xff\xd9")
        assert call(url, web.PROFILES_API + "/arm_a/frame/live", cookie="valid")[0] == 503
    finally:
        server.shutdown()
        server.server_close()


def test_live_frame_proxy_allows_loopback_and_blocks_remote_ssrf(store, tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class CamHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", "8")
            self.end_headers()
            self.wfile.write(b"\x89PNG-cam")

    cam = HTTPServer(("127.0.0.1", 0), CamHandler)
    threading.Thread(target=cam.serve_forever, daemon=True).start()
    try:
        reg = _write_test_profile(tmp_path, f"http://127.0.0.1:{cam.server_port}/top.jpg", include_tcp_x=True)
        server = web.make_server(store, 0, None, profiles_path=reg)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            assert call(url, web.PROFILES_API + "/arm_a/frame/live") == (200, b"\x89PNG-cam")
            # mutate live URL in registry to a non-loopback host -> must refuse (SSRF guard)
            items = json.loads(reg.read_text(encoding="utf-8"))
            items[0]["live_frame_url"] = "http://169.254.169.254/latest/meta-data"
            reg.write_text(json.dumps(items), encoding="utf-8")
            assert call(url, web.PROFILES_API + "/arm_a/frame/live")[0] == 403
        finally:
            server.shutdown()
            server.server_close()
    finally:
        cam.shutdown()
        cam.server_close()


def test_cross_verify_merges_depth_verify_and_touch_receipts_into_profile_snapshot(store, tmp_path):
    reg = _write_test_profile(tmp_path, "http://127.0.0.1:1/unused.jpg", include_tcp_x=True)
    work = tmp_path / "arm_test" / "w1"
    work.mkdir(parents=True, exist_ok=True)
    (work / "surface-pallet.json").write_text(json.dumps({"result": "touched", "surface_z": -0.011, "measured": "2026-11-16 00:01"}))
    (work / "depth-verify.json").write_text(json.dumps({
        "schema": "rosy.omx-cell-depth-verify.v1",
        "measured": "2026-11-16T00:02:00+00:00",
        "camera_top": {"config_height_m": 0.6, "cam_to_table_mm": 605.4, "plate_mm": 14.0},
        "sites": {"pallet": {"depth_surface_z_m": 0.018, "depth_diff_mm": 28.0, "place_vs_start_step_mm": 28.0,
                             "flags": ["depth_diff_gt_6mm", "place_vs_start_step_gt_8mm"]}},
    }))
    server = web.make_server(store, 0, None, profiles_path=reg)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        _, html = call(url, "/")
        html_txt = html.decode("utf-8")
        assert "교차 검증 (Eval · Depth · Touch · Map · FK · Drift)" in html_txt and "cvDepthTag" in html_txt and "cvEvalTag" in html_txt and "cvDriftTag" in html_txt
        status, body = call(url, web.PROFILES_API)
        assert status == 200
        prof = json.loads(body)["profiles"][0]
        cv = prof["cross_verify"]
        assert cv["present"] is True and cv["depth"]["cam_to_table_mm"] == 605.4
        assert cv["depth"]["verdict"] == "fail" and cv["touch"]["verdict"] == "pass"
        site = prof["sites"]["pallet"]
        assert site["depth_surface_z"] == 0.018 and site["depth_diff_mm"] == 28.0
        assert site["place_vs_start_step_mm"] == 28.0
        assert site["touch_surface_z"] == -0.011 and site["touch_diff_mm"] == -1.0
    finally:
        server.shutdown()
        server.server_close()


def test_cell_calibration_view_bundle_flags_over_limit_bias_and_ssrf_urls(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    cal = work / "cal.json"
    cal.write_text(json.dumps({"sites": {"pinky": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}))
    (work / "cal.bias.json").write_text(json.dumps({
        "schema": "rosy.omx-cell-bias.v1",
        "regions": [{"site": "pinky", "point_m": [0.03, 0.18], "bias_mm": [26.0, 20.0], "map_sha": "abc"}],
    }))
    cfg = tmp_path / "arm_s.json"
    cfg.write_text(json.dumps({
        "arm_id": "arm_s", "work_dir": str(work), "calibration_path": str(cal),
        "sites": {"pinky": {"surface_z": 0.028, "place": [0.02, 0.18]}},
        "cameras": {"top": {"url": "http://127.0.0.1:8767/frame/arm_s_top.jpg", "height_m": 0.65}},
    }))
    reg = tmp_path / "profiles.json"
    reg.write_text(json.dumps([{"id": "arm_s", "label": "Arm S", "config_path": str(cfg),
                                "live_frame_url": "http://127.0.0.1:8767/frame/arm_s_top.jpg"}]))
    entries = cell_calibration_view.load_profile_registry(reg)
    bundle = cell_calibration_view.build_bundle(entries, now_ts=1000.0)
    prof = bundle["profiles"][0]
    assert prof["bias"]["regions"][0]["over_limit"] is True
    assert prof["cross_verify"]["bias"]["verdict"] == "fail" and prof["cross_verify"]["bias"]["over_limit_regions"] == 1
    assert prof["cross_verify"]["eval_verdict"] == "hold"
    assert any(h["code"] == "bias_over_limit:pinky" for h in prof["hygiene"])
    assert cell_calibration_view.is_allowed_frame_url("http://127.0.0.1:8767/frame/top.jpg") is True
    assert cell_calibration_view.is_allowed_frame_url("http://169.254.169.254/latest") is False
