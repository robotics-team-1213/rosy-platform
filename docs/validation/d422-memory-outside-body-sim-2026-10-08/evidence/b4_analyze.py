#!/usr/bin/env python3
"""B4 summary per run dir: memory-sourced hold events and the longest HOLD obstacle_ahead stretch.

Usage: python3 b4_analyze.py <runs dir> [--json out.json]
latched = a HOLD obstacle_ahead with body_gap_m 0.0 that lasts > 1 s, or any hold event whose
clearance_source is memory (the B9/D-495 latch signature).
"""
import json
import sys
from pathlib import Path


def run(d):
    rows = [json.loads(line) for line in open(d / 'log.jsonl')] if (d / 'log.jsonl').exists() else []
    events = [json.loads(line) for line in open(d / 'events.jsonl')] if (d / 'events.jsonl').exists() else []
    holds = [e.get('data') or {} for e in events if e.get('type') == 'nav.line_obstacle_hold']
    longest, zero_longest, start, zstart = 0.0, 0.0, None, None
    for r in rows:
        held = r.get('reason') == 'obstacle_ahead'
        start = (start if start is not None else r['t']) if held else None
        if start is not None:
            longest = max(longest, r['t'] - start)
        z = held and r.get('body_gap_m') == 0.0
        zstart = (zstart if zstart is not None else r['t']) if z else None
        if zstart is not None:
            zero_longest = max(zero_longest, r['t'] - zstart)
    summary = json.loads((d / 'summary.json').read_text()) if (d / 'summary.json').exists() else {}
    final = summary.get('final') or {}
    sources = sorted({h.get('clearance_source') for h in holds}, key=str)
    return {'run': d.name, 'rows': len(rows), 'hold_events': len(holds), 'hold_sources': sources,
            'memory_hold_events': sum(h.get('clearance_source') == 'memory' for h in holds),
            'longest_obstacle_hold_s': round(longest, 2), 'longest_gap0_hold_s': round(zero_longest, 2),
            'gt_path_m': summary.get('gt_path_m'), 'final_state': final.get('state'),
            'final_reason': final.get('reason'), 'final_gt': final.get('gt'),
            'latched': bool(zero_longest > 1.0 or any(h.get('clearance_source') == 'memory' for h in holds)),
            'error': summary.get('error')}


def main():
    base = Path(sys.argv[1])
    out = [run(d) for d in sorted(base.iterdir()) if d.is_dir()]
    for r in out:
        print(json.dumps(r))
    print(json.dumps({'runs': len(out), 'latched': sum(r['latched'] for r in out),
                      'memory_hold_events': sum(r['memory_hold_events'] for r in out)}))
    if '--json' in sys.argv:
        Path(sys.argv[sys.argv.index('--json') + 1]).write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
