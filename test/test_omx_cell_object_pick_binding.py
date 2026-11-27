"""PR A tests: Cell PC catalog-only object view, width-clamped target binding, one-shot auto_pick, and :8771 -> :8781 proxy."""
from __future__ import annotations

import http.server
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import urllib.request
from unittest.mock import Mock

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_auto_pick  # noqa: E402
import cell_auto_pick_plan  # noqa: E402
import cell_auto_setup  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_job_api as api  # noqa: E402
import cell_job_client as client_mod  # noqa: E402
import cell_job_spec as job_spec  # noqa: E402
import cell_object_view as cov  # noqa: E402
import cell_objects as co  # noqa: E402
import cell_target_binding as ctb  # noqa: E402
import cell_task_exec  # noqa: E402

CATALOG = co.load_catalog(OMX / "object-catalog.example.json")
CAMERA = {"height_m": 0.5, "center_px": [320, 240]}
RECORD = {"homography": [[5e-4, 0, -0.16], [0, 5e-4, -0.12], [0, 0, 1]], "z_view": 0.0}
ROI = (60, 60, 580, 420)
TOP = 0.030


def _scene_jpg(rects, colour=(60, 160, 60), surface=(200, 200, 200)) -> bytes:
    img = np.full((480, 640, 3), surface, np.uint8)
    for cx, cy, length, width, ang in rects:
        pts = cv2.boxPoints(((cx, cy), (length, width), ang))
        px = [cal.parallax((320 + 2 * x, 240 + 2 * y), 0.0, TOP, CAMERA) for x, y in pts]
        cv2.fillPoly(img, [np.round(px).astype(np.int32)], colour)
    ok, enc = cv2.imencode(".jpg", img)
    assert ok
    return enc.tobytes()


