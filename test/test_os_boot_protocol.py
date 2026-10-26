"""Protocol 2 admission and authenticated provisioning policy; no card writes."""
import io
import json
from pathlib import Path
import sys

import pytest

BASE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro"
sys.path.insert(0, str(BASE / "native"))
sys.path.insert(0, str(BASE / "sd"))
from os_state_layout import _layout, _object
from test_os_state_admission import DESCRIPTOR, ROOT_UUID
from test_sd_gpt_layout import _table_image
from media_layout import LayoutCapture, inspect_device, parse_gpt, validate_layout


def _slot(root, version, marker):
    (root / "etc/rosy").mkdir(parents=True, exist_ok=True)
    (root / "proc").mkdir(exist_ok=True)
    (root / "etc/rosy/os-slot.json").write_text(json.dumps(dict(DESCRIPTOR, schema_version=version)))
    (root / "proc/cmdline").write_text(f"root=PARTUUID={ROOT_UUID} rosy.os_layout={marker}\n")


@pytest.mark.parametrize("version", [1, 2])
def test_reader_admits_matching_boot_protocol_without_changing_shared_state(tmp_path, version):
    _slot(tmp_path, version, f"ab-v{version}")
    descriptor, digest = _layout(tmp_path)
    assert descriptor["schema_version"] == version
    assert descriptor["state_schema"] == 1
    assert len(digest) == 64


@pytest.mark.parametrize("version,marker", [(1, "ab-v2"), (2, "ab-v1"), (3, "ab-v3"), (True, "ab-v1")])
def test_reader_rejects_mixed_or_unknown_boot_protocol(tmp_path, version, marker):
    _slot(tmp_path, version, marker)
    with pytest.raises(ValueError):
        _layout(tmp_path)


def test_slot_protocol_does_not_expand_shared_state_schema():
    with pytest.raises(ValueError, match="schema_version"):
        _object(b'{"schema_version":2,"state_schema":1}', {"schema_version", "state_schema"})


@pytest.mark.parametrize("role", ["boot_a", "bootstrap"])
def test_gpt_provision_policy_comes_from_authenticated_metadata(role):
    raw, layout = _table_image()
    layout["provision_role"] = role
    assert validate_layout(layout) == layout
    assert parse_gpt(lambda offset, count: raw[offset:offset + count], len(raw), role) == layout
    assert inspect_device(io.BytesIO(raw), layout) == layout
    capture = LayoutCapture(layout)
    capture.feed(0, raw)
    assert capture.finish() == layout
    # The same physical bytes alone cannot identify the provisioning policy.
    assert parse_gpt(lambda offset, count: raw[offset:offset + count], len(raw))["provision_role"] == "boot_a"


@pytest.mark.parametrize("role", ["boot_b", "root_a", True, None, ["bootstrap"]])
def test_unsupported_provision_policy_is_rejected(role):
    raw, layout = _table_image()
    layout["provision_role"] = role
    with pytest.raises(ValueError):
        validate_layout(layout)
