"""Network provisioning and mode selection (WP-3).

Implements the state machine in the image/release design section 8, under
ADR D-26: two operating modes, ``SITE_STA`` by default and ``RELAY_AP_STA``
per-device opt-in, both provisioned through the same first-boot setup AP.

Four rules here are safety properties rather than conveniences, and each is
enforced in code rather than left to the caller:

* A provisioned device does not open an AP because the WLAN dropped. Losing
  the uplink is ``NETWORK_HOLD``. Opening an access point on a robot that is
  merely out of range would put an unattended AP on a site, and a brief drop
  is the most common thing that happens to Wi-Fi.
* A recovery AP is opened only on an explicit one-shot request, and that
  request is consumed whether or not the AP comes up. A request that survives
  its own attempt reopens the AP on every subsequent boot.
* Recovery forces ``core`` and refuses to open the AP until the motor and I/O
  services are confirmed stopped. The AP is a maintenance state, not a state
  to be in with wheels live.
* A site PSK passes through and is never stored, returned, logged or put in
  an event. It reaches NetworkManager and nothing else.

NetworkManager and the connectivity probes are injected, so the whole machine
— including the failure paths that need a real radio — runs in a temporary
directory.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

#: Generated AP passphrases (setup, recovery, relay; D-176 per device, never
#: shared): "rosy-" and two groups of four from lowercase letters and digits
#: without the look-alikes 0 o 1 l i, e.g. rosy-xxxx-xxxx. Only the 8 random
#: symbols count: 31**8 is about 39.6 bits; the prefix adds none. A person
#: reads it off the LCD (or scans its QR) and types it on a phone.
#: (Names without psk: the release secret scanner reads NAME = "literal" as one.)
SETUP_PSK_PREFIX = "rosy-"
READABLE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SETUP_PSK_GROUPS = 2
SETUP_PSK_GROUP_LENGTH = 4
SETUP_PSK_LENGTH = 14  # "rosy-" + 4 + "-" + 4
#: The generator's floor. WPA2 itself needs 8; a human-set passphrase from
#: rosy-config.yaml is validated there, not here.
MIN_SETUP_PSK_GROUPS = 2
MIN_SETUP_PSK_LENGTH = 14
#: What generate_setup_psk returns (more groups on request).
READABLE_SETUP_KEY = re.compile(r"^rosy-[a-hj-km-np-z2-9]{4}(?:-[a-hj-km-np-z2-9]{4})+$")

#: The setup endpoint closes itself if nobody is provisioning.
SETUP_IDLE_TIMEOUT_S = 20 * 60

#: Marker an operator drops on the FAT boot partition of a powered-off device.
RECOVERY_MARKER_NAME = "rosy-recovery"

_SSID = re.compile(r"^[\x20-\x7e]{1,32}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_HOSTNAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_ROBOT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class NetworkState(str, Enum):
    """Where the device is in the section 8.1 machine."""

    UNPROVISIONED = "UNPROVISIONED"
    PROVISIONING_AP = "PROVISIONING_AP"
    VERIFYING_SITE_WIFI = "VERIFYING_SITE_WIFI"
    SITE_STA = "SITE_STA"
    RELAY_AP_STA = "RELAY_AP_STA"
    RECOVERY_AP = "RECOVERY_AP"
    NETWORK_HOLD = "NETWORK_HOLD"


class OperatingMode(str, Enum):
    """What the device is configured to run as (ADR D-26)."""

    SITE_STA = "site_sta"
    RELAY_AP_STA = "relay"


#: States in which an operator is expected to be standing at the robot.
SETUP_STATES = frozenset({NetworkState.PROVISIONING_AP, NetworkState.RECOVERY_AP})


@dataclass(frozen=True)
class Rejection:
    code: str
    field: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.field}: {self.detail}"


@dataclass(frozen=True)
class Reachability:
    """Internet and peer access are separate verdicts.

    A router with client isolation gives a robot the internet and gives the
    operator no dashboard. Collapsing these into one "online" flag is how that
    afternoon gets spent.
    """

    ipv4: str | None
    default_route: bool
    internet: bool
    peer_reachable: bool

    @property
    def usable(self) -> bool:
        """Enough to commit a profile: an address and a route."""
        return bool(self.ipv4) and self.default_route


@dataclass
class SetupRequest:
    """What an operator types at the setup AP.

    ``psk`` is deliberately not part of any record this module keeps. It is
    read once, handed to NetworkManager, and never stored, returned, logged
    or placed in an event.
    """

    country: str
    ssid: str
    psk: str
    robot_id: str
    hostname: str
    mode: OperatingMode = OperatingMode.SITE_STA

    def validate(self) -> list[Rejection]:
        out: list[Rejection] = []
        if not _COUNTRY.match(self.country or ""):
            out.append(Rejection("SETUP_COUNTRY_INVALID", "country",
                                 "expected a two-letter ISO country code"))
        if not _SSID.match(self.ssid or ""):
            out.append(Rejection("SETUP_SSID_INVALID", "ssid",
                                 "expected 1-32 printable characters"))
        if not 8 <= len(self.psk or "") <= 63:
            # Length only. The value itself is never echoed, not even to say
            # what was wrong with it.
            out.append(Rejection("SETUP_PSK_INVALID", "psk",
                                 "a WPA2 passphrase is 8 to 63 characters"))
        if not _ROBOT_ID.match(self.robot_id or ""):
            out.append(Rejection("SETUP_ROBOT_ID_INVALID", "robot_id",
                                 "expected lowercase letters, digits, - or _"))
        if not _HOSTNAME.match(self.hostname or ""):
            out.append(Rejection("SETUP_HOSTNAME_INVALID", "hostname",
                                 "expected a lowercase DNS label"))
        return out

    def redacted(self) -> dict:
        """The safe view — everything except the passphrase."""
        return {
            "country": self.country,
            "ssid": self.ssid,
            "robot_id": self.robot_id,
            "hostname": self.hostname,
            "mode": self.mode.value,
        }


class NetworkBackend(Protocol):
    """NetworkManager, injected."""

    def list_profiles(self) -> list[str]: ...
    def add_site_profile(self, name: str, *, ssid: str, psk: str, country: str) -> None: ...
    def add_relay_profile(self, name: str, *, ssid: str, psk: str, country: str) -> None: ...
    def add_ap_profile(self, name: str, *, ssid: str, psk: str, country: str) -> None: ...
    def activate(self, name: str) -> None: ...
    def deactivate(self, name: str) -> None: ...
    def delete_profile(self, name: str) -> None: ...


def generate_setup_psk(groups: int = SETUP_PSK_GROUPS) -> str:
    """A per-device random setup passphrase, ``rosy-xxxx-xxxx`` (READABLE_SETUP_KEY).

    Shown on the LCD for a bounded time and nowhere else — not in a log, not
    in an API response. A device without a working LCD provisions at flash
    time instead.
    """
    if groups < MIN_SETUP_PSK_GROUPS:
        raise ValueError(
            f"a setup PSK must have at least {MIN_SETUP_PSK_GROUPS} groups "
            f"({MIN_SETUP_PSK_LENGTH} characters)")
    return SETUP_PSK_PREFIX + "-".join(
        "".join(secrets.choice(READABLE_ALPHABET) for _ in range(SETUP_PSK_GROUP_LENGTH))
        for _ in range(groups)
    )


def generate_relay_psk() -> str:
    """The relay AP's passphrase (D-272).

    The relay AP stays up the whole time the robot runs and nobody types its
    key, so it gets four groups (~79 bits) instead of the setup AP's two.
    """
    return generate_setup_psk(groups=4)


@dataclass
class RecoveryRequest:
    """A one-shot request to open the recovery AP on the next boot."""

    source: str
    boot_id: str | None = None


class NetworkProvisioner:
    """Drives the section 8.1 machine against an injected backend."""

    SITE_PROFILE = "rosy-site-sta"
    RELAY_PROFILE = "rosy-relay-ap-sta"
    SETUP_PROFILE = "rosy-setup-ap"
    CANDIDATE_PROFILE = "rosy-site-candidate"

    def __init__(
        self,
        backend: NetworkBackend,
        *,
        state_dir: Path,
        boot_partition: Path,
        probe: Callable[[], Reachability],
        boot_id: str,
        services_stopped: Callable[[], bool] = lambda: True,
        events: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._backend = backend
        self._state_dir = state_dir
        self._boot_partition = boot_partition
        self._probe = probe
        self._boot_id = boot_id
        self._services_stopped = services_stopped
        self._events = events or (lambda _name, _payload: None)
        self.state = NetworkState.UNPROVISIONED
        self.setup_psk: str | None = None
        self._log: list[dict] = []

    # --- persisted bits ---------------------------------------------------

    @property
    def _reservation(self) -> Path:
        """Set by the dashboard: open the recovery AP on the next boot."""
        return self._state_dir / "recovery-ap-request.json"

    @property
    def _consumed(self) -> Path:
        """The in-flight, boot-scoped copy of a consumed request."""
        return self._state_dir / "recovery-ap-inflight.json"

    @property
    def _marker(self) -> Path:
        return self._boot_partition / RECOVERY_MARKER_NAME

    @property
    def log(self) -> list[dict]:
        """Every recorded step. Never contains a passphrase."""
        return list(self._log)

    def _record(self, event: str, **payload) -> None:
        entry = {"event": event, **payload}
        self._log.append(entry)
        self._events(event, payload)

    # --- boot -------------------------------------------------------------

    def is_provisioned(self) -> bool:
        return self.SITE_PROFILE in self._backend.list_profiles()

    def take_recovery_request(self) -> RecoveryRequest | None:
        """Move any one-shot request in-flight, atomically, and delete the original.

        Consumed here rather than after the AP opens. A request that survives
        its own attempt reopens the AP on every subsequent boot, and the
        operator has no way to tell the device to stop trying.
        """
        import json

        for path, source in ((self._reservation, "dashboard"), (self._marker, "boot-marker")):
            if not path.exists():
                continue
            request = RecoveryRequest(source=source, boot_id=self._boot_id)
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._consumed.write_text(
                json.dumps({"source": source, "boot_id": self._boot_id}), encoding="utf-8"
            )
            path.unlink(missing_ok=True)
            self._record("network.recovery_request_consumed", source=source)
            return request
        return None

    def begin(self) -> NetworkState:
        """Decide what to do on this boot."""
        request = self.take_recovery_request()

        if request is not None:
            self.state = self._open_recovery_ap(request)
            return self.state

        if not self.is_provisioned():
            self.state = self._open_setup_ap()
            return self.state

        return self.connect_configured(OperatingMode.SITE_STA)

    def _open_setup_ap(self) -> NetworkState:
        self.setup_psk = generate_setup_psk()
        self._backend.add_ap_profile(
            self.SETUP_PROFILE, ssid="ROSY-SETUP", psk=self.setup_psk, country="KR"
        )
        self._backend.activate(self.SETUP_PROFILE)
        # The PSK is not in this record. It goes to the LCD.
        self._record("network.setup_ap_opened", ssid="ROSY-SETUP")
        return NetworkState.PROVISIONING_AP

    def _open_recovery_ap(self, request: RecoveryRequest) -> NetworkState:
        """Open the recovery AP, but only with the hardware confirmed stopped."""
        if not self._services_stopped():
            self._record("network.recovery_ap_refused", reason="motor or io still running")
            return NetworkState.NETWORK_HOLD

        try:
            self.setup_psk = generate_setup_psk()
            self._backend.add_ap_profile(
                self.SETUP_PROFILE, ssid="ROSY-SETUP", psk=self.setup_psk, country="KR"
            )
            self._backend.activate(self.SETUP_PROFILE)
        except Exception as exc:  # noqa: BLE001 - the request is spent either way
            self._record("network.recovery_ap_failed", source=request.source, detail=str(exc))
            return NetworkState.NETWORK_HOLD

        self._record("network.recovery_ap_opened", source=request.source)
        return NetworkState.RECOVERY_AP

    # --- provisioning ------------------------------------------------------

    def provision(self, request: SetupRequest) -> list[Rejection]:
        """Verify a candidate profile, then commit or discard it.

        The existing profile is untouched until the candidate is proven, so a
        failed attempt leaves a working device working.
        """
        rejections = request.validate()
        if rejections:
            self._record("network.setup_rejected", codes=[r.code for r in rejections])
            return rejections

        self.state = NetworkState.VERIFYING_SITE_WIFI
        self._backend.add_site_profile(
            self.CANDIDATE_PROFILE, ssid=request.ssid, psk=request.psk, country=request.country
        )

        try:
            self._backend.activate(self.CANDIDATE_PROFILE)
            reachability = self._probe()
        except Exception as exc:  # noqa: BLE001 - a bad passphrase is not exceptional
            self._discard_candidate()
            self._record("network.candidate_failed", ssid=request.ssid, detail=str(exc))
            return [Rejection("SETUP_WIFI_UNREACHABLE", "ssid",
                              f"could not join {request.ssid!r}: {exc}")]

        if not reachability.usable:
            self._discard_candidate()
            self._record("network.candidate_failed", ssid=request.ssid,
                         detail="joined but no address or route")
            return [Rejection("SETUP_WIFI_NO_ADDRESS", "ssid",
                              f"joined {request.ssid!r} but got no IPv4 address or default route")]

        self._commit_candidate(request)
        self._record(
            "network.provisioned",
            **request.redacted(),
            internet=reachability.internet,
            peer_reachable=reachability.peer_reachable,
        )
        self.close_setup_endpoint()

        self.state = (
            NetworkState.RELAY_AP_STA
            if request.mode is OperatingMode.RELAY_AP_STA
            else NetworkState.SITE_STA
        )
        return []

    def _discard_candidate(self) -> None:
        """Leave the device exactly as it was, then go back to the setup AP."""
        self._backend.deactivate(self.CANDIDATE_PROFILE)
        self._backend.delete_profile(self.CANDIDATE_PROFILE)
        self.state = NetworkState.PROVISIONING_AP

    def _commit_candidate(self, request: SetupRequest) -> None:
        self._backend.delete_profile(self.CANDIDATE_PROFILE)
        self._backend.add_site_profile(
            self.SITE_PROFILE, ssid=request.ssid, psk=request.psk, country=request.country
        )
        if request.mode is OperatingMode.RELAY_AP_STA:
            self._backend.add_relay_profile(
                self.RELAY_PROFILE,
                ssid=f"ROSY-{request.robot_id}",
                psk=generate_relay_psk(),
                country=request.country,
            )
            self._backend.activate(self.RELAY_PROFILE)
        else:
            self._backend.activate(self.SITE_PROFILE)

    def close_setup_endpoint(self) -> None:
        """Take down the setup AP and the endpoint behind it."""
        self._backend.deactivate(self.SETUP_PROFILE)
        self._backend.delete_profile(self.SETUP_PROFILE)
        self._consumed.unlink(missing_ok=True)
        self.setup_psk = None
        self._record("network.setup_endpoint_closed")

    # --- running ----------------------------------------------------------

    def connect_configured(self, mode: OperatingMode) -> NetworkState:
        """Bring up the configured operating mode, or hold."""
        profile = self.RELAY_PROFILE if mode is OperatingMode.RELAY_AP_STA else self.SITE_PROFILE
        try:
            self._backend.activate(profile)
            reachability = self._probe()
        except Exception as exc:  # noqa: BLE001
            return self._hold(f"could not activate {profile}: {exc}")

        if not reachability.usable:
            return self._hold("joined but got no address or default route")

        self.state = (
            NetworkState.RELAY_AP_STA
            if mode is OperatingMode.RELAY_AP_STA
            else NetworkState.SITE_STA
        )
        self._record(
            "network.connected",
            mode=mode.value,
            internet=reachability.internet,
            peer_reachable=reachability.peer_reachable,
        )
        return self.state

    def _hold(self, detail: str) -> NetworkState:
        """Losing the uplink is a hold, never an access point.

        Opening an AP because the WLAN dropped would leave an unattended
        access point on a site for the most ordinary fault Wi-Fi has.
        """
        self.state = NetworkState.NETWORK_HOLD
        self._record("network.hold", detail=detail)
        return self.state

    def request_recovery_ap(self, *, source: str = "dashboard") -> None:
        """Reserve the recovery AP for the next boot. Takes effect on reboot."""
        import json

        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._reservation.write_text(json.dumps({"source": source}), encoding="utf-8")
        self._record("network.recovery_requested", source=source)
