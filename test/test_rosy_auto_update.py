"""D-406: the robot-side updater (deploy/robot/pinky_pro/native/rosy_auto_update.py).

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
                assets.append({"name": name, "browser_download_url": f"{self.base}/dl/{key}"})
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
        "docking_state": None, "line_follow_mode": "OFF", "line_follow_state": "IDLE",
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
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert updater(host, hub).run()["phase"] == "error"
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
    path.parent.mkdir(parents=True)
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
    order = [k for k in kinds(host) if k not in {"is-active", "failed"}]
    assert order[:4] == ["unpack", "verify", "activate", "mainpid"]
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
                      "Persistent=true", "WantedBy=timers.target"):
        assert directive in lines, directive
