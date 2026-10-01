"""D-341 3–5, 11 / D-391 4.3: the console's 카메라 연결 승인 section against the real routes.

The browser module (web/camera-pairing.js) is node-tested for its rules; this file pins the
page structure it needs and the server shapes it reads, so a renamed field or id fails here
instead of silently blanking the panel.
"""

from __future__ import annotations

import re
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

from fakes import FakeRobot
from fastapi.testclient import TestClient
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.pairing import PairingService
from fleet.server.pairing_store import PairingStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from pairing_fixtures import LEAF_SHA256, SITE_CA_PEM, TLS_HOST, FakeClock, Phone

WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"
BASE = "/api/fleet/pairing/v1"
OPERATOR = "op-" + "secret-2"
VIEWER = "view-" + "secret-2"
CONSOLE = "console-" + "secret-2"
SOURCES = {"ceiling_north": "paired", "ceiling_south": "paired", "bench_static": "static"}


def _console() -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id="rosy_01", base_url="http://127.0.0.1:8080", token="t")]
    return FleetConsole(endpoints, [FakeRobot("rosy_01")])


def _app(tmp_path, *, named=True):
    clock = FakeClock()
    store = PairingStore(tmp_path / "fleet.sqlite3", clock=clock.wall)
    service = PairingService(store, leaf_cert_sha256=LEAF_SHA256, site_ca_pem=SITE_CA_PEM,
                             tls_host=TLS_HOST, site_name="Rosy Lab", sources=SOURCES,
                             monotonic=clock.monotonic, wall=clock.wall)
    users = {sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "alice", "role": "operator"},
             sha256(VIEWER.encode()).hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=["rosy_01"])
    app = create_app(_console(), console_token=None if named else CONSOLE, task_service=tasks,
                     start_task_dispatcher=False, site_users=users if named else None, pairing=service)
    return TestClient(app), clock


