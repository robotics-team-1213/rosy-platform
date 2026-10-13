"""Heading and radial error against the 260919 ring when Fleet sends the SE `straight` (lap SIM 2).

Usage: python ring_entry_error.py <sends.jsonl> [...]
Ring: centre (-0.3357, 0.0011), r 0.2514 (lap SIM 2 result.md), counter-clockwise.
`line` = expect_in_m - pivot_past_line_m: the distance approach._corner_at_expected_line holds within
(CORNER_HOLD_AHEAD_M 0.45 + expect_tol_m).
"""
import json
import math
import sys

C, R = (-0.3357, 0.0011), 0.2514


def ring_error(x, y, yaw):
    tangent = math.atan2(y - C[1], x - C[0]) + math.pi / 2
    return math.hypot(x - C[0], y - C[1]) - R, math.degrees(math.remainder(yaw - tangent, math.tau))


if __name__ == '__main__':
    assert abs(ring_error(C[0], C[1] - R, 0.0)[1]) < 1e-9 and abs(ring_error(C[0], C[1] - R, 0.0)[0]) < 1e-9
    for path in sys.argv[1:]:
        for row in map(json.loads, open(path)):
            if row.get('place_id') == 'SE' and row.get('action') == 'straight':
                dr, err = ring_error(*row['gt'])
                e = row['expect']
                line = e['expect_in_m'] - e['pivot_past_line_m']
                print(f"dr={dr:+.3f} m heading_err={err:+.1f} deg line={line:.3f} m "
                      f"hold_range={0.45 + e['expect_tol_m']:.3f} m")
