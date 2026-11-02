"""Guarded descent: stops when the held box stops following the TCP, lifts one step, and reports when nothing was met."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guarded_release as g

SPEC = dict(step_m=.0005, limit_m=.008, stall_m=.0002)


def fake(floor_z):
    state = dict(tcp=.02, box=.02)  # box follows the TCP until its bottom reaches the floor

    def move(point):
        state['tcp'] = point[2]
        state['box'] = max(point[2], floor_z)
    return state, move, lambda: state['box']


def test_stops_on_the_floor_and_relieves_one_step():
    state, move, box_z = fake(.0165)
    command, log = g.descend(move, box_z, [0., 0., .02], SPEC)
    assert log['contact'] and abs(command[2]-.0165) < 1e-9  # pressed one step past the floor, then lifted it again
    assert state['box'] == .0165 and len(log['steps']) == 8


def test_reports_no_contact_within_the_limit():
    _, move, box_z = fake(-1.)
    command, log = g.descend(move, box_z, [0., 0., .02], SPEC)
    assert not log['contact'] and len(log['steps']) == 16 and abs(command[2]-.012) < 1e-9
