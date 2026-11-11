"""cell_params_web: guards and motion values stay locked, a save is validated and recorded, nothing is written while a
session runs or after the file moved, and the page answers only on the local host."""
import contextlib
import http.client
import json
from pathlib import Path
import sys
import threading

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_params as prm
    import cell_params_web as web
finally:
    sys.path.remove(str(OMX))

FREE = "objects.chroma"


@pytest.fixture
def path(tmp_path):
    file = tmp_path / "params.json"
    file.write_text(json.dumps({"schema": prm.SCHEMA, "params": {
        FREE: {"value": 25.0, "unit": "lab", "source": "measured", "evidence": "first look"},
        "auto.temp_stop_c": {"value": 50, "unit": "C", "source": "measured", "evidence": "kept"}}}), encoding="utf-8")
    return file


def files(path, hold=contextlib.nullcontext):
    return web.ParamFiles({"stack": path}, busy=lambda: False, hold=hold)


def save(store, path, **overrides):
    sha = store.snapshot()["files"][0].get("file_sha")
    return store.save({"file": "stack", "base_sha": sha, "changes": {FREE: 30.0}, "note": "그림자", **overrides})


@pytest.mark.parametrize("name", [
    "auto.temp_stop_c", "auto.pwm_fraction", "auto.pwm_window_s", "auto.max_gross_kg", "auto.grasp_depth_m",
    "safety.bus_watchdog_ms", "runner.contact_lag", "runner.contact_loaded_max", "windup.rest_pwm", "windup.jaw_pwm",
    "upkeep.jaw_gap", "jitter.pwm_std", "loadcheck.risky_share", "loadcheck.refuse_unknown", "corridor.half_width_mm",
    "corridor.clear_z_m", "zone.takeover", "push.speed_m_s", "push.height_m", "pivot.clear_above_m", "pivot.grip_closed",
    "gripper.held_30mm", "wrist.max_step_mm", "wrist.max_total_mm", "look.max_total_mm", "pinch.max_step_mm",
    "reach.max_mm", "pinch.enabled", "wrist.enabled", "feel.step_mm", "place.margin_mm", "wrist.tip_to_top_mm",
    "reach.gain", "wrist.servo_gain", "wrist.topmap_disagree_mm", "wrist.axis_tol_deg", "look.mark_err_mm",
    "objects.split_gap_mm", "objects.split_stagger_mm", "pinch.min_gap_mm", "pinch.width_tol"])
def test_guards_and_motion_values_are_locked(name):
    assert web.lock_reason(name)


def test_a_new_group_or_unit_is_locked_until_someone_decides(monkeypatch):
    monkeypatch.setitem(prm.DEFAULTS, "newguard.limit", (1.0, "mm", 0, 2))
    monkeypatch.setitem(prm.DEFAULTS, "objects.newunit", (1.0, "newton", 0, 2))
    assert web.lock_reason("newguard.limit") and web.lock_reason("objects.newunit")


def test_vision_thresholds_can_be_tuned():
    free = [name for name in prm.DEFAULTS if not web.lock_reason(name)]
    assert {FREE, "objects.min_px", "wrist.tol_mm", "look.tol_mm", "reach.tol_mm", "track.min_inliers"} <= set(free)
    assert all(prm.DEFAULTS[name][1] in web.VISION_UNITS for name in free)


def test_every_parameter_is_listed_with_its_file_value_or_default(path):
    rows = {row["name"]: row for row in files(path).snapshot()["files"][0]["rows"]}
    assert set(rows) == set(prm.DEFAULTS)
    assert rows[FREE]["source"] == "measured" and rows[FREE]["evidence"] == "first look" and not rows[FREE]["locked"]
    assert rows["auto.temp_stop_c"]["value"] == 50 and rows["auto.temp_stop_c"]["locked"]
    assert rows["objects.min_px"]["in_file"] is False and rows["objects.min_px"]["source"] == "default"


