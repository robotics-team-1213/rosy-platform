"""Physical workflow journal vocabulary; completion never means a Fleet business goal."""
_PICK_PLACE_PHASES = ("approach", "grasp", "transfer", "release")
_WORKFLOW_STATES = frozenset({"APPROACH", "GRASP", "VERIFY_HOLD", "TRANSFER", "RELEASE",
                              "VERIFY_RELEASE", "ACTION_SUCCEEDED", "HOLD"})
_WORKFLOW_EVIDENCE_KEYS = frozenset({
    "phase_result_id", "gripper_hold_sequence", "gripper_release_sequence", "hold_reason"})
_COMPLETION_BY_KIND = {"PICK_PLACE": ("pick-place-workflow", "PICK_PLACE_ACTION_COMPLETED"),
                       "CELL_TRANSFER": ("cell-transfer-workflow", "CELL_TRANSFER_ACTION_COMPLETED"),
                       "ARM_TRANSFER": ("arm-transfer-workflow", "ARM_TRANSFER_ACTION_COMPLETED")}
