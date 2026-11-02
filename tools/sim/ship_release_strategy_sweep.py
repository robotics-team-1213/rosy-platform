#!/usr/bin/env python3
"""Release strategy x container variant sweep on the MuJoCo ship-plate scene (candidates for Isaac only, D-947).

  python tools/sim/ship_release_strategy_sweep.py run OUT.jsonl [--stage main|clearance] [--workers 14]
  python tools/sim/ship_release_strategy_sweep.py table OUT.jsonl [--clearance 0.41]

Strategies are ship_release_strategies (drop, guarded, search) x release opening (33, 31.5 mm); variants are
ship_container_variants. Offsets are across the channel in mm, both signs, relative to the channel centre.
"""
import argparse
from itertools import product
import json
from multiprocessing import Pool
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ship_container_variants as variants  # noqa: E402
import ship_release_scene as scene  # noqa: E402
import ship_release_strategies as strategies  # noqa: E402

VARIANT_NAMES = ['plain', 'c05', 'c10', 'c15', 'a10', 'r294', 'r290', 'rail', 'c10rail']
STRATEGIES = [('drop', .033), ('drop', .0315), ('guarded', .033), ('guarded', .0315), ('search', .033), ('search', .0315)]
CAD_CLEARANCE_MM = .41  # KAN-108 drawing; the CAD dots (5.2 mm at pitch 36) give 0.40
DY1 = [0, .2, .3, .4, .5, .6, .8, 1., 1.5]
DY_CLEARANCE = [0, .25, .5, .75, 1., 1.25, 1.5, 1.75, 2.]


def signed(values):
    return sorted({v for d in values for v in (d, -d)})


def cases(stage):
    if stage == 'main':
        for (strategy, gap), variant, (layer, yaws, mus, dys) in product(STRATEGIES, VARIANT_NAMES, (
                (1, (0, 3), (.5, 1.), signed(DY1)), (2, (0,), (1.,), signed([0, 1., 1.5])))):
            for yaw, mu, dy in product(yaws, mus, dys):
                yield dict(layer=layer, variant=variant, strategy=strategy, gap=gap, yaw_deg=yaw, mu=mu, dy=dy/1e3, clearance_mm=None)
    else:  # clearance sensitivity: layer 1 only, the dot diameter is changed so the clearance per side is 0.2 / 0.5 / 1.0 mm
        for (strategy, gap), variant, clearance, yaw, mu, dy in product(
                [s for s in STRATEGIES if s[1] == .0315], VARIANT_NAMES, (.2, .5, 1.), (0,), (1.,), signed(DY_CLEARANCE)):
            yield dict(layer=1, variant=variant, strategy=strategy, gap=gap, yaw_deg=yaw, mu=mu, dy=dy/1e3, clearance_mm=clearance)


_models = {}


def one(case):
    key = (case['layer'], case['variant'], case['clearance_mm'])
    if key not in _models:
        _models[key] = scene.build(case['layer'], case['variant'], clearance_mm=case['clearance_mm'], weld=True)
    model, fixture = _models[key]
    kw = {k: v for k, v in case.items() if k not in ('clearance_mm',)}
    out = strategies.attempt(model, fixture, **kw)
    return dict(case, **{k: (None if v is None else float(v)) for k, v in out.items()})


def band(rows):
    """Largest |dy| (mm) such that every case with |dy| up to it, both signs, seated on the first try (grid contiguity)."""
    ok = 0.
    for d in sorted({abs(r['dy']) for r in rows}):
        if not all(r['seated'] for r in rows if abs(r['dy']) == d):
            break
        ok = d*1e3
    return ok


def table(path, clearance=None):
    rows = [json.loads(line) for line in open(path)]
    rows = [r for r in rows if r.get('clearance_mm') == clearance]
    groups = {}
    for r in rows:
        groups.setdefault((r['layer'], r['strategy'], round(r['gap']*1e3, 2), r['variant']), []).append(r)
    print('layer strategy opening variant | seat rate first try / with one re-place | band mm: mu 1 yaw 0 / mu 0.5 yaw 0 / mu 1 yaw 3 deg')
    for key in sorted(groups):
        g = groups[key]
        first = sum(r['seated'] for r in g)/len(g)
        failed = [r for r in g if not r['seated']]
        again = first+sum((r['recovered'] or 0.) for r in failed)/len(g)
        nominal = band([r for r in g if r['mu'] == 1. and r['yaw_deg'] == 0])
        low_mu = band([r for r in g if r['mu'] == .5 and r['yaw_deg'] == 0])
        yawed = band([r for r in g if r['mu'] == 1. and r['yaw_deg'] == 3])
        print(*key, '|', f'{first:.2f} / {again:.2f}', '|', f'{nominal:.2f} / {low_mu:.2f} / {yawed:.2f}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['run', 'table'])
    parser.add_argument('out', type=Path)
    parser.add_argument('--stage', choices=['main', 'clearance'], default='main')
    parser.add_argument('--clearance', type=float)
    parser.add_argument('--workers', type=int, default=14)
    args = parser.parse_args()
    if args.command == 'table':
        return table(args.out, args.clearance)
    todo = list(cases(args.stage))
    with Pool(args.workers) as pool, open(args.out, 'w') as f:
        for i, row in enumerate(pool.imap(one, todo, chunksize=4)):
            f.write(json.dumps(row)+'\n')
            if i % 500 == 0:
                print(i, '/', len(todo), flush=True)


if __name__ == '__main__':
    main()