def test_a_save_is_loadable_keeps_the_other_entries_and_records_what_it_replaced(path):
    before = json.loads(path.read_text(encoding="utf-8"))["params"]
    result = save(files(path), path)
    after = json.loads(path.read_text(encoding="utf-8"))["params"]
    assert prm.load(path)["values"][FREE] == 30.0 and result["params_sha"] == prm.load(path)["sha"]
    assert after["auto.temp_stop_c"] == before["auto.temp_stop_c"]
    assert after[FREE]["source"] == "tuned" and "25.0 -> 30.0: 그림자" in after[FREE]["evidence"]
    row = json.loads(path.with_name("params.json.history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["note"] == "그림자" and row["changes"] == [{"name": FREE, "from": 25.0, "to": 30.0, "before": before[FREE]}]
    assert result["history"][0]["after_sha"] == result["file_sha"]
    assert sorted(item.name for item in path.parent.iterdir()) == ["params.json", "params.json.history.jsonl"]


@pytest.mark.parametrize("overrides,message", [
    ({"changes": {"auto.temp_stop_c": 80}}, "바꿀 수 없습니다"), ({"changes": {"objects.nope": 1}}, "알 수 없는"),
    ({"changes": {FREE: 500.0}}, "outside"), ({"changes": {FREE: "30"}}, "number"), ({"changes": {FREE: True}}, "number"),
    ({"changes": {"objects.min_px": 150.5}}, "integer"), ({"changes": {}}, "바뀐 값"), ({"note": " "}, "근거"),
    ({"note": "두\n줄"}, "근거"), ({"note": "x" * 301}, "근거"), ({"file": "other"}, "등록되지")])
def test_a_refused_save_writes_nothing(path, overrides, message):
    before = path.read_bytes()
    with pytest.raises(ValueError, match=message):
        save(files(path), path, **overrides)
    assert path.read_bytes() == before and not path.with_name("params.json.history.jsonl").exists()


def test_a_real_session_lock_is_seen_and_refuses_a_save(path, tmp_path, monkeypatch):
    pytest.importorskip("fcntl")
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, str(OMX))
    try:
        import joint_tune
    finally:
        sys.path.remove(str(OMX))
    store = files(path, hold=web.cell_hold)
    sha = store.snapshot()["files"][0]["file_sha"]
    before = path.read_bytes()
    assert web.session_busy() is False
    for arm in ("arm_a", None):
        held = joint_tune.session_lock(arm)
        assert web.session_busy() is True
        with pytest.raises(web.Conflict, match="세션"):
            store.save({"file": "stack", "base_sha": sha, "changes": {FREE: 30.0}, "note": "그림자"})
        assert path.read_bytes() == before
        held.close()
        assert web.session_busy() is False
    assert save(store, path)["params_sha"] == prm.load(path)["sha"]
    joint_tune.session_lock(None).close()  # the save let go of the lock


def test_a_torn_history_line_does_not_hide_the_values(path):
    save(files(path), path)
    with path.with_name("params.json.history.jsonl").open("a", encoding="utf-8") as history:
        history.write('{"at": "torn')
    table = files(path).snapshot()["files"][0]
    assert "error" not in table and len(table["history"]) == 1


def test_a_save_over_a_changed_file_is_refused(path):
    store = files(path)
    sha = store.snapshot()["files"][0]["file_sha"]
    document = json.loads(path.read_text(encoding="utf-8"))
    document["params"][FREE]["value"] = 26.0
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(web.Conflict, match="바뀌었습니다"):
        store.save({"file": "stack", "base_sha": sha, "changes": {FREE: 30.0}, "note": "늦음"})
    assert prm.load(path)["values"][FREE] == 26.0


def test_a_failed_validation_of_the_written_file_leaves_no_trace(path, monkeypatch):
    before = path.read_bytes()
    monkeypatch.setattr(web.prm, "load", lambda _: (_ for _ in ()).throw(ValueError("disk said no")))
    with pytest.raises(ValueError):
        web.ParamFiles._replace(path, b"{}", {"at": "now"})
    assert path.read_bytes() == before and [item.name for item in path.parent.iterdir()] == ["params.json"]


SITE = {"11": {"pwm": 300}, "12": {"pwm": 600, "p": 1600}, "13": {"pwm": 600, "i": 30},
        "14": {"pwm": 300, "current": 250}, "15": {"pwm": 300, "current": 250}, "16": {"pwm": 300, "current": 250}}


def test_servo_layers_name_the_layer_that_load_caps_uses(tmp_path):
    session_caps = pytest.importorskip("session_caps")
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps(SITE))
    model, robot = {13: {"i": 50}, 14: {"i": 50}}, {14: {"i": 70, "p": 800}}
    table = session_caps.servo_layers(caps, model=model, robot=robot)
    assert table[13]["i"] == {"value": 30, "from": "site", "hidden": {"model": 50}}
    assert table[14]["i"] == {"value": 70, "from": "robot", "hidden": {"model": 50}}
    assert table[14]["p"] == {"value": 800, "from": "robot", "hidden": {}}
    assert table[12]["p"] == {"value": 1600, "from": "site", "hidden": {}}
    names = {"pwm": "pwm_limit", "current": "current_limit", "p": "p_gain", "i": "i_gain"}
    effective = session_caps.load_caps(caps, model=model, robot=robot)
    assert {motor: {names[key]: cell["value"] for key, cell in row.items()} for motor, row in table.items()} == effective


def test_a_caps_file_a_session_would_refuse_shows_its_reason(tmp_path):
    pytest.importorskip("session_caps")
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps({**SITE, "12": {"pwm": 5000}}))
    assert "pwm" in web.servo_table("arm", caps)["error"]
    assert "error" in web.servo_table("arm", tmp_path / "missing.json")


