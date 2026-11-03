#!/usr/bin/env python3
"""The Isaac 3-layer stack order as real-cell sites for one arm (plan B, D-969 step 6): offline, no motion.

Each stack cell and the arm's own leveling spot become a `config.sites` entry in that arm's frame (the transform
isaac_stack_plan uses), and the order becomes `cell_auto_pick.py --from ... --dest ...` commands. Heights are not guessed:
the plate-top and table-top heights in the arm frame are measured values (touch, cell_surface.py) passed in; layers stack
in container heights from there. Every site and command is a new D-911 scope: commissioning, one stage, person at switch.

  python tools/sim/ship_stack_sites.py --arm arm_b --plate-surface-z Z --table-surface-z Z [--case CASE] [--config CFG]
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'learning/envs/isaac'))
import mapped_stack_fixture as fx  # noqa: E402

ARMS = {'arm_a': 0, 'arm_b': 1}  # fixture arm index (D-969: arm_a is arm 0, y -)
CASE = 'nominal-palletizing-v21-ship-surveyed-bases'
BOX_H = .03


def to_arm(point, base, yaw):
    """World (fixture) x, y -> the arm's planning frame, as isaac_stack_plan.solve does."""
    dx, dy, c, s = point[0]-base[0], point[1]-base[1], math.cos(yaw), math.sin(yaw)
    return [round(c*dx+s*dy, 4), round(-s*dx+c*dy, 4)]


def layout_heights(arm):
    """Plate top and leveling-spot table top in the arm frame (m) from the measured layout in cell_model_inventory.yaml."""
    import yaml
    h = yaml.safe_load((Path(fx.__file__).with_name('cell_model_inventory.yaml')).read_text(encoding='utf-8'))['layout']['heights_mm']
    base = h[f'{arm}_base_plate']['value']  # arm frame z 0 = the base plate top (arm_b measured; arm_a not yet)
    return (h['ship_plate_top']['value']-base)/1000, (h['leveling_spot_table']['value']-base)/1000


def wrap180(deg):
    return (deg+180) % 360-180


def sites(arm, plate_z, table_z, case=CASE):
    f = fx.container_fixture(layers=3, case=case)
    k = ARMS[arm]
    base, yaw = f['arm_bases_m'][k], f['arm_base_yaws_rad'][k]
    out, order = {}, []
    level = fx.leveling_center(f, k)
    out[f'level-{arm}'] = dict(place=to_arm(level, base, yaw), surface_z=table_z,
                               yaw_deg=round(wrap180(math.degrees(f['leveling_yaws_rad'][k]-yaw)), 1),
                               source='isaac leveling spot', scope='SIM_PLAN_NOT_REVIEWED_D911')
    for i, item in enumerate(fx.plan(True, fixture=f)):
        row, layer = item['cell'][1], item['cell'][2]
        name = f'stack-r{row}-l{layer}'
        if item['arm'] != k:
            order.append(dict(item=i, site=name, arm='arm_a' if item['arm'] == 0 else 'arm_b', other_arm=True))
            continue
        out[name] = dict(place=to_arm(item['target'], base, yaw), surface_z=round(plate_z+layer*BOX_H, 4),
                         yaw_deg=round(wrap180(-math.degrees(yaw)), 1), source=f'isaac plan item {i}',
                         scope='SIM_PLAN_NOT_REVIEWED_D911')
        order.append(dict(item=i, site=name, arm=arm, steps=[['beltend', f'level-{arm}'], [f'level-{arm}', name]]))
    return out, order


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--arm', choices=sorted(ARMS), required=True)
    p.add_argument('--plate-surface-z', type=float, help='ship plate top in the arm frame (default: the inventory layout)')
    p.add_argument('--table-surface-z', type=float, help='table top at the leveling spot in the arm frame (default: layout)')
    p.add_argument('--case', default=CASE)
    p.add_argument('--config', default='<cell-config.json>')
    a = p.parse_args(argv)
    plate_z, table_z = layout_heights(a.arm)
    found, order = sites(a.arm, plate_z if a.plate_surface_z is None else a.plate_surface_z,
                         table_z if a.table_surface_z is None else a.table_surface_z, a.case)
    for step in order:
        step['commands'] = [f'cell_auto_pick.py --config {a.config} --from {s} --dest {d}' for s, d in step.get('steps', [])]
    print(json.dumps(dict(case=a.case, arm=a.arm, sites=found, order=order,
                          note='each command is one supervised D-911 stage; the other arm\'s items wait'), indent=1))


if __name__ == '__main__':
    main()
