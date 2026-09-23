"""Operator-editable rosy-config.yaml on the boot partition (D-176 Task 1)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"


def _module():
    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location("rosy_config", NATIVE / "rosy_config.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PASSWORD = "site-" + "wifi-" + "pass"


def _text(body: str) -> str:
    return "schema_version: 1\n" + body


def test_the_image_defaults_are_valid_and_carry_no_secrets():
    module = _module()
    defaults = module.load_defaults(NATIVE / "defaults.yaml")

    assert defaults["country"] == "KR"
    assert defaults["ap"]["mode"] == "fallback"
    assert defaults["ap"]["grace_seconds"] == 120
    assert "password" not in (NATIVE / "defaults.yaml").read_text(encoding="utf-8")


def test_a_full_operator_file_parses():
    module = _module()
    config = module.parse(_text(
        "country: KR\n"
        "timezone: Asia/Seoul\n"
        "wifi:\n"
        "  - ssid: site-5g\n"
        f"    password: {PASSWORD}\n"
        "    priority: 20\n"
        "  - ssid: backup\n"
        '    password: "<applied>"\n'
        "ap:\n"
        "  mode: off\n"
        "fleet:\n"
        "  endpoint: https://fleet.example.invalid\n"
        "  trust_profile: site-ca\n"
    ))

    assert [network["ssid"] for network in config["wifi"]] == ["site-5g", "backup"]
    assert config["wifi"][0]["priority"] == 20
    assert config["wifi"][1]["password"] == module.APPLIED
    assert config["ap"]["mode"] == "off"


def test_an_empty_or_missing_file_is_an_empty_config():
    module = _module()

    assert module.parse("") == {}
    assert module.parse(_text("")) == {}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("device_name: rosy-pinky-zzzz\n", "identity"),
        ("robot_number: 3\n", "identity"),
        ("wifi:\n  - ssid: ''\n    password: longenough\n", "ssid"),
        ("wifi:\n  - ssid: " + "x" * 33 + "\n    password: longenough\n", "ssid"),
        ("wifi:\n  - ssid: a\n    password: short\n", "password"),
        ("wifi:\n  - ssid: a\n    password: longenough\n    priority: 5000\n", "priority"),
        ("ap:\n  mode: always\n", "ap.mode"),
        ("ap:\n  password: short\n", "ap.password"),
        ("country: kr\n", "country"),
        ("timezone: ../etc/passwd\n", "timezone"),
        ("fleet:\n  endpoint: http://plain\n", "fleet.endpoint"),
        ("operator_ssh_keys:\n  - not-a-key\n", "operator_ssh_keys"),
        ("surprise: 1\n", "unknown key"),
    ],
)
def test_invalid_files_are_rejected_with_the_reason(body, message):
    module = _module()

    with pytest.raises(module.ConfigError) as error:
        module.parse(_text(body))

    assert message in str(error.value)


def test_malformed_yaml_is_a_config_error_not_a_crash():
    module = _module()

    with pytest.raises(module.ConfigError):
        module.parse("wifi: [unclosed\n")


def test_layers_merge_defaults_then_bundle_then_operator_file():
    module = _module()
    defaults = {"country": "KR", "timezone": "Asia/Seoul", "ap": {"mode": "fallback", "grace_seconds": 120}}
    bundle = {"country": "KR", "ap": {"ssid": "rosy-pinky-e4us"}}
    operator = {"country": "US", "ap": {"mode": "off"}}

    merged = module.merge(defaults, bundle, operator)

    assert merged["country"] == "US"
    assert merged["timezone"] == "Asia/Seoul"
    assert merged["ap"] == {"mode": "off", "grace_seconds": 120, "ssid": "rosy-pinky-e4us"}


def test_the_scrubbed_view_hides_every_password():
    module = _module()
    config = module.parse(_text(
        f"wifi:\n  - ssid: a\n    password: {PASSWORD}\nap:\n  password: {PASSWORD}\n"
    ))

    scrubbed = module.scrubbed(config)

    assert PASSWORD not in repr(scrubbed)
    assert scrubbed["wifi"][0]["password"] == module.APPLIED
    assert scrubbed["ap"]["password"] == module.APPLIED
    assert config["wifi"][0]["password"] == PASSWORD  # the original is untouched
