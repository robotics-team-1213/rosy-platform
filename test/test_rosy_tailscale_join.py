"""D-477 rosy-tailscale-join contracts: spend the key once, never leak it.

The helper is loaded the way the other native helper tests load theirs; every
subprocess seam is faked (host pytest must not need tailscale). The unit-file
and lockstep checks keep the join wired like every other rosy unit.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/pinky_pro/native"
UNIT = "rosy-tailscale-join.service"
KEY = "tskey-auth-k1234567890abcdefgh"


def _load(name: str = "rosy_tailscale_join_test"):
    spec = importlib.util.spec_from_file_location(name, NATIVE / "rosy-tailscale-join.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _join_file(root: Path, *, key: str = KEY, tags: list[str] | None = None,
               hostname: str = "rosy-pinky-8kcn") -> Path:
    path = root / "etc/rosy/tailscale-join.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "auth_key": key,
        "tags": tags or ["tag:rosy-robot"],
        "hostname": hostname,
    }), encoding="utf-8")
    return path


class _Recorder:
    """Answers each fake CLI call; up() decides the join outcome."""

    def __init__(self, *, up_rc: int = 0, up_stderr: str = "",
                 backend: str = "NeedsLogin", self_node: bool = False):
        self.up_rc = up_rc
        self.up_stderr = up_stderr
        self.backend = backend
        self.self_node = self_node
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout_s):
        self.calls.append(list(argv))
        if argv[1] == "status":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "BackendState": self.backend,
                    **({"Self": {"HostName": "rosy-pinky-8kcn"}} if self.self_node else {}),
                }),
                stderr="",
            )
        return SimpleNamespace(returncode=self.up_rc, stdout="", stderr=self.up_stderr)


class SimpleNamespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@pytest.fixture
def env_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_TAILSCALE_ROOT", str(tmp_path))
    monkeypatch.setenv("ROSY_TAILSCALE_CLI", "/usr/bin/tailscale")
    return tmp_path

def _result(root: Path) -> dict:
    return json.loads(
        (root / "var/lib/rosy/tailscale/join-result.json").read_text(encoding="utf-8"))


def test_a_fresh_robot_joins_and_the_key_is_spent(env_root, monkeypatch):
    module = _load()
    recorder = _Recorder(up_rc=0, backend="NeedsLogin")
    monkeypatch.setattr(module, "_invoke", recorder)

    join = _join_file(env_root)
    assert module.main() == 0

    up = next(call for call in recorder.calls if call[1] == "up")
    assert "--auth-key=" + KEY in up
    assert "--hostname=rosy-pinky-8kcn" in up
    assert "--advertise-tags=tag:rosy-robot" in up
    assert "--accept-dns=false" in up
    assert "--accept-routes=false" in up
    # The one-time key is gone from the card channel and the result is clean.
    assert KEY not in join.read_text(encoding="utf-8")
    assert json.loads(join.read_text(encoding="utf-8"))["hostname"] == "rosy-pinky-8kcn"
    assert _result(env_root)["status"] == "joined"
    assert KEY not in json.dumps(_result(env_root))


def test_an_already_joined_robot_still_consumes_the_key(env_root, monkeypatch):
    module = _load()
    recorder = _Recorder(backend="Running", self_node=True)
    monkeypatch.setattr(module, "_invoke", recorder)

    join = _join_file(env_root)
    assert module.main() == 0

    assert [call[1] for call in recorder.calls] == ["status"]
    assert KEY not in join.read_text(encoding="utf-8")
    assert _result(env_root)["status"] == "already_joined"


def test_a_failed_join_leaves_the_key_for_the_next_boot(env_root, monkeypatch):
    module = _load()
    recorder = _Recorder(up_rc=1, up_stderr=f"boom {KEY} boom")
    monkeypatch.setattr(module, "_invoke", recorder)

    join = _join_file(env_root)
    assert module.main() == 1

    assert KEY in join.read_text(encoding="utf-8")
    result = _result(env_root)
    assert result["status"] == "failed"
    assert KEY not in json.dumps(result)
    assert result["error"]


def test_a_timing_out_join_fails_without_losing_the_key(env_root, monkeypatch):
    module = _load()
    import subprocess

    def stuck(argv, timeout_s):
        recorder.calls.append(list(argv))
        if argv[1] == "status":
            return SimpleNamespace(returncode=1, stdout="{}", stderr="")
        raise subprocess.TimeoutExpired(argv, timeout_s)

    recorder = _Recorder()
    monkeypatch.setattr(module, "_invoke", stuck)
    join = _join_file(env_root)

    assert module.main() == 1
    assert KEY in join.read_text(encoding="utf-8")
    assert _result(env_root)["status"] == "failed"
    assert "timed out" in _result(env_root)["error"]


@pytest.mark.parametrize("payload", [
    {"auth_key": "tskey-auth-short", "tags": ["tag:rosy-robot"], "hostname": "rosy-pinky-8kcn"},
    {"auth_key": KEY, "tags": ["tag:rosy robot"], "hostname": "rosy-pinky-8kcn"},
    {"auth_key": KEY, "tags": [], "hostname": "rosy-pinky-8kcn"},
    {"auth_key": KEY, "tags": ["tag:rosy-robot"], "hostname": "Rosy_Pinky!"},
    {"auth_key": KEY, "tags": ["tag:rosy-robot"], "hostname": "rosy-pinky-8kcn", "extra": 1},
])
def test_a_malformed_join_file_is_refused_without_running_the_cli(
        env_root, monkeypatch, payload):
    module = _load()
    called = []
    monkeypatch.setattr(module, "_invoke", lambda argv, timeout_s: called.append(argv))

    join = env_root / "etc/rosy/tailscale-join.json"
    join.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(payload)
    join.write_text(original, encoding="utf-8")

    assert module.main() == 1
    assert called == []
    assert join.read_text(encoding="utf-8") == original
    assert not (env_root / "var/lib/rosy/tailscale/join-result.json").exists()


def test_a_robot_without_the_cli_refuses_before_touching_the_file(
        env_root, monkeypatch, capsys):
    module = _load()
    monkeypatch.delenv("ROSY_TAILSCALE_CLI")
    monkeypatch.setattr(module, "_resolve_cli", lambda: (_ for _ in ()).throw(
        RuntimeError("the tailscale CLI is not installed")))
    join = _join_file(env_root)

    assert module.main() == 1
    assert KEY in join.read_text(encoding="utf-8")
    assert KEY not in capsys.readouterr().err


# --- the unit and its lockstep wiring ---------------------------------------

def _read_unit() -> str:
    return (NATIVE / UNIT).read_text(encoding="utf-8")


def test_the_unit_only_runs_with_a_provisioned_join_file():
    unit = _read_unit()
    assert "ConditionPathExists=/etc/rosy/tailscale-join.json" in unit
    assert "ProtectSystem=strict" in unit
    assert "StateDirectory=rosy/tailscale" in unit
    assert "ReadWritePaths=-/etc/rosy/tailscale-join.json" in unit
    # The daemon holds the tailnet sockets; the helper still needs its own
    # address families, so unlike rosy-ssh-access it is not network-isolated.
    assert "PrivateNetwork=true" not in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK" in unit
    # A robot that booted without uplink retries at the next boot.
    assert "StartLimitIntervalSec=0" in unit


def test_the_unit_sets_no_test_seams_or_key_material():
    unit = _read_unit()
    for forbidden in ("ROSY_TAILSCALE_ROOT", "ROSY_TAILSCALE_CLI", "tskey-", "auth_key"):
        assert forbidden not in unit, forbidden


def test_every_install_list_carries_the_join_unit():
    payload = (ROOT / "deploy/robot/pinky_pro/image/build-native-payload.sh").read_text(
        encoding="utf-8")
    assert 'rosy-tailscale-join.service" "$OVERLAY/etc/systemd/system/"' in payload

    sys.path.insert(0, str(ROOT / "test"))
    try:
        spec = importlib.util.spec_from_file_location(
            "sync_image_layer_tailnet", ROOT / "deploy/robot/pinky_pro/native/sync-image-layer.py")
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
    finally:
        sys.path.pop(0)
    assert UNIT in sync.UNITS
    assert UNIT in sync.ENABLED_UNITS

    customizer = (ROOT / "deploy/robot/pinky_pro/image/customize-rootfs.sh").read_text(
        encoding="utf-8")
    assert "rosy-tailscale-join.service" in customizer
    # The package daemon must come up for the join helper to talk to.
    assert "tailscaled.service" in customizer

    twin = (ROOT / "tools/device_twin/image/install_twin.sh").read_text(encoding="utf-8")
    assert UNIT in twin
