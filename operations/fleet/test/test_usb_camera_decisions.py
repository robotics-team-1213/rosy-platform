"""D-963: USB camera candidates reported by a control PC, role decisions by a named operator."""
from hashlib import sha256
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from core_common.protocol.workcell_observations import UsbCameraReport, WorkcellObservationManifest
from fleet.server.usb_camera_decisions import FRESH_S, UsbCameraStore, install_usb_camera_routes
from fleet.server.workcell_observations import WorkcellObservations

PATH = "/api/fleet/workcell-observations"
KEY, KEY2 = "a" * 32, "b" * 32
OPERATOR = {"Authorization": "Bearer operator-secret"}
VIEWER = {"Authorization": "Bearer viewer-secret"}


def cell(name, secrets):
    return {"workcell_id": name, "label": name, "arms": [
        {"source_id": f"{name}_{n}", "arm_id": f"{name}_arm_{n}", "label": "Arm", "board_id": f"{name}-board-{n}",
         "joint_topic": f"/omx_commissioning/{name}_arm_{n}/joint_states", "joint_names": ["joint1"],
         "token_env": f"{name.upper()}_{n.upper()}", "credential_sha256": sha256(secrets[n].encode()).hexdigest()}
        for n in secrets],
        "cameras": [{"source_id": f"{name}_top", "label": "Top", "role": "overhead", "arm_id": None,
                     "image_topic": f"/{name}_top/image_raw", "device_path": f"/dev/v4l/by-path/{name}-top",
                     "token_env": f"{name.upper()}_TOP", "credential_sha256": sha256(f"{name}-top".encode()).hexdigest()}]}


def viewer(authorization: str | None = Header(None)):
    if authorization not in ("Bearer viewer-secret", "Bearer operator-secret"):
        raise HTTPException(401)


def named_operator(authorization: str | None = Header(None)):
    if authorization != "Bearer operator-secret":
        raise HTTPException(403)
    return SimpleNamespace(principal_id="kim")


@pytest.fixture
def parts(tmp_path):
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [
        cell("one", {"a": "one-a", "b": "one-b"}), cell("two", {"a": "two-a"})]})
    service = WorkcellObservations(manifest, {"one_a": "one-a", "one_b": "one-b", "two_a": "two-a"},
                                   wall=lambda: 100.0, monotonic=lambda: 10.0)
    clock = [0.]
    store = UsbCameraStore(tmp_path / "tasks.db", clock=lambda: clock[0], wall=lambda: 5.)
    app = FastAPI()
    install_usb_camera_routes(app, service=service, store=store, require_viewer=viewer,
                              require_named_operator=named_operator)
    return TestClient(app), store, clock, tmp_path


def report(*keys, workcell="one"):
    return {"workcell_id": workcell, "roles": ["top", "arm_a_wrist"], "candidates": [
        {"key": key, "usb_id": "0c45:6366", "roles": ["arm_a_wrist"], "suggest": "arm_a_wrist", "hub_arm": None}
        for key in keys]}


def send(client, body, workcell="one", token="one-a"):
    return client.post(f"{PATH}/{workcell}/usb-devices", json=body, headers={"X-Workcell-Observation-Token": token})


def test_contract_is_strict():
    assert UsbCameraReport.model_validate(report(KEY)).candidates[0].key == KEY
    for bad in (report("xyz"), {**report(KEY), "extra": 1}, report(*[f"{i:016x}" for i in range(17)]),
                {**report(KEY), "roles": ["bad role"]}, {**report(KEY), "workcell_id": 5}):
        with pytest.raises(ValidationError):
            UsbCameraReport.model_validate(bad)


def test_any_arm_token_of_the_workcell_reports_and_other_tokens_are_refused(parts):
    client = parts[0]
    assert send(client, report(KEY)).json() == {"decisions": []}
    assert send(client, report(KEY), token="one-b").status_code == 200
    assert send(client, report(KEY), token="two-a").status_code == 401
    assert send(client, report(KEY), token="").status_code == 401
    assert send(client, report(KEY), workcell="nope").status_code == 404
    assert send(client, report(KEY, workcell="two"), token="one-a").status_code == 422  # body names another workcell
    assert send(client, {**report(KEY), "extra": 1}).status_code == 422
    assert send(client, {**report(KEY), "roles": ["x" * 20] * 32, "pad": "y" * 17000}).status_code == 413


