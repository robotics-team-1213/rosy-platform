from vision_review_drafts import confirmed, scaled_boxes


def test_vision_box_conversion_drops_out_of_bounds_and_tiny_boxes():
    boxes, rejected = scaled_boxes({'boxes': [
        {'label': 'obstacle', 'bbox_xyxy': [600, 380, 800, 520]},
        {'label': 'obstacle', 'bbox_xyxy': [600, 380, 1800, 520]},
        {'label': 'cone', 'bbox_xyxy': [1, 1, 2, 2]},
    ]}, 320, 240)
    assert boxes == [{'label': 'obstacle', 'bbox_xyxy': [192.0, 91.2, 256.0, 124.8],
                      'source': 'qwen3_vl_review_candidate'}]
    assert len(rejected) == 2
    crowded, warnings = scaled_boxes({'boxes': [
        {'label': 'obstacle', 'bbox_xyxy': [100, 100, 200, 200]} for _ in range(6)
    ]}, 320, 240)
    assert crowded == [] and 'too many candidates' in warnings[0]


def test_second_vision_review_keeps_only_matching_class_and_location():
    first = [{'label': 'obstacle', 'bbox_xyxy': [20, 30, 50, 60]},
             {'label': 'robot', 'bbox_xyxy': [60, 30, 90, 60]}]
    second = [{'label': 'obstacle', 'bbox_xyxy': [22, 32, 51, 59]},
              {'label': 'obstacle', 'bbox_xyxy': [60, 30, 90, 60]}]
    assert confirmed(first, second) == first[:1]
