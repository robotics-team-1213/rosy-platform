"""D-587 5: sticker yaw offset from a straight forward drive (travel direction, not odom)."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ceiling_marker_yaw import EstimateError, estimate  # noqa: E402


def _drive(heading_deg, sighting_yaw_deg, *, n=12, length=0.4, wobble=0.0, yaw_noise=0.0):
    h = math.radians(heading_deg)
    rows = []
    for i in range(n):
        s = length * i / (n - 1)
        side = wobble * (1 if i % 2 else -1)
        rows.append((100.0 + 0.4 * i, 0.3 + s * math.cos(h) - side * math.sin(h),
                     -0.5 + s * math.sin(h) + side * math.cos(h),
                     math.radians(sighting_yaw_deg + yaw_noise * (1 if i % 3 else -1))))
    return rows


@pytest.mark.parametrize("heading, seen, current, expected, nearest", [
    (0.0, 0.0, 0.0, 0.0, 0),            # sticker right: no change
    (30.0, 200.0, 0.0, 170.0, 180),     # sticker on backwards, 10 deg short
    (-120.0, -30.0, 0.0, 90.0, 90),     # turned 90 deg left
    (90.0, 92.0, 180.0, -178.0, 180),   # already corrected by 180, 2 deg left
])
def test_offset_is_the_current_plus_the_yaw_minus_the_travel_direction(heading, seen, current, expected, nearest):
    result = estimate(_drive(heading, seen, yaw_noise=0.5), current)
    assert result["offset_deg"] == pytest.approx(expected, abs=0.3)
    assert result["travel_deg"] == pytest.approx(heading, abs=0.1)
    assert result["nearest_90_deg"] == nearest


def test_travel_direction_follows_time_not_the_axis_sign():
    rows = _drive(180.0, 180.0)
    assert estimate(rows)["offset_deg"] == pytest.approx(0.0, abs=0.1)
    reversed_time = [(200.0 - t, x, y, yaw) for t, x, y, yaw in rows]   # same points, driven the other way
    assert abs(estimate(reversed_time)["offset_deg"]) == pytest.approx(180.0, abs=0.1)


@pytest.mark.parametrize("rows, message", [
    (_drive(0.0, 0.0, n=4), "need 5"),
    (_drive(0.0, 0.0, length=0.2), "at least"),
    (_drive(0.0, 0.0, wobble=0.03), "straight line"),
    (_drive(0.0, 0.0, yaw_noise=6.0), "yaw spread"),
])
def test_refuses_a_drive_it_cannot_trust(rows, message):
    with pytest.raises(EstimateError, match=message):
        estimate(rows)


def test_offline_frames_in_capture_order(tmp_path, monkeypatch):
    """--frames: every recorded JPEG goes through frame_sample with its size and mtime."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    import os

    import ceiling_marker_yaw as tool

    for i in range(3):
        path = tmp_path / f"{i:03d}.jpg"
        cv2.imwrite(str(path), np.zeros((72, 128), np.uint8))
        os.utime(path, (1000.0 + i, 1000.0 + i))
    (tmp_path / "bad.jpg").write_bytes(b"not a jpeg")
    seen = []

    def fake(record, jpeg, size, captured_at, *, source, marker, heading_edge):
        seen.append((size, captured_at, source, marker, heading_edge))
        return None if captured_at == 1001.0 else (captured_at, 0.0, 0.0, 0.0)

    monkeypatch.setattr(tool, "frame_sample", fake)
    rows = tool.collect_offline(str(tmp_path), {"map_id": "m"}, source="ceiling_north", marker=41,
                                heading_edge=(0, 1))
    assert [r[0] for r in rows] == [1000.0, 1002.0]
    assert seen[0] == ((128, 72), 1000.0, "ceiling_north", 41, (0, 1)) and len(seen) == 3
