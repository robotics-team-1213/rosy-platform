"""cell_reach: the hover's FK error is fed forward into the pick and the arm hovers again; a stuck arm is refused."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_reach as cr  # noqa: E402


class Arm:
    """Hovers 8 mm short in y of whatever pick it was last given (2026-10-29), or never moves when stuck."""

    def __init__(self, stuck=False):
        self.aim, self.sent, self.stuck = (-0.032, 0.172), [], stuck

    def act(self, command):
        self.sent.append(command)
        return {"ok": True, "state": [self.aim[0], self.aim[1] - 0.008] + [0] * 4}


def test_a_repeatable_short_hover_is_fed_forward_and_passes():
    arm = Arm()

    def replan(dx, dy):
        if not arm.stuck:
            arm.aim = (-0.032 + dx / 1000, 0.172 + dy / 1000)
        return "lib.json"

    out = cr.correct(arm, (-0.032, 0.172), replan, fk=lambda s: (s[0], s[1]))
    assert out["verdict"] == "pass" and abs(out["dy_mm"] - 8.0) < 0.2 and arm.sent.count("goto above_pick") == 1


def test_an_arm_that_does_not_follow_the_correction_is_refused():
    arm = Arm(stuck=True)
    out = cr.correct(arm, (-0.032, 0.172), lambda dx, dy: "lib.json", fk=lambda s: (s[0], s[1]))
    assert out["verdict"] == "refuse" and len(out["iterations"]) == 3


def test_chain_stops_at_the_first_refusal():
    calls = []
    ok = lambda: calls.append("reach") or {"verdict": "pass"}  # noqa: E731
    no = lambda: calls.append("wrist") or {"verdict": "refuse"}  # noqa: E731
    assert cr.chain(ok, no)()["verdict"] == "refuse" and calls == ["reach", "wrist"]
    assert cr.chain(None, None) is None
