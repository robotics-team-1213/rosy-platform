"""Score the D-557 lap against a conservative circular body proxy, not field clearance."""
import json
import math
from pathlib import Path

HERE = Path(__file__).parent
CENTER = (-0.3357, 0.0011)
INNER_LINE_M = 0.155
OUTER_LINE_M = 0.345
NOMINAL_RADIUS_M = 0.076  # D-397 collision planning radius; actual footprint still needs proof.
SECTORS = (('ring_s', -137.7, -52.5), ('ring_e', -52.5, 52.3), ('ring_n', 52.3, 137.1))


def evaluate(rows, summary):
    arcs = {name: [] for name, _, _ in SECTORS}
    for row in rows:
        if not str(row.get('reason') or '').startswith('lane_arc') or not row.get('gt'):
            continue
        x, y, _ = row['gt']
        radius = math.hypot(x - CENTER[0], y - CENTER[1])
        angle = math.degrees(math.atan2(y - CENTER[1], x - CENTER[0]))
        name = next((name for name, lo, hi in SECTORS if lo <= angle < hi), None)
        if name:
            clearance = min(radius - INNER_LINE_M, OUTER_LINE_M - radius) - NOMINAL_RADIUS_M
            arcs[name].append(clearance)
    if any(not values for values in arcs.values()):
        raise ValueError('missing ground-truth samples for a ring arc')
    return {'trip_result': summary['result'], 'nominal_radius_m': NOMINAL_RADIUS_M,
            'line_centres_m': [INNER_LINE_M, OUTER_LINE_M],
            'arcs': {name: {'ticks': len(values), 'min_proxy_clearance_m': round(min(values), 4),
                            'negative_proxy_ticks': sum(value < 0 for value in values)}
                     for name, values in arcs.items()}}


if __name__ == '__main__':
    rows = [json.loads(line) for line in (HERE / 'log.jsonl').read_text(encoding='utf-8').splitlines()]
    result = evaluate(rows, json.loads((HERE / 'summary.json').read_text(encoding='utf-8')))
    assert result['trip_result'] == 'arrived'
    assert sum(arc['ticks'] for arc in result['arcs'].values()) == 132
    print(json.dumps(result, indent=2, sort_keys=True))
