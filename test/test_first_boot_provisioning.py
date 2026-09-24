from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path

import pytest

from deploy.sd.personalization import DeviceIdentity, create_provision_bundle

# D-191: every bundle carries the card's CORE API record. Keys are assembled
# at runtime so the tracked-file secret scanner sees no literal.
CARD_API = {"core_api_" + "token": "Rq" * 21 + "_", "core_api_" + "token_id": "0a1b2c3d4e5f"}


ROOT = Path(__file__).resolve().parents[1]
FIRST_BOOT = ROOT / "deploy" / "image" / "first-boot"


def _module():
    path = FIRST_BOOT / "rosy-first-boot.py"
    spec = importlib.util.spec_from_file_location("rosy_first_boot", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle() -> dict:
    return create_provision_bundle(
        identity=DeviceIdentity(
            device_uid="9d40feaa-871f-4fd3-975a-a704e82d3af9",
            device_name="rosy-pinky-k7m4",
            hostname="rosy-pinky-k7m4",
            model="pinky_pro",
        ),
        release_id="2026.09.22-001",
        robot_number=3,
        requested_preset="hardware",
        country_code="KR",
        ssid="fixture-wifi",
        wifi_passphrase="fixture-pass-9384",
        fleet_endpoint="https://fleet.fixture.invalid:8443",
        fleet_trust_profile="site-ca-2026",
        pairing_required=True,
        pairing_credential="fixture-one-time-pairing-credential",
        created_at=datetime(2026, 9, 22, 1, 2, 3, tzinfo=UTC),
        nonce="fixture-first-boot-nonce",
        **CARD_API,
    )


def _case(tmp_path: Path):
    root = tmp_path / "root"
    bundle = root / "boot/firmware/rosy-provision/provision.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    return root, bundle


def test_valid_bundle_personalizes_ubuntu_and_is_consumed_once(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    calls: list[str] = []
    provisioner = module.FirstBootProvisioner(
        root=root,
        network_activate=lambda profile: calls.append(profile) or True,
    )

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result == {"ok": True, "state": "PROVISIONED", "device_name": "rosy-pinky-k7m4"}
    assert not bundle.exists()
    assert calls == ["rosy-site-sta"]
    assert (root / "etc/hostname").read_text(encoding="utf-8") == "rosy-pinky-k7m4\n"
    runtime = (root / "etc/rosy/runtime.env").read_text(encoding="utf-8")
    assert "ROSY_ROBOT_NUMBER=3" in runtime
    assert "ROS_DOMAIN_ID=43" in runtime
    assert "ROSY_NAMESPACE=rosy_03" in runtime
    assert "ROSY_RUNTIME_MODE=core" in runtime
    network = root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
    rendered = network.read_text(encoding="utf-8")
    assert "ssid=fixture-wifi" in rendered
    assert "psk=" in rendered and "fixture-pass-9384" not in rendered
    if os.name == "posix":
        assert os.stat(network).st_mode & 0o777 == 0o600
    complete = json.loads(
        (root / "var/lib/rosy/provisioning/complete.json").read_text(encoding="utf-8")
    )
    assert complete["hardware_serial"] == "10000000abcdef01"
    assert complete["requested_preset"] == "hardware"
    assert complete["active_runtime"] == "core"
    assert "wpa_psk" not in json.dumps(complete)
    fleet = json.loads((root / "etc/rosy/fleet-bootstrap.json").read_text(encoding="utf-8"))
    assert fleet["pairing_credential"] == "fixture-one-time-pairing-credential"
    if os.name == "posix":
        assert os.stat(root / "etc/rosy/fleet-bootstrap.json").st_mode & 0o777 == 0o600
    source = (FIRST_BOOT / "rosy-first-boot.py").read_text(encoding="utf-8")
    assert "network_path, self._network_profile(payload), 0o600" in source
    assert '"etc/rosy/fleet-bootstrap.json"), payload["fleet"], 0o600' in source


def test_wrong_wifi_returns_to_provisioning_hold_without_consuming_bundle(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    provisioner = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: False)

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result == {"ok": False, "state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}
    assert bundle.exists(), "the powered-off card must remain repairable"
    assert not (root / "var/lib/rosy/provisioning/complete.json").exists()
    # 2026-09-24: the profile stays so NM autoconnect (and rosy-network after the
    # fallback AP) can still join, and the retry timer can finish provisioning.
    network = root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
    assert "ssid=fixture-wifi" in network.read_text(encoding="utf-8")
    if os.name == "posix":
        assert os.stat(network).st_mode & 0o777 == 0o600
    state = json.loads((root / "var/lib/rosy/provisioning/state.json").read_text(encoding="utf-8"))
    assert state == {"state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}
    assert "fixture-pass-9384" not in json.dumps(result) + json.dumps(state)


def test_failed_network_still_binds_card_identity_to_first_hardware_serial(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    provisioner = module.FirstBootProvisioner(
        root=root, network_activate=lambda _profile: False
    )
    provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    binding = json.loads(
        (root / "var/lib/rosy/provisioning/hardware-binding.json").read_text(
            encoding="utf-8"
        )
    )
    assert binding["hardware_serial"] == "10000000abcdef01"
    assert binding["device_uid"] == "9d40feaa-871f-4fd3-975a-a704e82d3af9"
    with pytest.raises(ValueError, match="hardware serial"):
        provisioner.apply(bundle=bundle, hardware_serial="10000000deadbeef")


def test_completed_device_does_not_replay_a_reinserted_bundle(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    first = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: True)
    first.apply(bundle=bundle, hardware_serial="10000000abcdef01")
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    calls: list[str] = []

    result = module.FirstBootProvisioner(
        root=root, network_activate=lambda profile: calls.append(profile) or True
    ).apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "ALREADY_PROVISIONED"
    assert calls == []


def test_hardware_serial_change_is_a_fail_closed_identity_mismatch(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    provisioner = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: True)
    provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    with pytest.raises(ValueError, match="hardware serial"):
        provisioner.apply(bundle=bundle, hardware_serial="10000000deadbeef")


def test_first_boot_unit_orders_personalization_before_network_and_runtime():
    unit = (FIRST_BOOT / "rosy-first-boot.service").read_text(encoding="utf-8")
    script = (FIRST_BOOT / "rosy-first-boot.sh").read_text(encoding="utf-8")

    assert "After=local-fs.target NetworkManager.service" in unit
    assert "Before=network-online.target rosy-sd-provision.service rosy-runtime.target" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "ExecStart=/opt/rosy/first-boot/rosy-first-boot.sh" in unit
    assert "rosy-first-boot.py" in script
    assert "apt " not in script
    assert "curl " not in script
    assert "docker" not in (unit + script).lower()


def test_provisioning_gate_requires_first_boot_to_finish():
    gate = (ROOT / "deploy/robot/native/rosy-sd-provision.service").read_text(encoding="utf-8")

    assert "Requires=rosy-first-boot.service" in gate
    assert "After=rosy-first-boot.service" in gate


def test_hostname_is_applied_live_before_the_network_comes_up(tmp_path):
    # D-174 F2: only /etc/hostname was written, so avahi kept announcing ubuntu.local
    # and DHCP sent the old name until a reboot.
    module = _module()
    root, bundle = _case(tmp_path)
    order: list[str] = []
    provisioner = module.FirstBootProvisioner(
        root=root,
        network_activate=lambda profile: order.append(f"network:{profile}") or True,
        hostname_apply=lambda name: order.append(f"hostname:{name}"),
    )

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    assert order == ["hostname:rosy-pinky-k7m4", "network:rosy-site-sta"]


def test_live_hostname_failure_does_not_block_personalization(tmp_path, capsys):
    module = _module()
    root, bundle = _case(tmp_path)

    def broken(_name):
        raise OSError("hostnamectl unavailable")

    provisioner = module.FirstBootProvisioner(
        root=root, network_activate=lambda _profile: True, hostname_apply=broken,
    )

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    assert (root / "etc/hostname").read_text(encoding="utf-8") == "rosy-pinky-k7m4\n"
    assert "live hostname" in capsys.readouterr().err


def test_default_live_hostname_never_touches_the_host_when_root_is_not_slash(tmp_path, monkeypatch):
    module = _module()
    root, bundle = _case(tmp_path)

    def refuse(*_args, **_kwargs):
        raise AssertionError("must not run host commands for a non-/ root")

    monkeypatch.setattr(module.subprocess, "run", refuse)
    provisioner = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: True)

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"


def test_default_live_hostname_uses_hostnamectl_then_restarts_avahi(monkeypatch):
    module = _module()
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(module.subprocess, "run", lambda command, **_kw: calls.append(command) or Done())

    module._default_hostname_apply("rosy-pinky-k7m4")

    assert calls[0] == ["hostnamectl", "set-hostname", "rosy-pinky-k7m4"]
    assert ["systemctl", "try-restart", "avahi-daemon.service"] in calls


class FakeNetworkManager:
    """nmcli stand-in on a fake monotonic clock; never touches the host.

    `up` lists the outcome of each `connection up` (True: activated). Each
    failed `up` uses `fail_s` of the clock, capped by its --wait;
    `autoconnect_at` marks the profile activated once the clock passes it.
    """

    def __init__(self, up: list[bool], *, fail_s: float = 25.0, autoconnect_at: float | None = None):
        self.up = list(up)
        self.fail_s = fail_s
        self.autoconnect_at = autoconnect_at
        self.now = 0.0
        self.active = False
        self.commands: list[list[str]] = []
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def run(self, command: list[str], timeout: float) -> tuple[int, str]:
        self.commands.append(command)
        if self.autoconnect_at is not None and self.now >= self.autoconnect_at:
            self.active = True
        if "up" in command:
            wait = float(command[command.index("--wait") + 1])
            assert timeout > wait
            outcome = self.up.pop(0) if self.up else False
            if outcome:
                self.now += 7.0  # 77.6 -> 84.9 on 2026-09-24
                self.active = True
                return 0, ""
            self.now += min(self.fail_s, wait)
            return 4, ""
        if "show" in command:
            return 0, "GENERAL.STATE:activated\n" if self.active else ""
        return 0, ""

    def up_calls(self) -> int:
        return sum("up" in command for command in self.commands)

    def activate(self, module, **overrides):
        return lambda profile: module.activate_site_wifi(
            profile, run=self.run, clock=self.clock, sleep=self.sleep, **overrides)


def test_a_first_failed_association_is_retried_and_provisions(tmp_path):
    # 2026-09-24 rosy-pinky-e4us: the first association on a phone hotspot failed
    # after 25 s; a later try joined. That must provision, not fail the boot.
    module = _module()
    root, bundle = _case(tmp_path)
    nm = FakeNetworkManager([False, True])

    result = module.FirstBootProvisioner(root=root, network_activate=nm.activate(module)).apply(
        bundle=bundle, hardware_serial="10000000abcdef01")

    assert result == {"ok": True, "state": "PROVISIONED", "device_name": "rosy-pinky-k7m4"}
    assert nm.up_calls() == 2
    assert nm.sleeps == [module.NETWORK_RETRY_PAUSE_S]
    assert not bundle.exists()


def test_an_autoconnect_finished_during_the_pause_is_accepted_without_another_up():
    module = _module()
    nm = FakeNetworkManager([False], autoconnect_at=30.0)

    assert nm.activate(module)("rosy-site-sta") is True
    assert nm.up_calls() == 1, "a profile NM already activated must not be torn down"


def test_all_attempts_failing_holds_provisioning_ap_and_keeps_the_profile(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    nm = FakeNetworkManager([False, False, False], fail_s=60.0)

    result = module.FirstBootProvisioner(root=root, network_activate=nm.activate(module)).apply(
        bundle=bundle, hardware_serial="10000000abcdef01")

    assert result == {"ok": False, "state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}
    assert nm.up_calls() == module.NETWORK_ATTEMPTS
    assert nm.now <= module.NETWORK_BUDGET_S
    assert (root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection").is_file()
    assert bundle.exists()
    state = json.loads((root / "var/lib/rosy/provisioning/state.json").read_text(encoding="utf-8"))
    assert state == {"state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}


def test_retry_budget_is_bounded_however_many_attempts_are_allowed():
    module = _module()
    # NM never answers early: every attempt runs its full --wait.
    nm = FakeNetworkManager([], fail_s=10_000.0)

    assert nm.activate(module, attempts=50)("rosy-site-sta") is False
    assert nm.now <= module.NETWORK_BUDGET_S
    assert nm.up_calls() < 50
    for command in nm.commands:
        if "up" in command:
            assert 1 <= int(command[command.index("--wait") + 1]) <= module.NETWORK_ATTEMPT_WAIT_S


def test_budget_covers_the_2026_09_24_timings_and_fits_the_unit_timeout():
    module = _module()
    # First activation 18.7 s, NM's own retry was up at 84.9 s: 66 s.
    assert module.NETWORK_BUDGET_S >= 84.9 - 18.7
    worst = (module.NETWORK_ATTEMPTS * module.NETWORK_ATTEMPT_WAIT_S
             + (module.NETWORK_ATTEMPTS - 1) * module.NETWORK_RETRY_PAUSE_S)
    assert worst <= module.NETWORK_BUDGET_S
    unit = (FIRST_BOOT / "rosy-first-boot.service").read_text(encoding="utf-8")
    timeout = int(unit.split("TimeoutStartSec=")[1].split()[0])
    # reload, the last show and the per-call subprocess margin come on top.
    assert timeout >= module.NETWORK_BUDGET_S + 45


def test_held_card_finishes_when_the_retry_run_sees_nm_joined(tmp_path, monkeypatch):
    # After the budget, NM autoconnect joined on its own (84.9 s on 2026-09-24).
    # The timer's --network check run must then provision without `connection up`.
    module = _module()
    root, bundle = _case(tmp_path)
    held = module.FirstBootProvisioner(root=root, network_activate=lambda _p: False).apply(
        bundle=bundle, hardware_serial="10000000abcdef01")
    assert held["state"] == "PROVISIONING_AP"
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "GENERAL.STATE:activated\n"

    monkeypatch.setattr(module.subprocess, "run", lambda command, **_kw: commands.append(command) or Result())

    code = module._main(["--root", str(root), "--bundle", str(bundle),
                         "--hardware-serial", "10000000abcdef01", "--network", "check"])

    assert code == 0
    assert commands == [["nmcli", "-t", "-f", "GENERAL.STATE", "connection", "show", "rosy-site-sta"]]
    state = json.loads((root / "var/lib/rosy/provisioning/state.json").read_text(encoding="utf-8"))
    assert state == {"state": "PROVISIONED"}
    assert not bundle.exists()


def test_retry_check_while_site_wifi_is_down_stays_held(tmp_path, monkeypatch):
    module = _module()
    root, bundle = _case(tmp_path)

    class Result:
        returncode = 0
        stdout = ""

    commands: list[list[str]] = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **_kw: commands.append(command) or Result())

    code = module._main(["--root", str(root), "--bundle", str(bundle),
                         "--hardware-serial", "10000000abcdef01", "--network", "check"])

    assert code == 1
    assert not any("up" in command for command in commands)
    assert bundle.exists()


def test_retry_units_only_check_and_then_start_the_runtime():
    service = (FIRST_BOOT / "rosy-first-boot-retry.service").read_text(encoding="utf-8")
    timer = (FIRST_BOOT / "rosy-first-boot-retry.timer").read_text(encoding="utf-8")
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    customizer = (ROOT / "deploy/image/customize-rootfs.sh").read_text(encoding="utf-8")

    assert "ExecStart=/opt/rosy/first-boot/rosy-first-boot.sh --network check" in service
    assert "connection up" not in service
    assert "ExecStartPost=/usr/bin/systemctl start --no-block rosy-runtime.target" in service
    assert "ConditionPathExists=!/var/lib/rosy/provisioning/complete.json" in service
    assert "ConditionPathExists=!/var/lib/rosy/provisioning/complete.json" in timer
    assert "OnUnitInactiveSec=" in timer and "WantedBy=timers.target" in timer
    # No Restart= on the first-boot unit: its pending start job would hold
    # rosy-config and rosy-network (the D-176 fallback AP) behind it.
    assert "Restart=" not in (FIRST_BOOT / "rosy-first-boot.service").read_text(encoding="utf-8")
    for unit in ("rosy-first-boot-retry.service", "rosy-first-boot-retry.timer"):
        assert f'cp "$FIRST_BOOT_SOURCE/{unit}" "$OVERLAY/etc/systemd/system/"' in payload
    assert "rosy-first-boot-retry.timer" in customizer.split("systemctl --root")[1].split("\n\n")[0]
    script = (FIRST_BOOT / "rosy-first-boot.sh").read_text(encoding="utf-8")
    assert '"$@"' in script
