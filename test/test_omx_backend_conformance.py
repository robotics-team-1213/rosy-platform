"""D-866 §2 backend conformance judge (tools/sim/omx_backend_conformance.py), ROS-free part."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sim" / "omx_backend_conformance.py"


def _mod():
    spec = importlib.util.spec_from_file_location("omx_backend_conformance", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _samples(mod, **changes):
    names = list(mod.JOINTS)
    frames = [(n*200_000_000, 'rgb8', 240, 320) for n in range(20)]
    samples = dict(joint_states=[(n*10_000_000, names, [0.0]*6) for n in range(200)],
                   cameras={name: list(frames) for name in mod.CAMERAS},
                   clock=[n*1_000_000 for n in range(100)],
                   stop=dict(accepted=True, cancel_acknowledged=True, travel_before_rad=0.05, travel_after_rad=0.001))
    samples.update(changes)
    return samples


def test_conforming_backend_has_no_failures():
    mod = _mod()
    assert mod.check(_samples(mod), shape=(240, 320), camera_hz=4.5) == []


def test_each_contract_breach_is_reported():
    mod = _mod()
    names = list(mod.JOINTS)
    cases = {
        'names': dict(joint_states=[(n*10_000_000, names[:-1], [0.0]*5) for n in range(200)]),
        'order': dict(joint_states=[(n*10_000_000, names if n % 2 else names[::-1], [0.0]*6) for n in range(200)]),
        'stamps': dict(joint_states=[(10_000_000*(n % 50), names, [0.0]*6) for n in range(200)]),
        'joint rate': dict(joint_states=[(n*100_000_000, names, [0.0]*6) for n in range(20)]),
        'camera size': dict(cameras={name: [(n*200_000_000, 'rgb8', 480, 640) for n in range(20)] for name in mod.CAMERAS}),
        'camera missing': dict(cameras={'front': [(n*200_000_000, 'rgb8', 240, 320) for n in range(20)]}),
        'camera rate': dict(cameras={name: [(n*1_000_000_000, 'rgb8', 240, 320) for n in range(5)] for name in mod.CAMERAS}),
        'clock': dict(clock=[5, 4, 6]),
        'cancel': dict(stop=dict(accepted=True, cancel_acknowledged=False)),
        'moving after stop': dict(stop=dict(accepted=True, cancel_acknowledged=True, travel_before_rad=0.05,
                                             travel_after_rad=0.05)),
        'goal ignored': dict(stop=dict(accepted=True, cancel_acknowledged=True, travel_before_rad=0.0,
                                       travel_after_rad=0.0)),
        'object drift': dict(objects={'infeed_block': [(0.0, 0.17, 0.015), (0.0, 0.17, 0.0)]}),
    }
    for label, change in cases.items():
        assert mod.check(_samples(mod, **change), shape=(240, 320), camera_hz=4.5), label


def test_still_objects_and_a_backend_without_object_facts_conform():
    mod = _mod()
    still = {'infeed_block': [(0.0, 0.17, 0.015), (0.0, 0.1702, 0.0151)]}
    assert mod.check(_samples(mod, objects=still), shape=(240, 320), camera_hz=4.5) == []
    assert mod.check(_samples(mod, objects={}), shape=(240, 320), camera_hz=4.5) == []
