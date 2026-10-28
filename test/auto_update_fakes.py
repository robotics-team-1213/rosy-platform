"""D-412: shared fakes for the robot-side updater tests (test_rosy_auto_update_*.py, split by D-798).

The updater is deploy/robot/pinky_pro/native/rosy_auto_update.py and its auto_update_*.py siblings.
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
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from signing import sign_checksums


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "robot" / "pinky_pro" / "native"
REPO = "robotics-team-1213/rosy-platform"
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
                if self.path in (f"/repos/{REPO}/releases?per_page=20", f"/repos/{REPO}/releases?per_page=100"):
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
                prefix = f"/repos/{REPO}/releases/tags/"
                if self.path.startswith(prefix):
                    release = next((item for item in hub.releases if item.get("tag_name") == self.path[len(prefix):]), None)
                    self.send_response(200 if release is not None else 404)
                    self.end_headers()
                    if release is not None: self.wfile.write(json.dumps(release).encode())
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

    def _stop(self, argv):
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

    def _is_enabled(self, argv):
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
    if argv[:2] == ["systemctl", "stop"]:
        return "stop"
    if argv[:2] == ["systemctl", "show"] and "ActiveState,SubState,MainPID" in argv:
        return "corestate"
    if argv[:2] == ["systemctl", "show"]:
        return "mainpid"
    if argv[:2] == ["systemctl", "restart"]:
        return "restart"
    if argv[:2] == ["systemctl", "is-active"]:
        return "is-active"
    if argv[:2] == ["systemctl", "is-enabled"]:
        return "is-enabled"
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
    # Explicitly enabled (it is also the default since 2026-10-02).
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


def journal(device: Path, step: str, release_id: str = NEXT, **extra) -> None:
    applying = {"release_id": release_id, "previous": CURRENT, "step": step, "started_at": _z(T0),
                "boot_id": BOOT, "baseline": {"active": {u: None for u in upd.HEALTH_UNITS}, "failed": []}}
    applying.update(extra)
    write_json(device / "var/lib/rosy/updates/state.json", {"applying": applying})


def switched(device: Path, host: FakeHost) -> None:
    (device / "opt/rosy/releases" / NEXT / "deploy/robot/native").mkdir(parents=True, exist_ok=True)
    host.links = {"current": NEXT, "previous": CURRENT}


def _stale_inputs(device: Path, host: FakeHost) -> None:
    write_json(device / "run/rosy/status-inputs.json", idle_inputs(T0 - dt.timedelta(minutes=10)))
    host.write_inputs = lambda: None


def _retired_display(device):
    units = device / "etc/systemd/system"
    units.mkdir(parents=True, exist_ok=True)
    (units / upd.RETIRED_DISPLAY_UNIT).write_text("[Unit]\n", encoding="utf-8")
    return units
