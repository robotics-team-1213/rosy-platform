"""Camera paint becomes a metric map draft, never an activated driving map."""
import json

import cv2
import numpy as np
import pytest

from rosy_vision.lane_map import _graph, generate_map, main


def test_broad_border_outside_roi_keeps_road_loop_without_island_lanes():
    image = np.zeros((600, 600, 3), np.uint8)
    cv2.rectangle(image, (20, 20), (580, 580), (255, 255, 255), 40)
    cv2.rectangle(image, (80, 80), (520, 520), (255, 255, 255), 4)
    # An island's U-shaped marking is one boundary, not two road edges.
    cv2.polylines(image, [np.array([[280, 340], [280, 260], [320, 260], [320, 340]])],
                  False, (255, 255, 255), 4)
    calibration = {"image_size": [600, 600], "image_to_map":
                   [[0.005, 0, -1.5], [0, -0.005, 1.5], [0, 0, 1]],
                   "bounds_m": {"min_x": -1.25, "max_x": 1.25, "min_y": -1.25, "max_y": 1.25},
                   "road_seed_m": [0, 1.2]}
    draft, _ = generate_map(image, calibration, lane_width_m=0.2)
    assert len(draft["edges"]) == 3 and len(draft["places"]) == 3
    assert all(sum(p["id"] in (e["from"], e["to"]) for e in draft["edges"]) == 2
               for p in draft["places"])
    assert all(max(abs(x), abs(y)) > 1.0 for e in draft["edges"] for x, y in e["polyline"])
    with pytest.raises(ValueError, match="white_value_min"):
        generate_map(image, {**calibration, "white_value_min": True}, lane_width_m=0.2)


