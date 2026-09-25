"""D-257 site sighting contract: derived geometry only, never image or policy evidence."""

import pytest
from pydantic import ValidationError

from core_common.protocol.sightings import SiteSightingPayload


def _payload(**changes):
    body = {
        "robot_id": "rosy_01",
        "x": 1.25,
        "y": -0.5,
        "yaw": 0.2,
        "captured_at": 1_790_000_000.25,
        "seq": 42,
        "map_id": "lane-map:sha256:abc",
        "calibration_revision": "ceiling-1-v2",
        "processor_revision": "aruco-map-v1",
        "quality": 0.98,
        "corner_marker_ids": [30, 31, 32, 33],
    }
    body.update(changes)
    return body


def test_site_sighting_round_trips_only_small_derived_evidence():
    sighting = SiteSightingPayload.model_validate(_payload())
    assert sighting.model_dump(mode="json") == _payload()


def test_sighting_can_explicitly_report_unmeasured_quality_as_null():
    sighting = SiteSightingPayload.model_validate(_payload(quality=None))
    assert sighting.quality is None


@pytest.mark.parametrize("changes", [
    {"x": float("nan")},
    {"y": float("inf")},
    {"yaw": float("-inf")},
    {"captured_at": float("nan")},
    {"quality": 1.01},
    {"seq": -1},
    {"corner_marker_ids": [30, 31, 32]},
    {"corner_marker_ids": [30, 31, 31, 33]},
    {"corner_marker_ids": [30, 31, True, 33]},
    {"corner_marker_ids": [30, 31, "32", 33]},
    {"quality": True},
    {"source_id": "claimed-by-client"},
    {"jpeg": "AAECAw=="},
])
def test_site_sighting_rejects_untrusted_or_invalid_fields(changes):
    with pytest.raises(ValidationError):
        SiteSightingPayload.model_validate(_payload(**changes))
