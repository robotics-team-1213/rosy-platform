"""Device-neutral helpers for per-card ROSY OS personalization."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
import secrets
from typing import Any, Collection, Mapping, Protocol
from uuid import UUID, uuid4


SHORT_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
DEVICE_NAME_PATTERN = re.compile(r"^rosy-pinky-[a-hj-km-np-z2-9]{4}$")
RELEASE_ID_PATTERN = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
RAW_64_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
VALID_PRESETS = frozenset({"core", "motor", "hardware"})
# D-174 F3: operator access is public-key only; these are the accepted key types.
OPERATOR_KEY_TYPES = frozenset({
    "ssh-ed25519", "sk-ssh-ed25519@openssh.com",
    "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
})
MAX_OPERATOR_KEYS = 8
_OPERATOR_KEY = re.compile(r"^(?P<type>[a-z0-9@.-]+) (?P<blob>[A-Za-z0-9+/]+={0,2})(?: (?P<comment>[!-~ ]{1,100}))?$")


def validate_operator_key(key: str) -> str:
    """Return a single-line OpenSSH public key of an allowed type, or raise."""
    if not isinstance(key, str):
        raise ValueError("operator key must be text")
    key = key.strip()
    match = _OPERATOR_KEY.fullmatch(key)
    if match is None or match["type"] not in OPERATOR_KEY_TYPES:
        raise ValueError("operator key is not an allowed single-line public key")
    try:
        blob = base64.b64decode(match["blob"], validate=True)
    except ValueError as exc:
        raise ValueError("operator key body is not base64") from exc
    declared = match["type"].encode("ascii")
    if blob[:4] != len(declared).to_bytes(4, "big") or blob[4:4 + len(declared)] != declared:
        raise ValueError("operator key body does not match its type")
    return key


def operator_key_fingerprint(key: str) -> str:
    blob = base64.b64decode(validate_operator_key(key).split()[1])
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


class ChoiceSource(Protocol):
    def choice(self, alphabet: str) -> str: ...


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    device_uid: str
    device_name: str
    hostname: str
    model: str


def generate_short_code(
    *, length: int = 4, rng: ChoiceSource = secrets
) -> str:
    if length <= 0:
        raise ValueError("short-code length must be positive")
    return "".join(rng.choice(SHORT_CODE_ALPHABET) for _ in range(length))


def validate_device_identity(identity: DeviceIdentity) -> DeviceIdentity:
    if identity.model != "pinky_pro":
        raise ValueError("unsupported device model")
    if not DEVICE_NAME_PATTERN.fullmatch(identity.device_name):
        raise ValueError("invalid Pinky device name")
    if identity.hostname != identity.device_name:
        raise ValueError("hostname must equal the public device name")
    parsed = UUID(identity.device_uid)
    if parsed.version != 4:
        raise ValueError("device_uid must be UUIDv4")
    return identity


def generate_device_identity(
    model: str,
    *,
    rng: ChoiceSource = secrets,
    registered_names: Collection[str] = (),
    max_attempts: int = 32,
) -> DeviceIdentity:
    if model != "pinky_pro":
        raise ValueError("unsupported device model")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    existing = set(registered_names)
    for _ in range(max_attempts):
        device_name = f"rosy-pinky-{generate_short_code(rng=rng)}"
        if device_name in existing:
            continue
        return validate_device_identity(
            DeviceIdentity(
                device_uid=str(uuid4()),
                device_name=device_name,
                hostname=device_name,
                model=model,
            )
        )
    raise RuntimeError(
        f"could not allocate a unique Pinky device name after {max_attempts} attempts"
    )


def derive_wpa_psk(ssid: str, passphrase: str) -> str:
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("SSID length is invalid")
    if not 8 <= len(passphrase) <= 63:
        raise ValueError("Wi-Fi passphrase length is invalid")
    return hashlib.pbkdf2_hmac(
        "sha1", passphrase.encode("utf-8"), ssid.encode("utf-8"), 4096, 32
    ).hex()


def _checksum(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_provision_bundle(
    *,
    identity: DeviceIdentity,
    release_id: str,
    robot_number: int,
    requested_preset: str,
    country_code: str,
    ssid: str,
    wifi_passphrase: str,
    fleet_endpoint: str,
    fleet_trust_profile: str,
    pairing_required: bool,
    pairing_credential: str | None = None,
    operator_ssh_keys: Collection[str] | None = None,
    ap_password: str | None = None,
    created_at: datetime | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    validate_device_identity(identity)
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ValueError("release_id is invalid")
    if not isinstance(robot_number, int) or isinstance(robot_number, bool) or not 1 <= robot_number <= 61:
        raise ValueError("robot_number must be between 1 and 61")
    if requested_preset not in VALID_PRESETS:
        raise ValueError("requested_preset is invalid")
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        raise ValueError("country_code must be two uppercase letters")
    if not fleet_endpoint.startswith("https://"):
        raise ValueError("Fleet endpoint must use HTTPS")
    if not fleet_trust_profile or len(fleet_trust_profile) > 128:
        raise ValueError("Fleet trust profile is invalid")
    if pairing_credential is not None and not pairing_required:
        raise ValueError("pairing credential requires pairing_required")

    created = created_at or datetime.now(UTC)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    created_text = created.astimezone(UTC).isoformat().replace("+00:00", "Z")
    generated_nonce = nonce or secrets.token_urlsafe(24)
    if len(generated_nonce) < 16:
        raise ValueError("nonce is too short")

    fleet: dict[str, Any] = {
        "endpoint": fleet_endpoint,
        "trust_profile": fleet_trust_profile,
        "pairing_required": pairing_required,
    }
    if pairing_credential is not None:
        fleet["pairing_credential"] = pairing_credential

    bundle: dict[str, Any] = {
        "schema_version": 1,
        "device_identity": {
            "device_uid": identity.device_uid,
            "device_name": identity.device_name,
            "hostname": identity.hostname,
            "model": identity.model,
        },
        "release": {"release_id": release_id},
        "dds": {
            "robot_number": robot_number,
            "ros_domain_id": 40 + robot_number,
            "namespace": f"rosy_{robot_number:02d}",
        },
        "runtime": {"requested_preset": requested_preset},
        "network": {
            "country_code": country_code,
            "ssid": ssid,
            "wpa_psk": derive_wpa_psk(ssid, wifi_passphrase),
            # D-176: per-card fallback AP, named after the device.
            **({"ap": {"ssid": identity.device_name, "password": ap_password}} if ap_password else {}),
        },
        "fleet": fleet,
        "created_at": created_text,
        "nonce": generated_nonce,
    }
    if operator_ssh_keys:
        bundle["operator"] = {"ssh_authorized_keys": [validate_operator_key(key) for key in operator_ssh_keys]}
    bundle["payload_checksum"] = _checksum(bundle)
    return validate_provision_bundle(bundle)


def validate_provision_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    expected_top = {
        "schema_version", "device_identity", "release", "dds", "runtime",
        "network", "fleet", "created_at", "nonce", "payload_checksum",
    }
    if set(bundle) - {"operator"} != expected_top:
        raise ValueError("provision bundle keys are invalid")
    if "operator" in bundle:
        operator = bundle["operator"]
        if not isinstance(operator, dict) or set(operator) != {"ssh_authorized_keys"}:
            raise ValueError("operator keys are invalid")
        keys = operator["ssh_authorized_keys"]
        if (not isinstance(keys, list) or not all(isinstance(key, str) for key in keys)
                or not 1 <= len(keys) <= MAX_OPERATOR_KEYS or len(set(keys)) != len(keys)):
            raise ValueError("operator keys are invalid")
        for key in keys:
            if validate_operator_key(key) != key:
                raise ValueError("operator keys are invalid")
    expected_nested = {
        "device_identity": {"device_uid", "device_name", "hostname", "model"},
        "release": {"release_id"},
        "dds": {"robot_number", "ros_domain_id", "namespace"},
        "runtime": {"requested_preset"},
        "network": {"country_code", "ssid", "wpa_psk"},
    }
    for section, keys in expected_nested.items():
        present = set(bundle[section]) if isinstance(bundle.get(section), dict) else None
        if present is not None and section == "network":
            present -= {"ap"}
        if present != keys:
            raise ValueError(f"{section} keys are invalid")
    if "ap" in bundle["network"]:
        ap = bundle["network"]["ap"]
        if (not isinstance(ap, dict) or set(ap) != {"ssid", "password"}
                or not isinstance(ap["ssid"], str) or not 1 <= len(ap["ssid"].encode("utf-8")) <= 32
                or not isinstance(ap["password"], str) or not 12 <= len(ap["password"]) <= 63
                or not all(33 <= ord(char) <= 126 for char in ap["password"])):
            raise ValueError("network.ap must hold an SSID and a 12-63 character printable password")
    fleet_keys = set(bundle.get("fleet", {}))
    if not {"endpoint", "trust_profile", "pairing_required"} <= fleet_keys or not fleet_keys <= {
        "endpoint", "trust_profile", "pairing_required", "pairing_credential"
    }:
        raise ValueError("fleet keys are invalid")
    identity_data = bundle["device_identity"]
    validate_device_identity(DeviceIdentity(**identity_data))
    if bundle["schema_version"] != 1:
        raise ValueError("schema_version is invalid")
    if not RELEASE_ID_PATTERN.fullmatch(bundle["release"].get("release_id", "")):
        raise ValueError("release_id is invalid")
    robot_number = bundle["dds"].get("robot_number")
    if not isinstance(robot_number, int) or isinstance(robot_number, bool) or not 1 <= robot_number <= 61:
        raise ValueError("robot_number must be between 1 and 61")
    if bundle["dds"] != {
        "robot_number": robot_number,
        "ros_domain_id": 40 + robot_number,
        "namespace": f"rosy_{robot_number:02d}",
    }:
        raise ValueError("DDS identity is not derived from robot_number")
    if not RAW_64_HEX_PATTERN.fullmatch(bundle["network"].get("wpa_psk", "")):
        raise ValueError("network PSK must be 64 lowercase hexadecimal characters")
    if bundle["runtime"].get("requested_preset") not in VALID_PRESETS:
        raise ValueError("requested_preset is invalid")
    if not re.fullmatch(r"[A-Z]{2}", bundle["network"].get("country_code", "")):
        raise ValueError("country_code is invalid")
    ssid = bundle["network"].get("ssid")
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("SSID length is invalid")
    fleet = bundle["fleet"]
    if not isinstance(fleet.get("pairing_required"), bool):
        raise ValueError("pairing_required must be boolean")
    if "pairing_credential" in fleet and not fleet["pairing_required"]:
        raise ValueError("pairing credential requires pairing_required")
    supplied = bundle["payload_checksum"]
    unsigned = {key: value for key, value in bundle.items() if key != "payload_checksum"}
    if not secrets.compare_digest(supplied, _checksum(unsigned)):
        raise ValueError("provision bundle checksum does not match")
    return bundle


def create_provision_receipt(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return operator evidence without any transient credential material."""
    return {
        "schema_version": bundle["schema_version"],
        "device_identity": dict(bundle["device_identity"]),
        "release": dict(bundle["release"]),
        "dds": dict(bundle["dds"]),
        "runtime": dict(bundle["runtime"]),
        "network": {
            "ssid": bundle["network"]["ssid"],
            "country_code": bundle["network"]["country_code"],
            **({"ap_ssid": bundle["network"]["ap"]["ssid"]} if "ap" in bundle["network"] else {}),
        },
        "fleet": {
            "endpoint": bundle["fleet"]["endpoint"],
            "trust_profile": bundle["fleet"]["trust_profile"],
            "pairing_required": bundle["fleet"]["pairing_required"],
        },
        "created_at": bundle["created_at"],
        "nonce": bundle["nonce"],
        "payload_checksum": bundle["payload_checksum"],
        **({"operator": {"ssh_key_fingerprints": [
            operator_key_fingerprint(key) for key in bundle["operator"]["ssh_authorized_keys"]
        ]}} if "operator" in bundle else {}),
    }