def test_camera_lane_map_and_rejection(tmp_path):
    image = np.zeros((240, 400, 3), np.uint8)
    cv2.line(image, (25, 90), (375, 90), (255, 255, 255), 5)
    cv2.line(image, (25, 130), (375, 130), (255, 255, 255), 5)
    calibration = {"image_size": [400, 240], "image_to_map":
                   [[0.005, 0, -1], [0, -0.005, 0.6], [0, 0, 1]]}
    draft, evidence = generate_map(image, calibration, lane_width_m=0.2)
    assert draft["schema"] == "rosy.site_map/1"
    assert len(draft["edges"]) == 1 and len(draft["places"]) == 2
    edge = draft["edges"][0]
    assert edge["drive_mode"] == "lane" and edge["direction"] == "two_way"
    points = np.array(edge["polyline"])
    assert np.ptp(points[:, 0]) > 1.5
    assert np.max(np.abs(points[:, 1] - 0.05)) < 0.02
    assert evidence["paint_pixels"] > 100
    dead_end = image.copy()
    cv2.line(dead_end, (25, 90), (25, 130), (255, 255, 255), 5)
    closed, _ = generate_map(dead_end, calibration, lane_width_m=0.2)
    assert len(closed["edges"]) == 1  # connected border paint must not erase a valid road
    from fleet.site_map import SiteMap
    SiteMap.model_validate(draft)
    occluded = image.copy()
    occluded[:, 180:230] = 0
    split, _ = generate_map(occluded, calibration, lane_width_m=0.2)
    SiteMap.model_validate(split)
    assert len(split["edges"]) == 2  # no invented link across the hidden lane
    selected, _ = generate_map(occluded, {**calibration, "road_seed_m": [-0.7, 0.05]}, lane_width_m=0.2)
    assert len(selected["edges"]) == 1
    with pytest.raises(ValueError, match="road_seed_m"):
        generate_map(occluded, {**calibration, "road_seed_m": [0, 0.5]}, lane_width_m=0.2)
    transform = cv2.getPerspectiveTransform(np.float32([[0, 0], [399, 0], [399, 239], [0, 239]]),
                                            np.float32([[60, 30], [340, 10], [390, 220], [5, 230]]))
    tilted = cv2.warpPerspective(image, transform, (400, 240))
    tilted_calibration = {**calibration, "image_to_map":
                          (np.array(calibration["image_to_map"]) @ np.linalg.inv(transform)).tolist()}
    fitted, _ = generate_map(tilted, tilted_calibration, lane_width_m=0.2)
    SiteMap.model_validate(fitted)
    assert len(fitted["edges"]) == 1
    with pytest.raises(ValueError, match="lane"):
        generate_map(np.zeros_like(image), calibration, lane_width_m=0.2)
    with pytest.raises(ValueError, match="image_size"):
        generate_map(image, {**calibration, "image_size": [800, 240]}, lane_width_m=0.2)
    with pytest.raises(ValueError):
        generate_map(image, {**calibration, "image_to_map": np.zeros((3, 3)).tolist()}, lane_width_m=0.2)
    # One white marking is not a road: do not create parallel offset ghost lanes.
    single = image.copy()
    single[120:] = 0
    with pytest.raises(ValueError, match="lane"):
        generate_map(single, calibration, lane_width_m=0.2)
    cv2.imwrite(str(tmp_path / "camera.jpg"), image)
    (tmp_path / "calibration.json").write_text(json.dumps(calibration), encoding="utf-8")
    assert main(["--image", str(tmp_path / "camera.jpg"), "--calibration",
                 str(tmp_path / "calibration.json"), "--lane-width-m", "0.2",
                 "--output", str(tmp_path / "draft.json")]) == 0
    SiteMap.model_validate(json.loads((tmp_path / "draft.json").read_text()))
    assert (tmp_path / "draft.evidence.json").exists()
    saved = (tmp_path / "draft.json").read_bytes()
    assert main(["--image", str(tmp_path / "camera.jpg"), "--calibration",
                 str(tmp_path / "calibration.json"), "--lane-width-m", "0.2",
                 "--output", str(tmp_path / "draft.json")]) == 2
    assert (tmp_path / "draft.json").read_bytes() == saved
    assert main(["--frame-url", "http://example.invalid/frame", "--calibration",
                 str(tmp_path / "calibration.json"), "--lane-width-m", "0.2",
                 "--output", str(tmp_path / "rejected.json")]) == 2
    assert not (tmp_path / "rejected.json").exists()
    ring = np.zeros((400, 400, 3), np.uint8)
    cv2.circle(ring, (200, 200), 100, (255, 255, 255), 4)
    cv2.circle(ring, (200, 200), 140, (255, 255, 255), 4)
    larger = {"image_size": [400, 400], "image_to_map":
              [[0.005, 0, -1], [0, -0.005, 1], [0, 0, 1]]}
    ring_map, _ = generate_map(ring, larger, lane_width_m=0.2)
    SiteMap.model_validate(ring_map)
    assert len(ring_map["edges"]) == 3
    junction = np.zeros_like(ring)
    cv2.line(junction, (25, 180), (375, 180), (255, 255, 255), 4)
    cv2.line(junction, (25, 220), (375, 220), (255, 255, 255), 4)
    cv2.line(junction, (180, 25), (180, 180), (255, 255, 255), 4)
    cv2.line(junction, (220, 25), (220, 180), (255, 255, 255), 4)
    junction[178:183, 182:218] = 0
    junction_map, _ = generate_map(junction, larger, lane_width_m=0.2)
    SiteMap.model_validate(junction_map)
    degree = {p["id"]: sum(p["id"] in (e["from"], e["to"]) for e in junction_map["edges"])
              for p in junction_map["places"]}
    assert sorted(degree.values()) == [1, 1, 1, 3]
    # A roundabout with an entrance must keep the loop, not just its entrance.
    skeleton = np.zeros((160, 160), bool)
    skeleton[20, 20:81] = skeleton[80, 20:81] = True
    skeleton[20:81, 20] = skeleton[20:81, 80] = True
    skeleton[50, 80:141] = True
    attached = _graph(skeleton, (0, 1.6), 0.01, 0.2, "attached-ring")
    SiteMap.model_validate(attached)
    assert len(attached["edges"]) == 4
