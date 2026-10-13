#!/usr/bin/env python3
"""Summarise bend_probe.py runs: python3 bend_analyze.py <runs dir> [--json out.json].

Per run: result, whether the bend stretch was reached (CORE junction 'armed' seen), where CORE
took over ('bending'), how the pass ended, the ground-truth lane offset and heading on the SW spoke
when CORE handed back (idle), and the first junction sighting after the pass.
"""
import json
import math
import sys
from pathlib import Path

#: SW spoke centre line (lane_graph west, fitted): through the bend vertex at 63.58 deg.
VERTEX, SPOKE = (-0.6924, -0.5091), math.radians(63.58)


def spoke(gt):
    dx, dy = gt[0]-VERTEX[0], gt[1]-VERTEX[1]
    return (round(-math.sin(SPOKE)*dx+math.cos(SPOKE)*dy, 3),
            round(math.degrees(math.remainder(gt[2]-SPOKE, math.tau)), 1))


def one(run):
    d = json.loads((run/'summary.json').read_text())
    states = d.get('states') or []
    keys = [s['key'][0] for s in states]
    took = next((s for s in states if s['key'][0] == 'bending'), None)
    end = next((s for s in states if s['key'][0] in ('aborted', 'unresolved')), None)
    done = d.get('done')
    gts = [r['gt'] for r in map(json.loads, (run/'log.jsonl').read_text().splitlines()) if r.get('gt')]
    row = {'run': run.name, 'result': d.get('result'), 'armed': 'armed' in keys,
           # past the W->S corner onto the bottom road, 0.2 m before the 0.15 m arc's start
           'reached_bend_stretch': any(g[0] > -1.0 and g[1] < -0.44 for g in gts),
           'took_over_gt': took and [round(v, 3) for v in took['gt']],
           'took_over_on': took and states[states.index(took)-1]['key'][2:],
           'ended': end and end['key'][:2], 'ended_gt': end and [round(v, 3) for v in end['gt']],
           'handback_spoke_offset_m_heading_deg': done and done.get('gt') and spoke(done['gt']),
           'min_to_sw_node_m': d.get('min_to_sw_node_m'),
           'first_sighting_after_bend': (d.get('first_sighting_after_bend') or {}).get('to_sw_node_m'),
           'last_state': states[-1]['key'] if states else None,
           'last_gt': states[-1].get('gt') and [round(v, 3) for v in states[-1]['gt']] if states else None}
    return row


def main():
    runs = sorted(p for p in Path(sys.argv[1]).iterdir() if (p/'summary.json').exists())
    rows = [one(r) for r in runs]
    for r in rows:
        print(json.dumps(r))
    if '--json' in sys.argv:
        Path(sys.argv[sys.argv.index('--json')+1]).write_text(json.dumps(rows, indent=1))


if __name__ == '__main__':
    main()
