from fleet.pipeline.omx_cell_policy import evaluate_omx_cell_station, resolve_omx_cells


def test_resolve_omx_workcell_stations():
    cells = resolve_omx_cells()
    assert (cells["cell_s"].station_place, cells["cell_s"].arm_roles, cells["cell_s"].handoff_yaw_deg) == (
        "S3", ("arm_s",), -85.0
    )
    assert (cells["cell_ab"].station_place, cells["cell_ab"].arm_roles,
            cells["cell_ab"].handoff_yaw_deg, cells["cell_ab"].max_tier) == (
        "S5", ("arm_a", "arm_b"), -90.0, 3
    )


def test_docked_pinky_cell_phase_controls_stage_and_motion_interlock():
    station = resolve_omx_cells()["cell_s"]
    robot = {"robot_id": "rosy_01", "robot_kind": "pinky",
             "pose": {"x": 0.68, "y": -0.2528, "yaw": 0.0},
             "v_cmd_mps": 0.0, "wheel_brake_locked": True, "bed_ready": True}
    claimed = evaluate_omx_cell_station(station, docked_robot=robot,
                                        cell_state={"phase": "CLAIMED"})
    in_zone = evaluate_omx_cell_station(station, docked_robot=robot,
                                        cell_state={"phase": "ARM_IN_BED_ZONE"})
    released = evaluate_omx_cell_station(station, docked_robot=robot,
                                         cell_state={"phase": "RELEASED"})
    assert claimed["stage_directive"]["schema"] == "rosy.omx-cell-area-xyz-directive.v1"
    assert in_zone["receipt"]["amr_motion_inhibited"] is True
    assert released["receipt"]["amr_motion_inhibited"] is False
    assert released["stage_directive"] is None
