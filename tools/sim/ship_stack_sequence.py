#!/usr/bin/env python3
"""Whole 3-layer stack on the MuJoCo ship-plate scene: the Isaac order (mapped_stack_fixture.plan, centre row then outer rows,
layer by layer), each container released by the floating jaw with a random placement error, earlier containers left in place.
Answers what single releases cannot: error that builds up over layers and releases that disturb boxes already placed.
Candidates for Isaac only (D-947 section 1); every number comes from the Isaac-side modules through ship_release_scene.

  python tools/sim/ship_stack_sequence.py run OUT.jsonl [--workers 12]
  python tools/sim/ship_stack_sequence.py table OUT.jsonl
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
import math
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ship_release_scene as scene  # noqa: E402

mujoco = scene.mujoco
NAMES = [f'c{i}' for i in range(9)]
SIGMA_MM = [0., .1, .2, .3, .4, .6]   # release position error, each axis (Isaac release feedback converges to ~0.05 mm)
SIGMA_YAW = [0., .25, .5]             # degrees
MU, GAP, ORDER = [.5, 1.], [.033, .0315], [(1, 0, 2), (0, 1, 2)]
SEEDS = range(12)
SEAT_MM, XY_MM, TILT_DEG, DISTURB_MM = .3, 1.5, .5, .3   # ship_release_scene.verdict and the Isaac judge


def targets(f, order):
    """Plan targets in release order for a row order; outer rows are packed against the measured centre box later."""
    old = f.get('row_order')
    f = dict(f, row_order=list(order))
    items = scene.fx.plan(True, fixture=f)
    f['row_order'] = old
    return [(it['cell'][1], it['cell'][2], it['target']) for it in items]


def tilt_deg(q):
    w, x, y, z = q
    return math.degrees(math.acos(max(-1., min(1., 1-2*(x*x+y*y)))))


def run(case):
    variant = case.get('variant', 'plain')
    model, f = scene.build(1, variant=variant, cargo=NAMES)
    nest = scene.variants.NEST_MM/1e3 if scene.variants.VARIANTS[variant].get('rail') else 0.
    data = mujoco.MjData(model)
    model.geom_friction[:, 0] = case['mu']
    rng = random.Random(case['seed'])
    for k, name in enumerate(NAMES):  # parked far away until their turn
        scene._set_free(model, data, name, [.6+.1*k, .6, .2])
    tcp = scene.jaw.description()['tcp']
    contact = scene.jaw.angle_for_gap(scene.jaw.GRASP_WIDTH_M)
    close, release = scene.jaw.finger_angles(case['open_gap_m'])['close'], scene.jaw.finger_angles(case['open_gap_m'])['release']
    clearance = case['clearance_mm']/1e3 if 'clearance_mm' in case else f['stack_release_clearance_m']
    row_clear = f['row_clearance_m']
    placed, worst_disturb, rows = [], 0., []

    def step(seconds):
        for _ in range(round(seconds/scene.DT)):
            mujoco.mj_step(model, data)

    for i, (row, layer, target) in enumerate(targets(f, case['order'])):
        target = list(target)
        target[2] -= layer*nest  # a rail tongue nests into the groove above: layers are 28 mm, not 30
        centre = next((scene._pose(data, NAMES[j])[0] for j, (r, l, _) in enumerate(targets(f, case['order'])[:i])
                       if l == layer and r == 1), None)
        if row != 1 and centre is not None:  # Isaac packed_release_position: beside the measured centre box
            direction = 1 if target[1] > centre[1] else -1
            edge = centre[1]+direction*(.015+.015+row_clear)
            target[1] = max(target[1], edge) if direction > 0 else min(target[1], edge)
        err = [rng.gauss(0, case['sigma_mm'])/1e3 for _ in range(2)]
        yaw = math.radians(rng.gauss(0, case['sigma_yaw']))
        before = [scene._pose(data, n)[0] for n in placed]

        def release_at(box, yaw):
            scene._set_free(model, data, NAMES[i], box, yaw)
            for k, sign in enumerate((1, -1)):
                data.qpos[model.joint(f'q{k}').qposadr[0]] = sign*contact
            data.mocap_pos[0], data.mocap_quat[0] = scene._jaw_pose(box, yaw, tcp)
            mujoco.mj_forward(model, data)
            for n in range(1, 201):
                data.ctrl[0] = contact+(close-contact)*n/200
                step(scene.DT)
            step(.25)
            q_hold = data.qpos[model.joint('q0').qposadr[0]]
            steps = round(scene.fx.grip_duration(q_hold, release, f['release_gripper_acceleration_rad_s2'])/scene.DT)
            for n in range(1, steps+1):
                data.ctrl[0] = q_hold+(release-q_hold)*(1-math.cos(math.pi*n/steps))/2
                step(scene.DT)
            step(scene.SETTLE_S)
            z0 = data.mocap_pos[0][2]
            for n in range(1, 101):
                data.mocap_pos[0][2] = z0+scene.LIFT_M*n/100
                step(.005)
            data.mocap_pos[0] = [1., 1., 1.]  # out of the way
            step(scene.SETTLE_S)

        release_at([target[0]+err[0], target[1]+err[1], target[2]+clearance], yaw)
        retried = 0
        # D-956 seat check and re-place: the regrasp is idealised (the box returns to the jaw where it lies, lifted), so this
        # measures what a second, corrected release buys, not the regrasp contact itself.
        while retried < case.get('retries', 0):
            pos, quat = data.body(NAMES[i]).xpos.copy(), data.body(NAMES[i]).xquat.copy()
            if (abs(1e3*(pos[2]-target[2])) <= SEAT_MM and tilt_deg(quat) <= TILT_DEG
                    and 1e3*math.dist(pos[:2], target[:2]) <= XY_MM):
                break
            retried += 1
            fix = [rng.gauss(0, case.get('retry_sigma_mm', .1))/1e3 for _ in range(2)]  # error after measuring the miss
            release_at([target[0]+fix[0], target[1]+fix[1], target[2]+clearance], 0.)
        disturb = max([1e3*math.dist(scene._pose(data, n)[0], b) for n, b in zip(placed, before)] or [0.])
        worst_disturb = max(worst_disturb, disturb)
        placed.append(NAMES[i])
        rows.append(dict(row=row, layer=layer, target=target, disturb_mm=round(disturb, 3), retried=retried))
    failures = []
    for i, r in enumerate(rows):
        pos = data.body(NAMES[i]).xpos
        dz, dxy = 1e3*(pos[2]-r['target'][2]), 1e3*math.dist(pos[:2], r['target'][:2])
        tilt = tilt_deg(data.body(NAMES[i]).xquat)
        r.update(z_mm=round(dz, 3), xy_mm=round(dxy, 3), tilt_deg=round(tilt, 3))
        if abs(dz) > SEAT_MM or tilt > TILT_DEG:
            failures.append(f'{i}:not-seated')
        elif dxy > XY_MM:
            failures.append(f'{i}:xy')
        if r['disturb_mm'] > DISTURB_MM:
            failures.append(f'{i}:disturbed-earlier')
    return dict(case, ok=not failures, failures=failures, worst_disturb_mm=round(worst_disturb, 3), boxes=rows)


FIX_VARIANTS, FIX_CLEARANCE_MM, FIX_SIGMA_MM = ['plain', 'c10', 'a10', 'r290', 'rail', 'c10rail'], [5., 2.], [.3, .4, .6, .8]


def cases(stage='base'):
    if stage == 'retry':  # seat check and re-place (D-956) on the two best set-ups of the fix stage
        for variant, retries, mu, sigma, seed in product(['plain', 'r290'], [0, 1, 2], MU, [.4, .6, .8], SEEDS):
            yield dict(order=(1, 0, 2), open_gap_m=.0315, mu=mu, sigma_mm=sigma, sigma_yaw=.25, seed=seed,
                       variant=variant, clearance_mm=2., retries=retries, retry_sigma_mm=.1)
        return
    if stage == 'fix':  # improvement candidates at the error levels the base sweep failed (2026-11-04)
        for variant, clear, mu, sigma, seed in product(FIX_VARIANTS, FIX_CLEARANCE_MM, MU, FIX_SIGMA_MM, SEEDS):
            yield dict(order=(1, 0, 2), open_gap_m=.0315, mu=mu, sigma_mm=sigma, sigma_yaw=.25, seed=seed,
                       variant=variant, clearance_mm=clear)
        return
    for order, gap, mu, sigma, yaw, seed in product(ORDER, GAP, MU, SIGMA_MM, SIGMA_YAW, SEEDS):
        yield dict(order=order, open_gap_m=gap, mu=mu, sigma_mm=sigma, sigma_yaw=yaw, seed=seed)


def table(path):
    rows = [json.loads(line) for line in open(path, encoding='utf-8')]
    groups = {}
    for r in rows:
        key = (tuple(r['order']), r['open_gap_m'], r['mu'], r['sigma_mm'], r['sigma_yaw'])
        groups.setdefault(key, []).append(r)
    print('order    gap_mm  mu   sigma_mm yaw_deg  ok/n   first-failing-box(layer)  worst_disturb_mm')
    for key, group in sorted(groups.items()):
        ok = sum(r['ok'] for r in group)
        firsts = [int(r['failures'][0].split(':')[0]) for r in group if r['failures']]
        layer = ' '.join(f"{i}({group[0]['boxes'][i]['layer']+1})" for i in sorted(set(firsts))[:4]) or '-'
        print(f"{''.join(map(str, key[0])):8} {key[1]*1e3:5.2f} {key[2]:4.1f} {key[3]:7.2f} {key[4]:7.2f}  "
              f"{ok:2d}/{len(group):2d}   {layer:25} {max(r['worst_disturb_mm'] for r in group):6.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('out', type=Path)
    r.add_argument('--workers', type=int, default=12)
    r.add_argument('--limit', type=int, default=None, help='first N cases only (smoke)')
    r.add_argument('--stage', choices=('base', 'fix', 'retry'), default='base')
    sub.add_parser('table').add_argument('out', type=Path)
    args = parser.parse_args()
    if args.cmd == 'table':
        return table(args.out)
    todo = list(cases(args.stage))[:args.limit]
    with args.out.open('x', encoding='utf-8') as out, ProcessPoolExecutor(args.workers) as pool:
        for row in pool.map(run, todo, chunksize=4):
            out.write(json.dumps(row)+'\n')
            out.flush()


if __name__ == '__main__':
    main()
