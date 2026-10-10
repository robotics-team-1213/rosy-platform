from rosy_situation.incident_context import ContextDraft


def test_context_draft_keeps_sources_and_missing_image_separate():
    snapshot = {"observed_at": 100.0,
                "line_stuck": {"pending": [{"robot_id": "pinky", "stuck_id": "s1", "cause": "lane_lost",
                                            "rear_state": "clear"}]},
                "state": {"robots": [{"robot_id": "pinky", "localization": {"trusted": True, "legacy": False},
                                      "state": {"pose": {"x": 1.0, "y": 2.0},
                                                "line_follow": {"mode": "CAMERA_LINE", "stuck": True}}}]},
                "incident_context": {"map": {"map_id": "site", "places": [{"id": "P1", "x": 1, "y": 2}]},
                                     "cameras": {"pinky": {"source_id": "rosy-cam", "seq": 7,
                                                           "captured_at": 99.9, "age_ms": 100, "stale": False}}}}
    drafts = ContextDraft()
    fact = drafts(snapshot)[0]
    assert fact["value"]["cause_draft"] == "line_marking"
    assert [item["source"] for item in fact["value"]["support"]] == [
        "core", "rosy_cam", "fleet_map", "core_sensor"]
    assert fact["value"]["missing"] == ["interpreted_front_image"]
    assert fact["evidence"]["camera_frame_interpreted"] is False
    assert drafts(snapshot) == []


def test_untrusted_or_missing_context_stays_uncertain():
    snapshot = {"observed_at": 100.0,
                "line_stuck": {"pending": [{"robot_id": "pinky", "stuck_id": "s2", "cause": "no_motion"}]},
                "state": {"robots": [{"robot_id": "pinky", "localization": {"trusted": False}, "state": {}}]}}
    fact = ContextDraft()(snapshot)[0]
    assert fact["value"]["cause_draft"] == "unknown"
    assert "fresh_rosy_cam_sighting" in fact["value"]["missing"]
    assert "trusted_map_pose_and_active_map" in fact["value"]["missing"]
    assert fact["confidence"] == 0.2
