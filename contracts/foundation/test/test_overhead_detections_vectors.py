"""D-457 4: overhead detections follow the shared vectors (Vision and Fleet read the same file)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core_common.protocol.overhead_detections import (
    MAX_DETECTIONS, STATUSES, OverheadDetectionsPayload,
)

FIXTURE = json.loads((Path(__file__).resolve().parents[3]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
def test_payload_validation_matches_the_vector(case):
    if case["expect"]["valid"]:
        payload = OverheadDetectionsPayload.model_validate(case["payload"])
        assert payload.model_dump(mode="json") == case["payload"]
    else:
        with pytest.raises(ValidationError):
            OverheadDetectionsPayload.model_validate(case["payload"])


def test_constants_are_the_vector_constants():
    assert MAX_DETECTIONS == FIXTURE["max_detections"] == 16
    assert STATUSES == tuple(FIXTURE["statuses"])


def test_more_than_the_maximum_is_refused():
    body = dict(CASES["ok_two_detections"]["payload"])
    one = body["detections"][0]
    body["detections"] = [one] * MAX_DETECTIONS
    assert len(OverheadDetectionsPayload.model_validate(body).detections) == MAX_DETECTIONS
    body["detections"] = [one] * (MAX_DETECTIONS + 1)
    with pytest.raises(ValidationError):
        OverheadDetectionsPayload.model_validate(body)


def test_payload_is_immutable():
    payload = OverheadDetectionsPayload.model_validate(CASES["ok_empty"]["payload"])
    with pytest.raises(ValidationError):
        payload.seq = 7


def _detection(**changes):
    body = {"x": 1.0, "y": 1.0, "footprint_m": 0.18, "score": 0.8}
    body.update(changes)
    return {**CASES["ok_empty"]["payload"], "detections": [body]}


def _frame(**changes):
    return {**CASES["ok_empty"]["payload"], **changes}


NAN, INF = float("nan"), float("inf")

PYTHON_ONLY_INVALID = {
    "nan_x": _detection(x=NAN),
    "inf_y": _detection(y=INF),
    "nan_score": _detection(score=NAN),
    "inf_footprint": _detection(footprint_m=INF),
    "nan_captured_at": _frame(captured_at=NAN),
    "inf_captured_at": _frame(captured_at=INF),
    "bool_score": _detection(score=True),
    "bool_footprint": _detection(footprint_m=True),
    "bool_captured_at": _frame(captured_at=True),
    "bool_seq": _frame(seq=True),
    "seq_overflow": _frame(seq=0x100000000),
    "footprint_zero": _detection(footprint_m=0),
    "footprint_above_max": _detection(footprint_m=2.01),
    "score_negative": _detection(score=-0.01),
    "blank_map_id": _frame(map_id=" "),
    "blank_calibration_revision": _frame(calibration_revision="	"),
    "blank_processor_revision": _frame(processor_revision=""),
}


@pytest.mark.parametrize("body", PYTHON_ONLY_INVALID.values(), ids=PYTHON_ONLY_INVALID.keys())
def test_python_only_invalid_values_are_refused(body):
    with pytest.raises(ValidationError):
        OverheadDetectionsPayload.model_validate(body)


def test_seq_upper_bound_is_valid():
    assert OverheadDetectionsPayload.model_validate(_frame(seq=0xFFFFFFFF)).seq == 0xFFFFFFFF


@pytest.mark.parametrize("marker", [-1, True, 7.0, "7"])
def test_marker_id_is_a_strict_nonnegative_integer(marker):
    with pytest.raises(ValidationError):
        OverheadDetectionsPayload.model_validate(_detection(marker_id=marker))


def test_duplicate_marker_in_one_frame_is_refused():
    one = _detection(marker_id=7)["detections"][0]
    with pytest.raises(ValidationError):
        OverheadDetectionsPayload.model_validate(_frame(detections=[one, one]))
