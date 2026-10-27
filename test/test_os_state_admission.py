"""Malformed A/B state must not silently use the legacy updater policy."""
import json

import pytest

from auto_update_fakes import REPO, device, host, hub, keys, upd, updater

ROOT_UUID = "d42e6eca-5905-4f13-9ba3-7a966de708a1"
DESCRIPTOR = dict(schema_version=1, state_schema=1, slot="a", root_partuuid=ROOT_UUID,
                  data_partuuid="272db95d-597f-4643-a377-e14691849d9e",
                  provision_partuuid="7ba3053b-e4e5-4770-99dc-d5d27117bc04")


def test_legacy_updater_policy_is_unchanged_without_ab_marker_or_descriptor(host, hub):
    assert updater(host, hub)._config() == dict(enabled=True, repo=REPO, api_base=None)


@pytest.mark.parametrize("case", ["missing_descriptor", "missing_marker", "duplicate_marker",
    "unknown_marker", "invalid_json", "unsupported_schema", "boolean_schema", "unknown_field"])
def test_ab_configuration_errors_never_fall_back_to_legacy_policy(device, host, hub, case):
    command = f"root=PARTUUID={ROOT_UUID} rosy.os_layout=ab-v1"
    descriptor = dict(DESCRIPTOR)
    if case == "missing_marker":
        command = f"root=PARTUUID={ROOT_UUID}"
    elif case == "duplicate_marker":
        command += " rosy.os_layout=ab-v1"
    elif case == "unknown_marker":
        command = f"root=PARTUUID={ROOT_UUID} rosy.os_layout=ab-v999"
    elif case == "unsupported_schema":
        descriptor["schema_version"] = 2
    elif case == "boolean_schema":
        descriptor["schema_version"] = True
    elif case == "unknown_field":
        descriptor["skip_admission"] = True
    (device / "proc/cmdline").write_text(command + "\n", encoding="ascii")
    if case != "missing_descriptor":
        (device / "etc/rosy/os-slot.json").write_text(
            "{" if case == "invalid_json" else json.dumps(descriptor), encoding="utf-8")
    with pytest.raises(upd.UpdateError, match="OS_STATE_HOLD"):
        updater(host, hub)._config()
    assert not (device / "var/lib/rosy/updates/state.json").exists()
    assert json.loads((device / "var/lib/rosy/updates/config.json").read_text()) == dict(enabled=True, repo=REPO)