def _seed_cell_workdir(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cal_file = tmp_path / "cal.json"
    cal_file.write_text(json.dumps({"schema": cal.SCHEMA, "sites": {"temp_plate_a": RECORD}, "cameras": {"top": None}}), encoding="utf-8")
    cfg = {
        "arm_id": "arm_a",
        "calibration_path": str(cal_file),
        "cameras": {"top": CAMERA},
        "plan": {"approach_m": 0.04, "limits": {"park_reach_m": 0.28}},
        "sites": {
            "temp_plate_a": {"z": TOP, "surface_z": 0.0, "detect_roi": list(ROI), "place": [0.1, 0.1], "yaw_deg": 0.0},
        },
    }
    (tmp_path / "cell-arm-a-stack.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "object-catalog-orange.json").write_text((OMX / "object-catalog.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=/opt/omx\n", encoding="utf-8")
    return tmp_path


class _ViewerServer:
    def __init__(self, jpg_fn):
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                body, seq, stamp = jpg_fn(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("X-Frame-Seq", str(seq))
                self.send_header("X-Source-Stamp", str(stamp))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def test_cell_object_view_filters_unmatched_splits_strip_corners_and_caches(tmp_path, monkeypatch):
    wd = _seed_cell_workdir(tmp_path)
    cov._DETECT_CACHE.clear()
    # One matched container-1, one unmatched 45x45 square, and two touching strips (container-2 + container-3)
    jpg = _scene_jpg([(40, -10, 30, 30, 0), (110, 60, 45, 45, 10), (-30, 0, 60, 30, 0), (-15, 31, 90, 30, 0)])
    viewer = _ViewerServer(lambda _p: (jpg, 42, 1234.5))
    try:
        monkeypatch.setattr(cell_auto_pick_plan, "choose", lambda *a, **k: pytest.fail("GET /objects must not call choose()"))
        res = cov.detect_objects(wd, "arm_a", viewer_url=viewer.url, cell_state_gen=7)
        assert res["schema"] == cov.SCHEMA and res["source_seq"] == 42 and res["cell_state_gen"] == 7
        ids = sorted(o["catalog_id"] for o in res["objects"])
        assert ids == ["container-1", "container-2", "container-3"]
        assert all(o["site"] == "temp_plate_a" and o["pickable"] for o in res["objects"])
        c2 = next(o for o in res["objects"] if o["catalog_id"] == "container-2")
        c3 = next(o for o in res["objects"] if o["catalog_id"] == "container-3")
        assert c2["corners_px"] and c3["corners_px"] and c2["corners_px"] != c3["corners_px"]
        assert next(o for o in res["objects"] if o["catalog_id"] == "container-1")["bind_tol_mm"] == 13.5
        assert not list(wd.glob("auto-*.json"))

        detect_calls = [0]
        orig_detect = co.detect

        def _spy_detect(*a, **k):
            detect_calls[0] += 1
            return orig_detect(*a, **k)

        monkeypatch.setattr(co, "detect", _spy_detect)
        # Second read at same source_seq=42 uses cache
        res2 = cov.detect_objects(wd, "arm_a", viewer_url=viewer.url, cell_state_gen=7)
        assert res2["objects"] == res["objects"]
        assert detect_calls[0] == 0
    finally:
        viewer.close()


def test_target_binding_width_clamped_uniqueness_ttl_and_admission():
    now = 2000.0
    assert ctb.bind_tol_mm(CATALOG[0]) == 13.5  # 30 mm container -> 13.5 mm even without override
    assert ctb.bind_tol_mm(CATALOG[0], 20.0) == 13.5  # cannot widen past width-clamped cap
    assert ctb.bind_tol_mm({"width_mm": 60, "length_mm": 80}) == 20.0  # >= 45 mm capped at 20.0 mm

    # Neighbor 30 mm away must NEVER satisfy missing object at (0, 0)
    objs = [{"matched": True, "object": "container-1", "centre_mm": [30.0, 0.0]}]
    m, code, _ = ctb.bind_observed(
        objs, CATALOG, {"catalog_id": "container-1", "centroid_mm": [0.0, 0.0], "observed_at": now - 1.0, "source_seq": 10},
        {"source_seq": 10}, now_fn=lambda: now,
    )
    assert m == [] and code == "TARGET_NOT_FOUND_OR_MOVED"

    # Ambiguity
    dup = [
        {"matched": True, "object": "container-1", "centre_mm": [1.0, 0.0]},
        {"matched": True, "object": "container-1", "centre_mm": [4.0, 0.0]},
    ]
    _, code_amb, _ = ctb.bind_observed(dup, CATALOG, {"catalog_id": "container-1", "centroid_mm": [2.0, 0.0], "observed_at": now}, now_fn=lambda: now)
    assert code_amb == "TARGET_AMBIGUOUS"

    # Catalog mismatch, unknown, expired, seq regressed
    _, code_mis, _ = ctb.bind_observed([{"matched": True, "object": "container-2", "centre_mm": [0.5, 0.5]}], CATALOG, {"catalog_id": "container-1", "centroid_mm": [0.0, 0.0], "observed_at": now}, now_fn=lambda: now)
    assert code_mis == "TARGET_CATALOG_MISMATCH"
    _, code_unk, _ = ctb.bind_observed(dup, CATALOG, {"catalog_id": "nope", "centroid_mm": [0.0, 0.0], "observed_at": now}, now_fn=lambda: now)
    assert code_unk == "TARGET_CATALOG_UNKNOWN"
    _, code_exp, _ = ctb.bind_observed(dup[:1], CATALOG, {"catalog_id": "container-1", "centroid_mm": [1.0, 0.0], "observed_at": now - 16.0}, now_fn=lambda: now)
    assert code_exp == "TARGET_OBSERVATION_EXPIRED"
    _, code_seq, _ = ctb.bind_observed(dup[:1], CATALOG, {"catalog_id": "container-1", "centroid_mm": [1.0, 0.0], "observed_at": now, "source_seq": 12}, {"source_seq": 11}, now_fn=lambda: now)
    assert code_seq == "TARGET_FRAME_SEQ_REGRESSED"
    _, code_nan, _ = ctb.bind_observed(dup[:1], CATALOG, {"catalog_id": "container-1", "centroid_mm": [1.0, 0.0], "observed_at": float("nan")}, now_fn=lambda: now)
    assert code_nan == "TARGET_OBSERVATION_EXPIRED"

    assert ctb.check_admission({"expected_cell_state_gen": 4}, 5)["error_code"] == "STALE_CELL_STATE"
    assert ctb.check_admission({"target_catalog_id": "container-1", "target_centroid_mm": [0.0, 0.0], "target_observed_at": now - 20.0}, 5, now_fn=lambda: now)["error_code"] == "TARGET_OBSERVATION_EXPIRED"
    assert ctb.check_admission({"target_catalog_id": "container-1", "target_centroid_mm": [0.0, 0.0], "target_observed_at": float("nan")}, 5, now_fn=lambda: now)["error_code"] == "TARGET_OBSERVATION_EXPIRED"
    assert ctb.check_admission({"target_catalog_id": "container-1"}, 5)["error_code"] == "TARGET_BINDING_INCOMPLETE"
    nan_args = cell_auto_setup.pick_parser("doc").parse_args(["--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "10", "10", "--dest", "stand", "--target-catalog-id", "container-1", "--target-centroid-mm", "1,2", "--target-observed-at", "nan"])
    with pytest.raises(SystemExit):
        cell_auto_setup.validate_pick_args(nan_args)


def test_cell_auto_pick_bound_one_shot_and_pre_motion_veto(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    now = time.time()
    cal_p = tmp_path / "cal.json"
    cal_p.write_text("{}", encoding="utf-8")
    config = {
        "arm_id": "arm_a",
        "params": {"auto.attempts": 3},
        "cameras": {"top": CAMERA},
        "sites": {
            "belt": {"surface_z": 0.0, "place": [0.1, 0.1], "yaw_deg": 0.0},
            "stand": {"surface_z": 0.0, "place": [0.2, 0.0], "yaw_deg": 0.0},
        },
        "_target_binding": {"catalog_id": "container-1", "centroid_mm": [10.0, 20.0], "observed_at": now, "source_seq": 5},
        "_one_shot": True,
    }
    objects = [
        {"matched": True, "object": "container-1", "centre_mm": [10.0, 20.0], "raw_m": [0.01, 0.02], "long_axis_deg": 0.0},
        {"matched": True, "object": "container-1", "centre_mm": [80.0, 20.0], "raw_m": [0.08, 0.02], "long_axis_deg": 0.0},
    ]

    class FakeCell:
        def act(self, cmd):
            return {"ok": True}

        def frame(self, _cam):
            return np.zeros((480, 640, 3), np.uint8)

    monkeypatch.setattr(cell_auto_pick.cell_auto_evidence, "source_frame", lambda _c, _p: ({"image": FakeCell().frame("top"), "source_seq": 5}, {"path": "x"}, None))
    monkeypatch.setattr(cell_auto_pick.cell_auto_evidence, "destination_view", lambda *a: (None, None))
    monkeypatch.setattr(cell_auto_pick, "observe", lambda *a, **k: (FakeCell().frame("top"), np.zeros((360, 520), np.uint8), list(objects), None))
    monkeypatch.setattr(cell_auto_pick, "finger_room_view", lambda *a, **k: None)
    seen_counts = []

    def fake_choose(_cell, _cfg, _cal, _src, _dst, _pxy, _roi, cand_objs, *_a, **_k):
        seen_counts.append([o["centre_mm"] for o in cand_objs])
        obj = cand_objs[0]
        return ([{
            "object": obj, "entry": CATALOG[0], "offset": 90.0, "bias_region": None, "bias_mm": [0.0, 0.0],
            "library": tmp_path / "lib.json", "pick": {"x": 0.01, "y": 0.02, "yaw_deg": 0.0},
            "place": {"x": 0.2, "y": 0.0}, "approach_m": 0.04, "plan": {},
        }], [])

    monkeypatch.setattr(cell_auto_pick, "choose", fake_choose)
    monkeypatch.setattr(cell_auto_pick, "self_calibrate", lambda *a, **k: ({}, None))
    monkeypatch.setattr(cell_auto_pick.cell_auto_evidence, "pre_motion_frame", lambda *a, **k: (None, {"path": "b"}, "target moved 7.2 mm"))
    monkeypatch.setattr(cell_auto_pick.cell_attempts, "record", lambda *a, **k: "att-1")

    choices = type("C", (), {"data": {"values": {}}})()
    res = cell_auto_pick.run_auto(FakeCell(), config, {"sites": {}}, cal_p, CATALOG, list(ROI), "belt", "stand", work, choices)
    assert seen_counts == [[[10.0, 20.0]]]
    assert res["refusal_code"] == "TARGET_MOVED_BEFORE_GRASP"
    assert len(res["attempts"]) == 1


def test_job_api_objects_admission_and_exec_handoff(tmp_path, monkeypatch):
    wd = _seed_cell_workdir(tmp_path)
    cov._DETECT_CACHE.clear()
    jpg = _scene_jpg([(40, -10, 30, 30, 0)])
    viewer = _ViewerServer(lambda _p: (jpg, 15, time.time()))
    monkeypatch.setattr(api, "_check_arm_incident", lambda _a: None)
    monkeypatch.setattr(api, "_session_lock_held", lambda _a, _l=None: False)
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda _l=None: False)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _l=None: False)
    monkeypatch.setattr(api, "prove_job", lambda *a, **k: ({"ok": True}, None))
    runner = api.Runner(wd, lock_dir=wd)
    tok = "h" * 32
    srv = api.make_server("127.0.0.1", 0, tok, runner, viewer=viewer.url)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/objects?arm=arm_a", headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.headers.get("Cache-Control") == "no-store"
            assert resp.headers.get("X-Cell-State-Gen") == str(runner.state_gen())
            data = json.loads(resp.read().decode("utf-8"))
            assert data["schema"] == cov.SCHEMA and [o["catalog_id"] for o in data["objects"]] == ["container-1"]

        cli = client_mod.CellJobClient(f"http://127.0.0.1:{srv.server_port}", tok)
        with pytest.raises(client_mod.CellJobError) as exc:
            cli.start("auto_pick", {
                "arm": "arm_a", "config": "cell-arm-a-stack.json", "catalog": "object-catalog-orange.json",
                "roi": list(ROI), "source": "temp_plate_a", "dest": "stand",
                "expected_cell_state_gen": runner.state_gen() + 1,
                "target_catalog_id": "container-1", "target_centroid_mm": [40.0, -10.0], "target_observed_at": time.time(),
            })
        assert exc.value.status_code == 409

        argv = job_spec.build_argv(job_spec.JOBS["auto_pick_dry_run"], {
            "config": "cell-arm-a-stack.json", "catalog": "object-catalog-orange.json",
            "roi": list(ROI), "source": "temp_plate_a", "dest": "stand",
            "target_object_ref": "det:15:0", "target_catalog_id": "container-1",
            "target_centroid_mm": [40.0, -10.0], "target_observed_at": time.time(), "target_tolerance_mm": 13.5, "one_shot": True,
        }, wd)
        assert "--one-shot" in argv and "--target-catalog-id" in argv and "container-1" in argv
        with pytest.raises(ValueError):
            job_spec.build_argv(job_spec.JOBS["auto_pick_dry_run"], {
                "config": "cell-arm-a-stack.json", "catalog": "object-catalog-orange.json",
                "roi": list(ROI), "source": "temp_plate_a", "dest": "stand",
                "target_catalog_id": "unmatched", "target_centroid_mm": [0.0, 0.0], "target_observed_at": time.time(),
            }, wd)
    finally:
        srv.shutdown(); srv.server_close(); viewer.close()

    cli_args = ctb.handoff_cli_args({"target_object": {"catalog_id": "container-1", "centroid_mm": [1.0, 2.0], "observed_at": 100.0, "source_seq": 9}})
    assert cli_args == ["--one-shot", "--target-catalog-id", "container-1", "--target-centroid-mm", "1.0,2.0", "--target-observed-at", "100.0", "--target-source-seq", "9"]
    ap_args = cell_auto_setup.pick_parser("doc").parse_args(["--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "10", "10", "--dest", "stand", *cli_args])
    assert ap_args.target_catalog_id == "container-1" and ap_args.one_shot is True


def test_bench_record_http_objects_recording_and_strict_8781_proxy(tmp_path, monkeypatch):
    import bench_record_http as brh
    from test_omx_bench_record import _setup

    bench, _, _, commands = _setup(tmp_path, monkeypatch)
    wd = _seed_cell_workdir(cov._bench_workdir(bench))
    assert wd == bench.prep / "work"
    tok_p = tmp_path / "job-api.token"
    tok_p.write_text("h" * 32, encoding="utf-8")
    tok_p.chmod(0o600)

    # 503 when :8781 token not configured, unreadable, or raises SystemExit
    bench._config["job_api_token_file"] = str(tmp_path / "missing.token")
    code_no_tok, body_no_tok = cov.proxy_pick_place(bench, {
        "arm": "arm_a", "dest_site": "temp_plate_a", "idempotency_key": "k-1",
        "target_object": {"catalog_id": "container-1", "centroid_mm": [40.0, -10.0], "observed_at": time.time()},
    })
    assert code_no_tok == 503 and body_no_tok["error_code"] == "JOB_API_UNCONFIGURED"
    bad_tok_p = tmp_path / "bad.token"
    bad_tok_p.write_text("short", encoding="utf-8")
    bench._config["job_api_token_file"] = str(bad_tok_p)
    with monkeypatch.context() as mp:
        mp.setattr(cov, "read_token_file", lambda _p: (_ for _ in ()).throw(SystemExit("token too short")))
        code_sys, body_sys = cov.proxy_pick_place(bench, {
            "arm": "arm_a", "dest_site": "temp_plate_a", "idempotency_key": "k-1",
            "target_object": {"catalog_id": "container-1", "centroid_mm": [40.0, -10.0], "observed_at": time.time()},
        })
    assert code_sys == 503 and body_sys["error_code"] == "JOB_API_UNCONFIGURED"
    bench._config["job_api_token_file"] = str(tok_p)
    code_bad_roi, _ = cov.proxy_pick_place(bench, {
        "arm": "arm_a", "dest_site": "temp_plate_a", "roi": 123, "idempotency_key": "k-1",
        "target_object": {"catalog_id": "container-1", "centroid_mm": [40.0, -10.0], "observed_at": time.time()},
    })
    assert code_bad_roi == 400
    code_bad_seq, _ = cov.proxy_pick_place(bench, {
        "arm": "arm_a", "dest_site": "temp_plate_a", "idempotency_key": "k-1",
        "target_object": {"catalog_id": "container-1", "centroid_mm": [40.0, -10.0], "observed_at": time.time(), "source_seq": "bad"},
    })
    assert code_bad_seq == 400

    seen_calls = []

    class JobApiMock(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_POST(self):
            ln = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(ln).decode("utf-8"))
            seen_calls.append((self.path, self.headers.get("Authorization"), self.headers.get("Idempotency-Key"), payload))
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            raw = json.dumps({"id": "job-42"}).encode("utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    j_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), JobApiMock)
    threading.Thread(target=j_srv.serve_forever, daemon=True).start()
    viewer = _ViewerServer(lambda _p: (b"jpg-bytes", 77, 999.5))
    monkeypatch.setattr(brh, "VIEWER", viewer.url)
    bench._config["job_api_url"] = f"http://127.0.0.1:{j_srv.server_port}"
    bench._config["job_api_token_file"] = str(tok_p)
    srv = brh.make_server(bench, 0, bind="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/camera/top.jpg", timeout=5) as resp:
            assert resp.read() == b"jpg-bytes"
            assert resp.headers.get("X-Frame-Seq") == "77"
            assert resp.headers.get("X-Source-Stamp") == "999.5"

        bench.state["status"] = "recording"
        bench.live_preview = Mock(frame=lambda _lbl: b"jpg")
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/api/objects?arm=arm_a", timeout=5) as resp:
            rec_obs = json.loads(resp.read().decode("utf-8"))
        assert rec_obs["status"] == "recording_active" and rec_obs["objects"] == []
        bench.state["status"] = "idle"
        bench.live_preview = None

        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_port}/api/pick_place",
            data=json.dumps({
                "arm": "arm_a", "dest_site": "temp_plate_a", "dry_run": False, "idempotency_key": "idem-99",
                "target_object": {"catalog_id": "container-1", "centroid_mm": [40.0, -10.0], "observed_at": time.time(), "object_ref": "det:1:0"},
            }).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-Bench": "1"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert json.loads(resp.read().decode("utf-8")) == {"id": "job-42"}
        assert len(seen_calls) == 1
        path, auth, idem, pl = seen_calls[0]
        assert path == "/jobs/auto_pick" and auth == f"Bearer {'h' * 32}" and idem == "idem-99" and pl["one_shot"] is True

        dry_req = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_port}/api/pick_place",
            data=json.dumps({
                "arm": "arm_a", "dest_site": "temp_plate_a", "dry_run": True,
                "target_object": {"catalog_id": "container-1", "centroid_mm": [40.0, -10.0], "observed_at": time.time(), "object_ref": "det:1:0"},
            }).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-Bench": "1"},
        )
        with urllib.request.urlopen(dry_req, timeout=5) as resp:
            assert json.loads(resp.read().decode("utf-8")) == {"id": "job-42"}
        assert seen_calls[-1][0] == "/jobs/auto_pick_dry_run"
        assert "arm" not in seen_calls[-1][3] and "one_shot" not in seen_calls[-1][3]
        assert not commands  # never spawns cell_auto_pick.py directly
    finally:
        srv.shutdown(); srv.server_close(); j_srv.shutdown(); j_srv.server_close(); viewer.close()