def _auth(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def _request(client) -> tuple[Phone, str, str]:
    phone = Phone()
    created = client.post(f"{BASE}/requests", content=phone.request_bytes())
    assert created.status_code == 201, created.text
    request_id = created.json()["request_id"]
    revealed = client.post(f"{BASE}/requests/{request_id}/reveal", content=phone.reveal_bytes(),
                           headers={"Authorization": phone.bearer})
    assert revealed.status_code == 200, revealed.text
    return phone, request_id, phone.code(request_id, created.json()["server_nonce"])


def test_the_pending_and_summary_shapes_carry_every_field_the_panel_reads(tmp_path):
    client, _clock = _app(tmp_path)
    _phone, request_id, code = _request(client)

    pending = client.get(f"{BASE}/pending", headers=_auth(VIEWER))
    assert pending.status_code == 200
    body = pending.json()
    assert {"requests", "paired_sources", "site_ca_fingerprint", "refused_requests",
            "commit_mismatches"} <= set(body)
    row = body["requests"][0]
    assert {"request_id", "device_label", "app_version", "state", "expires_in_s",
            "attempts_left"} <= set(row)
    assert row["state"] == "revealed"
    assert code not in pending.text  # the console never learns the code
    assert {s["source_id"] for s in body["paired_sources"]} == {"ceiling_north", "ceiling_south"}

    wrong = "000000" if code != "000000" else "111111"
    mismatch = client.post(f"{BASE}/requests/{request_id}/approve", headers=_auth(OPERATOR),
                           json={"code": wrong, "source_id": "ceiling_north"})
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == {"code": "CODE_MISMATCH", "message": "code does not match the phone",
                                         "attempts_left": 2}

    approved = client.post(f"{BASE}/requests/{request_id}/approve", headers=_auth(OPERATOR),
                           json={"code": code, "source_id": "ceiling_north"})
    assert approved.status_code == 200, approved.text
    assert {"credential_id", "source_id", "site_ca_fingerprint", "confirm_within_s"} <= set(approved.json())
    assert approved.json()["confirm_within_s"] == 120

    summary = client.get(f"{BASE}/credentials/summary", headers=_auth(VIEWER)).json()
    cred = summary["credentials"][0]
    assert {"credential_id", "source_id", "state", "device_label", "approved_by", "approved_at",
            "expires_at", "expired"} <= set(cred)
    assert (cred["state"], cred["approved_by"]) == ("pending_confirm", "alice")
    after = client.get(f"{BASE}/pending", headers=_auth(VIEWER)).json()
    assert {"source_id": "ceiling_north", "has_credential": True} in after["paired_sources"]


def test_a_single_token_site_is_recognised_by_the_panel_and_refused_with_the_reason(tmp_path):
    client, _clock = _app(tmp_path, named=False)
    session = client.get("/api/fleet/session", headers=_auth(CONSOLE)).json()
    # camera-pairing.js (via enrollment.canManage) hides approve for this principal.
    assert (session["principal_id"], session["role"]) == ("site-console", "operator")
    _phone, request_id, code = _request(client)
    refused = client.post(f"{BASE}/requests/{request_id}/approve", headers=_auth(CONSOLE),
                          json={"code": code, "source_id": "ceiling_north"})
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"


def test_a_fleet_without_pairing_answers_the_panel_with_a_plain_404(tmp_path):
    client = TestClient(create_app(_console(), console_token=CONSOLE))
    response = client.get(f"{BASE}/pending", headers=_auth(CONSOLE))
    assert response.status_code == 404
    detail = response.json().get("detail")
    assert not isinstance(detail, dict) or "code" not in detail


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: dict[str, dict] = {}
        self.stack: list[str] = []
        self.order: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids[attrs["id"]] = {"tag": tag, "attrs": attrs, "ancestors": list(self.stack)}
            self.order.append(attrs["id"])
        if tag not in ("input", "br", "img", "meta", "link"):
            self.stack.append(attrs.get("id") or tag)

    def handle_endtag(self, tag):
        if self.stack and tag not in ("input", "br", "img", "meta", "link"):
            self.stack.pop()


def _page() -> _Ids:
    parser = _Ids()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    return parser


def test_every_id_the_module_touches_is_on_the_page_inside_the_camera_section():
    module = (WEB / "camera-pairing.js").read_text(encoding="utf-8")
    page = _page()
    used = set(re.findall(r'el\("([\w-]+)"\)', module))
    assert used, "the scan found no ids"
    missing = sorted(used - set(page.ids))
    assert missing == [], missing
    for name in used - {"camera-link"}:
        assert "camera-link" in page.ids[name]["ancestors"], name


def test_the_camera_section_sits_in_device_link_beside_robot_enrollment_with_a_role_lock():
    page = _page()
    section = page.ids["camera-link"]
    assert "hidden" not in section["attrs"]
    assert "data-role-lock" in section["attrs"]
    assert page.ids["camera-role-lock"]["attrs"].get("class") == "role-lock-note"
    assert page.order.index("robot-enrollment") < page.order.index("camera-link")
    heading = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<h4 id="camera-link-heading">카메라 연결 승인</h4>' in heading
    for name in ("camera-approve-source", "camera-approve-code"):
        assert "ui-field" in page.ids[name]["attrs"].get("class", ""), name
    assert page.ids["camera-approve-dialog"]["tag"] == "dialog"


def test_the_shell_wires_the_panel_and_reasks_it_on_every_login():
    shell = (WEB / "console.js").read_text(encoding="utf-8")
    module = (WEB / "camera-pairing.js").read_text(encoding="utf-8")
    assert 'import { createCameraPairingPanel } from "./camera-pairing.js";' in shell
    assert "dialogs: { confirmIrreversible, openLiveDialog }" in shell
    assert "locked: () => auth.locked" in shell
    assert "cameraPairing.resetPolling();" in shell
    # 로그인마다 자격을 다시 묻는다 — 갱신 호출은 Promise.allSettled 묶음 안에 있다.
    assert "cameraPairing.refresh({ credentials: true })" in shell
    # route-absent 404 closes the gate; the calm sentence is the page's, not a failure.
    assert 'gate.fail(err.status, err.code) === "absent"' in module
    assert "dialogs.openLiveDialog(dialog" in module and "showModal" not in module
