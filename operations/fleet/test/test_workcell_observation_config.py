"""Configured native observation intake starts without inventing map calibration."""
import json

import pytest

from fleet import cli
from fleet.server.workcell_observation_config import load_workcell_observations


@pytest.fixture
def configured(tmp_path):
    path = tmp_path / "observations.json"
    path.write_text(json.dumps({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "example", "label": "Example", "arms": [{
            "source_id": "arm_a", "arm_id": "arm_a", "label": "Arm A", "board_id": "EXAMPLE-BOARD",
            "joint_topic": "/omx_commissioning/arm_a/joint_states", "joint_names": ["joint1"],
            "token_env": "EXAMPLE_ARM_TOKEN"}], "cameras": [{
                "source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
                "image_topic": "/top/image_raw", "device_path": "/dev/v4l/by-id/example-top",
                "token_env": "EXAMPLE_TOP_TOKEN"}]}]}), encoding="utf-8")
    return path


def test_manifest_resolves_only_arm_credentials_for_fleet(configured):
    service = load_workcell_observations(configured, environ={"EXAMPLE_ARM_TOKEN": "producer-secret"})
    assert service.camera_source_ids() == ("top",)
    assert "producer-secret" not in json.dumps(service.snapshot())
    assert service.snapshot()["workcells"][0]["arms"][0]["positions"] is None


def test_missing_or_empty_producer_credential_fails_closed(configured):
    for environ in ({}, {"EXAMPLE_ARM_TOKEN": ""}):
        with pytest.raises(ValueError, match="credential|EXAMPLE_ARM_TOKEN"):
            load_workcell_observations(configured, environ=environ)


def test_console_cli_binds_opt_in_manifest(configured, tmp_path):
    args = cli.parse_args(["console", "--robots", str(tmp_path / "robots.yaml"),
                           "--workcell-observations", str(configured)])
    assert args.workcell_observations == configured