def test_retired_development_session_never_contacts_fleet(monkeypatch, capsys):
    import ceiling_marker_yaw as tool

    def unexpected_request(*args, **kwargs):
        pytest.fail("retired development login must not contact Fleet")

    monkeypatch.setattr(tool, "_request", unexpected_request)
    with pytest.raises(SystemExit) as refused:
        tool.main(["--robot", "rosy_41", "--marker", "41", "--dev-session"])
    assert refused.value.code == 2
    captured = capsys.readouterr()
    assert "sign in" in captured.err and "ROSY_FLEET_TOKEN" in captured.err
    assert not captured.out


def _cargo_rows(distance, *, fixed_prop=False, reverse_cue=False):
    import ceiling_marker_yaw as tool

    rear = 0.09 if reverse_cue else -0.09
    return [tool.CueSample(float(i), (x, 0.0, math.pi),
                           (rear if fixed_prop else x + rear, 0.0))
            for i in range(8) for x in (distance * i / 7,)]


def test_stationary_orange_evidence_is_only_an_unverified_candidate():
    import ceiling_marker_yaw as tool

    result = tool.estimate_cargo(_cargo_rows(0.0, fixed_prop=True))
    assert result["association"] == "unverified_stationary"
    assert result["candidate_offset_deg"] == pytest.approx(180.0)
    assert result["installation_allowed"] is False


def test_short_comotion_supports_candidate_but_stationary_prop_conflicts():
    import ceiling_marker_yaw as tool

    result = tool.estimate_cargo(_cargo_rows(0.0455), forward_motion=True)
    assert result["association"] == "co_moves"
    assert result["forward_cross_check"] is True
    assert result["installation_allowed"] is False
    with pytest.raises(EstimateError, match="co-move"):
        tool.estimate_cargo(_cargo_rows(0.0455, fixed_prop=True))
    with pytest.raises(EstimateError, match="forward travel"):
        tool.estimate_cargo(_cargo_rows(0.0455, reverse_cue=True), forward_motion=True)


def test_cargo_video_rejects_mismatched_revision_before_reading_frames(monkeypatch, tmp_path):
    import json
    import ceiling_marker_yaw as tool

    record = tmp_path / "approved.json"
    record.write_text(json.dumps({"source_id": "ceiling_north", "map_id": "world",
                                  "calibration_revision": "new", "approved_by": "operator"}))
    monkeypatch.setattr(tool, "collect_cargo_video", lambda *args, **kwargs: pytest.fail("opened video"),
                        raising=False)
    code = tool.main(["--robot", "rosy_45", "--marker", "45", "--cargo-video", "old.mp4",
                      "--record", str(record), "--calibration-revision", "old", "--cargo-height-m", "0.10"])
    assert code == 2


def test_projected_cargo_footprint_rejects_small_distractor_and_abstains_on_two_candidates():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from rosy_vision.detect import generate_marker_image

    import ceiling_marker_yaw as tool

    record = {"source_id": "camera", "map_id": "m", "calibration_revision": "v",
              "map_to_image": [250, 0, 320, 0, -250, 240, 0, 0, 1],
              "image": {"width": 640, "height": 480},
              "track_bounds_m": {"min_x": -1.0, "min_y": -0.8, "max_x": 1.0, "max_y": 0.8},
              "lens": {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 67.8}}
    frame = np.full((480, 640, 3), 240, dtype=np.uint8)
    frame[233:247, 313:327] = cv2.cvtColor(generate_marker_image(45, 14), cv2.COLOR_GRAY2BGR)
    frame[265:274, 309:332] = (0, 125, 235)
    frame[212:215, 313:327] = (0, 125, 235)

    def sample():
        jpeg = cv2.imencode(".jpg", frame)[1].tobytes()
        return tool.cargo_frame_sample(record, jpeg, 1.0, source="camera", marker=45,
                                       heading_edge=(0, 1), cargo_height_m=0.10)

    assert sample().cargo[1] == pytest.approx(-0.11, abs=0.01)
    frame[210:219, 309:332] = (0, 125, 235)
    with pytest.raises(tool.CueUnavailable, match="multiple orange objects"):
        sample()
