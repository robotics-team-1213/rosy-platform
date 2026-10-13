"""D-430 §3 invariants 3b and 4: behavioural safety checks on the ROS-free CORE path.

Behavioural tests: they drive ``CommandManager.select_output`` (the value
``cmd_vel_cycle`` hands the single writer) and ``PersonAdvisoryFeed``. The
structural side lives in ``test/architecture/test_safety_separation.py``.
A host pytest pass is not device or field acceptance.
"""

import pytest

from core_common.protocol.detections import Detection
from core_features.command.arbitration import DEFAULT_SOURCES, Mode, ModeMachine, SourceRegistry
from core_features.command.manager import ZERO, CommandManager, Twist
from core_features.safety.manager import BatteryPolicy, PersonAdvisoryFeed, SafetyManager, SpeedLimits

NOW = 10.0
FAST = Twist(5.0, 5.0)  # far above every limit, so clip is visible

#: One case per output slot: teleop (MANUAL), the nav slot, the docking slot.
#: ``fleet`` and ``swarm`` goals reach the wheels only through ``set_nav_twist``,
#: the same code as ``navigation``, so they share its case; give them their own
#: when source-specific output code appears.
SOURCE_MODES = {
    "manual": Mode.MANUAL,
    "navigation": Mode.NAVIGATION,
    "docking": Mode.DOCKING,
}
NAV_SLOT_SOURCES = {"fleet", "swarm"}


def _rig(mode):
    registry = SourceRegistry()
    registry.set_enabled("docking", True)
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(registry, modes, safety)
    assert modes.transition(mode)[0]
    return command, safety, modes


def _feed(command, source, twist, now=NOW):
    """Offer ``twist`` from ``source``; returns whether the input was taken."""
    if source == "manual":
        return command.teleop(twist.linear, twist.angular)[0]
    if source == "docking":
        command.set_docking_twist(twist, now=now)
    else:
        command.set_nav_twist(twist, now=now)
    return True


def test_every_registered_source_is_covered():
    assert set(SOURCE_MODES) | NAV_SLOT_SOURCES == set(DEFAULT_SOURCES)


def _stop(safety, modes, how):
    if how in ("api", "latch"):
        safety.trigger_estop("test")  # SAF-001 latch; the API latches first
    if how in ("api", "mode"):
        assert modes.transition(Mode.EMERGENCY)[0]


def _release(safety, modes, how, mode):
    if how in ("api", "mode"):
        assert modes.release_emergency()[0]
        assert modes.transition(mode)[0]
    if how in ("api", "latch"):
        assert safety.release("admin")


@pytest.mark.parametrize("source", sorted(SOURCE_MODES))
@pytest.mark.parametrize("how", ["api", "latch", "mode"])
def test_estop_zeroes_every_source_and_clip_applies(source, how):
    """Behavioural. D-430 §3 invariant 3b: without a stop the output is the clipped
    command. With the E-stop latch, EMERGENCY mode, or both (the API path) every
    source yields zero and new input stays zero. After a latched stop, release
    alone does not resume the held command; only a fresh command moves.

    Known gap: this proves the output is zero, not which layer zeroed it. The stop
    check in ``select_output``, the E-stop listener, the input setters and the
    EMERGENCY ``else: return ZERO`` overlap, so removing one alone stays green."""
    mode = SOURCE_MODES[source]
    command, safety, modes = _rig(mode)
    manual = source == "manual"
    limit_l = safety.limits.manual_linear if manual else safety.limits.max_linear
    limit_a = safety.limits.manual_angular if manual else safety.limits.max_angular

    assert _feed(command, source, FAST)
    moving = command.select_output(now=NOW)
    assert (moving.linear, moving.angular) == pytest.approx((limit_l, limit_a))

    _stop(safety, modes, how)
    assert command.select_output(now=NOW) == ZERO
    if how != "mode":
        _release(safety, modes, how, mode)
        assert command.select_output(now=NOW) == ZERO, "release must not resume the held command"
        _stop(safety, modes, how)
    _feed(command, source, FAST)
    assert command.select_output(now=NOW) == ZERO

    _release(safety, modes, how, mode)
    assert _feed(command, source, FAST)
    moving = command.select_output(now=NOW)
    assert (moving.linear, moving.angular) == pytest.approx((limit_l, limit_a))


def _packet(observed_at=1000.0, confidence=0.8, detections=None):
    return {
        "model_revision": "yolo11n-r1", "observed_at": observed_at,
        "seq": 41, "input_width": 640, "input_height": 640,
        "input_fps": 10.0, "inference_ms": 12.0,
        "detections": [Detection(label="person", x=0.4, y=0.3, w=0.2, h=0.4, confidence=confidence)]
        if detections is None else detections,
    }


def test_person_feet_does_not_tighten_limits():
    """D-602: a person_feet box is not a person advisory."""
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    feed = PersonAdvisoryFeed(safety, clock=lambda: 1000.1, seat_clock=lambda: NOW)
    profile = safety.clip(5.0, 5.0, now=NOW)
    feet = _packet(detections=[Detection(label="person_feet", x=0.4, y=0.3, w=0.2, h=0.4, confidence=0.9)])
    assert feed.ingest(feet)["advisory"] is False
    assert safety.clip(5.0, 5.0, now=NOW) == pytest.approx(profile)


def test_learned_inputs_only_tighten_limits():
    """Behavioural. D-430 §3 invariant 4 / §4 perception rule: a learned person
    advisory can only lower the cap below the default profile; stale, invalid or
    absent advisories return exactly to the profile; no advisory raises a limit or
    releases a latched stop."""
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    feed = PersonAdvisoryFeed(safety, clock=lambda: 1000.1, seat_clock=lambda: NOW)
    profile = safety.clip(5.0, 5.0, now=NOW)
    assert profile == pytest.approx((safety.limits.max_linear, safety.limits.max_angular))

    assert feed.ingest(_packet())["advisory"] is True
    tightened = safety.clip(5.0, 5.0, now=NOW)
    assert tightened[0] < profile[0] and tightened[1] <= profile[1]

    for lost in (_packet(observed_at=999.0), _packet(detections=[]), _packet(confidence=0.1),
                 "not a packet", {**_packet(), "seq": "x"}):
        feed.ingest(_packet())
        assert feed.ingest(lost)["advisory"] is False
        assert safety.clip(5.0, 5.0, now=NOW) == pytest.approx(profile)

    for packet in (_packet(confidence=1.0), _packet(confidence=0.5), _packet(observed_at=1000.1)):
        feed.ingest(packet)
        clipped = safety.clip(5.0, 5.0, now=NOW)
        assert clipped[0] <= profile[0] and clipped[1] <= profile[1]

    safety.trigger_estop("test")
    for packet in (_packet(), _packet(detections=[]), "not a packet"):
        feed.ingest(packet)
        assert safety.estop is True
