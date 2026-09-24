from types import SimpleNamespace

from control.sensing.v4l2_controls import freeze_v4l2_controls, v4l2_lock_summary


CV2 = SimpleNamespace(
    CAP_PROP_EXPOSURE=1,
    CAP_PROP_GAIN=2,
    CAP_PROP_WB_TEMPERATURE=3,
    CAP_PROP_AUTO_EXPOSURE=4,
    CAP_PROP_AUTO_WB=5,
)


class Capture:
    def __init__(self, *, reject=None):
        self.values = {1: -6.0, 2: 2.5, 3: 4200.0}
        self.reject = set(reject or ())
        self.sets = []

    def get(self, key):
        return self.values.get(key, -1.0)

    def set(self, key, value):
        self.sets.append((key, value))
        accepted = key not in self.reject
        if accepted:
            self.values[key] = value
        return accepted


def test_v4l2_freeze_disables_both_auto_loops_and_reapplies_settled_values():
    capture = Capture()

    controls = freeze_v4l2_controls(capture, CV2)

    assert controls == {"exposure": -6.0, "gain": 2.5, "white_balance": 4200.0}
    assert (CV2.CAP_PROP_AUTO_EXPOSURE, 0.25) in capture.sets
    assert (CV2.CAP_PROP_AUTO_WB, 0.0) in capture.sets
    assert (CV2.CAP_PROP_EXPOSURE, -6.0) in capture.sets
    assert v4l2_lock_summary(controls).startswith("v4l2 exposure=-6.000")


def test_v4l2_freeze_fails_closed_when_auto_white_balance_cannot_be_disabled():
    capture = Capture(reject={CV2.CAP_PROP_AUTO_WB})

    assert freeze_v4l2_controls(capture, CV2) is None
