"""A route names the side; it cannot admit a still-distant observed exit.

The mask is native re-inference of sim-100c962ec4-dbea6c's 45.125s PNG.
The gzip fixture preserves source PNG/model hashes and all inferred way pixels.
"""
import base64
import copy
import gzip
import json
from pathlib import Path
import zlib

import numpy as np

from control.sensing.perception.camera_ground import GroundPlane
from control.sensing.perception.drivable.drivable_steer import DrivableSteer, way_target


G = GroundPlane(.06343, .13962634015954636, 281.59681292203703, 160, 120, .6)
POSE = (0., 0., 0.)


def test_the_route_cannot_restore_the_recorded_far_exit_or_remember_it():
    doc = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures' /
        'drivable_far_exit_20261020.json.gz').read_bytes()))['mask']
    packed = zlib.decompress(base64.b64decode(doc['way_packbits_zlib_b64']))
    assert len(packed) == 9600
    way = np.unpackbits(np.frombuffer(packed, np.uint8)).reshape(240, 320).astype(bool)
    raw = way_target(way, G, .03317, .0925)
    assert raw['exit'] is None and raw['seen_exit'] == 'right'
    owner = DrivableSteer()
    _, _, info = owner.update(way, 1., G, .03317, .0925, POSE, POSE,
                             guide_here_deg=0., guide_deg=-50.)
    assert info['strategy'] == 'drivable_centre'
    assert owner._memory is None and owner._side is None


def raw():
    return dict(target_m=(.24, 0.), ahead_m=.2, exit='right', seen_exit='right', straddle=None,
        both=False, exit_point_m={'right': (.2, -.1)}, exit_reach_m={'right': .25},
        exit_near={'right': True}, near_centre_m=(.16, 0.), centre_path_m=[],
        edges_m=[], near_edges_m={})


def update(monkeypatch, owner, observation, key, current=POSE, source=POSE):
    import control.sensing.perception.drivable.drivable_steer as module
    monkeypatch.setattr(module, 'way_target', lambda *args: copy.deepcopy(observation))
    return owner.update(np.ones((240, 320), bool), key, G, .03317, .0925, source, current,
                        guide_here_deg=0., guide_deg=-50.)


def test_a_near_secondary_exit_can_be_selected_when_the_winning_exit_is_far(monkeypatch):
    observation = raw()
    observation.update(exit=None, seen_exit='left', exit_near={'left': False, 'right': True},
        exit_reach_m={'left': .5, 'right': .25}, exit_point_m={'left': (.4, .2), 'right': (.2, -.1)})
    owner = DrivableSteer()
    _, _, info = update(monkeypatch, owner, observation, 1.)
    assert info['strategy'] == 'drivable_turn_right'
    assert owner._memory == ('right', POSE)


def test_consuming_the_same_near_frame_keeps_the_memory_bound_to_its_source(monkeypatch):
    owner = DrivableSteer()
    update(monkeypatch, owner, raw(), 1.)
    update(monkeypatch, owner, raw(), 1., current=(.02, 0., 0.))
    assert owner._memory == ('right', POSE)


def test_an_admitted_near_exit_retains_its_existing_distance_bounded_memory(monkeypatch):
    owner = DrivableSteer()
    update(monkeypatch, owner, raw(), 1.)
    hidden = raw()
    hidden.update(exit=None, seen_exit=None, exit_near={}, exit_reach_m={}, exit_point_m={},
                  ahead_m=.1, target_m=None)
    _, _, info = update(monkeypatch, owner, hidden, 2., source=(.2, 0., 0.), current=(.2, 0., 0.))
    assert info.get('exit_from_memory') and owner._memory == ('right', POSE)
    update(monkeypatch, owner, hidden, 3., source=(.51, 0., 0.), current=(.51, 0., 0.))
    assert owner._memory is None


def test_a_near_selected_exit_cannot_override_a_side_wall_stop(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as module
    monkeypatch.setattr(module, 'way_target', lambda *args: raw())
    _, _, info = DrivableSteer().update(np.ones((240, 320), bool), 1., G, .03317, .0925,
        POSE, POSE, guide_here_deg=0., guide_deg=-50., side_clear_m={'right': .01})
    assert info['strategy'] == 'drivable_centre' and info['exit'] is None
