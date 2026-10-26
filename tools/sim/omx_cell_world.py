"""D-877: the OMX cell's boxes from the Gazebo world, so every simulator backend builds the same work scene.

omx_cell_workcell.sdf is the one source (table, pallets, sheet stand, slip sheet, infeed block). Gazebo loads it
directly; the MuJoCo and Isaac adapters call boxes() and add the same boxes. ROS-free and stdlib only, because the
Isaac adapter runs on the Isaac SDK's own Python.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

WORLD = Path(__file__).resolve().parents[2]/'integrations/simulation/gazebo/worlds/omx_cell_workcell.sdf'


def _floats(text, count):
    values = [float(v) for v in (text or '').split()]
    if len(values) != count:
        raise ValueError(f'expected {count} numbers, got {text!r}')
    return values


def boxes(path=WORLD):
    """[{name, pos, rpy, size, static, mass, friction}] for every model whose only collision is one box."""
    out = []
    for model in ET.parse(path).getroot().iter('model'):
        collisions = list(model.iter('collision'))
        shapes = [shape for c in collisions for shape in c.find('geometry')]
        if len(collisions) != 1 or [s.tag for s in shapes] != ['box']:
            continue  # Ground plane, cameras and anything not a single box are not part of the work scene.
        pose = _floats(model.findtext('pose') or '0 0 0 0 0 0', 6)
        static = (model.findtext('static') or 'false').strip() == 'true'
        mass = model.findtext('.//inertial/mass')
        mu = model.findtext('.//friction/ode/mu')
        if not static and mass is None:
            raise ValueError(f"movable box {model.get('name')} has no mass")
        out.append(dict(name=model.get('name'), pos=pose[:3], rpy=pose[3:], size=_floats(shapes[0].findtext('size'), 3),
                        static=static, mass=None if static else float(mass), friction=float(mu) if mu else 1.0))
    if not out:
        raise ValueError(f'no box models in {path}')
    return out


def quaternion(rpy):
    """SDF roll-pitch-yaw (fixed X, Y, Z) as a w-x-y-z quaternion."""
    from math import cos, sin
    (cr, sr), (cp, sp), (cy, sy) = ((cos(a/2), sin(a/2)) for a in rpy)
    return [cr*cp*cy+sr*sp*sy, sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy]
