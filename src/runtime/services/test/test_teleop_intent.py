"""D-411 A: every teleop decision is evidence; evidence never refuses a command."""

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


def _rig(mode=Mode.MANUAL):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety)
    modes.transition(mode)
    seen = []
    command.intent_sink = lambda **fields: seen.append(fields)
    return command, seen


def test_accepted_teleop_records_raw_and_clipped():
    command, seen = _rig()
    assert command.teleop(0.5, 0.0) == (True, "")
    (intent,) = seen
    assert intent["raw_linear"] == 0.5 and intent["clipped"] == (0.15, 0.0)
    assert intent["accepted"] is True and intent["code"] == "" and intent["mode"] == "MANUAL"
    assert intent["source"] == "manual" and intent["t_mono_ns"] > 0


def test_rejected_teleop_records_the_code_without_clipped_values():
    command, seen = _rig(Mode.IDLE)
    assert command.teleop(0.1, 0.0) == (False, "MODE_CONFLICT")
    assert seen[0]["accepted"] is False and seen[0]["code"] == "MODE_CONFLICT"
    assert seen[0]["clipped"] is None and seen[0]["mode"] == "IDLE"


def test_a_failing_sink_never_refuses_the_command():
    command, _ = _rig()

    def boom(**_):
        raise RuntimeError("publisher gone")

    command.intent_sink = boom
    assert command.teleop(0.1, 0.0) == (True, "")
    assert command.intent_errors == 1
    assert command.select_output().linear > 0


def test_no_sink_is_inert():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety)
    modes.transition(Mode.MANUAL)
    assert command.teleop(0.1, 0.0) == (True, "")


def test_note_intent_covers_rejections_before_the_manager():
    command, seen = _rig()
    command.note_intent(0.2, 0.0, "manual", False, "CAPABILITY_WITHHELD")
    assert seen[0]["code"] == "CAPABILITY_WITHHELD" and seen[0]["clipped"] is None
