"""D-520 7 golden: a fixed line-follow scenario using only API present on main 627ae3c0c (follow,
D-495 turn with advance and reacquire, straight, stop, IR guard, loss to LOST). Its trace on main
is test_lane_arc_off_golden.json; with arc_enabled false the branch must match it tick for tick."""
from core_features.line_follow.model import LineFollowMode, LineObservation
from test_line_junction import BODY, Rig

IR = LineFollowMode.IR_LINE
CLEAR = [(1.5, 1.5)]


def scenario(ir_guard):
    out = []
    rig = Rig(**(dict(BODY, ir_guard_enabled=True, obstacle_mode='path') if ir_guard else {}))

    def step(ir=None, **kwargs):
        if ir is not None:
            t = round(rig.now + .05, 6)
            error = {'clear': None, 'left': -.9, 'right': .9, 'centre': 0.}[ir]
            rig.m.observe(LineObservation(IR, t, error is not None, error, .9 if error is not None else 0.,
                                          ir_calibrated=True, calibration_revision='r'), received_at=t)
        d, s = rig.step(move=True, points=CLEAR if ir_guard else None, **kwargs)
        out.append([round(d.linear, 9), round(d.angular, 9), s.state, s.reason, s.junction.state,
                    s.junction.pivot_basis, s.junction.seq])

    ir = 'clear' if ir_guard else None
    for _ in range(4):
        step(ir)
    rig.send('left', turn_deg=90.)
    step(ir, junction=True, seen=False)
    for _ in range(140):
        step(ir, seen=False)
    for _ in range(4):
        step(ir)
    rig.m.set_junction('straight', 'J2', 10.)
    for _ in range(3):
        step(ir, junction=True)
    for _ in range(8):
        step(ir)
    if ir_guard:
        for side in ('left', 'right', 'centre', 'clear'):
            step(side)
    rig.m.set_junction('stop', 'J3', 10., .05)
    for _ in range(6):
        step(ir)
    rig.m.set_junction('straight', 'J4', 10.)
    for _ in range(80):
        step(ir, seen=False)
    return out
