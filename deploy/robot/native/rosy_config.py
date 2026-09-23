"""Operator-editable boot configuration (D-176).

Three layers, later ones win: image defaults (/etc/rosy/defaults.yaml), the
one-time personalization bundle, and /boot/firmware/rosy-config.yaml, which a
person edits on any PC. Identity (device UID, name, robot number) is never
configurable here; it comes only from the bundle and reprovisioning (D-33,
D-154). Passwords in the operator file are applied, then replaced on the card
by APPLIED so the plaintext does not stay on the FAT32 partition.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import yaml

try:
    from deploy.sd.personalization import validate_operator_key
except ModuleNotFoundError:  # installed image layout
    # The image installs deploy/sd beside this runtime: /opt/rosy/deploy/sd
    # next to /opt/rosy/native-runtime (build-native-payload.sh).
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from deploy.sd.personalization import validate_operator_key


APPLIED = "<applied>"
AP_MODES = {"fallback", "relay", "off"}
IDENTITY_KEYS = {"device_uid", "device_name", "hostname", "robot_number", "ros_domain_id", "namespace"}
TOP_KEYS = {"schema_version", "country", "timezone", "wifi", "ap", "fleet", "operator_ssh_keys"}
MAX_WIFI = 8
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_TIMEZONE = re.compile(r"^[A-Za-z]+(?:/[A-Za-z0-9_+-]+){0,2}$")


class ConfigError(ValueError):
    """The operator file is invalid; nothing from it is applied."""


def _password(value: object, where: str) -> str:
    if value == APPLIED:
        return APPLIED
    if not isinstance(value, str) or not 8 <= len(value) <= 63 or not value.isprintable():
        raise ConfigError(f"{where}: must be 8-63 printable characters or {APPLIED}")
    return value


def _ssid(value: object, where: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 32:
        raise ConfigError(f"{where}: ssid must be 1-32 bytes")
    return value


def validate(document: object) -> dict:
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigError("rosy-config.yaml must be a mapping")
    identity = IDENTITY_KEYS & set(document)
    if identity:
        raise ConfigError(f"identity keys are not configurable here: {', '.join(sorted(identity))}")
    unknown = set(document) - TOP_KEYS
    if unknown:
        raise ConfigError(f"unknown key: {', '.join(sorted(unknown))}")
    if document.get("schema_version", 1) != 1:
        raise ConfigError("schema_version must be 1")
    config: dict = {}
    if "country" in document:
        if not isinstance(document["country"], str) or not _COUNTRY.fullmatch(document["country"]):
            raise ConfigError("country must be two uppercase letters")
        config["country"] = document["country"]
    if "timezone" in document:
        if not isinstance(document["timezone"], str) or not _TIMEZONE.fullmatch(document["timezone"]):
            raise ConfigError("timezone must look like Area/City")
        config["timezone"] = document["timezone"]
    if "wifi" in document:
        networks = document["wifi"] or []
        if not isinstance(networks, list) or len(networks) > MAX_WIFI:
            raise ConfigError(f"wifi must be a list of at most {MAX_WIFI} networks")
        config["wifi"] = []
        for index, network in enumerate(networks):
            where = f"wifi[{index}]"
            if not isinstance(network, dict) or set(network) - {"ssid", "password", "priority"}:
                raise ConfigError(f"{where}: allowed keys are ssid, password, priority")
            entry = {"ssid": _ssid(network.get("ssid"), where),
                     "password": _password(network.get("password"), f"{where}.password")}
            priority = network.get("priority", 10)
            if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 999:
                raise ConfigError(f"{where}.priority must be 0-999")
            entry["priority"] = priority
            config["wifi"].append(entry)
    if "ap" in document:
        ap = document["ap"] or {}
        if not isinstance(ap, dict) or set(ap) - {"mode", "ssid", "password"}:
            raise ConfigError("ap: allowed keys are mode, ssid, password")
        config["ap"] = {}
        if "mode" in ap:
            if ap["mode"] is False:  # YAML 1.1 reads a bare `off` as false
                ap = {**ap, "mode": "off"}
            if ap["mode"] not in AP_MODES:
                raise ConfigError(f"ap.mode must be one of {', '.join(sorted(AP_MODES))}")
            config["ap"]["mode"] = ap["mode"]
        if "ssid" in ap:
            config["ap"]["ssid"] = _ssid(ap["ssid"], "ap")
        if "password" in ap:
            config["ap"]["password"] = _password(ap["password"], "ap.password")
    if "fleet" in document:
        fleet = document["fleet"] or {}
        if not isinstance(fleet, dict) or set(fleet) - {"endpoint", "trust_profile"}:
            raise ConfigError("fleet: allowed keys are endpoint, trust_profile")
        config["fleet"] = {}
        if "endpoint" in fleet:
            if not isinstance(fleet["endpoint"], str) or not fleet["endpoint"].startswith("https://"):
                raise ConfigError("fleet.endpoint must use https://")
            config["fleet"]["endpoint"] = fleet["endpoint"]
        if "trust_profile" in fleet:
            profile = fleet["trust_profile"]
            if not isinstance(profile, str) or not 1 <= len(profile) <= 128:
                raise ConfigError("fleet.trust_profile must be 1-128 characters")
            config["fleet"]["trust_profile"] = profile
    if "operator_ssh_keys" in document:
        keys = document["operator_ssh_keys"] or []
        if not isinstance(keys, list) or len(keys) > 8:
            raise ConfigError("operator_ssh_keys must be a list of at most 8 public keys")
        try:
            config["operator_ssh_keys"] = [validate_operator_key(key) for key in keys]
        except ValueError as exc:
            raise ConfigError(f"operator_ssh_keys: {exc}") from exc
    return config


def parse(text: str) -> dict:
    try:
        document = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as exc:
        raise ConfigError(f"rosy-config.yaml is not valid YAML: {exc}") from exc
    if isinstance(document, dict) and set(document) == {"schema_version"}:
        document = None
    return validate(document)


def load_defaults(path: Path) -> dict:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    ap = document.pop("ap", {}) or {}
    config = validate({key: value for key, value in document.items() if key in TOP_KEYS})
    config["ap"] = {"mode": ap.get("mode", "fallback"),
                    "grace_seconds": int(ap.get("grace_seconds", 120)),
                    "hold_seconds": int(ap.get("hold_seconds", 600))}
    if config["ap"]["mode"] not in AP_MODES:
        raise ConfigError("defaults: ap.mode is invalid")
    return config


def merge(*layers: dict) -> dict:
    merged: dict = {}
    for layer in layers:
        for key, value in (layer or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = copy.deepcopy(value)
    return merged


def scrubbed(config: dict) -> dict:
    view = copy.deepcopy(config)
    for network in view.get("wifi", []):
        if "password" in network:
            network["password"] = APPLIED
    if "password" in view.get("ap", {}):
        view["ap"]["password"] = APPLIED
    return view
