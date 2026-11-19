"""Parity contracts for D-940 registered duplicates in OMX demonstration and _iso helpers."""

from __future__ import annotations

import io
import math
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for _rel in (
    "contracts/learning/src",
    "middleware/core/gateway",
    "middleware/core/services",
    "operations/account",
):
    _entry = str(ROOT / _rel)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from core.trip_lease import _iso as trip_lease_iso  # noqa: E402
from core_features.calibration.session import _iso as calibration_session_iso  # noqa: E402
from omx_adapter import demonstration as writer_demo  # noqa: E402
from rosy.contracts.learning import omx as contract_omx  # noqa: E402
from rosy_account.password_session import _iso as password_session_iso  # noqa: E402


def _provenance() -> dict:
    return {
        "simulation": True,
        "instance_id": "sim01",
        "source_revision": "a" * 40,
        "vendor_revision": "b" * 40,
        "world_sha256": "c" * 64,
        "source_tree_sha256": "e" * 64,
        "calibration_revision": "sim-v1",
        "clock_domain": "gazebo_sim",
        "joint_names": ["joint1", "gripper_joint_1"],
        "gripper_joint": "gripper_joint_1",
        "position_limits_rad": {"joint1": [-1.0, 1.0], "gripper_joint_1": [-0.5, 0.5]},
        "camera": {
            "name": "front",
            "identity": "gazebo:front",
            "width": 8,
            "height": 6,
            "camera_info_sha256": "d" * 64,
        },
        "fps": 10,
    }


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), (12, 34, 56)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, True),
        (-1, True),
        (0.0, True),
        (-3.14159, True),
        (1e-12, True),
        (True, False),
        (False, False),
        (math.nan, False),
        (math.inf, False),
        (-math.inf, False),
        (None, False),
        ("0.5", False),
        ([0.0], False),
        ({"v": 0.0}, False),
    ],
)
def test_omx_demonstration_finite_parity(value, expected):
    assert writer_demo._finite(value) is expected
    assert contract_omx._finite(value) is expected


@pytest.mark.parametrize(
    "payload",
    [
        {"b": 1, "a": 2},
        {"task": "블록 집기", "nested": {"z": [1, 2, 3], "a": "한글-utf8"}},
        {"empty": {}, "items": [], "zero": 0.0},
    ],
)
def test_omx_demonstration_json_and_sha_parity(payload):
    writer_bytes = writer_demo._json(payload)
    contract_bytes = contract_omx._json(payload)
    assert writer_bytes == contract_bytes
    assert writer_demo._sha(writer_bytes) == contract_omx._sha(contract_bytes)


@pytest.mark.parametrize("bad_number", [math.nan, math.inf, -math.inf])
def test_omx_demonstration_json_rejects_non_finite_numbers_identically(bad_number):
    payload = {"nested": {"value": bad_number}}
    with pytest.raises(ValueError):
        writer_demo._json(payload)
    with pytest.raises(ValueError):
        contract_omx._json(payload)


def test_omx_writer_record_is_accepted_by_contract_validator(tmp_path):
    recorder = writer_demo.DemonstrationRecorder(tmp_path, _provenance())
    recorder.start("pick and place block")
    png = _png_bytes()
    for index, ts in enumerate((1_000_000_000, 1_100_000_000)):
        recorder.sample(
            capture_time_ns=ts,
            state_time_ns=ts - 10_000_000,
            positions={"joint1": 0.01 * (index + 1), "gripper_joint_1": -0.1},
            target={"joint1": 0.02 * (index + 1), "gripper_joint_1": 0.2},
            state_sequence=index + 1,
            command_id=f"cmd-{index}",
            ros_goal_id=f"11111111-1111-4111-8111-11111111111{index + 1}",
            duration_s=0.4,
            image_png=png,
            received_at_ns=ts + 100,
        )
    manifest = recorder.stop("success")
    episode_dir = tmp_path / manifest["episode_id"]

    writer_validated = writer_demo.validate_episode(episode_dir)
    contract_validated = contract_omx.validate_demonstration(episode_dir)
    assert writer_validated == contract_validated


@pytest.mark.parametrize(
    "epoch,expected",
    [
        (0.0, "1970-01-01T00:00:00+00:00"),
        (1_700_000_000.0, "2023-11-14T22:13:20+00:00"),
        (1_700_000_000.987654, "2023-11-14T22:13:20+00:00"),
    ],
)
def test_iso_timestamp_helper_parity(epoch, expected):
    results = (
        trip_lease_iso(epoch),
        calibration_session_iso(epoch),
        password_session_iso(epoch),
    )
    assert results == (expected, expected, expected)

    now = time.time()
    assert trip_lease_iso(now) == calibration_session_iso(now) == password_session_iso(now)