def test_the_servo_view_is_read_only_and_local(path, tmp_path):
    pytest.importorskip("session_caps")
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps(SITE))
    before = caps.read_bytes()
    running = web.make_server(files(path), 0, servo={"arm": (caps, None)})
    threading.Thread(target=running.serve_forever, daemon=True).start()
    try:
        status, body, _ = call(running, "GET", "/servo.json")
        table = json.loads(body)[0]
        assert status == 200 and [row["joint"] for row in table["motors"]][2] == "elbow_flex"
        assert table["motors"][2]["values"]["i"]["from"] == "site"
        assert call(running, "GET", "/servo.json", headers={"Host": "evil.example"})[0] == 403
        assert call(running, "POST", "/servo.json", "{}", {"X-Cell-Params": "1"})[0] == 404
    finally:
        running.shutdown()
        running.server_close()
    assert caps.read_bytes() == before


@pytest.fixture
def server(path):
    running = web.make_server(files(path), 0)
    threading.Thread(target=running.serve_forever, daemon=True).start()
    yield running
    running.shutdown()
    running.server_close()


def call(server, method, target, body=None, headers=None):
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    try:
        client.request(method, target, body, {"Host": f"127.0.0.1:{server.server_port}", **(headers or {})})
        response = client.getresponse()
        return response.status, response.read(), response.getheaders()
    finally:
        client.close()


def test_the_page_answers_only_on_the_local_host_and_a_post_needs_the_header(server, path):
    assert call(server, "GET", "/")[0] == 200
    assert call(server, "GET", "/params.json", headers={"Host": "evil.example"})[0] == 403
    body = json.dumps({"file": "stack", "base_sha": "x", "changes": {FREE: 30.0}, "note": "n"})
    assert call(server, "POST", "/save", body)[0] == 403
    assert call(server, "POST", "/save", body, {"X-Cell-Params": "1", "Host": "evil.example"})[0] == 403
    assert call(server, "POST", "/save", body, {"X-Cell-Params": "1"})[0] == 409
    assert call(server, "POST", "/save", "[1]", {"X-Cell-Params": "1"})[0] == 400
    assert call(server, "POST", "/save", "[" * 60000, {"X-Cell-Params": "1"})[0] == 400


def test_the_page_loads_nothing_from_elsewhere_and_never_writes_file_text_as_markup(server):
    status, page, headers = call(server, "GET", "/")
    text = page.decode("utf-8")
    assert status == 200 and "innerHTML" not in text and "http://" not in text and "https://" not in text
    assert "frame-ancestors 'none'" in dict(headers)["Content-Security-Policy"]


def test_attempts_and_incidents_endpoints_serve_tier_history_and_clear_hold(path, tmp_path, monkeypatch):
    import omx_incident

    attempts_file = tmp_path / "attempts.jsonl"
    attempts_file.write_text(json.dumps({
        "attempt_id": "20261110T080443Z-001", "t_utc": "2026-11-10T08:04:43Z",
        "from": "ship", "to": "pallet-l1", "tier": 2, "object": "1-cell", "outcome": "placed",
        "holding": True, "gripper_current_ma": 239, "verify": {"inside": True},
    }) + "\n", encoding="utf-8")

    cleared = []
    monkeypatch.setattr(omx_incident, "status", lambda arm: {
        "arm": arm, "held": not bool(cleared), "reason": None if cleared else "open hold",
        "incident_ids": [] if cleared else ["a" * 32],
    })
    monkeypatch.setattr(omx_incident, "clear", lambda arm, note, cause=None, basis=None: cleared.append((arm, note, cause, basis)))

    running = web.make_server(files(path), 0, attempts={"tier": attempts_file}, incident_arms=["arm_b"])
    threading.Thread(target=running.serve_forever, daemon=True).start()
    try:
        st, body, _ = call(running, "GET", "/attempts.json")
        rows = json.loads(body)[0]["rows"]
        assert st == 200 and len(rows) == 1 and rows[0]["tier"] == 2 and rows[0]["gripper_current_ma"] == 239

        st, body, _ = call(running, "GET", "/incidents.json")
        inc = json.loads(body)[0]
        assert st == 200 and inc["arm"] == "arm_b" and inc["held"] is True

        st, body, _ = call(running, "POST", "/incidents/clear",
                           json.dumps({"arm": "arm_b", "note": "확인 완료", "cause": "operator_verified", "basis": "direct_observation"}),
                           {"X-Cell-Params": "1"})
        after = json.loads(body)
        assert st == 200 and after["held"] is False
        assert cleared == [("arm_b", "확인 완료", "operator_verified", "direct_observation")]
    finally:
        running.shutdown()
        running.server_close()

