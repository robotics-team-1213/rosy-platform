"""Subject: same-frame visible lane-pair hypotheses, without driving authority.

Order is relative to the robot, never a persistent lane ID or a global lane count.
Only neighbouring, overlapping boundaries can form a candidate. Junction paint,
parallel fragments and lanes outside the camera's field of view remain unknown.
"""
import math


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _geometry(record):
    if not isinstance(record, dict) or record.get('rejected'):
        return None
    ends = record.get('ends_m')
    if (not isinstance(ends, (list, tuple)) or len(ends) != 2
            or any(not isinstance(p, (list, tuple)) or len(p) != 2
                   or not all(_number(v) and abs(v) <= 2 for v in p) for p in ends)):
        return None
    a, b = sorted(ends)
    if b[0] - a[0] < .025:
        return None
    heading = record.get('heading_deg')
    lateral = record.get('y_at_side_x_m')
    if not _number(heading) or abs(heading) > 45 or not _number(lateral) or abs(lateral) > 1:
        return None
    return a, b, lateral, heading


def lane_hypotheses(keep):
    """Pair camera boundaries for display; selected is supplied by the keeper.

    Width must be 75..125% of the configured lane at both observed overlap ends,
    and heading difference <=12 degrees. These conservative display gates do
    not replace the keeper's wider control pairing gates.
    """
    if not isinstance(keep, dict):
        return []
    width, records = keep.get('lane_width_m'), keep.get('boundaries')
    if not _number(width) or not .05 <= width <= 1 or not isinstance(records, list):
        return []
    ordered = []
    for record in records[:24]:
        geometry = _geometry(record)
        if geometry is not None:
            ordered.append((record, geometry))
    # A RANSAC fragment/double edge within 25 mm is not another lane boundary.
    # Preserve an explicitly selected record before a duplicate unselected one.
    ordered.sort(key=lambda r: (not bool(r[0].get('selected')), -r[1][2]))
    unique = []
    for record, geometry in ordered:
        if not any(abs(geometry[2] - g[2]) < .025 and abs(geometry[3] - g[3]) < 10
                   for _, g in unique):
            unique.append((record, geometry))
    unique.sort(key=lambda r: -r[1][2])
    lanes = []
    for (left, lg), (right, rg) in zip(unique, unique[1:]):
        lo, hi = max(lg[0][0], rg[0][0]), min(lg[1][0], rg[1][0])
        if hi - lo < .03 or abs(lg[3] - rg[3]) > 12:
            continue
        def y(geometry, x):
            a, b = geometry[:2]
            return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
        if not all(.75 * width <= y(lg, x) - y(rg, x) <= 1.25 * width for x in (lo, hi)):
            continue
        selected = (keep.get('strategy') == 'both'
                    and left.get('selected') is True and right.get('selected') is True)
        centre = (lg[2] + rg[2]) / 2
        relation = 'current' if selected else ('left' if centre > .03 else (
            'right' if centre < -.03 else 'unselected'))
        lanes.append(dict(left=left, right=right, selected=selected, relation=relation,
                          overlap_m=[lo, hi], centre_y_m=centre))
    return lanes
