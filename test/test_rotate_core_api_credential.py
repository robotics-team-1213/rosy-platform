"""Contract tests for deploy/sd/rotate-core-api-credential.ps1 (D-193 5).

The script runs against a fake CORE on loopback that answers the four routes it
uses (whoami, POST/DELETE system/tokens) the way core_api_web does. The
operator's DPAPI store lives in a temporary LOCALAPPDATA.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "sd" / "rotate-core-api-credential.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
DEVICE = "rosy-pinky-k7m4"
UID = "9d40feaa-871f-4fd3-975a-a704e82d3af9"
OLD_ID = "0a1b2c3d4e5f"
OLD_VALUE = "Rq" * 21 + "_"  # CORE's generate_token shape, assembled for the secret scanner

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


class FakeCore:
    """Just enough of core_api_web's token routes, with switches for faults."""

    def __init__(self) -> None:
        self.tokens: dict[str, dict] = {
            OLD_VALUE: {"id": OLD_ID, "role": "administrator", "expires_at": None, "source": "card"},
        }
        self.requests: list[tuple[str, str, str]] = []  # (method, path, bearer)
        self.forget_new_token = False
        self.new_token_expires_at = None  # what whoami reports for the new token
        self.create_reply_expires_at = None  # what the create reply says
        self.refuse_delete_of: set[str] = set()
        self.create_status = 201
        self.issued: dict[str, dict] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # keep pytest output clean
                return

            def _reply(self, status: int, body: dict | None = None) -> None:
                payload = b"" if body is None else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _caller(self):
                header = self.headers.get("Authorization", "")
                presented = header[len("Bearer "):] if header.startswith("Bearer ") else ""
                server.requests.append((self.command, self.path, presented))
                return server.tokens.get(presented)

            def _unauthorized(self):
                self._reply(401, {"error": {"code": "UNAUTHORIZED", "message": "missing or invalid token"}})

            def do_GET(self):  # noqa: N802
                caller = self._caller()
                if caller is None:
                    return self._unauthorized()
                if self.path == "/api/v1/auth/whoami":
                    return self._reply(200, {**caller, "label": "card", "created_at": "2026-09-24T00:00:00+00:00"})
                self._reply(404, {"error": {"code": "NOT_FOUND", "message": "no route"}})

            def do_POST(self):  # noqa: N802
                caller = self._caller()
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if caller is None:
                    return self._unauthorized()
                if self.path != "/api/v1/system/tokens":
                    return self._reply(404, {"error": {"code": "NOT_FOUND", "message": "no route"}})
                if server.create_status != 201:
                    return self._reply(server.create_status,
                                       {"error": {"code": "FORBIDDEN", "message": "not allowed"}})
                value = secrets.token_urlsafe(32)
                record = {"id": secrets.token_hex(6), "role": body["role"], "expires_at": None,
                          "source": "manual", "label": body.get("label", "")}
                if not server.forget_new_token:
                    server.tokens[value] = {**record, "expires_at": server.new_token_expires_at}
                server.created_label = body.get("label")
                server.issued[value] = record
                self._reply(201, {**record, "expires_at": server.create_reply_expires_at,
                                  "created_at": "2026-09-24T00:00:00+00:00", "token": value})

            def do_DELETE(self):  # noqa: N802
                caller = self._caller()
                if caller is None:
                    return self._unauthorized()
                target = self.path.rsplit("/", 1)[-1]
                if target == caller["id"]:
                    return self._reply(400, {"error": {"code": "VALIDATION_ERROR",
                                                       "message": "cannot delete the token in use"}})
                if target in server.refuse_delete_of:
                    return self._reply(409, {"error": {"code": "VALIDATION_ERROR", "message": "refused"}})
                for value, record in list(server.tokens.items()):
                    if record["id"] == target:
                        del server.tokens[value]
                        self.send_response(204)
                        self.end_headers()
                        return
                self._reply(404, {"error": {"code": "NOT_FOUND", "message": "token id not found"}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def ids(self) -> set[str]:
        return {record["id"] for record in self.tokens.values()}


@pytest.fixture
def core():
    fake = FakeCore()
    fake.thread.start()
    yield fake
    fake.httpd.shutdown()
    fake.httpd.server_close()


@pytest.fixture
def local_app_data(tmp_path):
    root = tmp_path / "LocalAppData"
    root.mkdir()
    return root


def _env(local_app_data: Path) -> dict:
    return {**os.environ, "LOCALAPPDATA": str(local_app_data)}


def _store(local_app_data: Path) -> Path:
    return local_app_data / "Rosy" / "api" / f"{DEVICE}.credential.xml"


def _seed(local_app_data: Path, user_name: str = f"{OLD_ID}|{UID}", value: str = OLD_VALUE) -> Path:
    store = _store(local_app_data)
    store.parent.mkdir(parents=True, exist_ok=True)
    command = (f"$s = ConvertTo-SecureString '{value}' -AsPlainText -Force; "
               f"[pscredential]::new('{user_name}', $s) | Export-Clixml -LiteralPath '{store}'")
    subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], check=True, env=_env(local_app_data))
    return store


