"""Scale._scale_update publishes on real values (D-171 track 1).

The pure corridor helpers were already covered by test_scale.py; the mixin
that publishes the HUD/narrow values had no host test because it imported
std_msgs. The node's publish_float is recorded instead.
"""
from types import SimpleNamespace

import pytest

from control.safety import scale
from control.safety.scale import Scale


class FakeSafety(Scale):
    def __init__(self, auto_map=True, radius=.076):
        self.params = {'auto_map': auto_map, 'map_range_min': .18, 'map_range_max': .40}
        self.map_range, self.open_max = .30, .40
        self.robot_r = radius
        self.profile = SimpleNamespace(turn_clear=.14)
        self._corr_buf, self._corr_generation = [], None
        self.generation = 0
        self.observations = SimpleNamespace(generation=lambda name: self.generation)
        self.map_pub, self.open_max_pub, self.corr_pub, self.narrow_pub = 'map', 'open_max', 'corridor', 'narrow'
        self.sent = []

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def get_logger(self):
        return SimpleNamespace(info=lambda message: None)

    def publish_float(self, publisher, value):
        self.sent.append((publisher, value))


def test_module_is_ros_free():
    assert 'Float32' not in scale.__dict__


def test_manual_map_publishes_fixed_values_and_unknown_corridor():
    node = FakeSafety(auto_map=False)
    node._scale_update(.13, .16)
    assert node.sent == [('map', .30), ('open_max', .40), ('corridor', -1.0), ('narrow', -1.0)]


@pytest.mark.parametrize('left, right, narrow', [
    (2.0, 2.5, -1.0),              # finite far walls: known open
    (float('inf'), 2.5, 0.0),      # a missing wall is unknown, never fast
    (.10, 2.5, 0.0),               # one wall inside turn clearance
])
def test_no_maze_corridor_reports_open_or_unknown(left, right, narrow):
    node = FakeSafety()
    node._corr_buf.append(.3)
    node._scale_update(left, right)
    assert node.sent == [('map', .30), ('open_max', .40), ('narrow', narrow)]
    assert node._corr_buf == []


def test_corridor_needs_eight_fresh_lidar_generations():
    node = FakeSafety()
    for generation in range(7):
        node.generation = generation
        node._scale_update(.13, .16)
    node._scale_update(.13, .16)                              # same generation: not re-sampled
    assert len(node._corr_buf) == 7
    assert set(node.sent) == {('narrow', 0.0)}


def test_measured_corridor_sets_map_open_and_machine_clearance():
    node = FakeSafety()
    for generation in range(8):
        node.generation = generation
        node._scale_update(.13, .16)
    corridor = pytest.approx(.29)
    assert node.sent[-4:] == [('corridor', corridor), ('narrow', pytest.approx(.29 - 2 * .076)),
                              ('map', pytest.approx(.3915)), ('open_max', pytest.approx(.4495))]
    assert node.map_range == pytest.approx(.3915) and node.open_max == pytest.approx(.4495)
