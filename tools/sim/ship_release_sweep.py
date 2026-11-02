#!/usr/bin/env python3
"""Off-centre release sweep on the MuJoCo ship-plate scene (ship_release_scene). Writes one JSON line per case.

  python tools/sim/ship_release_sweep.py run OUT.jsonl [--workers 12]
  python tools/sim/ship_release_sweep.py table OUT.jsonl

away = the offset moves the box from the neighbour (row * dy > 0); toward moves it into the neighbour's lane.
"""
import argparse
from itertools import product
import json
from multiprocessing import Pool
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ship_release_scene as scene  # noqa: E402

DY = [round(.25*k, 2) for k in range(-6, 7)]  # across the channel, mm
YAW, HEIGHT, MU, GAP = [0, .25, .5, 1, 2, 3], [3, 5, 8], [.5, 1., 1.2], [.033, .040]


def cases():
    for layer, row, gap, mu, h, yaw, dy in product((1, 2), (1, -1), GAP, MU, HEIGHT, YAW, DY):
        yield dict(layer=layer, row=row, open_gap_m=gap, mu=mu, height_m=h/1e3, yaw_deg=yaw, dy=dy/1e3, dx=0.)
    for layer, row, gap, h, yaw, dx, dy in product((1, 2), (1, -1), GAP, (4, 5, 6), (0, 1, 3), (0, .5, 1, 1.5), (0, .5, -.5, 1, -1)):
        yield dict(layer=layer, row=row, open_gap_m=gap, mu=1., height_m=h/1e3, yaw_deg=yaw, dy=dy/1e3, dx=dx/1e3)  # along-offset stage


_models = {}


def one(case):
    layer = case['layer']
    if layer not in _models:
        _models[layer] = scene.build(layer)
    model, fixture = _models[layer]
    out = {k: float(v) for k, v in scene.run(model, fixture, **case).items()}
    return dict(case, **out, fail=scene.verdict(out, layer))


def table(path):
    rows = [json.loads(line) for line in open(path)]
    groups = {}
    for r in rows:
        if r['dx'] == 0 and round(r['height_m']*1e3) in (3, 5, 8):  # the main grid; the along-offset stage has coarse dy
            key = (r['layer'], round(r['open_gap_m']*1e3), r['mu'], round(r['height_m']*1e3), r['yaw_deg'])
            groups.setdefault(key, []).append(r)
    print('layer gap mu h yaw | max pass offset mm away / toward neighbour (first fail reason)')
    for key in sorted(groups):
        side = {}
        for sign, name in ((1, 'away'), (-1, 'toward')):
            ok, why = 0., ''
            for r in sorted((r for r in groups[key] if r['dy']*r['row']*sign >= 0), key=lambda r: abs(r['dy'])):
                bad = [x for x in groups[key] if abs(x['dy']) == abs(r['dy']) and x['dy']*x['row']*sign >= 0 and x['fail']]
                if bad:
                    why = ','.join(sorted({f for x in bad for f in x['fail']}))
                    break
                ok = abs(r['dy'])*1e3
            side[name] = f'{ok:.2f}' + (f' ({why})' if why else '')
        print(*key, '|', side['away'], '/', side['toward'])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['run', 'table'])
    parser.add_argument('out', type=Path)
    parser.add_argument('--workers', type=int, default=12)
    args = parser.parse_args()
    if args.command == 'table':
        return table(args.out)
    todo = list(cases())
    with Pool(args.workers) as pool, open(args.out, 'w') as f:
        for i, row in enumerate(pool.imap(one, todo, chunksize=8)):
            f.write(json.dumps(row)+'\n')
            if i % 500 == 0:
                print(i, '/', len(todo), flush=True)


if __name__ == '__main__':
    main()
