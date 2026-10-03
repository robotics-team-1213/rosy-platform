"""D-425: declared API owners and real server authorization/write boundaries."""

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for relative in ("middleware/core/api_web", "middleware/core/services", "middleware/core/events"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from core_api_web.api.errors import register_exception_handlers  # noqa: E402
from core_api_web.api.v1 import safety  # noqa: E402
from core_api_web.api.v1.auth import auth_router  # noqa: E402
from fleet.server.app import create_app  # noqa: E402
from fleet.server.console import FleetConsole  # noqa: E402
from fleet.server.task_service import FleetTaskService  # noqa: E402
from fleet.server.task_store import FleetTaskStore  # noqa: E402


REGISTRY = ROOT / "shared/web/surfaces.yaml"


def _rows():
    return {row["id"]: row for row in yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["surfaces"]}


@pytest.mark.parametrize("surface,owners", [
    ("robot", ["CORE"]), ("pilot", ["CORE"]), ("console", ["Fleet"]),
    ("cam", ["Fleet-pairing", "Vision-ingest"]), ("robot-face", []), ("web-common", []),
])
def test_product_surface_names_its_actual_api_owners(surface, owners):
    assert _rows()[surface].get("api_owners") == owners


def _headers(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


@pytest.fixture
def core(monkeypatch):
    """Real routers/auth; only side-effect owners and persistence are local fakes."""
    writes = []
    config = {"auth": {"tokens": [
        {"id": f"core-{role}", "role": role, "source": "manual",
         "sha256": sha256(f"core-{role}".encode()).hexdigest()}
        for role in ("viewer", "operator", "administrator")
    ]}}
    limits = SimpleNamespace(max_linear=0.5, max_angular=2.0, manual_linear=0.3, manual_angular=1.0)
    safety_owner = SimpleNamespace(
        limits=limits, estop=False, estop_source=None, fleet_loss_policy="STOP", session_linear=0.5,
        battery_policy=SimpleNamespace(warning_percent=30, critical_percent=15, critical_action="STOP"),
        trigger_estop=lambda reason: writes.append(("estop", reason)),
        release=lambda **kw: writes.append(("release", kw["by"])),
    )
    services = SimpleNamespace(
        config=config, safety=safety_owner, fleet_loss=None,
        battery=SimpleNamespace(_cfg=SimpleNamespace(deep_percent=5)),
        calibration=SimpleNamespace(blocking=lambda token_id: None),
        modes=SimpleNamespace(transition=lambda mode: writes.append(("mode", mode.value)),
                              release_emergency=lambda: (True, "")),
        state=SimpleNamespace(set_estop=lambda value: writes.append(("state-estop", value))),
        events=SimpleNamespace(publish=lambda *args, **kw: writes.append(("event", args[0]))),
    )
    monkeypatch.setattr(safety, "patch_local_config", lambda patch: writes.append(("persist", patch)))
    app = FastAPI()
    register_exception_handlers(app)
    app.state.core = services
    app.include_router(auth_router)
    app.include_router(safety.safety_router)
    with TestClient(app) as client:
        yield client, services, writes


@pytest.mark.parametrize("token,status", [
    (None, 401), ("camera-ingest", 401), ("fleet-operator", 401),
    ("core-viewer", 403), ("core-operator", 403),
])
def test_robot_persistent_settings_reject_before_touching_the_owner(core, token, status):
    client, services, writes = core
    response = client.put("/api/v1/safety/limits", json={"manual_linear": 0.2}, headers=_headers(token))
    assert response.status_code == status
    assert response.json()["error"]["code"] == ("UNAUTHORIZED" if status == 401 else "FORBIDDEN")
    assert writes == []
    assert services.safety.limits.manual_linear == 0.3


def test_robot_administrator_persists_through_the_existing_owner(core):
    client, services, writes = core
    response = client.put("/api/v1/safety/limits", json={"manual_linear": 0.2},
                          headers=_headers("core-administrator"))
    assert response.status_code == 200
    assert response.json()["limits"]["manual_linear"] == 0.2
    assert services.config["safety"] == {"manual_linear": 0.2}
    assert writes == [("persist", {"safety": {"manual_linear": 0.2}}), ("event", "config.changed")]


def test_authenticated_viewer_can_stop_but_cannot_release(core):
    client, _, writes = core
    stop = client.post("/api/v1/safety/stop", headers=_headers("core-viewer"))
    assert stop.status_code == 200 and stop.json() == {"estop": True}
    assert writes == [("estop", "api:viewer"), ("mode", "EMERGENCY"), ("state-estop", True)]
    writes.clear()
    assert client.post("/api/v1/safety/release", headers=_headers("core-viewer")).status_code == 403
    assert writes == []
    assert client.post("/api/v1/safety/release", headers=_headers("core-administrator")).status_code == 200
    assert writes == [("release", "api:administrator"), ("state-estop", False)]


def test_robot_and_pilot_get_roles_from_the_real_core_authenticator(core):
    client, _, writes = core
    for role in ("viewer", "operator", "administrator"):
        response = client.get("/api/v1/auth/whoami", headers=_headers(f"core-{role}"))
        assert response.status_code == 200
        assert response.json()["role"] == role
    assert writes == []


class RecordingConsole(FleetConsole):
    def __init__(self):
        super().__init__([], [])
        self.stops = 0

    async def estop_all(self):
        self.stops += 1
        return {"accepted": [], "failed": []}


@pytest.fixture
def fleet(tmp_path):
    console = RecordingConsole()
    users = {sha256(f"fleet-{role}".encode()).hexdigest(): {"principal_id": f"site-{role}", "role": role}
             for role in ("viewer", "operator", "policy-admin")}
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=set())
    app = create_app(console, site_users=users, task_service=service)
    with TestClient(app) as client:
        yield client, console


@pytest.mark.parametrize("token,status", [
    (None, 401), ("camera-ingest", 401), ("core-operator", 401),
    ("fleet-viewer", 403), ("fleet-policy-admin", 403),
])
def test_console_both_documents_reject_site_stop_before_dispatch(fleet, token, status):
    client, console = fleet
    assert client.post("/api/fleet/estop", headers=_headers(token)).status_code == status
    assert console.stops == 0


def test_console_operator_dispatches_once_via_fleet_owner(fleet):
    client, console = fleet
    response = client.post("/api/fleet/estop", headers=_headers("fleet-operator"))
    assert response.status_code == 200
    assert console.stops == 1
    assert response.json()["accepted"] == []


def test_console_documents_have_one_api_and_session_owner(fleet):
    client, _ = fleet
    for document in ("/console", "/console/install"):
        response = client.get(document)
        assert response.status_code == 200
        assert "connect-src 'self'" in response.headers["content-security-policy"]
    response = client.get("/api/fleet/session", headers=_headers("fleet-operator"))
    assert response.status_code == 200 and response.json()["role"] == "operator"


@pytest.mark.parametrize("surface,source,function,path", [
    ("robot", "middleware/ui/robot/client.js", "api", "/api/v1/auth/whoami"),
    ("pilot", "middleware/ui/pilot/client.js", "api", "/api/v1/auth/whoami"),
    ("console", "operations/fleet/fleet/server/web/console.js", "call", "/api/fleet/state"),
    ("console", "operations/fleet/fleet/server/web/install.js", "call", "/api/fleet/discovery"),
])
def test_existing_client_request_reaches_its_declared_plane(surface, source, function, path):
    """Run the exact request function; isolate its DOM/session hooks, not its fetch path."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    owner = _rows()[surface]["api_owners"][0]
    script = r"""
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const [source, name, path, owner, fleetModule] = JSON.parse(process.argv[1]);
const {createFleetClient} = await import(pathToFileURL(fleetModule));
const {createPageScope} = await import(new URL('./scope.js', pathToFileURL(fleetModule)));
const text = fs.readFileSync(source, 'utf8');
const match = text.match(new RegExp('(?:export )?async function ' + name + '\\([^]*?\\n\\}'));
if (!match) throw new Error('request function not found');
const calls = [];
const fetch = async (path, options) => {
  calls.push({path: new URL(path, 'https://plane.test').pathname,
    authorization: new Headers(options.headers).get('Authorization')});
  return new Response(JSON.stringify({owner}), {status: 200});
};
const token = owner.toLowerCase() + '-test-token';
const noop = () => {};
const fleetClient = createFleetClient({origin: 'https://plane.test', credential: () => token, fetchImpl: fetch});
const pageScope = createPageScope({events: new EventTarget()});
const request = new Function('fetch', 'authHeaders', 'session', 'classifyOperation',
  'window', 'CustomEvent', 'httpError', 'markLocked', 'markUnlocked', 'fleetClient', 'pageScope',
  'return (' + match[0].replace(/^export /, '') + ');')(
  fetch, () => ({Authorization: 'Bearer ' + token}), {token}, () => null,
  {dispatchEvent: noop}, class {}, () => new Error('unexpected HTTP failure'), noop, noop, fleetClient, pageScope);
await request(path);
pageScope.dispose();
console.log(JSON.stringify(calls));
"""
    data = json.dumps([str(ROOT / source), function, path, owner,
                       str(ROOT / "shared/web/fleet-client.js")])
    result = subprocess.run([node, "--input-type=module", "--eval", script, data],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {"path": path, "authorization": f"Bearer {owner.lower()}-test-token"}]
    assert path.startswith("/api/v1/" if owner == "CORE" else "/api/fleet/")
