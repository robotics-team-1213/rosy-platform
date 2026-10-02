"""D-412: the robot-side updater (deploy/robot/pinky_pro/native/rosy_auto_update.py).

A fake GitHub runs on a local HTTP server and is reached through the real
urllib transport. The device is a temporary root plus a FakeHost that records
every command and simulates activate-release.sh, rollback-release.sh,
native_release.py verify, the unpack script, sync-image-layer.py, the CORE
ready probe and systemctl. No real systemctl, network or robot is touched.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.server
import importlib.util
import json
import shutil
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from signing import sign_checksums


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "robot" / "pinky_pro" / "native"
REPO = "livsbittt/rosy-os"
HOST = "rosy-pinky-8kcn"
OTHER = "rosy-pinky-9dfk"
CURRENT = "2026.10.01-021"
NEXT = "2026.10.01-022"
NEWER = "2026.10.01-023"
BOOT = "boot-1"
T0 = dt.datetime(2026, 10, 1, 16, 0, 0, tzinfo=dt.timezone.utc)
PUBLISHED = "2026-10-01T15:00:00Z"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, NATIVE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


claim_mod = _load("rosy_claim", "rosy_claim.py")
upd = _load("rosy_auto_update", "rosy_auto_update.py")


# --- keys -------------------------------------------------------------------


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    folder = tmp_path_factory.mktemp("keys")
    private = folder / "release.key"
    public = folder / "release.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    other = folder / "other.key"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(other)],
                   check=True, capture_output=True)
    return {"private": private, "public": public, "other": other}


# --- fake GitHub --------------------------------------------------------------


class FakeGitHub:
    def __init__(self) -> None:
        self.releases: list[dict] = []
        self.assets: dict[str, bytes] = {}
        self.requests: list[tuple[str, dict]] = []
        self.etag = '"v1"'
        self.status: int | None = None  # forced status for the list endpoint
        self.asset_status: dict[str, int] = {}  # forced status per asset key
        self.extra_headers: dict[str, str] = {}
        handler = self._handler()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _handler(self):
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def do_GET(self):  # noqa: N802
                hub.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                if self.path == f"/repos/{REPO}/releases?per_page=20":
                    if hub.status is not None:
                        self.send_response(hub.status)
                        for key, value in hub.extra_headers.items():
                            self.send_header(key, value)
                        self.end_headers()
                        return
                    if self.headers.get("If-None-Match") == hub.etag:
                        self.send_response(304)
                        self.end_headers()
                        return
                    body = json.dumps(hub.releases).encode()
                    self.send_response(200)
                    self.send_header("ETag", hub.etag)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path.startswith("/dl/") and self.path[4:] in hub.asset_status:
                    self.send_response(hub.asset_status[self.path[4:]])
                    self.end_headers()
                    return
                if self.path.startswith("/dl/") and self.path[4:] in hub.assets:
                    body = hub.assets[self.path[4:]]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        return Handler

    def publish(self, keys, release_id: str, *, canary=(HOST,), canary_ok=False, wave_delay_s=600,
                withdrawn=False, tarball: bytes | None = None, sha: str | None = None,
                bad_signature=False, draft=False, prerelease=False, skip_asset: str | None = None,
                published_at=PUBLISHED, rollout_overrides: dict | None = None) -> dict:
        tarball = tarball if tarball is not None else f"payload {release_id}".encode()
        rollout = {
            "schema": 1, "release_id": release_id, "tarball": f"{release_id}.tar.gz",
            "tarball_sha256": sha or hashlib.sha256(tarball).hexdigest(),
            "source_revision": "a" * 40, "published_at": published_at, "canary": list(canary),
            "canary_ok": canary_ok, "wave_delay_s": wave_delay_s, "withdrawn": withdrawn, "reason": "",
        }
        rollout.update(rollout_overrides or {})
        raw = (json.dumps(rollout, sort_keys=True) + "\n").encode()
        signature = sign_checksums(raw, keys["other"] if bad_signature else keys["private"])
        names = {f"{release_id}.tar.gz": tarball, "rollout.json": raw, "rollout.json.sig": signature.encode()}
        assets = []
        for name, body in names.items():
            key = f"{release_id}/{name}"
            self.assets[key] = body
            if name != skip_asset:
                assets.append({"name": name, "size": len(body),
                               "browser_download_url": f"{self.base}/dl/{key}"})
        self.releases = [r for r in self.releases if r["tag_name"] != f"payload-{release_id}"]
        self.releases.append({"tag_name": f"payload-{release_id}", "draft": draft,
                              "prerelease": prerelease, "assets": assets})
        self.etag = f'"v{len(self.requests)}-{release_id}-{len(self.releases)}"'
        return rollout

    def list_requests(self) -> list[dict]:
        return [headers for path, headers in self.requests if path.startswith(f"/repos/{REPO}/releases")]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def hub():
    server = FakeGitHub()
    yield server
    server.close()


# --- fake device ----------------------------------------------------------------


def _z(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def idle_inputs(moment: dt.datetime, **changes) -> dict:
    data = {
        "schema": 2, "written_at": moment.isoformat(timespec="seconds"),
        "battery_warning_percent": 20.0, "devices": [],
        "robot_mode": "IDLE", "nav_state": "IDLE", "swarm_role": None,
        "velocity_linear": 0.0, "velocity_angular": 0.0,
        "battery_percent": 80.0, "battery_charging": False,
        "docking_state": None, "line_follow_mode": "OFF", "line_follow_state": "OFF",
        "swarm_active": False, "estop": False, "activity_kind": None,
    }
    data.update(changes)
    return data


class FakeHost(upd.Host):
    """The device: clock, commands and the two release links, all in memory."""

    def __init__(self, root: Path, current: str | None = CURRENT) -> None:
        super().__init__(root)
        self.calls: list[list[str]] = []
        self.links = {"current": current, "previous": None}
        self.host = HOST
        self.overrides: dict[str, object] = {}
        self.inputs_changes: dict = {}
        self.second_sample_changes: dict | None = None
        self.core_restarts = 0
        self.stale_core = False
        self.free = 64 * 1024 ** 3
        self.t = T0

    # clock: CORE rewrites status-inputs every 10 s, so moving the clock rewrites it.
    @property
    def t(self) -> dt.datetime:
        return self._t

    @t.setter
    def t(self, value: dt.datetime) -> None:
        self._t = value
        self.write_inputs()

    def now(self) -> dt.datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        if self.second_sample_changes is not None:
            self.inputs_changes = {**self.inputs_changes, **self.second_sample_changes}
        self.t += dt.timedelta(seconds=seconds)

    def write_inputs(self) -> None:
        path = self.root / "run/rosy/status-inputs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.inputs_changes is None:
            path.unlink(missing_ok=True)
            return
        path.write_text(json.dumps(idle_inputs(self.t, **self.inputs_changes)), encoding="utf-8")

    # identity ----------------------------------------------------------------
    def hostname(self) -> str:
        return self.host

    def current_release(self) -> str | None:
        return self.links["current"]

    def previous_release(self) -> str | None:
        return self.links["previous"]

    def free_bytes(self, path: Path) -> int:
        return self.free

    def process_cwd(self, pid: int) -> str | None:
        release = self.links["current"]
        if self.stale_core and pid == 101:
            release = self.links["previous"]
        override = self.overrides.get("cwd")
        if callable(override):
            return override(pid, release)
        return str(self.root / "opt/rosy/releases" / str(release))

    # commands ----------------------------------------------------------------
    def run(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess:
        assert timeout and timeout > 0, argv
        self.calls.append(list(argv))
        kind = kind_of(argv)
        override = self.overrides.get(kind)
        if callable(override):
            result = override(self, argv)
            if result is not None:
                return result
        return getattr(self, "_" + kind.replace("-", "_"))(argv)

    def _ok(self, out: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], 0, out, "")

    def _unpack(self, argv):
        release_id, tarball, releases = argv[-3], Path(argv[-2]), Path(argv[-1])
        (releases / release_id / "deploy/robot/native").mkdir(parents=True, exist_ok=True)
        tarball.unlink()
        return self._ok(f"unpacked {release_id}\n")

    def _verify(self, argv):
        release_id = argv[argv.index("--release-id") + 1]
        ok = (self.root / "opt/rosy/releases" / release_id).is_dir()
        return subprocess.CompletedProcess([], 0 if ok else 1, json.dumps({"ok": ok, "release_id": release_id}), "")

    def _activate(self, argv):
        release_id = argv[-1]
        self.links = {"current": release_id, "previous": self.links["current"]}
        return self._ok(json.dumps({"ok": True, "release_id": release_id, "previous": self.links["previous"]}))

    def _rollback(self, argv):
        self.links = {"current": self.links["previous"], "previous": self.links["current"]}
        self.stale_core = False
        return self._ok(json.dumps({"ok": True, "release_id": self.links["current"]}))

    def _sync(self, argv):
        return self._ok(json.dumps({"ok": True, "release_id": self.links["current"],
                                    "restart_units": ["rosy-io.service", "rosy-auto-update.service",
                                                      "rosy-auto-update.timer", "bad unit;"]}))

    def _ready(self, argv):
        return self._ok()

    def _recover(self, argv):
        journal = self.root / "var/lib/rosy/releases/native-activation.json"
        if journal.exists():
            data = json.loads(journal.read_text(encoding="utf-8"))
            self.links = {"current": data["old_current"], "previous": data["candidate"]}
            journal.unlink()
        return self._ok(json.dumps({"ok": True}))

    def _start(self, argv):
        return self._ok()

    def _corestate(self, argv):
        return self._ok("ActiveState=active\nSubState=running\nMainPID=101\n")

    def _mainpid(self, argv):
        return self._ok({"rosy-core.service": "101\n", "rosy-io.service": "102\n",
                         "rosy-camera.service": "103\n"}.get(argv[-1], "0\n"))

    def _restart(self, argv):
        if "rosy-core.service" in argv:
            self.core_restarts += 1
            self.stale_core = False
        return self._ok()

    def _is_active(self, argv):
        return self._ok()

    def _failed(self, argv):
        return self._ok("")


def kind_of(argv: list[str]) -> str:
    joined = " ".join(argv)
    for needle, kind in (("rosy-release-unpack.sh", "unpack"), ("activate-release.sh", "activate"),
                         ("rollback-release.sh", "rollback"), ("sync-image-layer.py", "sync"),
                         ("wait-core-ready.py", "ready")):
        if needle in joined:
            return kind
    if "native_release.py" in joined and "verify" in argv:
        return "verify"
    if "native_release.py" in joined and "recover" in argv:
        return "recover"
    if argv[:2] == ["systemctl", "start"]:
        return "start"
    if argv[:2] == ["systemctl", "show"] and "ActiveState,SubState,MainPID" in argv:
        return "corestate"
    if argv[:2] == ["systemctl", "show"]:
        return "mainpid"
    if argv[:2] == ["systemctl", "restart"]:
        return "restart"
    if argv[:2] == ["systemctl", "is-active"]:
        return "is-active"
    if argv[:2] == ["systemctl", "list-units"]:
        return "failed"
    raise AssertionError(f"unexpected command {argv}")


@pytest.fixture
def device(tmp_path, keys):
    key = tmp_path / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
    key.parent.mkdir(parents=True)
    key.write_bytes(keys["public"].read_bytes())
    sync = tmp_path / "opt/rosy/releases" / CURRENT / "deploy/robot/native/sync-image-layer.py"
    sync.parent.mkdir(parents=True)
    sync.write_text("# the current release's own sync\n", encoding="utf-8")
    (tmp_path / "opt/rosy/native-runtime").mkdir(parents=True)
    boot = tmp_path / "proc/sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text(BOOT + "\n", encoding="utf-8")
    # Auto-update is off unless configured (D-412 landing, 2026-10-02).
    write_json(tmp_path / "var/lib/rosy/updates/config.json", {"enabled": True, "repo": REPO})
    return tmp_path


@pytest.fixture
def host(device):
    return FakeHost(device)


def updater(host: FakeHost, hub: FakeGitHub) -> "upd.Updater":
    return upd.Updater(host, api_base=hub.base)


def kinds(host: FakeHost) -> list[str]:
    return [kind_of(argv) for argv in host.calls]


def status(device: Path) -> dict:
    return json.loads((device / "var/lib/rosy/updates/status.json").read_text(encoding="utf-8"))


def state(device: Path) -> dict:
    return json.loads((device / "var/lib/rosy/updates/state.json").read_text(encoding="utf-8"))


def history(device: Path) -> list[dict]:
    path = device / "var/lib/rosy/updates/history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# --- config and the GitHub check -------------------------------------------------


def test_a_robot_without_a_config_is_off_by_default(device, host, hub, keys):
    # D-412 landing decision (2026-10-02): until the first two-robot device
    # validation, a robot auto-updates only when config.json says enabled=true.
    hub.publish(keys, NEXT)
    (device / "var/lib/rosy/updates/config.json").unlink()

    result = updater(host, hub).run()

    assert result["phase"] == "disabled"
    assert hub.requests == []
    assert host.calls == []


def test_a_config_without_the_enabled_key_is_off(device, host, hub, keys):
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/config.json", {"repo": REPO})

    result = updater(host, hub).run()

    assert result["phase"] == "disabled"
    assert hub.requests == []


def test_disabled_config_stops_before_any_request(device, host, hub, keys):
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/config.json", {"enabled": False, "repo": REPO})

    result = updater(host, hub).run()

    assert result["phase"] == "disabled"
    assert hub.requests == []
    assert host.calls == []


def test_unreadable_config_fails_closed(device, host, hub, keys):
    hub.publish(keys, NEXT)
    path = device / "var/lib/rosy/updates/config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert updater(host, hub).run()["phase"] == "error"
    assert hub.requests == []


def test_config_api_base_points_the_updater_at_another_server(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    write_json(device / "var/lib/rosy/updates/config.json",
               {"enabled": True, "repo": REPO, "api_base": hub.base + "/"})

    # The CLI default; the config key must win over it (device twin, tests).
    result = upd.Updater(host, api_base=upd.API_BASE).run()

    assert hub.list_requests(), "the release list was not requested from config api_base"
    assert result["candidate"] == NEXT


@pytest.mark.parametrize("api_base", ["ftp://example.test", "http://", 42, "http://host/ path"])
def test_invalid_config_api_base_fails_closed(device, host, hub, keys, api_base):
    hub.publish(keys, NEXT, canary=())
    write_json(device / "var/lib/rosy/updates/config.json", {"enabled": True, "repo": REPO, "api_base": api_base})

    result = upd.Updater(host, api_base=hub.base).run()

    assert result["phase"] == "error"
    assert "CONFIG_INVALID" in result["reason"]
    assert hub.requests == []


def test_api_request_carries_user_agent_and_etag(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    up = updater(host, hub)

    up.run()
    first = hub.list_requests()[-1]
    assert first["user-agent"].startswith("rosy-auto-update")
    assert "if-none-match" not in first
    assert state(device)["etag"] == hub.etag

    up.run()
    second = hub.list_requests()[-1]
    assert second["if-none-match"] == hub.etag


def test_304_reuses_the_cached_release_list(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    up = updater(host, hub)
    up.run()
    calls_before = len(hub.list_requests())

    result = up.run()

    assert len(hub.list_requests()) == calls_before + 1
    assert result["candidate"] == NEXT  # from the cache: the 304 carried no body
    assert result["phase"] == "waiting"


def test_chooses_the_highest_newer_complete_release(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER, canary=())
    hub.publish(keys, "2026.10.01-024", canary=(), skip_asset="rollout.json.sig")
    hub.publish(keys, "2026.10.01-025", canary=(), draft=True)
    hub.publish(keys, "2026.10.01-026", canary=(), prerelease=True)

    result = updater(host, hub).run()

    assert result["candidate"] == NEWER
    assert (device / "opt/rosy/releases" / NEWER).is_dir()
    assert not (device / "opt/rosy/releases" / NEXT).exists()


def test_invalid_rollout_signature_is_skipped(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER, canary=(), bad_signature=True)

    result = updater(host, hub).run()

    assert result["candidate"] == NEXT
    assert not (device / "opt/rosy/releases" / NEWER).exists()


def test_withdrawn_rollout_is_skipped(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER, withdrawn=True)

    assert updater(host, hub).run()["candidate"] == NEXT


def test_rollout_for_another_release_is_skipped(device, host, hub, keys):
    hub.publish(keys, NEWER, rollout_overrides={"release_id": NEXT})

    result = updater(host, hub).run()

    assert result["phase"] == "idle" and result["candidate"] is None


def test_failed_id_is_never_retried(device, host, hub, keys):
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/state.json",
               {"failed": {NEXT: {"at": _z(T0), "detail": "health"}}})

    result = updater(host, hub).run()

    assert result["phase"] == "idle"
    assert "unpack" not in kinds(host) and "activate" not in kinds(host)


@pytest.mark.parametrize("release_id", ["2026.10.01-020", CURRENT])
def test_lower_or_equal_id_is_ignored(device, host, hub, keys, release_id):
    hub.publish(keys, release_id)

    result = updater(host, hub).run()

    assert result["phase"] == "idle"
    assert host.calls == []
    assert not any(path.startswith("/dl/") for path, _ in hub.requests)


def test_apply_refuses_an_id_at_or_below_current(device, host, hub):
    up = updater(host, hub)
    with pytest.raises(upd.UpdateError, match="NOT_NEWER"):
        up.apply(CURRENT, {})
    with pytest.raises(upd.UpdateError, match="NOT_NEWER"):
        up.apply("2026.09.30-001", {})
    assert host.calls == []


# --- staging ----------------------------------------------------------------------


def test_sha_mismatch_does_not_stage(device, host, hub, keys):
    hub.publish(keys, NEXT, sha="0" * 64)

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert "SHA256_MISMATCH" in result["reason"]
    assert "unpack" not in kinds(host)
    assert not (device / "opt/rosy/releases" / NEXT).exists()
    assert not list((device / "var/lib/rosy/updates").rglob("*.part"))
    assert not list((device / "var/lib/rosy/updates").rglob("*.tar.gz"))


def test_stages_while_held_and_leaves_current_alone(device, host, hub, keys):
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("tester", "G4 recording", 2)

    result = up.run()

    assert result["phase"] == "held"
    assert (device / "opt/rosy/releases" / NEXT).is_dir()
    assert kinds(host) == ["unpack", "verify"]
    assert host.links["current"] == CURRENT
    assert state(device)["staged"] == NEXT
    unpack = host.calls[0]
    assert unpack[0] == "bash" and unpack[1].endswith("rosy-release-unpack.sh")
    assert unpack[-3] == NEXT and unpack[-1] == str(device / "opt/rosy/releases")


def test_already_staged_release_is_not_downloaded_again(device, host, hub, keys):
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("tester", "G4", 2)
    up.run()
    downloads = sum(path.endswith(".tar.gz") for path, _ in hub.requests)

    up.run()

    assert sum(path.endswith(".tar.gz") for path, _ in hub.requests) == downloads
    assert kinds(host).count("unpack") == 1


def test_failed_verify_marks_the_id_failed(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["verify"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_INVALID: x"}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert NEXT in state(device)["failed"]
    assert "activate" not in kinds(host)


# --- the rollout gate ---------------------------------------------------------------


def test_canary_host_applies_before_canary_ok(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=(HOST,), canary_ok=False)

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert host.links["current"] == NEXT


def test_non_canary_waits_for_canary_ok(device, host, hub, keys):
    host.host = OTHER
    hub.publish(keys, NEXT, canary=(HOST,), canary_ok=False, published_at=_z(T0 - dt.timedelta(hours=2)))

    result = updater(host, hub).run()

    assert result["phase"] == "waiting"
    assert "activate" not in kinds(host)


def test_non_canary_waits_for_the_wave_delay(device, host, hub, keys):
    host.host = OTHER
    hub.publish(keys, NEXT, canary=(HOST,), canary_ok=True, wave_delay_s=600,
                published_at=_z(T0 - dt.timedelta(seconds=599)))

    assert updater(host, hub).run()["phase"] == "waiting"
    assert "activate" not in kinds(host)

    host.t = T0 + dt.timedelta(seconds=2)
    assert updater(host, hub).run()["phase"] == "committed"


# --- eligibility --------------------------------------------------------------------


def test_idle_robot_is_eligible(device, host, hub):
    report = updater(host, hub).eligibility()
    assert report["eligible"] is True, report
    assert report["reasons"] == []


@pytest.mark.parametrize("changes", [
    {"robot_mode": "MANUAL"},
    {"robot_mode": None},
    {"nav_state": "NAVIGATING"},
    {"nav_state": "PLANNING"},
    {"nav_state": None},
    {"line_follow_mode": "IR_LINE"},
    {"docking_state": "DOCKING"},
    {"docking_state": "UNDOCKING"},
    {"swarm_active": True},
    {"estop": True},
    {"activity_kind": "CALIBRATING"},
    {"velocity_linear": 0.05},
    {"velocity_linear": -0.05},
    {"velocity_angular": 0.2},
    {"velocity_linear": None},
    {"velocity_linear": True},
    {"battery_percent": 39.0, "battery_charging": False},
    {"battery_percent": None, "battery_charging": False},
    {"battery_percent": None, "battery_charging": None},
    # Contract amendment b63cb7f2: null is unknown, unknown is ineligible, checked first.
    {"battery_percent": None, "battery_charging": True},
    {"battery_percent": float("nan"), "battery_charging": True},
    {"battery_percent": float("inf")},
    {"estop": None},
    {"swarm_active": None},
    {"line_follow_mode": None},
    {"line_follow_state": None},
    {"velocity_linear": None, "velocity_angular": 0.0},
    {"velocity_angular": None},
    {"velocity_linear": float("nan")},
    {"velocity_angular": float("-inf")},
    {"velocity_linear": "0"},
    {"battery_percent": "80", "battery_charging": True},
    {"battery_percent": True, "battery_charging": True},
    {"swarm_role": "leader"},
    {"swarm_role": "follower"},
    {"schema": 1},
    {"schema": "2"},
    {"written_at": "2026-10-01T15:58:59+00:00"},  # 61 s old
    {"written_at": "not a time"},
], ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()))
def test_each_busy_signal_makes_the_robot_ineligible(device, host, hub, changes):
    host.inputs_changes = changes
    host.write_inputs()

    report = updater(host, hub).eligibility()

    assert report["eligible"] is False
    assert report["reasons"]


@pytest.mark.parametrize("changes", [
    {"battery_percent": 30.0, "battery_charging": True},
    {"battery_percent": 40.0},
    {"nav_state": "ARRIVED"},
    {"docking_state": "DOCKED"},
    {"velocity_linear": 0.004, "velocity_angular": -0.01},
    {"schema": 3},
    {"swarm_role": "none"},
    {"swarm_role": None},
    {"battery_percent": 80.0, "battery_charging": None},
], ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()))
def test_values_that_do_not_block(device, host, hub, changes):
    host.inputs_changes = changes
    host.write_inputs()

    report = updater(host, hub).eligibility()

    assert report["eligible"] is True, report


@pytest.mark.parametrize("missing", ["velocity_linear", "battery_charging", "docking_state",
                                     "line_follow_mode", "swarm_active", "estop", "activity_kind",
                                     "robot_mode", "nav_state", "swarm_role"])
def test_a_missing_schema_2_key_is_ineligible(device, host, hub, missing):
    data = idle_inputs(host.t)
    del data[missing]
    write_json(device / "run/rosy/status-inputs.json", data)
    host.second_sample_changes = None
    host.write_inputs = lambda: None  # keep the broken file across the sample sleep

    assert updater(host, hub).eligibility()["eligible"] is False


def test_missing_or_oversized_status_inputs_are_ineligible(device, host, hub):
    path = device / "run/rosy/status-inputs.json"
    host.write_inputs = lambda: None
    path.unlink()
    assert updater(host, hub).eligibility()["eligible"] is False

    data = idle_inputs(host.t)
    data["pad"] = "x" * (17 * 1024)
    write_json(path, data)
    assert updater(host, hub).eligibility()["eligible"] is False


def test_two_samples_ten_seconds_apart_must_both_be_idle(device, host, hub):
    host.second_sample_changes = {"velocity_linear": 0.2}
    start = host.t

    report = updater(host, hub).eligibility()

    assert report["eligible"] is False
    assert host.t - start >= dt.timedelta(seconds=10)


def test_eligibility_is_read_only(device, host, hub):
    shutil.rmtree(device / "var/lib/rosy/updates")  # the fixture's config dir
    updater(host, hub).eligibility()
    assert not (device / "var/lib/rosy/updates").exists()
    assert not (device / "run/rosy-claim").exists()


# --- hold, sealed approvals, claim -----------------------------------------------------


def test_active_hold_holds(device, host, hub):
    up = updater(host, hub)
    up.hold("agent-x", "G5 drive", 1)

    report = up.eligibility()

    assert report["eligible"] is False and report["held"] is True
    hold = json.loads((device / "var/lib/rosy/updates/hold.json").read_text(encoding="utf-8"))
    assert set(hold) == {"holder", "reason", "created_at", "expires_at"}
    assert hold["expires_at"] == _z(T0 + dt.timedelta(hours=1))


def test_expired_hold_is_ignored_and_moved_to_history(device, host, hub, keys):
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("agent-x", "G5 drive", 1)
    host.t = T0 + dt.timedelta(hours=1, seconds=1)

    assert up.eligibility()["held"] is False
    result = up.run()

    assert result["phase"] == "committed"
    assert not (device / "var/lib/rosy/updates/hold.json").exists()
    assert any(entry["event"] == "hold_expired" for entry in history(device))


@pytest.mark.parametrize("hours", [0, -1, 168.01, 1000])
def test_hold_with_excessive_or_no_expiry_is_refused(device, host, hub, hours):
    with pytest.raises(upd.UpdateError):
        updater(host, hub).hold("agent-x", "x", hours)
    assert not (device / "var/lib/rosy/updates/hold.json").exists()


@pytest.mark.parametrize("payload", [
    {"holder": "a", "reason": "r", "created_at": _z(T0)},  # no expiry
    {"holder": "a", "reason": "r", "created_at": _z(T0), "expires_at": _z(T0 + dt.timedelta(days=8))},
    "garbage",
])
def test_hand_written_invalid_hold_fails_closed(device, host, hub, payload):
    path = device / "var/lib/rosy/updates/hold.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")

    report = updater(host, hub).eligibility()

    assert report["eligible"] is False and report["held"] is True
    assert "release-hold" in report["reasons"][0]


def test_over_long_hold_never_expires_on_its_own(device, host, hub):
    # Treated as invalid (fail closed), not as a hold that lapses after its 8 days.
    write_json(device / "var/lib/rosy/updates/hold.json",
               {"holder": "a", "reason": "r", "created_at": _z(T0), "expires_at": _z(T0 + dt.timedelta(days=8))})
    host.t = T0 + dt.timedelta(days=9)

    report = updater(host, hub).eligibility()

    assert report["held"] is True and "7 days" in report["reasons"][0]


def test_release_hold_clears_it(device, host, hub):
    up = updater(host, hub)
    up.hold("agent-x", "x", 1)
    up.release_hold()
    assert up.eligibility()["eligible"] is True
    assert [entry["event"] for entry in history(device)] == ["hold_set", "hold_released"]


@pytest.mark.parametrize("marker", ["hardware.approved", "navigation.approved"])
def test_sealed_approval_for_the_current_release_holds(device, host, hub, marker):
    write_json(device / "etc/rosy/approvals" / marker, {"release_id": CURRENT})
    report = updater(host, hub).eligibility()
    assert report["held"] is True and report["eligible"] is False


def test_approval_for_another_release_does_not_hold(device, host, hub):
    write_json(device / "etc/rosy/approvals/hardware.approved", {"release_id": "2026.09.30-001"})
    assert updater(host, hub).eligibility()["eligible"] is True


def test_claim_held_by_another_party_is_ineligible(device, host, hub, keys):
    hub.publish(keys, NEXT)
    claim_mod.acquire(device, "push-pc", "release push", 1800, now=T0)

    up = updater(host, hub)
    assert up.eligibility()["eligible"] is False
    result = up.run()

    assert result["phase"] == "ineligible"
    assert "push-pc" in result["reason"]
    assert "activate" not in kinds(host)


def test_stale_claim_is_taken_over(device, host, hub, keys):
    hub.publish(keys, NEXT)
    claim_mod.acquire(device, "push-pc", "release push", 60, now=T0 - dt.timedelta(minutes=5))

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert not (device / "run/rosy-claim").exists()  # released after the apply


# --- apply ------------------------------------------------------------------------------


def test_apply_success_runs_the_transaction_in_order(device, host, hub, keys):
    hub.publish(keys, NEXT)

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert result["current_release"] == NEXT
    assert result["last_result"]["outcome"] == "committed"
    order = [k for k in kinds(host) if k not in {"is-active", "failed", "mainpid"}]
    assert order[:3] == ["unpack", "verify", "activate"]
    # The pre-apply baseline (active units, failed units) is taken before activation.
    before = kinds(host)[:kinds(host).index("activate")]
    assert "is-active" in before and "failed" in before
    assert order.index("sync") < order.index("restart") < order.index("ready")
    sync = next(argv for argv in host.calls if kind_of(argv) == "sync")
    assert sync[-1] == str(device / "opt/rosy/releases" / NEXT / "deploy/robot/native/sync-image-layer.py")
    restart = next(argv for argv in host.calls if kind_of(argv) == "restart")
    assert restart == ["systemctl", "restart", "rosy-io.service", "rosy-auto-update.timer"]
    assert host.t - T0 >= dt.timedelta(seconds=60)  # health held for 60 s
    assert not (device / "run/rosy-claim").exists()
    assert state(device).get("applying") is None
    events = [entry["event"] for entry in history(device)]
    assert events.index("staged") < events.index("applying") < events.index("committed")


def test_core_on_the_old_release_is_restarted(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: (setattr(h, "stale_core", True), None)[1]

    result = updater(host, hub).run()

    assert host.core_restarts == 1
    assert result["phase"] == "committed"


@pytest.mark.parametrize("failure", ["ready", "cwd", "inactive", "failed_unit", "sync", "core_restart"])
def test_health_failure_rolls_back_and_marks_the_id_failed(device, host, hub, keys, failure):
    hub.publish(keys, NEXT)
    bad = subprocess.CompletedProcess([], 1, "", "boom")
    if failure == "ready":
        host.overrides["ready"] = lambda h, argv: bad if h.links["current"] == NEXT else None
    elif failure == "cwd":
        host.overrides["cwd"] = lambda pid, release: str(
            device / "opt/rosy/releases" / (CURRENT if pid == 103 else str(release)))
    elif failure == "inactive":
        host.overrides["is-active"] = lambda h, argv: bad if "rosy-camera.service" in argv and h.links["current"] == NEXT else None
    elif failure == "failed_unit":
        host.overrides["failed"] = lambda h, argv: subprocess.CompletedProcess(
            [], 0, "rosy-hw-probe.service loaded failed failed probe\n" if h.links["current"] == NEXT else "", "")
    elif failure == "sync":
        host.overrides["sync"] = lambda h, argv: bad if NEXT in " ".join(argv) else None
    else:
        host.overrides["activate"] = lambda h, argv: (setattr(h, "stale_core", True), None)[1]
        host.overrides["restart"] = lambda h, argv: bad if "rosy-core.service" in argv and h.links["current"] == NEXT else None

    up = updater(host, hub)
    result = up.run()

    assert result["phase"] == "rolled_back", result
    assert result["last_result"]["outcome"] == "rolled_back"
    assert host.links["current"] == CURRENT
    assert "rollback" in kinds(host)
    after = kinds(host)[kinds(host).index("rollback"):]
    assert "sync" in after and "ready" in after
    rolled_sync = [argv for argv in host.calls[kinds(host).index("rollback"):] if kind_of(argv) == "sync"][0]
    assert CURRENT in rolled_sync[-1]
    assert NEXT in state(device)["failed"]
    assert not (device / "run/rosy-claim").exists()

    # never retried
    host.calls.clear()
    again = up.run()
    assert again["phase"] == "idle"
    assert "activate" not in kinds(host)


def _down(unit: str, *, after_only: bool = False):
    def override(h, argv):
        if unit in argv and (not after_only or h.links["current"] == NEXT):
            return subprocess.CompletedProcess([], 3, "", "inactive")
        return None
    return override


def test_camera_down_before_the_apply_does_not_block_the_commit(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-camera.service")

    result = updater(host, hub).run()

    assert result["phase"] == "committed", result
    assert "rosy-camera.service" in result["last_result"]["detail"]
    assert NEXT not in state(device).get("failed", {})


def test_camera_up_before_and_down_after_rolls_back(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-camera.service", after_only=True)

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "rosy-camera.service" in result["last_result"]["detail"]


def test_core_is_always_required_even_if_it_was_down_before(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-core.service")

    assert updater(host, hub).run()["phase"] == "rolled_back"


def test_io_cwd_is_not_checked_when_io_was_down_before(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-io.service")
    host.overrides["cwd"] = lambda pid, release: str(
        device / "opt/rosy/releases" / (CURRENT if pid == 102 else str(release)))

    assert updater(host, hub).run()["phase"] == "committed"


def test_a_unit_failed_before_the_apply_does_not_block_the_commit(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["failed"] = lambda h, argv: subprocess.CompletedProcess(
        [], 0, "rosy-hw-probe.service loaded failed failed probe\n", "")

    result = updater(host, hub).run()

    assert result["phase"] == "committed", result
    assert "rosy-hw-probe.service" in result["last_result"]["detail"]


def test_a_unit_that_fails_during_the_apply_rolls_back_beside_an_old_failure(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["failed"] = lambda h, argv: subprocess.CompletedProcess(
        [], 0, "rosy-hw-probe.service loaded failed failed probe\n"
        + ("rosy-io.service loaded failed failed io\n" if h.links["current"] == NEXT else ""), "")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "rosy-io.service" in result["last_result"]["detail"]


def test_activation_busy_retries_later_and_is_not_failed(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: another operation is active"}), "")

    up = updater(host, hub)
    result = up.run()

    assert result["phase"] == "waiting"
    assert "NATIVE_RELEASE_BUSY" in result["reason"]
    assert NEXT not in state(device).get("failed", {})
    assert "rollback" not in kinds(host)
    assert not (device / "run/rosy-claim").exists()

    del host.overrides["activate"]
    assert up.run()["phase"] == "committed"


def test_activation_refused_marks_failed_without_rollback(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_PYTHON_RUNTIME: mismatch"}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "failed"
    assert result["last_result"]["outcome"] == "refused"
    assert NEXT in state(device)["failed"]
    assert "rollback" not in kinds(host)


def test_interrupted_apply_is_finished_on_the_next_run(device, host, hub, keys):
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    host.links = {"current": NEXT, "previous": CURRENT}
    write_json(device / "var/lib/rosy/updates/state.json",
               {"applying": {"release_id": NEXT, "previous": CURRENT, "started_at": _z(T0), "boot_id": BOOT}})

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert state(device).get("applying") is None
    assert any(entry["event"] == "apply_interrupted" for entry in history(device))


# --- network and rate limits -------------------------------------------------------------


@pytest.mark.parametrize("code", [403, 429])
def test_rate_limit_backs_off_without_crashing(device, host, hub, keys, code):
    hub.publish(keys, NEXT)
    hub.status = code
    hub.extra_headers = {"Retry-After": "120"}
    up = updater(host, hub)

    result = up.run()
    assert result["phase"] == "error"
    assert str(code) in result["reason"]
    requests = len(hub.requests)

    host.t += dt.timedelta(seconds=60)
    assert up.run()["phase"] == "error"
    assert len(hub.requests) == requests  # still backing off: no request

    hub.status = None
    host.t += dt.timedelta(seconds=61)
    assert up.run()["phase"] == "committed"


def test_network_error_is_an_error_phase(device, host, hub, keys):
    up = upd.Updater(host, api_base="http://127.0.0.1:9")  # nothing listens

    result = up.run()

    assert result["phase"] == "error"
    assert result["reason"]


def test_server_error_is_an_error_phase(device, host, hub, keys):
    hub.status = 500
    assert updater(host, hub).run()["phase"] == "error"


# --- records -----------------------------------------------------------------------------


def test_status_and_history_follow_the_contract(device, host, hub, keys):
    hub.publish(keys, NEXT)

    updater(host, hub).run()

    current = status(device)
    assert set(current) == {"schema", "updated_at", "hostname", "current_release", "candidate",
                            "phase", "reason", "last_result"}
    assert current["schema"] == 1 and current["hostname"] == HOST
    assert current["phase"] in upd.PHASES
    assert current["updated_at"].endswith("Z")
    assert set(current["last_result"]) == {"release_id", "outcome", "at", "detail"}
    lines = history(device)
    assert lines
    for entry in lines:
        assert set(entry) == {"at", "event", "release_id", "detail", "boot_id"}
        assert entry["boot_id"] == BOOT
    raw = (device / "var/lib/rosy/updates/history.jsonl").read_bytes()
    assert b"\r\n" not in raw


def test_cli_status_and_eligibility_json(device, host, hub, keys, capsys, monkeypatch):
    hub.publish(keys, NEXT)
    monkeypatch.setattr(upd, "Host", lambda root: host)
    monkeypatch.setattr(upd, "API_BASE", hub.base)

    assert upd.main(["--root", str(device), "run"]) == 0
    capsys.readouterr()
    assert upd.main(["--root", str(device), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "committed"
    assert upd.main(["--root", str(device), "eligibility", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["eligible"] is True
    assert upd.main(["--root", str(device), "hold", "--holder", "a", "--reason", "b", "--hours", "200"]) == 2
    assert upd.main(["--root", str(device), "hold", "--holder", "a", "--reason", "b", "--hours", "2"]) == 0
    assert upd.main(["--root", str(device), "eligibility", "--json"]) == 1
    assert upd.main(["--root", str(device), "release-hold"]) == 0


def test_real_host_bounds_every_command(tmp_path):
    real = upd.Host(tmp_path)
    result = real.run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.5)
    assert result.returncode == 124
    assert "TIMEOUT" in result.stderr
    missing = real.run(["definitely-not-a-command-xyz"], timeout=5)
    assert missing.returncode == 127


# --- the units -------------------------------------------------------------------------


def _unit(name: str) -> list[str]:
    return [line.strip() for line in (NATIVE / name).read_text(encoding="utf-8").splitlines()]


def test_the_service_is_a_low_priority_root_oneshot_with_network():
    lines = _unit("rosy-auto-update.service")
    for directive in ("Type=oneshot", "Nice=19", "IOSchedulingClass=idle", "ProtectSystem=strict",
                      "ExecStart=/usr/bin/python3 -I -B /opt/rosy/native-runtime/rosy_auto_update.py run",
                      "Wants=network-online.target", "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"):
        assert directive in lines, directive
    assert not any(line.startswith(("User=", "DynamicUser=", "PrivateNetwork=")) for line in lines)
    assert not any(line.startswith("[Install]") for line in lines)  # started by the timer only


def test_the_timer_runs_every_ten_minutes_spread_out():
    lines = _unit("rosy-auto-update.timer")
    for directive in ("OnBootSec=5min", "OnUnitActiveSec=10min", "RandomizedDelaySec=2min",
                      "WantedBy=timers.target"):
        assert directive in lines, directive
    assert not any(line.startswith("Persistent=") for line in lines)  # no effect without OnCalendar (L5)


def test_the_service_requires_recovery_and_keeps_proc_readable():
    # L8: /var/lib/rosy/releases comes from rosy-release-recover (StateDirectory), which
    # the unit requires and follows; nothing may hide other processes' /proc/<pid>/cwd.
    lines = _unit("rosy-auto-update.service")
    assert "Requires=rosy-release-recover.service" in lines
    assert any(line.startswith("After=") and "rosy-release-recover.service" in line for line in lines)
    assert not any("-/var/lib/rosy/releases" in line for line in lines)
    for forbidden in ("CapabilityBoundingSet=", "ProtectProc=", "PrivatePIDs=", "ProcSubset="):
        assert not any(line.startswith(forbidden) for line in lines), forbidden


def test_claim_ttl_outlasts_the_unit_timeout():
    # M8: the claim must not expire while the run that holds it may still be running.
    timeout = next(line.split("=", 1)[1] for line in _unit("rosy-auto-update.service")
                   if line.startswith("TimeoutStartSec="))
    assert timeout.endswith("min")
    assert upd.CLAIM_TTL_S >= int(timeout[:-3]) * 60


# --- independent review (REQUEST CHANGES) ------------------------------------------------


def journal(device: Path, step: str, release_id: str = NEXT, **extra) -> None:
    applying = {"release_id": release_id, "previous": CURRENT, "step": step, "started_at": _z(T0),
                "boot_id": BOOT, "baseline": {"active": {u: None for u in upd.HEALTH_UNITS}, "failed": []}}
    applying.update(extra)
    write_json(device / "var/lib/rosy/updates/state.json", {"applying": applying})


def switched(device: Path, host: FakeHost) -> None:
    (device / "opt/rosy/releases" / NEXT / "deploy/robot/native").mkdir(parents=True, exist_ok=True)
    host.links = {"current": NEXT, "previous": CURRENT}


RESTARTING = {"sync", "restart", "rollback", "activate", "start"}


def test_resume_waits_for_a_hold_before_any_restart(device, host, hub, keys):
    # H1
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "health")
    up = updater(host, hub)
    up.hold("agent", "G5", 2)

    result = up.run()

    assert result["phase"] == "held"
    assert not RESTARTING & set(kinds(host))  # reading MainPID (is CORE running?) is allowed
    assert state(device)["applying"]["release_id"] == NEXT

    up.release_hold()
    assert up.run()["phase"] == "committed"


@pytest.mark.parametrize("cause", ["moving", "sealed", "same_sample"])
def test_resume_waits_until_the_robot_is_idle(device, host, hub, keys, cause):
    # H1 (+ M1 in the resume path)
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "image-layer-sync")
    if cause == "moving":
        host.inputs_changes = {"velocity_linear": 0.3}
        host.write_inputs()
    elif cause == "sealed":
        write_json(device / "etc/rosy/approvals/hardware.approved", {"release_id": NEXT})
    else:
        host.write_inputs = lambda: None

    result = updater(host, hub).run()

    assert result["phase"] in {"held", "ineligible"}
    assert not RESTARTING & set(kinds(host))
    assert state(device)["applying"]["step"] == "image-layer-sync"


def test_resume_after_rollback_step_never_commits(device, host, hub, keys):
    # H2: the journal reached rollback with the new release still current.
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "rollback", why="HEALTH: x")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert host.links["current"] == CURRENT
    order = kinds(host)
    assert order.index("rollback") < order.index("sync") < order.index("ready")
    assert NEXT in state(device)["failed"]
    assert state(device).get("applying") is None


def test_resume_after_rollback_step_with_old_release_current_still_syncs(device, host, hub, keys):
    # H2: rollback-release.sh already ran; only the tail is left.
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    host.links = {"current": CURRENT, "previous": NEXT}
    journal(device, "rollback", why="HEALTH: x")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "rollback" not in kinds(host)
    sync = [argv for argv in host.calls if kind_of(argv) == "sync"]
    assert sync and CURRENT in sync[0][-1]
    assert "ready" in kinds(host)


def test_resume_after_boot_recovery_mid_sync_resyncs_the_current_release(device, host, hub, keys):
    # H2: current != release_id and the step was later than activate.
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    journal(device, "image-layer-sync")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    sync = [argv for argv in host.calls if kind_of(argv) == "sync"]
    assert sync and CURRENT in sync[0][-1]
    assert "activate" not in kinds(host)


@pytest.mark.parametrize("outcome", [
    subprocess.CompletedProcess([], 124, "", "TIMEOUT after 900s"),
    subprocess.CompletedProcess([], 127, "", "cannot run bash"),
    subprocess.CompletedProcess([], 1, "Traceback (most recent call last)", "boom"),
], ids=["timeout", "missing", "no-json"])
def test_transient_activation_failure_is_not_marked_failed(device, host, hub, keys, outcome):
    # H3
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: outcome

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert NEXT not in state(device).get("failed", {})
    assert state(device).get("applying") is None
    del host.overrides["activate"]
    host.t += dt.timedelta(minutes=11)  # past the first apply backoff (N7)
    assert updater(host, hub).run()["phase"] == "committed"


def test_activation_failure_with_a_native_journal_recovers_and_restarts_runtime(device, host, hub, keys):
    # H3
    hub.publish(keys, NEXT)

    def killed_midway(h, argv):
        write_json(device / "var/lib/rosy/releases/native-activation.json",
                   {"schema_version": 1, "operation": "activate", "candidate": NEXT,
                    "old_current": CURRENT, "old_previous": None, "phase": "switched"})
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = killed_midway

    result = updater(host, hub).run()

    order = kinds(host)
    assert order.index("recover") < order.index("start")
    start = next(argv for argv in host.calls if kind_of(argv) == "start")
    assert start == ["systemctl", "start", "rosy-runtime.target"]
    assert host.links["current"] == CURRENT
    assert NEXT not in state(device).get("failed", {})
    assert result["phase"] == "error"


def test_transient_activation_failure_that_left_the_new_release_current_rolls_back_unmarked(
        device, host, hub, keys):
    # H3: no native journal, yet the switch happened: roll back but keep the id retryable.
    hub.publish(keys, NEXT)

    def switched_then_timed_out(h, argv):
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = switched_then_timed_out

    result = updater(host, hub).run()

    assert host.links["current"] == CURRENT
    assert "rollback" in kinds(host)
    assert NEXT not in state(device).get("failed", {})
    assert result["last_result"]["outcome"] == "rolled_back"


def test_staging_verify_timeout_is_transient(device, host, hub, keys):
    # H3
    hub.publish(keys, NEXT)
    host.overrides["verify"] = lambda h, argv: subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert NEXT not in state(device).get("failed", {})


def test_operator_rollback_of_a_committed_release_is_respected(device, host, hub, keys):
    # H4
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    assert up.run()["phase"] == "committed"
    assert NEXT in state(device)["committed"]
    host.links = {"current": CURRENT, "previous": NEXT}  # rosy-release-push.ps1 -Rollback
    host.calls.clear()

    result = up.run()

    assert result["phase"] == "idle"
    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"
    assert "activate" not in kinds(host)


def test_two_samples_must_be_two_different_writes(device, host, hub):
    # M1: CORE stopped writing, so the second sample is the same file.
    host.write_inputs = lambda: None
    report = updater(host, hub).eligibility()
    assert report["eligible"] is False
    assert any("second sample" in reason for reason in report["reasons"])


def test_samples_older_than_25_seconds_are_stale(device, host, hub):
    # M1: two distinct writes, each 26 s old when read (CORE lagging, not stopped).
    def lagging():
        write_json(device / "run/rosy/status-inputs.json", idle_inputs(host.t - dt.timedelta(seconds=26)))

    host.write_inputs = lagging
    lagging()
    report = updater(host, hub).eligibility()
    assert report["eligible"] is False
    assert any("stale" in reason for reason in report["reasons"])


def test_inputs_are_checked_again_right_before_activation(device, host, hub, keys):
    # M2: the robot started moving after eligibility passed.
    hub.publish(keys, NEXT)
    seen = {"n": 0}

    def started_moving(h, argv):
        seen["n"] += 1
        h.inputs_changes = {"robot_mode": "MANUAL"}
        h.write_inputs()
        return None

    host.overrides["failed"] = started_moving  # the baseline lists failed units before activation

    result = updater(host, hub).run()

    assert seen["n"] >= 1
    assert result["phase"] == "ineligible"
    assert "activate" not in kinds(host)
    assert state(device).get("applying") is None
    assert not (device / "run/rosy-claim").exists()


def test_run_busy_writes_nothing(device, host, hub, keys):
    # M3
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    write_json(device / "var/lib/rosy/updates/status.json", {"phase": "sentinel"})
    write_json(device / "var/lib/rosy/updates/state.json", {"sentinel": True})
    with up._run_lock():
        result = updater(host, hub).run()

    assert "RUN_BUSY" in result["reason"]
    assert status(device) == {"phase": "sentinel"}
    assert state(device) == {"sentinel": True}
    assert hub.requests == []


def test_a_withdrawal_is_remembered(device, host, hub, keys):
    # M4
    hub.publish(keys, NEXT, withdrawn=True, rollout_overrides={"reason": "bad canary"})
    up = updater(host, hub)
    assert up.run()["phase"] == "idle"
    assert NEXT in state(device)["withdrawn"]

    hub.publish(keys, NEXT, withdrawn=False)
    result = up.run()

    assert result["phase"] == "idle"
    assert "activate" not in kinds(host) and "unpack" not in kinds(host)


def test_definitive_stage_errors_back_off_and_fail_after_three(device, host, hub, keys):
    # M5
    hub.publish(keys, NEXT, sha="0" * 64)
    up = updater(host, hub)
    for attempt in range(1, 4):
        result = up.run()
        assert result["phase"] == "error"
        downloads = sum(path.endswith(".tar.gz") for path, _ in hub.requests)
        assert downloads == attempt
        # inside the backoff: no new download
        up.run()
        assert sum(path.endswith(".tar.gz") for path, _ in hub.requests) == attempt
        host.t += dt.timedelta(hours=7)
    assert NEXT in state(device)["failed"]
    assert up.run()["phase"] == "idle"


def test_network_stage_errors_back_off_but_never_fail(device, host, hub, keys):
    # M5
    hub.publish(keys, NEXT)
    hub.asset_status[f"{NEXT}/{NEXT}.tar.gz"] = 503
    up = updater(host, hub)
    for _ in range(4):
        assert up.run()["phase"] == "error"
        host.t += dt.timedelta(hours=7)
    assert NEXT not in state(device).get("failed", {})
    assert state(device)["stage_errors"][NEXT]["attempts"] == 4


def test_not_enough_disk_is_refused_before_downloading(device, host, hub, keys):
    # M5: tarball size x 2 + 512 MiB
    hub.publish(keys, NEXT)
    host.free = 512 * 1024 * 1024
    result = updater(host, hub).run()
    assert result["phase"] == "error" and "DISK" in result["reason"]
    assert not any(path.endswith(".tar.gz") for path, _ in hub.requests)


def test_old_and_failed_release_directories_are_pruned_after_commit(device, host, hub, keys):
    # M5
    releases = device / "opt/rosy/releases"
    stamp = (T0 - dt.timedelta(hours=2)).timestamp()
    for old in ("2026.09.30-001", "2026.09.30-002"):
        (releases / old).mkdir()
        os.utime(releases / old, (stamp, stamp))  # older than the 1 h prune guard (N6)
    host.links["previous"] = "2026.09.30-002"
    (releases / ".tmp-2026.10.01-099-1").mkdir()
    hub.publish(keys, NEXT)

    assert updater(host, hub).run()["phase"] == "committed"

    left = sorted(path.name for path in releases.iterdir())
    assert left == [".tmp-2026.10.01-099-1", CURRENT, NEXT]  # current=NEXT, previous=CURRENT


@pytest.mark.parametrize("content", [b"{not json", b"[1, 2]", b"x" * (70 * 1024), b'{"release_id": 5}'],
                         ids=["corrupt", "not-object", "oversize", "bad-id"])
def test_an_unreadable_approval_marker_holds(device, host, hub, content):
    # M6
    path = device / "etc/rosy/approvals/hardware.approved"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    report = updater(host, hub).eligibility()
    assert report["held"] is True and report["eligible"] is False


def test_a_symlinked_approval_marker_holds(device, host, hub, tmp_path):
    # M6
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"release_id": "2026.09.30-001"}), encoding="utf-8")
    link = device / "etc/rosy/approvals/navigation.approved"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("this host cannot create symlinks")
    assert updater(host, hub).eligibility()["held"] is True


@pytest.mark.parametrize("outcome", [
    subprocess.CompletedProcess([], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), ""),
    subprocess.CompletedProcess([], 124, "", "TIMEOUT"),
], ids=["busy", "timeout"])
def test_a_rollback_that_cannot_run_now_is_retried(device, host, hub, keys, outcome):
    # M7
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: outcome
    up = updater(host, hub)

    result = up.run()

    assert result["phase"] == "error"
    assert state(device)["applying"]["step"] == "rollback"
    assert host.links["current"] == NEXT

    del host.overrides["rollback"]
    final = up.run()
    assert final["phase"] == "rolled_back"
    assert host.links["current"] == CURRENT
    assert state(device).get("applying") is None


def test_the_claim_is_refreshed_at_each_journal_step(device, host, hub, keys):
    # M8
    hub.publish(keys, NEXT)
    seen = {}

    def slow_sync(h, argv):
        h.t += dt.timedelta(seconds=2000)
        return None

    def capture(h, argv):
        seen["claim"] = json.loads((device / "run/rosy-claim/claim.json").read_text(encoding="utf-8"))
        seen["t"] = h.t
        return None

    host.overrides["sync"] = slow_sync
    host.overrides["restart"] = capture

    assert updater(host, hub).run()["phase"] == "committed"
    expires = upd.parse_z(seen["claim"]["expires_at"])
    assert expires >= seen["t"] + dt.timedelta(seconds=upd.CLAIM_TTL_S - 1)


def test_rollout_network_errors_do_not_fall_through_to_a_lower_release(device, host, hub, keys):
    # L1
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER)
    hub.asset_status[f"{NEWER}/rollout.json"] = 502

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert result["candidate"] == NEWER
    assert not (device / "opt/rosy/releases" / NEXT).exists()


@pytest.mark.parametrize("changes,eligible", [
    ({"docking_state": "UNDOCKED"}, True),
    ({"docking_state": "DOCKED"}, True),
    ({"docking_state": "CHARGING"}, True),
    ({"docking_state": "DOCK_FAILED"}, False),
    ({"docking_state": "SOMETHING_NEW"}, False),
    ({"line_follow_state": "TRACKING"}, False),
    ({"line_follow_state": "WAITING"}, False),
    ({"velocity_linear": 10 ** 400}, False),
    ({"battery_percent": 10 ** 400}, False),
], ids=lambda value: str(value)[:40])
def test_docking_allowlist_line_follow_state_and_overflow(device, host, hub, changes, eligible):
    # L2, L3
    host.inputs_changes = changes
    host.write_inputs()
    assert updater(host, hub).eligibility()["eligible"] is eligible


def test_history_records_only_changes_of_phase_or_reason_class(device, host, hub, keys):
    # L4
    hub.publish(keys, NEXT)
    write_json(device / "run/rosy/status-inputs.json", idle_inputs(T0 - dt.timedelta(seconds=100)))
    host.write_inputs = lambda: None
    up = updater(host, hub)
    up.run()
    host.t += dt.timedelta(seconds=60)
    up.run()

    ineligible = [entry for entry in history(device) if entry["event"] == "ineligible"]
    assert len(ineligible) == 1


def test_history_rotates_at_its_size_limit(device, host, hub, monkeypatch):
    # L4
    monkeypatch.setattr(upd, "HISTORY_MAX_BYTES", 400)
    up = updater(host, hub)
    for index in range(10):
        up.hold("agent", f"reason {index}", 1)
    path = device / "var/lib/rosy/updates/history.jsonl"
    assert path.stat().st_size <= 400 + 300
    assert (device / "var/lib/rosy/updates/history.jsonl.1").is_file()


def test_real_host_kills_the_whole_process_group_on_timeout(tmp_path):
    # L6: a grandchild of a timed-out command must not survive it.
    marker = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open(r'{marker}', 'w').write(str(p.pid))\n"
        "time.sleep(30)\n"
    )
    result = upd.Host(tmp_path).run([sys.executable, "-c", script], timeout=3)
    assert result.returncode == 124
    pid = int(marker.read_text())
    deadline = dt.datetime.now() + dt.timedelta(seconds=5)
    while dt.datetime.now() < deadline and _alive(pid):
        pass
    assert not _alive(pid)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in listed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_a_stray_directory_in_downloads_does_not_block_staging(device, host, hub, keys):
    # L7
    stray = device / "var/lib/rosy/updates/downloads/junk"
    stray.mkdir(parents=True)
    (stray / "file").write_text("x", encoding="utf-8")
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("agent", "x", 1)

    assert up.run()["phase"] == "held"
    assert not stray.exists()


def test_disabled_while_applying_still_finishes_the_apply(device, host, hub, keys):
    # L9
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "health")
    write_json(device / "var/lib/rosy/updates/config.json", {"enabled": False, "repo": REPO})

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert hub.requests == []


def test_unexpected_exception_after_activation_rolls_back(device, host, hub, keys):
    hub.publish(keys, NEXT)

    def explode(h, argv):
        raise RuntimeError("bug in a helper")

    host.overrides["restart"] = lambda h, argv: explode(h, argv) if h.links["current"] == NEXT else None

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "UNEXPECTED" in result["last_result"]["detail"]
    assert host.links["current"] == CURRENT


# --- coordinator decision on H1: CORE down waives idleness for a resume ---------------
# Re-review N2: "down" is read fail-closed from systemctl show ActiveState/SubState/MainPID.


def _core_state(active: str, sub: str, pid: int, returncode: int = 0):
    return lambda h, argv: subprocess.CompletedProcess(
        [], returncode, f"ActiveState={active}\nSubState={sub}\nMainPID={pid}\n" if returncode == 0 else "", "")


def _core_down_until_restarted(host: FakeHost, *, fresh_after_restart: bool = False,
                               active: str = "inactive", sub: str = "dead") -> None:
    host.core_up = False
    real_write = FakeHost.write_inputs

    def core_state(h, argv):
        if h.core_up:
            return None
        return _core_state(active, sub, 0)(h, argv)

    def is_active(h, argv):
        if "rosy-core.service" in argv and not h.core_up:
            return subprocess.CompletedProcess([], 3, "", "inactive")
        return None

    def restart(h, argv):
        if "rosy-core.service" in argv:
            h.core_up = True
            if fresh_after_restart:
                h.write_inputs = lambda: real_write(h)
                h.write_inputs()
        return None

    def mainpid(h, argv):
        if argv[-1] == "rosy-core.service" and not h.core_up:
            return subprocess.CompletedProcess([], 0, "0\n", "")
        return None

    host.overrides.update({"corestate": core_state, "is-active": is_active, "restart": restart,
                           "mainpid": mainpid})


def _stale_inputs(device: Path, host: FakeHost) -> None:
    write_json(device / "run/rosy/status-inputs.json", idle_inputs(T0 - dt.timedelta(minutes=10)))
    host.write_inputs = lambda: None


def _resume_case(device, host, hub, keys, step="image-layer-sync"):
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, step)


def test_resume_with_core_down_waives_the_idleness_check(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=True)
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "committed", result
    assert "core not running; idleness check waived" in result["last_result"]["detail"]
    assert any("idleness check waived" in entry["detail"] for entry in history(device))


@pytest.mark.parametrize("active,sub", [("failed", "failed"), ("activating", "auto-restart")])
def test_failed_or_restarting_core_without_a_pid_is_down(device, host, hub, keys, active, sub):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=True, active=active, sub=sub)
    _stale_inputs(device, host)

    assert updater(host, hub).run()["phase"] == "committed"


@pytest.mark.parametrize("override", [
    _core_state("active", "running", 0),           # active without a MainPID
    _core_state("inactive", "dead", 4242),         # a PID still recorded
    _core_state("activating", "start-pre", 0),     # starting, not crash-looping
    _core_state("inactive", "dead", 0, returncode=1),  # systemctl failed: assume running
    lambda h, argv: subprocess.CompletedProcess([], 0, "garbage\n", ""),
], ids=["active-no-pid", "pid-left", "start-pre", "systemctl-failed", "unparseable"])
def test_anything_else_counts_as_core_running(device, host, hub, keys, override):
    _resume_case(device, host, hub, keys)
    host.overrides["corestate"] = override
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "waived" not in result["reason"]
    assert not RESTARTING & set(kinds(host))


def test_resume_with_core_down_still_honours_a_hold(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host)
    _stale_inputs(device, host)
    up = updater(host, hub)
    up.hold("agent", "G5", 2)

    result = up.run()

    assert result["phase"] == "held"
    assert not RESTARTING & set(kinds(host))
    assert state(device)["applying"]["step"] == "image-layer-sync"


def test_resume_with_core_down_still_honours_a_seal_and_a_claim(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host)
    _stale_inputs(device, host)
    claim_mod.acquire(device, "push-pc", "release push", 1800, now=T0)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "push-pc" in result["reason"]
    assert not RESTARTING & set(kinds(host))


def test_resume_with_core_active_and_stale_inputs_is_ineligible(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "waived" not in result["reason"]
    assert not RESTARTING & set(kinds(host))


def test_waived_resume_defers_when_core_comes_back_without_idle_status(device, host, hub, keys):
    # N4: CORE restarted by the core-release check; before restarting units the
    # normal idleness check applies, and stale inputs defer the resume.
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=False)
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "deferred" in result["reason"]
    assert state(device)["applying"]["release_id"] == NEXT
    assert not any(kind_of(argv) == "restart" and "rosy-io.service" in argv for argv in host.calls)
    assert "rollback" not in kinds(host)


def test_the_waiver_note_is_dropped_once_core_runs_again(device, host, hub, keys):
    # N15: a later resume with CORE running must not carry the old waiver note.
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=False)
    _stale_inputs(device, host)
    up = updater(host, hub)
    assert up.run()["phase"] == "ineligible"
    host.write_inputs = lambda: FakeHost.write_inputs(host)
    host.write_inputs()

    result = up.run()

    assert result["phase"] == "committed", result
    assert "waived" not in result["last_result"]["detail"]


def test_core_active_but_silent_for_30_minutes_is_stuck(device, host, hub, keys):
    # N5: no auto-rollback; tell the operator.
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)
    assert updater(host, hub).run()["phase"] == "ineligible"  # silent_since = T0
    host.t = T0 + dt.timedelta(minutes=29)
    assert updater(host, hub).run()["phase"] == "ineligible"

    host.t = T0 + dt.timedelta(minutes=31)
    result = updater(host, hub).run()

    assert result["phase"] == "stuck"
    assert result["reason"].startswith("CORE active but not writing status; operator action required")
    assert "rosy-release-push.ps1 -Rollback" in result["reason"]  # L3
    assert state(device)["applying"]["release_id"] == NEXT
    assert not RESTARTING & set(kinds(host))


# --- re-review: classification, backoff, precheck, rollback recovery --------------------


@pytest.mark.parametrize("error,definitive", [
    ("NATIVE_MANIFEST_PAYLOAD: digest mismatch for x", True),
    ("NATIVE_TARGET_MISMATCH: host", True),
    ("NATIVE_PYTHON_RUNTIME: mismatch", True),
    ("SIGNATURE_INVALID: does not verify", True),
    ("CHECKSUM_MISMATCH: x", True),
    ("candidate failed health check and was rolled back", True),
    ("SIGNATURE_KEY_UNREADABLE: trusted public key is missing", False),
    ("Command '['systemctl', 'stop', 'rosy-core.service']' timed out after 120 seconds", False),
    ("[Errno 28] No space left on device", False),
    ("NATIVE_RELEASE_MISSING: release directory is unavailable", False),
], ids=lambda value: str(value)[:30])
def test_only_known_release_errors_are_definitive(device, host, hub, keys, error, definitive):
    # N3
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": error}), "")

    result = updater(host, hub).run()

    assert (NEXT in state(device).get("failed", {})) is definitive
    assert result["phase"] == ("failed" if definitive else "error")


def test_staging_verify_with_an_unreadable_key_is_transient(device, host, hub, keys):
    # N3
    hub.publish(keys, NEXT)
    host.overrides["verify"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_KEY_UNREADABLE: missing"}), "")

    assert updater(host, hub).run()["phase"] == "error"
    assert NEXT not in state(device).get("failed", {})


def test_repeated_transient_apply_failures_back_off_then_hold(device, host, hub, keys):
    # N7
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess([], 124, "", "TIMEOUT")
    up = updater(host, hub)
    for attempt in range(1, 4):
        assert up.run()["phase"] == "error"
        assert kinds(host).count("activate") == attempt
        # inside the backoff no activation; after the third failure the robot is held
        assert up.run()["phase"] == ("waiting" if attempt < 3 else "held")
        assert kinds(host).count("activate") == attempt
        host.t += dt.timedelta(hours=7)

    result = up.run()

    assert result["phase"] == "held"
    assert result["reason"] == upd.ESCALATED_REASON
    assert result["reason"].startswith("repeated transient apply failures; operator action required")
    assert kinds(host).count("activate") == 3
    assert NEXT not in state(device).get("failed", {})

    del host.overrides["activate"]
    up.release_hold()  # operator action clears the count
    assert up.run()["phase"] == "committed"


def test_the_activator_gets_the_updater_precheck(device, host, hub, keys):
    # N1
    hub.publish(keys, NEXT)
    updater(host, hub).run()
    activate = next(argv for argv in host.calls if kind_of(argv) == "activate")
    assert activate[0] == "env"
    precheck = next(item for item in activate if item.startswith("ROSY_ACTIVATE_PRECHECK="))
    assert "rosy_auto_update.py" in precheck and precheck.endswith(" precheck")


def test_a_refused_precheck_is_ineligible_not_a_failure(device, host, hub, keys):
    # N1
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_PRECHECK_REFUSED: robot mode is MANUAL"}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert NEXT not in state(device).get("failed", {})
    assert not state(device).get("apply_errors")


@pytest.mark.parametrize("setup,code", [
    (lambda device, host, up: None, 0),
    (lambda device, host, up: up.hold("agent", "G5", 1), 3),
    (lambda device, host, up: write_json(device / "etc/rosy/approvals/hardware.approved",
                                         {"release_id": CURRENT}), 3),
    (lambda device, host, up: (setattr(host, "inputs_changes", {"velocity_linear": 0.3}),
                               host.write_inputs()), 3),
    (lambda device, host, up: _stale_inputs(device, host), 3),
], ids=["idle", "hold", "sealed", "moving", "stale"])
def test_cli_precheck(device, host, hub, setup, code, monkeypatch, capsys):
    # N1: what the activator runs; one sample, our own claim allowed.
    up = updater(host, hub)
    setup(device, host, up)
    claim_mod.acquire(device, upd.CLAIM_HOLDER, "auto-update", 600, now=host.t)
    monkeypatch.setattr(upd, "Host", lambda root: host)
    assert upd.main(["--root", str(device), "precheck"]) == code


def test_prune_skips_young_directories_and_runs_under_the_release_lock(device, host, hub, keys):
    # N6
    releases = device / "opt/rosy/releases"
    old = releases / "2026.09.30-001"
    young = releases / "2026.09.30-002"
    old.mkdir()
    young.mkdir()
    stamp = (T0 - dt.timedelta(hours=2)).timestamp()
    os.utime(old, (stamp, stamp))
    young_stamp = (T0 - dt.timedelta(minutes=30)).timestamp()
    os.utime(young, (young_stamp, young_stamp))
    up = updater(host, hub)

    with up._locked_file(device / "var/lib/rosy/releases/native-release.lock"):
        up._prune({})
    assert old.exists()  # lock busy: nothing pruned

    up._prune({})
    assert not old.exists() and young.exists()

    os.utime(young, (stamp, stamp))
    host.links = {"current": None, "previous": None}
    up._prune({})
    assert young.exists()  # no current: never prune


def test_a_failed_rollback_recovers_a_native_journal(device, host, hub, keys):
    # N8, N10
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)

    def died_midway(h, argv):
        write_json(device / "var/lib/rosy/releases/native-activation.json",
                   {"schema_version": 1, "operation": "rollback", "candidate": CURRENT,
                    "old_current": NEXT, "old_previous": CURRENT, "phase": "prepared"})
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["rollback"] = died_midway

    updater(host, hub).run()

    order = kinds(host)
    assert "recover" in order and order.index("recover") < order.index("start")


def test_runtime_is_not_started_when_recover_fails(device, host, hub, keys):
    # N10
    hub.publish(keys, NEXT)

    def killed_midway(h, argv):
        write_json(device / "var/lib/rosy/releases/native-activation.json", {"bad": True})
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = killed_midway
    host.overrides["recover"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RECOVERY_HOLD: invalid"}), "")

    updater(host, hub).run()

    assert "recover" in kinds(host)
    assert "start" not in kinds(host)


def test_previous_above_current_is_an_operator_rollback(device, host, hub, keys):
    # N9
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    host.links = {"current": CURRENT, "previous": NEXT}
    hub.publish(keys, NEXT)

    result = updater(host, hub).run()

    assert result["phase"] == "idle"
    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"


def test_interrupted_activation_that_never_switched_is_not_a_failure(device, host, hub, keys):
    # N11
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    journal(device, "activate")

    result = updater(host, hub).run()

    assert NEXT not in state(device).get("failed", {})
    assert state(device).get("applying") is None
    assert result["phase"] == "waiting"


def test_rollback_pending_gives_up_after_five_retries(device, host, hub, keys):
    # N12
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    results = [up.run() for _ in range(7)]
    phases = [result["phase"] for result in results]

    # the first attempt and five retries; the sixth failure gives up
    assert phases[:5] == ["error"] * 5
    assert phases[5] == "failed"
    assert "operator" in results[5]["reason"]
    assert state(device).get("applying") is None
    assert kinds(host).count("rollback") == 6
    assert phases[6] == "failed"  # stays visible (L2), no further rollback attempts


def test_a_claim_release_error_does_not_crash_the_run(device, host, hub, keys, monkeypatch):
    # N13
    hub.publish(keys, NEXT)

    def broken(root, holder):
        raise OSError("read-only /run")

    monkeypatch.setattr(claim_mod, "release", broken)

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert any(entry["event"] == "claim_release_failed" for entry in history(device))


# --- verification review (REQUEST CHANGES) ---------------------------------------------


def test_a_self_rollback_is_not_mistaken_for_an_operator_rollback(device, host, hub, keys):
    # HIGH: N9 must not catch our own unmarked rollback (N7); the release is retried.
    hub.publish(keys, NEXT)

    def switched_then_timed_out(h, argv):
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = switched_then_timed_out
    up = updater(host, hub)
    up.run()
    assert host.links == {"current": CURRENT, "previous": NEXT}
    assert NEXT not in state(device).get("failed", {})

    del host.overrides["activate"]
    host.t += dt.timedelta(hours=1)
    result = up.run()

    assert NEXT not in state(device).get("failed", {}), state(device).get("failed")
    assert result["phase"] == "committed", result
    assert NEXT not in state(device).get("self_rolled_back", {})  # cleared by the commit


def test_stuck_is_measured_from_the_first_silent_resume(device, host, hub, keys):
    # M1: an old journal is not stuck the moment it is first seen silent.
    _resume_case(device, host, hub, keys)
    journal(device, "image-layer-sync", started_at=_z(T0 - dt.timedelta(hours=2)))
    _stale_inputs(device, host)
    up = updater(host, hub)

    assert up.run()["phase"] == "ineligible"
    assert state(device)["applying"]["silent_since"] == _z(T0)
    host.t = T0 + dt.timedelta(minutes=29)
    assert up.run()["phase"] == "ineligible"
    host.t = T0 + dt.timedelta(minutes=31)
    assert up.run()["phase"] == "stuck"


def test_silent_since_restarts_after_a_held_resume(device, host, hub, keys):
    # M1: silence, then a hold, then silence again is a new silent period.
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)
    up = updater(host, hub)
    assert up.run()["phase"] == "ineligible"
    assert state(device)["applying"]["silent_since"] == _z(T0)

    up.hold("agent", "x", 1)
    host.t = T0 + dt.timedelta(minutes=5)
    assert up.run()["phase"] == "held"
    assert "silent_since" not in state(device)["applying"]

    up.release_hold()
    host.t = T0 + dt.timedelta(minutes=31)
    assert up.run()["phase"] == "ineligible"  # not stuck: silent only since now
    assert state(device)["applying"]["silent_since"] == _z(host.t)


def test_silent_since_is_cleared_by_an_eligible_resume(device, host, hub, keys):
    # M1: an eligible (waived, then deferred) resume ends the silent period.
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)
    up = updater(host, hub)
    assert up.run()["phase"] == "ineligible"
    assert state(device)["applying"]["silent_since"] == _z(T0)

    _core_down_until_restarted(host, fresh_after_restart=False)
    host.t = T0 + dt.timedelta(minutes=5)
    result = up.run()
    assert result["phase"] == "ineligible" and "deferred" in result["reason"]
    assert "silent_since" not in state(device)["applying"]

    host.t = T0 + dt.timedelta(minutes=31)
    assert up.run()["phase"] == "ineligible"  # CORE back but silent: a new period, not stuck


@pytest.mark.parametrize("error", [
    "NATIVE_PRECHECK_FAILED: exit 1: Traceback (most recent call last)",
    "NATIVE_PRECHECK_FAILED: precheck could not run: timed out after 60 seconds",
], ids=["crashed", "timeout"])
def test_a_precheck_that_failed_is_an_apply_error_not_busy(device, host, hub, keys, error):
    # M2
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": error}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert "precheck" in result["reason"].lower()
    assert state(device)["apply_errors"][NEXT]["attempts"] == 1
    assert NEXT not in state(device).get("failed", {})


def test_runtime_mismatch_is_definitive(device, host, hub, keys):
    # L1
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RUNTIME_MISMATCH: core-only native systemd"}), "")
    assert updater(host, hub).run()["phase"] == "failed"
    assert NEXT in state(device)["failed"]


def test_rollback_failure_stays_visible(device, host, hub, keys):
    # L2: after the N12 cap the robot keeps saying so until a person fixes it.
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"

    result = up.run()

    assert result["phase"] == "failed"
    assert result["last_result"]["outcome"] == "rollback_failed"
    assert "rosy-release-push.ps1 -Rollback" in result["reason"]
    assert kinds(host).count("rollback") == 6

    host.links = {"current": CURRENT, "previous": NEXT}  # the operator rolled back
    assert up.run()["phase"] == "idle"


def test_escalation_reasons_name_the_remedy(device, host, hub, keys):
    # L3
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess([], 124, "", "TIMEOUT")
    up = updater(host, hub)
    for _ in range(3):
        up.run()
        host.t += dt.timedelta(hours=7)
    result = up.run()
    assert result["phase"] == "held"
    assert "release-hold" in result["reason"]


# --- verification review 2 (REQUEST CHANGES, 2 HIGH) ------------------------------------


def _switched_then_timed_out(h, argv):
    h.links = {"current": NEXT, "previous": CURRENT}
    return subprocess.CompletedProcess([], 124, "", "TIMEOUT")


def test_a_rollback_that_gave_up_then_an_operator_rollback_fails_the_release(device, host, hub, keys):
    # HIGH 1 (the reviewer's probe): our rollback never moved current, so the
    # operator's later rollback is an operator rollback (N9).
    hub.publish(keys, NEXT)
    host.overrides["activate"] = _switched_then_timed_out
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"
    assert NEXT not in (state(device).get("self_rolled_back") or {})

    del host.overrides["activate"], host.overrides["rollback"]
    host.links = {"current": CURRENT, "previous": NEXT}  # rosy-release-push.ps1 -Rollback
    host.t += dt.timedelta(minutes=5)
    up.run()

    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"
    assert kinds(host).count("activate") == 1


def test_a_definitive_rollback_error_is_not_a_self_rollback(device, host, hub, keys):
    # HIGH 1
    hub.publish(keys, NEXT)
    host.overrides["activate"] = _switched_then_timed_out
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_INVALID: previous does not verify"}), "")

    updater(host, hub).run()

    assert host.links["current"] == NEXT
    assert NEXT not in (state(device).get("self_rolled_back") or {})


def test_a_failing_rollback_tail_still_backs_off(device, host, hub, keys):
    # HIGH 2 (the reviewer's probe): moved away but the tail failed; the apply
    # error must still be counted so the loop is bounded.
    hub.publish(keys, NEXT)
    host.overrides["activate"] = _switched_then_timed_out
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == CURRENT else None)
    up = updater(host, hub)
    for _ in range(6):
        host.t += dt.timedelta(minutes=5)
        up.run()

    assert kinds(host).count("activate") <= 3
    assert state(device)["apply_errors"][NEXT]["attempts"] >= 1
    assert NEXT in state(device)["self_rolled_back"]  # it did move current away


def test_release_hold_acknowledges_a_rollback_failure(device, host, hub, keys):
    # MEDIUM
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    sticky = up.run()
    assert sticky["phase"] == "failed" and "release-hold" in sticky["reason"]

    up.release_hold()

    assert state(device).get("last_result") is None
    assert up.run()["phase"] != "failed"


def test_stale_self_rollback_entries_are_pruned(device, host, hub, keys):
    # LOW
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/state.json", {
        "self_rolled_back": {CURRENT: _z(T0), NEWER: _z(T0), "2026.10.01-030": _z(T0), NEXT: _z(T0)},
        "failed": {NEWER: {"at": _z(T0), "detail": "x"}},
        "withdrawn": {"2026.10.01-030": {"at": _z(T0), "reason": "x"}},
    })
    up = updater(host, hub)
    up.hold("agent", "x", 1)

    up.run()

    assert set(state(device)["self_rolled_back"]) == {NEXT}


def test_the_precheck_busy_exit_matches_native_release():
    # LOW: the activator's "busy" code and the updater's precheck exit are one value.
    from deploy.robot.pinky_pro.native import native_release

    assert native_release.PRECHECK_BUSY_EXIT == upd.PRECHECK_BUSY_EXIT == 3


# --- final verification batch ----------------------------------------------------------------


def test_release_hold_waits_for_no_run(device, host, hub, keys, capsys, monkeypatch):
    # MEDIUM: release-hold rewrites state.json, so it takes the run lock; busy is an error.
    up = updater(host, hub)
    up.hold("agent", "x", 1)
    write_json(device / "var/lib/rosy/updates/state.json", {"apply_errors": {NEXT: {"attempts": 3}}})
    with up._run_lock():
        with pytest.raises(upd.RunBusy):
            updater(host, hub).release_hold()
        monkeypatch.setattr(upd, "Host", lambda root: host)
        code = upd.main(["--root", str(device), "release-hold"])
    out = json.loads(capsys.readouterr().out)

    assert code == 4
    assert out["ok"] is False and "RUN_BUSY" in out["error"]
    assert (device / "var/lib/rosy/updates/hold.json").exists()
    assert state(device)["apply_errors"] == {NEXT: {"attempts": 3}}


def test_a_refused_rollback_is_a_sticky_acknowledgeable_rollback_failure(device, host, hub, keys):
    # LOW 1
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_INVALID: previous does not verify"}), "")
    up = updater(host, hub)
    up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"

    sticky = up.run()
    assert sticky["phase"] == "failed" and "release-hold" in sticky["reason"]
    assert up.release_hold()["acknowledged_rollback_failure"] == NEXT
    assert up.run()["phase"] != "failed"


def test_release_hold_reports_what_it_acknowledged(device, host, hub, keys, capsys, monkeypatch):
    # LOW 2
    up = updater(host, hub)
    up.hold("agent", "x", 1)
    write_json(device / "var/lib/rosy/updates/state.json", {
        "apply_errors": {NEXT: {"attempts": 3}, NEWER: {"attempts": 1}},
        "last_result": {"release_id": NEXT, "outcome": "rollback_failed", "at": _z(T0), "detail": "x"},
    })
    monkeypatch.setattr(upd, "Host", lambda root: host)

    assert upd.main(["--root", str(device), "release-hold"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out == {"ok": True, "released": True, "acknowledged_rollback_failure": NEXT,
                   "cleared_apply_errors": [NEXT, NEWER]}

    assert upd.main(["--root", str(device), "release-hold"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "released": False,
                                                   "acknowledged_rollback_failure": None,
                                                   "cleared_apply_errors": []}


def test_self_rollback_entries_below_current_are_pruned_unless_previous(device, host, hub, keys):
    # LOW 3
    hub.publish(keys, NEXT)
    host.links = {"current": CURRENT, "previous": "2026.10.01-019"}
    write_json(device / "var/lib/rosy/updates/state.json", {
        "self_rolled_back": {"2026.10.01-018": _z(T0), "2026.10.01-019": _z(T0), NEXT: _z(T0)},
    })
    up = updater(host, hub)
    up.hold("agent", "x", 1)

    up.run()

    assert set(state(device)["self_rolled_back"]) == {"2026.10.01-019", NEXT}


def test_acknowledged_unmarked_rollback_failure_then_operator_rollback(device, host, hub, keys):
    # LOW 4: the mark_failed=False variant: transient switch, the rollback never runs.
    hub.publish(keys, NEXT)

    def switched_then_timed_out(h, argv):
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = switched_then_timed_out
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"
    assert NEXT not in state(device).get("failed", {})

    assert up.release_hold()["acknowledged_rollback_failure"] == NEXT
    del host.overrides["activate"], host.overrides["rollback"]
    host.t += dt.timedelta(hours=7)
    assert up.run()["phase"] != "failed"
    assert kinds(host).count("activate") == 1  # NEXT is current: nothing to activate again

    host.links = {"current": CURRENT, "previous": NEXT}  # rosy-release-push.ps1 -Rollback
    up.run()
    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"
    assert kinds(host).count("activate") == 1
