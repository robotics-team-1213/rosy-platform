"""Code references forwarded into secret fields are not embedded secret literals."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import secret_scan  # noqa: E402


def test_psk_field_can_forward_a_form_value_without_a_literal_finding():
    assert secret_scan.scan_text(
        "operations.js",
        'postHost(connect, {ssid: name, psk: field.value}, "confirm");',
    ) == []


def test_known_failure_pytest_node_ids_are_not_credential_assignments():
    node_id = (
        "test/test_sd_api_" + "token.py::test_core_accepts_the_issued_cred"
        + "ential_from_the_installed_overlay"
    )
    line = node_id + "  # reason for the test failure"
    assert secret_scan.scan_text("test/known_failures.txt", line) == []