def test_decision_needs_a_named_operator_and_a_reported_key(parts):
    client = parts[0]
    send(client, report(KEY))
    url = f"{PATH}/one/usb-devices/{KEY}/decision"
    assert client.post(url, json={"role": "top"}).status_code == 403
    assert client.post(url, json={"role": "top"}, headers=VIEWER).status_code == 403
    assert client.post(url, json={"role": "bad role"}, headers=OPERATOR).status_code == 422
    assert client.post(url, json={"role": "top", "x": 1}, headers=OPERATOR).status_code == 422
    assert client.post(url, content=b'{"role":"a","role":"b"}', headers=OPERATOR).status_code == 400
    assert client.post(f"{PATH}/one/usb-devices/{KEY2}/decision", json={"role": "top"}, headers=OPERATOR).status_code == 404
    done = client.post(url, json={"role": "new_side"}, headers=OPERATOR)
    assert done.status_code == 200 and done.headers["Cache-Control"] == "no-store"
    assert send(client, report(KEY)).json() == {"decisions": [{"key": KEY, "role": "new_side"}]}


def test_decision_is_dropped_when_the_camera_is_no_longer_reported_and_survives_a_restart(parts):
    client, _, clock, tmp_path = parts
    send(client, report(KEY, KEY2))
    client.post(f"{PATH}/one/usb-devices/{KEY}/decision", json={"role": "top"}, headers=OPERATOR)
    assert UsbCameraStore(tmp_path / "tasks.db")._decisions("one") == {KEY: ("top", "kim")}
    assert send(client, report(KEY2)).json() == {"decisions": []}  # applied or unplugged
    assert send(client, report(KEY, KEY2)).json() == {"decisions": []}  # a returning camera asks again


def test_listing_shows_candidates_and_decisions_without_paths_or_tokens_and_hides_stale_reports(parts):
    client, _, clock, _ = parts
    send(client, report(KEY))
    client.post(f"{PATH}/one/usb-devices/{KEY}/decision", json={"role": "top"}, headers=OPERATOR)
    assert client.get(f"{PATH}/usb-devices").status_code == 401
    listing = client.get(f"{PATH}/usb-devices", headers=VIEWER)
    row = listing.json()["workcells"][0]["candidates"][0]
    assert row["decision"] == {"role": "top", "principal_id": "kim"} and listing.headers["Cache-Control"] == "no-store"
    assert "/dev/" not in listing.text and "one-a" not in listing.text
    clock[0] = FRESH_S + 1
    assert client.get(f"{PATH}/usb-devices", headers=VIEWER).json() == {"workcells": []}


def test_usb_decision_accepts_named_operator_cookie_but_keeps_viewer_and_csrf_guards(parts, tmp_path):
    from rosy_account.password_session import COOKIE, PasswordSessions
    from fleet.server.site_auth import build_authorize, build_role_guards
    from rosy_account.site_users import hash_password

    original, store, _, _ = parts
    send(original, report(KEY))
    app = original.app
    logins = {role: {"principal_id": role + "-human", "role": role,
                     "password_scrypt": hash_password("usb-cookie-fixture")}
              for role in ("operator", "viewer")}
    sessions = PasswordSessions(tmp_path / "usb-cookie-sessions.sqlite3", logins)
    authorize = build_authorize(None, {}, None, None, sessions)
    read, _, decide, _ = build_role_guards(authorize, {}, named_logins=True)
    app.dependency_overrides[viewer] = read
    app.dependency_overrides[named_operator] = decide
    origin = "https://fleet.example"
    path = f"{PATH}/one/usb-devices/{KEY}/decision"
    with TestClient(app, base_url=origin) as client:
        assert client.get(f"{PATH}/usb-devices").status_code == 401
        assert client.post(path, json={"role": "top"}, headers={"Origin": origin}).status_code == 401
        for role in ("viewer", "operator"):
            client.cookies.set(COOKIE, sessions.issue(role, remember=False))
            assert client.get(f"{PATH}/usb-devices").status_code == 200
            assert client.post(path, json={"role": "top"}).status_code == 403
            result = client.post(path, json={"role": "top"}, headers={"Origin": origin})
            assert result.status_code == (200 if role == "operator" else 403)
            if role == "viewer":
                assert store._decisions("one") == {}
        assert store._decisions("one") == {KEY: ("top", "operator-human")}