def _read(local_app_data: Path) -> tuple[str, str]:
    # The read-back command from the runbook.
    command = (f'$c = Import-Clixml "$env:LOCALAPPDATA\\Rosy\\api\\{DEVICE}.credential.xml"; '
               "$c.UserName; $c.GetNetworkCredential().Password")
    completed = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True,
                               text=True, env=_env(local_app_data), check=True)
    user_name, value = completed.stdout.split()
    return user_name, value


def _rotate(core: FakeCore, local_app_data: Path, *extra: str) -> subprocess.CompletedProcess:
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-DeviceName", DEVICE, "-BaseUrl", core.url, "-TimeoutSeconds", "10", *extra]
    return subprocess.run(command, capture_output=True, text=True, env=_env(local_app_data), timeout=120)


def _assert_no_secret_printed(completed: subprocess.CompletedProcess, *values: str) -> None:
    for value in values:
        assert value not in completed.stdout and value not in completed.stderr


def _new_values(core: FakeCore) -> list[str]:
    """Every token value the fake CORE handed out in a create response."""
    return [value for value, record in core.issued.items()]


def _assert_store_clean(local_app_data: Path, core: FakeCore) -> None:
    """Only the store file is left, and no token value is readable anywhere under LOCALAPPDATA."""
    store = _store(local_app_data)
    assert sorted(path.name for path in store.parent.iterdir()) == [store.name]
    for path in local_app_data.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            for value in [OLD_VALUE, *_new_values(core)]:
                for encoding in ("utf-8", "utf-16-le"):
                    assert value.encode(encoding) not in raw, path


def test_rotation_adds_stores_confirms_then_deletes_the_old_id(core, local_app_data):
    _seed(local_app_data)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 0, completed.stderr
    user_name, value = _read(local_app_data)
    new_id, uid = user_name.split("|")
    assert uid == UID  # the store stays bound to the device
    assert re.fullmatch(r"[0-9a-f]{12}", new_id) and new_id != OLD_ID
    assert core.ids() == {new_id}  # the old id is gone, the new one is live
    assert core.tokens[value]["id"] == new_id
    # D-193 5 order: whoami(old) -> add -> whoami(new, read back from the store) -> delete old.
    assert [(method, path) for method, path, _ in core.requests] == [
        ("GET", "/api/v1/auth/whoami"),
        ("POST", "/api/v1/system/tokens"),
        ("GET", "/api/v1/auth/whoami"),
        ("DELETE", f"/api/v1/system/tokens/{OLD_ID}"),
    ]
    assert [bearer for _, _, bearer in core.requests] == [OLD_VALUE, OLD_VALUE, value, value]
    assert core.created_label.startswith("card (rotated ")
    # Plaintext only in the DPAPI store: never printed, never in the file as text.
    _assert_no_secret_printed(completed, value, OLD_VALUE)
    _assert_store_clean(local_app_data, core)
    assert new_id in completed.stdout and OLD_ID in completed.stdout
    assert "GetNetworkCredential().Password" in completed.stdout
    assert sorted(path.name for path in _store(local_app_data).parent.iterdir()) == [f"{DEVICE}.credential.xml"]


def test_a_store_written_before_the_uid_binding_keeps_its_shape(core, local_app_data):
    _seed(local_app_data, user_name=OLD_ID)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 0, completed.stderr
    user_name, _value = _read(local_app_data)
    assert "|" not in user_name and user_name != OLD_ID


def test_no_store_means_no_request(core, local_app_data):
    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "no stored CORE API credential" in completed.stderr
    assert core.requests == []


def test_a_store_for_another_robot_changes_nothing(core, local_app_data):
    core.tokens[OLD_VALUE]["id"] = "ffffffffffff"  # the URL points at a different robot's CORE
    store = _seed(local_app_data)
    before = store.read_bytes()

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "the store says 0a1b2c3d4e5f" in completed.stderr
    assert [method for method, _, _ in core.requests] == ["GET"]
    assert store.read_bytes() == before


def test_a_paired_session_is_not_rotated(core, local_app_data):
    core.tokens[OLD_VALUE]["expires_at"] = "2026-09-25T00:00:00+00:00"
    _seed(local_app_data)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "not a non-expiring administrator" in completed.stderr
    assert [method for method, _, _ in core.requests] == ["GET"]


def test_a_refused_create_leaves_the_store_alone(core, local_app_data):
    store = _seed(local_app_data)
    before = store.read_bytes()
    core.create_status = 403

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "HTTP 403 FORBIDDEN" in completed.stderr
    assert store.read_bytes() == before
    assert core.ids() == {OLD_ID}


