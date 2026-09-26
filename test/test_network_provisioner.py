"""Provisioning and mode contracts (WP-3, design section 8, ADR D-26).

Four of these are safety properties rather than behaviours: a dropped WLAN
must not open an access point, a recovery request must be spent exactly once,
recovery must not open with the wheels live, and a site passphrase must not
survive anywhere. Each is asserted directly.

NetworkManager and the reachability probe are injected, so the failure paths
that would need a real radio — a wrong passphrase, an association with no
address, a router with client isolation — all run here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from network import (  # via test/conftest.py
    MIN_SETUP_PSK_LENGTH,
    READABLE_ALPHABET,
    READABLE_SETUP_KEY,
    SETUP_PSK_LENGTH,
    RECOVERY_MARKER_NAME,
    NetworkProvisioner,
    NetworkState,
    OperatingMode,
    Reachability,
    SetupRequest,
    generate_setup_psk,
)

SITE_PSK = "site-passphrase-not-to-be-kept"


class FakeNetworkManager:
    """Records profiles and activations; never a real radio."""

    def __init__(self, *, fail_activate: set[str] | None = None) -> None:
        self.profiles: dict[str, dict] = {}
        self.active: str | None = None
        self.activations: list[str] = []
        self.fail_activate = set(fail_activate or ())

    def list_profiles(self) -> list[str]:
        return sorted(self.profiles)

    def _add(self, kind: str, name: str, ssid: str, psk: str, country: str) -> None:
        self.profiles[name] = {"kind": kind, "ssid": ssid, "psk": psk, "country": country}

    def add_site_profile(self, name, *, ssid, psk, country):
        self._add("site", name, ssid, psk, country)

    def add_relay_profile(self, name, *, ssid, psk, country):
        self._add("relay", name, ssid, psk, country)

    def add_ap_profile(self, name, *, ssid, psk, country):
        self._add("ap", name, ssid, psk, country)

    def activate(self, name):
        if name in self.fail_activate:
            raise RuntimeError(f"association failed for {name}")
        self.activations.append(name)
        self.active = name

    def deactivate(self, name):
        if self.active == name:
            self.active = None

    def delete_profile(self, name):
        self.profiles.pop(name, None)


ONLINE = Reachability(ipv4="192.168.0.42", default_route=True, internet=True, peer_reachable=True)
ISOLATED = Reachability(ipv4="192.168.0.42", default_route=True, internet=True, peer_reachable=False)
NO_ADDRESS = Reachability(ipv4=None, default_route=False, internet=False, peer_reachable=False)


@pytest.fixture
def backend() -> FakeNetworkManager:
    return FakeNetworkManager()


def _provisioner(tmp_path: Path, backend, *, probe=lambda: ONLINE,
                 boot_id="boot-1", services_stopped=lambda: True) -> NetworkProvisioner:
    return NetworkProvisioner(
        backend,
        state_dir=tmp_path / "state",
        boot_partition=tmp_path / "boot",
        probe=probe,
        boot_id=boot_id,
        services_stopped=services_stopped,
    )


def _request(**overrides) -> SetupRequest:
    fields = {
        "country": "KR",
        "ssid": "site-wifi",
        "psk": SITE_PSK,
        "robot_id": "rosy_01",
        "hostname": "rosy-01",
    }
    fields.update(overrides)
    return SetupRequest(**fields)


# --- first boot ------------------------------------------------------------


def test_an_unprovisioned_device_opens_the_setup_ap(tmp_path, backend):
    provisioner = _provisioner(tmp_path, backend)

    assert provisioner.begin() is NetworkState.PROVISIONING_AP
    assert backend.active == NetworkProvisioner.SETUP_PROFILE


def test_the_setup_passphrase_is_per_device_and_long_enough(tmp_path, backend):
    first = _provisioner(tmp_path, backend)
    first.begin()
    second = _provisioner(tmp_path, FakeNetworkManager())
    second.begin()

    assert len(first.setup_psk) >= MIN_SETUP_PSK_LENGTH
    assert first.setup_psk != second.setup_psk, "the setup PSK must not be a shared secret"


def test_a_short_setup_passphrase_is_refused():
    with pytest.raises(ValueError, match="at least"):
        generate_setup_psk(1)


def test_the_setup_passphrase_is_rosy_and_two_readable_groups():
    """rosy-xxxx-xxxx from 31 symbols without 0 o 1 l i: easy to read off the LCD and type."""
    assert READABLE_ALPHABET == "abcdefghjkmnpqrstuvwxyz23456789"
    assert not set("0o1li") & set(READABLE_ALPHABET)
    for _ in range(200):
        value = generate_setup_psk()
        assert READABLE_SETUP_KEY.fullmatch(value), value
        assert len(value) == MIN_SETUP_PSK_LENGTH == 14
        prefix, *groups = value.split("-")
        assert prefix == "rosy"
        assert [len(group) for group in groups] == [4, 4]
        assert set("".join(groups)) <= set(READABLE_ALPHABET)
    assert 8 <= MIN_SETUP_PSK_LENGTH <= 63  # WPA2 passphrase bounds
    assert SETUP_PSK_LENGTH == len("rosy-") + 4 + 1 + 4
    # The pattern's class is exactly the alphabet.
    assert "".join(c for c in map(chr, range(128)) if READABLE_SETUP_KEY.fullmatch(f"rosy-{c * 4}-{c * 4}"))         == "".join(sorted(READABLE_ALPHABET))


def test_the_setup_passphrase_entropy_is_the_eight_random_symbols():
    import math

    # The fixed prefix adds nothing; 8 symbols of 31 are ~39.6 bits (D-176 amendment).
    assert round(8 * math.log2(len(READABLE_ALPHABET)), 1) == 39.6
    seen = set()
    values = {generate_setup_psk() for _ in range(500)}
    for value in values:
        seen |= set(value.removeprefix("rosy-").replace("-", ""))
    assert len(values) == 500, "two of 500 generated passphrases collided"
    assert seen == set(READABLE_ALPHABET)
    assert READABLE_SETUP_KEY.fullmatch(generate_setup_psk(3))  # longer on request


def test_the_setup_passphrase_is_never_logged(tmp_path, backend):
    """It goes to the LCD, and nowhere a log or an API can reach."""
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()

    rendered = json.dumps(provisioner.log)
    assert provisioner.setup_psk not in rendered


# --- provisioning both modes through one setup AP --------------------------


@pytest.mark.parametrize(
    "mode,expected",
    [
        (OperatingMode.SITE_STA, NetworkState.SITE_STA),
        (OperatingMode.RELAY_AP_STA, NetworkState.RELAY_AP_STA),
    ],
)
def test_both_modes_are_reachable_from_the_same_setup_ap(tmp_path, backend, mode, expected):
    """ADR D-26: one provisioning path, two operating modes."""
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()

    assert provisioner.provision(_request(mode=mode)) == []
    assert provisioner.state is expected


def test_relay_mode_gets_credentials_of_its_own(tmp_path, backend):
    """NET-005, and one step further.

    The operating AP must not reuse the setup AP's passphrase — and it must
    not reuse the *site* passphrase either. Handing an operator the robot's
    AP password would otherwise hand them the site Wi-Fi password with it.
    """
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()
    setup_psk = provisioner.setup_psk

    provisioner.provision(_request(mode=OperatingMode.RELAY_AP_STA))

    relay = backend.profiles[NetworkProvisioner.RELAY_PROFILE]
    assert relay["kind"] == "relay"
    assert relay["psk"] != setup_psk, "the relay AP reuses the setup passphrase"
    assert relay["psk"] != SITE_PSK, "the relay AP hands out the site Wi-Fi passphrase"
    assert len(relay["psk"]) >= MIN_SETUP_PSK_LENGTH


def test_no_profile_shares_a_passphrase_with_another(tmp_path, backend):
    """Every credential on the device is its own."""
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()
    provisioner.provision(_request(mode=OperatingMode.RELAY_AP_STA))

    site = backend.profiles[NetworkProvisioner.SITE_PROFILE]["psk"]
    relay = backend.profiles[NetworkProvisioner.RELAY_PROFILE]["psk"]

    assert site == SITE_PSK, "the site profile keeps the operator's own passphrase"
    assert relay != site


def test_site_mode_opens_no_access_point(tmp_path, backend):
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()

    provisioner.provision(_request(mode=OperatingMode.SITE_STA))

    assert NetworkProvisioner.RELAY_PROFILE not in backend.profiles
    assert backend.active == NetworkProvisioner.SITE_PROFILE


def test_the_setup_endpoint_closes_after_provisioning(tmp_path, backend):
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()

    provisioner.provision(_request())

    assert NetworkProvisioner.SETUP_PROFILE not in backend.profiles
    assert provisioner.setup_psk is None
    assert any(e["event"] == "network.setup_endpoint_closed" for e in provisioner.log)


# --- a failed attempt leaves a working device working ----------------------


def test_a_wrong_passphrase_returns_to_the_setup_ap(tmp_path):
    backend = FakeNetworkManager(fail_activate={NetworkProvisioner.CANDIDATE_PROFILE})
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()

    rejections = provisioner.provision(_request())

    assert [r.code for r in rejections] == ["SETUP_WIFI_UNREACHABLE"]
    assert provisioner.state is NetworkState.PROVISIONING_AP


def test_a_failed_candidate_is_discarded(tmp_path):
    """The existing profile is untouched until the candidate is proven."""
    backend = FakeNetworkManager(fail_activate={NetworkProvisioner.CANDIDATE_PROFILE})
    backend.add_site_profile("rosy-site-sta", ssid="old-wifi", psk="old", country="KR")
    provisioner = _provisioner(tmp_path, backend)

    provisioner.provision(_request())

    assert NetworkProvisioner.CANDIDATE_PROFILE not in backend.profiles
    assert backend.profiles["rosy-site-sta"]["ssid"] == "old-wifi", "the working profile survived"


def test_associating_without_an_address_is_a_failure(tmp_path, backend):
    """Joining is not the same as being on the network."""
    provisioner = _provisioner(tmp_path, backend, probe=lambda: NO_ADDRESS)
    provisioner.begin()

    rejections = provisioner.provision(_request())

    assert [r.code for r in rejections] == ["SETUP_WIFI_NO_ADDRESS"]
    assert NetworkProvisioner.CANDIDATE_PROFILE not in backend.profiles


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("country", "kr", "SETUP_COUNTRY_INVALID"),
        ("country", "KOR", "SETUP_COUNTRY_INVALID"),
        ("ssid", "", "SETUP_SSID_INVALID"),
        ("ssid", "x" * 33, "SETUP_SSID_INVALID"),
        ("psk", "short", "SETUP_PSK_INVALID"),
        ("psk", "x" * 64, "SETUP_PSK_INVALID"),
        ("robot_id", "Rosy 01", "SETUP_ROBOT_ID_INVALID"),
        ("hostname", "Rosy_01", "SETUP_HOSTNAME_INVALID"),
    ],
)
def test_malformed_setup_input_is_refused_before_any_radio_change(tmp_path, backend, field, value, code):
    provisioner = _provisioner(tmp_path, backend)
    rejections = provisioner.provision(_request(**{field: value}))

    assert code in [r.code for r in rejections]
    assert backend.profiles == {}, "nothing may be configured from invalid input"


# --- the passphrase does not survive ---------------------------------------


def test_the_site_passphrase_never_appears_in_a_record(tmp_path, backend):
    """It reaches NetworkManager and nothing else."""
    provisioner = _provisioner(tmp_path, backend)
    provisioner.begin()
    provisioner.provision(_request())

    assert SITE_PSK not in json.dumps(provisioner.log)


def test_the_passphrase_is_absent_from_the_redacted_view():
    view = _request().redacted()

    assert SITE_PSK not in json.dumps(view)
    assert "psk" not in view
    assert view["ssid"] == "site-wifi", "the SSID is displayable"


def test_a_rejection_does_not_echo_the_passphrase(tmp_path, backend):
    """Not even to explain what was wrong with it."""
    provisioner = _provisioner(tmp_path, backend)
    rejections = provisioner.provision(_request(psk="short"))

    assert "short" not in json.dumps([r.detail for r in rejections])


def test_events_carry_no_passphrase(tmp_path, backend):
    seen: list[tuple[str, dict]] = []
    provisioner = NetworkProvisioner(
        backend,
        state_dir=tmp_path / "state",
        boot_partition=tmp_path / "boot",
        probe=lambda: ONLINE,
        boot_id="boot-1",
        events=lambda name, payload: seen.append((name, payload)),
    )
    provisioner.begin()
    provisioner.provision(_request())

    assert seen
    assert SITE_PSK not in json.dumps(seen)
    assert provisioner.setup_psk is None


# --- a dropped WLAN is a hold, never an access point -----------------------


def test_losing_the_uplink_holds_rather_than_opening_an_ap(tmp_path):
    """The most ordinary Wi-Fi fault must not put an AP on a site."""
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    provisioner = _provisioner(tmp_path, backend, probe=lambda: NO_ADDRESS)

    state = provisioner.begin()

    assert state is NetworkState.NETWORK_HOLD
    assert NetworkProvisioner.SETUP_PROFILE not in backend.profiles


def test_a_failed_association_on_a_provisioned_device_also_holds(tmp_path):
    backend = FakeNetworkManager(fail_activate={NetworkProvisioner.SITE_PROFILE})
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    provisioner = _provisioner(tmp_path, backend)

    assert provisioner.begin() is NetworkState.NETWORK_HOLD
    assert NetworkProvisioner.SETUP_PROFILE not in backend.profiles


def test_a_provisioned_device_connects_when_the_wlan_is_there(tmp_path):
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    provisioner = _provisioner(tmp_path, backend)

    assert provisioner.begin() is NetworkState.SITE_STA


# --- internet and peer reachability are separate verdicts ------------------


def test_client_isolation_is_recorded_separately_from_the_internet(tmp_path):
    """A router with client isolation gives the internet and no dashboard."""
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    provisioner = _provisioner(tmp_path, backend, probe=lambda: ISOLATED)

    provisioner.begin()

    connected = [e for e in provisioner.log if e["event"] == "network.connected"][-1]
    assert connected["internet"] is True
    assert connected["peer_reachable"] is False


def test_reachability_needs_an_address_and_a_route():
    assert ONLINE.usable
    assert not NO_ADDRESS.usable
    assert Reachability("192.168.0.42", False, True, True).usable is False


# --- the recovery AP is explicit and one-shot ------------------------------


def test_a_recovery_ap_is_not_opened_without_a_request(tmp_path):
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    provisioner = _provisioner(tmp_path, backend, probe=lambda: NO_ADDRESS)

    assert provisioner.begin() is NetworkState.NETWORK_HOLD


def test_a_dashboard_reservation_opens_the_recovery_ap_next_boot(tmp_path):
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    first = _provisioner(tmp_path, backend)
    first.request_recovery_ap()

    rebooted = _provisioner(tmp_path, backend, boot_id="boot-2")

    assert rebooted.begin() is NetworkState.RECOVERY_AP


def test_a_boot_partition_marker_opens_the_recovery_ap(tmp_path):
    """For a device that is powered off and cannot be asked."""
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    boot = tmp_path / "boot"
    boot.mkdir(parents=True)
    (boot / RECOVERY_MARKER_NAME).write_text("", encoding="utf-8")

    provisioner = _provisioner(tmp_path, backend)

    assert provisioner.begin() is NetworkState.RECOVERY_AP


def test_a_recovery_request_is_spent_exactly_once(tmp_path):
    """A request that survives its attempt reopens the AP on every boot."""
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    first = _provisioner(tmp_path, backend)
    first.request_recovery_ap()

    assert _provisioner(tmp_path, backend, boot_id="boot-2").begin() is NetworkState.RECOVERY_AP

    third = _provisioner(tmp_path, FakeNetworkManager(), boot_id="boot-3")
    third._backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    assert third.begin() is not NetworkState.RECOVERY_AP, "the request came back"


def test_a_boot_marker_is_deleted_when_it_is_consumed(tmp_path):
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    boot = tmp_path / "boot"
    boot.mkdir(parents=True)
    marker = boot / RECOVERY_MARKER_NAME
    marker.write_text("", encoding="utf-8")

    _provisioner(tmp_path, backend).begin()

    assert not marker.exists(), "the marker would reopen the AP on the next boot"


def test_a_request_is_spent_even_when_the_ap_fails_to_open(tmp_path):
    """Otherwise a device that cannot open an AP retries forever."""
    backend = FakeNetworkManager(fail_activate={NetworkProvisioner.SETUP_PROFILE})
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    first = _provisioner(tmp_path, backend)
    first.request_recovery_ap()

    second = _provisioner(tmp_path, backend, boot_id="boot-2")
    assert second.begin() is NetworkState.NETWORK_HOLD

    third = _provisioner(tmp_path, backend, boot_id="boot-3")
    third.begin()
    assert not any(e["event"] == "network.recovery_request_consumed" for e in third.log), (
        "a failed attempt must still spend the request"
    )


# --- recovery does not open with the wheels live ---------------------------


def test_recovery_refuses_while_motor_or_io_is_running(tmp_path):
    """The AP is a maintenance state, not a state to be in with wheels live."""
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    first = _provisioner(tmp_path, backend)
    first.request_recovery_ap()

    running = _provisioner(tmp_path, backend, boot_id="boot-2", services_stopped=lambda: False)
    state = running.begin()

    assert state is NetworkState.NETWORK_HOLD
    assert NetworkProvisioner.SETUP_PROFILE not in backend.profiles
    assert any(e["event"] == "network.recovery_ap_refused" for e in running.log)


def test_the_refusal_still_spends_the_request(tmp_path):
    backend = FakeNetworkManager()
    backend.add_site_profile("rosy-site-sta", ssid="site-wifi", psk="x", country="KR")
    _provisioner(tmp_path, backend).request_recovery_ap()

    running = _provisioner(tmp_path, backend, boot_id="boot-2", services_stopped=lambda: False)
    running.begin()

    later = _provisioner(tmp_path, backend, boot_id="boot-3")
    assert not any(e["event"] == "network.recovery_request_consumed" for e in later.log)
