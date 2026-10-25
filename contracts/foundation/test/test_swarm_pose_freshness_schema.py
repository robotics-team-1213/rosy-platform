"""Original pose capture time survives forwarding without becoming send time."""

import json

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import Envelope, EnvelopeType, PoseSample


@pytest.mark.parametrize("sampled_at", [1792886400, 1792886400.125])
def test_pose_capture_time_roundtrips_independently_of_envelope_send_time(sampled_at):
    sample = PoseSample(robot_id="rosy_01", pose={"x": 1.0}, seq=7,
                        sampled_at=sampled_at)
    envelope = Envelope(type=EnvelopeType.POSE, ts="2026-10-25T12:00:01Z",
                        payload=sample.model_dump(mode="json"))

    decoded = Envelope.model_validate_json(envelope.model_dump_json())
    parsed = PoseSample.model_validate(decoded.payload)

    assert parsed.sampled_at == sampled_at
    assert decoded.payload["sampled_at"] == sampled_at
    assert decoded.ts == "2026-10-25T12:00:01Z"
    assert decoded.protocol_version == "1.0"
    assert (parsed.robot_id, parsed.pose.x, parsed.seq) == ("rosy_01", 1.0, 7)


@pytest.mark.parametrize("metadata", [{}, {"sampled_at": None}])
def test_missing_pose_capture_time_stays_unknown(metadata):
    payload = {"robot_id": "rosy_01", "pose": {}, "seq": 7, **metadata}
    sample = PoseSample.model_validate_json(json.dumps(payload))

    assert sample.sampled_at is None
    assert PoseSample.model_validate_json(sample.model_dump_json()).sampled_at is None


@pytest.mark.parametrize("sampled_at", [
    float("nan"), float("inf"), -float("inf"), -1, 0, True, False, "1792886400.125",
])
@pytest.mark.parametrize("wire_json", [False, True])
def test_pose_capture_time_rejects_nonpositive_nonfinite_or_coerced_values(sampled_at, wire_json):
    payload = {"robot_id": "rosy_01", "pose": {}, "seq": 7, "sampled_at": sampled_at}

    with pytest.raises(ValidationError):
        if wire_json:
            PoseSample.model_validate_json(json.dumps(payload))
        else:
            PoseSample.model_validate(payload)