def test_an_unconfirmed_new_credential_is_rolled_back(core, local_app_data):
    # CORE answers the create but does not know the value afterwards.
    core.forget_new_token = True
    store = _seed(local_app_data)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "not confirmed by whoami" in completed.stderr
    assert _read(local_app_data) == (f"{OLD_ID}|{UID}", OLD_VALUE)
    assert core.ids() == {OLD_ID}
    assert [method for method, _, _ in core.requests][-1] == "DELETE"  # tried to undo the new id
    assert sorted(path.name for path in store.parent.iterdir()) == [store.name]
    _assert_no_secret_printed(completed, OLD_VALUE, *_new_values(core))
    _assert_store_clean(local_app_data, core)


def test_an_old_id_that_cannot_be_deleted_is_named_and_the_new_one_kept(core, local_app_data):
    core.refuse_delete_of = {OLD_ID}
    _seed(local_app_data)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert f"the old id {OLD_ID} is still valid" in completed.stderr
    user_name, value = _read(local_app_data)
    assert core.tokens[value]["id"] == user_name.split("|")[0]
    assert core.ids() == {OLD_ID, user_name.split("|")[0]}
    _assert_no_secret_printed(completed, value, OLD_VALUE)
    _assert_store_clean(local_app_data, core)


def test_leftovers_from_an_interrupted_rotation_stop_the_next_one(core, local_app_data):
    store = _seed(local_app_data)
    Path(str(store) + ".previous").write_bytes(store.read_bytes())

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "interrupted rotation" in completed.stderr
    assert core.requests == []


@pytest.mark.parametrize("device", ["rosy-pinky-K7M4", "rosy-pinky-k7m", "pinky-k7m4"])
def test_the_device_name_is_checked_like_the_writer_does(core, local_app_data, device):
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-DeviceName", device, "-BaseUrl", core.url]
    completed = subprocess.run(command, capture_output=True, text=True, env=_env(local_app_data), timeout=60)

    assert completed.returncode == 1
    assert "DeviceName is invalid" in completed.stderr
    assert core.requests == []


def test_the_script_keeps_the_token_off_proxies_logs_and_command_lines():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.isascii()  # Windows PowerShell 5.1 reads a BOM-less script as ANSI
    assert "$handler.UseProxy = $false" in text
    assert "$handler.AllowAutoRedirect = $false" in text
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("Invoke-RestMethod", "Invoke-WebRequest", "Start-Transcript", "Write-Host",
                      "Write-Verbose", "Write-Debug", "Set-Clipboard", "ssh "):
        assert forbidden not in code, forbidden
    # The new value only ever goes to CORE, the SecureString and the whoami check.
    uses = [line.strip() for line in text.splitlines() if "$newValue" in line]
    assert len(uses) == 3, uses
    assert any("ConvertTo-SecureString $newValue" in line for line in uses)


def test_a_new_token_that_expires_is_rolled_back(core, local_app_data):
    # M2: an expiring administrator would lock the operator out when it lapses.
    core.new_token_expires_at = "2026-09-25T00:00:00+00:00"
    _seed(local_app_data)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "non-expiring administrator" in completed.stderr
    assert _read(local_app_data) == (f"{OLD_ID}|{UID}", OLD_VALUE)
    assert core.ids() == {OLD_ID}
    _assert_no_secret_printed(completed, OLD_VALUE, *_new_values(core))
    _assert_store_clean(local_app_data, core)


def test_a_create_reply_with_an_expiry_is_undone(core, local_app_data):
    core.create_reply_expires_at = "2026-09-25T00:00:00+00:00"
    _seed(local_app_data)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 1
    assert "non-expiring administrator" in completed.stderr
    assert _read(local_app_data) == (f"{OLD_ID}|{UID}", OLD_VALUE)
    assert core.ids() == {OLD_ID}  # the new id was deleted before anything was stored
    _assert_store_clean(local_app_data, core)


def test_plain_http_is_warned_about(core, local_app_data):
    _seed(local_app_data)

    completed = _rotate(core, local_app_data)

    assert completed.returncode == 0, completed.stderr
    assert "WARNING" in completed.stderr and "plain HTTP" in completed.stderr


def test_a_store_that_cannot_be_swapped_is_left_as_it_was(core, local_app_data):
    # L5: the swap fails (read-only store); the old store stays and the new id is undone.
    store = _seed(local_app_data)
    before = store.read_bytes()
    os.chmod(store, 0o444)
    try:
        completed = _rotate(core, local_app_data)
    finally:
        os.chmod(store, 0o666)

    assert completed.returncode == 1
    assert "could not be stored" in completed.stderr
    assert store.read_bytes() == before
    assert core.ids() == {OLD_ID}
    _assert_no_secret_printed(completed, OLD_VALUE, *_new_values(core))
    _assert_store_clean(local_app_data, core)
