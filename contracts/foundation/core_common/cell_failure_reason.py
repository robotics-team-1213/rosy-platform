"""Failure codes that the cell worker and Fleet can publish in a cell plan."""

HARDWARE_REFUSALS = frozenset({
    "SITE_NOT_CALIBRATED", "SITE_NOT_MEASURED", "STAND_NOT_CALIBRATED", "STAND_REQUIRES_ARM_A", "SITE_ARM_NOT_ALLOWED",
    "UNCALIBRATED_DISPLACED_SITE", "ROUTE_DEPTH_INPUTS_MISSING", "CELL_CONFIG_OR_WRAPPER_MISSING",
    "ZONE_FIX_REQUESTED", "SUBPROCESS_TIMEOUT", "FOLD_READBACK_MISSING",
})
RECEIPT_REFUSALS = HARDWARE_REFUSALS | {
    "REVIEW_REQUIRED", "UNKNOWN_SITE", "HANDOFF_TASK_MISMATCH", "AMR_NOT_LOCKED_AT_HANDOFF",
    "HUMAN_HOLD_OR_SAFETY_FEED_LOST", "SAFETY_WATCHDOG_UNRESPONSIVE",
}


def hardware_abort_reason(telemetry):
    if telemetry.get("review_required"):
        return "REVIEW_REQUIRED"
    error = telemetry.get("error")
    return error if isinstance(error, str) and error in HARDWARE_REFUSALS else "MEASURED_PLACEMENT_MISSING"


def persisted_abort_reason(task):
    if task.get("status") != "ABORTED":
        return None
    receipt = task.get("receipt")
    reason = receipt.get("reason") if isinstance(receipt, dict) else None
    if isinstance(reason, str) and reason in RECEIPT_REFUSALS:
        return reason
    # Older workers put the typed calibration error only in hardware telemetry.
    telemetry = task.get("hardware_telemetry")
    return hardware_abort_reason(telemetry if isinstance(telemetry, dict) else {})
