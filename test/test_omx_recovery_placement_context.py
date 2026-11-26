from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from cell_recovery_placement_context import bind_incident, load_context, remember_cargo


def test_cargo_requires_matching_session_arm_and_fleet_receipt(tmp_path):
    cargo = {"item": "measured-box", "destination": "board"}
    remember_cargo(tmp_path, "arm_s", "session-1", cargo)
    bind_incident(tmp_path, "arm_s", "session-2", "incident")
    bind_incident(tmp_path, "arm_b", "session-1", "incident")
    assert load_context(tmp_path, "arm_s", "incident") is None
    bind_incident(tmp_path, "arm_s", "session-1", "incident")
    first = load_context(tmp_path, "arm_s", "incident")
    assert first["cargo"] == cargo and first["stopped_at"] > 0
    remember_cargo(tmp_path, "arm_s", "session-1", {"item": "changed"})
    bind_incident(tmp_path, "arm_s", "session-1", "incident")
    assert load_context(tmp_path, "arm_s", "incident") == first
    assert load_context(tmp_path, "arm_b", "incident") is None
