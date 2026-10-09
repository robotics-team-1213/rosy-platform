#!/usr/bin/env python3
"""B4 (D-507 10) obstacle SIM probe: a real box on the lane must still stop the robot.

Reuses the D-495 Probe (CORE HTTP API, gz set_pose/create/remove, 10 Hz log, cmd.jsonl, events).
  --ahead A   box placed A m ahead of the body front before CAMERA_LINE (approach and stop)
  --drop D    drive --drive-s s first, then place the box D m ahead of the body front (sudden)
Summary: box gap (body front to box face, ground truth) at the first HOLD obstacle_ahead and
its minimum, the first all-zero /cmd_vel after the box (latency), and the hold events' source.
Usage: python3 b4_box.py --out runs/<name> [--ahead 0.30 | --drop 0.08] --base http://127.0.0.1:8100
"""
import argparse
import json
import math
import sys
import time

from d495_sim_probe import BODY_FRONT_X, Probe, brief, first_zero_cmd

BOX = 0.03


def gap(r, bx, by):
    """Body-front-to-box-face distance along the robot heading (ground truth)."""
    x, y, yaw = r['gt']
    return (bx - x) * math.cos(yaw) + (by - y) * math.sin(yaw) - BODY_FRONT_X - BOX / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--x', type=float, default=-1.26955)
    ap.add_argument('--y', type=float, default=0.24255)
    ap.add_argument('--yaw', type=float, default=-1.5708)
    ap.add_argument('--ahead', type=float, default=None)
    ap.add_argument('--drop', type=float, default=None)
    ap.add_argument('--drive-s', type=float, default=3.0)
    ap.add_argument('--duration', type=float, default=40.0)
    ap.add_argument('--base', default='http://127.0.0.1:8100')
    ap.add_argument('--token', default='rosy-dev-operator')
    a = ap.parse_args()
    p = Probe(a)
    res = {'scenario': 'box', 'ahead': a.ahead, 'drop': a.drop}
    try:
        p.set_pose(a.x, a.y, a.yaw)
        t0 = p.t()
        def place(dist):
            x, y, yaw = p.last().get('gt') or (a.x, a.y, a.yaw)
            d = BODY_FRONT_X + dist + BOX / 2
            bx, by = x + d * math.cos(yaw), y + d * math.sin(yaw)
            return bx, by, p.box('b4_box', bx, by, size=BOX)
        if a.ahead is not None:
            bx, by, row = place(a.ahead)
            time.sleep(1.0)
            p.mode('CAMERA_LINE')
        else:
            p.mode('CAMERA_LINE')
            time.sleep(a.drive_s)
            moving = p.last().get('cmd')
            res['cmd_before_drop'] = moving
            bx, by, row = place(a.drop)
        res['box'] = {'x': round(bx, 4), 'y': round(by, 4), 'sim_t': row['sim_t'], 'rep': row['rep']}
        time.sleep(a.duration)
        with p.lock:
            rows = [r for r in p.rows if r['t'] >= t0 and r.get('gt')]
        after = [r for r in rows if r['sim_t'] is not None and row['sim_t'] is not None
                 and r['sim_t'] >= row['sim_t']]
        held = [r for r in after if r.get('reason') == 'obstacle_ahead']
        res['first_hold'] = dict(brief(held[0]), box_gap_m=round(gap(held[0], bx, by), 4)) if held else None
        res['min_box_gap_m'] = round(min(gap(r, bx, by) for r in after), 4) if after else None
        res['final'] = dict(brief(rows[-1]), box_gap_m=round(gap(rows[-1], bx, by), 4)) if rows else None
        res['held_rows'] = len(held)
        res['rows_after_box'] = len(after)
        prev, zero = first_zero_cmd(p, row['sim_t'])
        res['cmd_before_box'], res['first_zero_cmd_after_box'] = prev, zero
        if zero and row['sim_t'] is not None:
            res['zero_cmd_latency_s'] = round(zero['sim_t'] - row['sim_t'], 3)
        p.files['events'].flush()
        res['hold_events'] = [json.loads(line).get('data') for line in open(p.out / 'events.jsonl')
                              if '"nav.line_obstacle_hold"' in line]
    except Exception as e:  # noqa: BLE001 - keep the evidence of a broken run
        res['error'] = repr(e)
    finally:
        p.mode('OFF')
        p.unbox('b4_box')
    p.close(res)
    return 0


if __name__ == '__main__':
    sys.exit(main())
