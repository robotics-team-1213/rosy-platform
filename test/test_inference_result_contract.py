"""Source-bound numerical output remains valid until the owner consumes it."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/learning/src"))
from rosy.contracts.learning.inference import InferenceObservation, InferenceResult


def observation():
    return InferenceObservation(
        episode_id="episode", lease_id="lease", joint_names=("j1", "j2"),
        positions=(0., 0.), sequence=3, observed_at_ns=10,
        camera_identity="wrist", camera_calibration_sha256="a" * 64,
        camera_shape=(3, 1, 1), camera_received_at_ns=12, rgb=b"rgb",
    )


def result(**changes):
    fields = dict(policy_revision="policy-v1", source=observation(), positions=(.1, .2),
                  produced_at_ns=20, returned_at_ns=21, chunk_index=0, consumed_current=True)
    fields.update(changes)
    return InferenceResult(**fields)


def test_result_freezes_output_before_candidate_is_built():
    positions = [.1, .2]
    output = result(positions=positions)
    positions[0] = 99.
    candidate = output.candidate_fields()
    assert output.positions == (.1, .2)
    assert candidate["positions"] == (.1, .2)
    assert candidate["sequence"] == output.source.sequence
    assert candidate["camera_frames"] == (output.source.frame_sha256,)


@pytest.mark.parametrize("changes", [
    {"policy_revision": ""}, {"policy_revision": " policy-v1"},
    {"source": None}, {"positions": (.1,)}, {"positions": (.1, float("nan"))},
    {"positions": (True, .2)}, {"positions": (.1, float("inf"))},
    {"produced_at_ns": True}, {"produced_at_ns": -1}, {"produced_at_ns": 20.},
    {"produced_at_ns": 11}, {"returned_at_ns": 19}, {"returned_at_ns": 2**63},
    {"returned_at_ns": True}, {"chunk_index": -1}, {"chunk_index": True},
    {"chunk_index": .5}, {"consumed_current": 1}, {"consumed_current": "false"},
])
def test_result_rejects_invalid_output_or_provenance(changes):
    with pytest.raises(ValueError):
        result(**changes)


def test_queued_result_keeps_original_source_and_generation_time():
    source = observation()
    queued = result(source=source, chunk_index=3, consumed_current=False, returned_at_ns=100)
    assert queued.source is source
    assert queued.produced_at_ns == 20
    assert queued.candidate_fields()["observed_at_ns"] == 10
