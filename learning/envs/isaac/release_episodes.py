"""Short release episodes for RL: one placement per episode instead of a whole nine-container run.

Each episode resets the arms, sets the prior stack at its targets (+-1 mm, scene initialisation only) and the held
box flat on the leveling table, then runs the accepted flow from regrasp to the settle window with physics only.
A failed episode is recorded and the next one starts. The nine-container flow in mapped_stack_task is unchanged.
"""
import math
import time

from mapped_stack_fixture import (cube_release_ready, cube_release_target, free_lift, home, measured_motion, plan, prefix_held, row_gaps,
                                  stable_box)
from release_corrector import BLOCKED_REWARD, estimate, observation, policy_command, release_reward


def yaw_quaternion(yaw):
    return [math.cos(yaw/2), 0., 0., math.sin(yaw/2)]


def layout(fixture, rng):
    """Episode start: which cell to place, the prior stack poses and the held box pose on the table."""
    items = plan(True, fixture=fixture)
    index = int(rng.integers(0, len(items)))
    # 0.5 mm above the target: exact touching heights made a six-box prior stack pop apart (run 8e96).
    # Yaw pi as after tabletop leveling: a yaw-0 start was outside the BC data and needed a half-turn wrist
    # path, and run e48a ended 20-26 mm off the release target or lost arm tracking.
    # Prior jitter +-0.5 mm / +-0.003 rad: +-1 mm with +-0.01 rad swung a 90 mm corner past the 1 mm envelope
    # tolerance (run 29b7, 12 prior failures). Arm 1 boxes are recorded at quaternion (0,0,0,-1) after leveling,
    # so they start at -pi: +pi put the BC model 18-27 mm off for every arm-1 centre-row episode in that run.
    prior = [([items[j]['target'][0]+rng.uniform(-.0005, .0005), items[j]['target'][1]+rng.uniform(-.0005, .0005),
               items[j]['target'][2]+.0005], math.pi+float(rng.uniform(-.003, .003))) for j in range(index)]
    centre = fixture['leveling_center_m']
    turn = math.pi if items[index]['arm'] == 0 else -math.pi
    held = ([centre[0]+rng.uniform(-.005, .005), centre[1]+rng.uniform(-.005, .005), centre[2]+.015],
            turn+float(rng.uniform(-.05, .05)))
    return dict(index=index, prior=prior, held=held)


def episode_rows(report):
    """(observation, noise, reward) for every explored decision of every episode."""
    rows = []
    for episode in report['trials'][0].get('episodes', []):
        reward = release_reward(episode['outcome']) if episode.get('outcome') else BLOCKED_REWARD
        rows.extend((d['observation'], d['noise'], reward) for d in episode.get('decisions', []))
    return rows


def run(t, fixture, cargo, initial, corrector, residual, seed, *, budget_s=1800.):
    """Run fixture['release_episodes'] episodes (or until budget_s of wall time) and return their records."""
    import numpy as np
    from pxr import UsdGeom
    from mapped_stack_task import await_prefix, packing_target, settle_stack
    rng, estimate_rng = np.random.default_rng(seed), np.random.default_rng(seed+7919)
    items, episodes, start = plan(True, fixture=fixture), [], time.monotonic()
    iterations, carry = fixture['release_feedback_iterations'], fixture['carry_height_m']
    for number in range(fixture['release_episodes']):
        if time.monotonic()-start > budget_s:
            break
        lay = layout(fixture, rng)
        index, record = lay['index'], dict(episode=number, index=lay['index'], decisions=[], outcome=None)
        item, arm = items[lay['index']], items[lay['index']]['arm']
        t.reset()
        for j, (position, yaw) in enumerate(lay['prior'] + [lay['held']]):
            box = cargo[index if j == len(lay['prior']) else j]
            box.set_world_pose(np.array(position), np.array(yaw_quaternion(yaw)))
            box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
            UsdGeom.Imageable(box.prim).MakeVisible()
        t.hold(240)
        try:
            first = t.snapshot()  # not `start`: that is the wall-clock budget origin (run a3b1 crashed on it)
            if not prefix_held(first, index, fixture):
                record['prior_failures'] = [dict(box=j, error_mm=[round(1000*(first['boxes'][j]['position'][k]
                    - items[j]['target'][k]), 3) for k in range(3)]) for j in range(index)
                    if not stable_box(first['boxes'][j], j, True, fixture=fixture, speed=False)]
                raise ValueError('initialised prior stack did not hold')
            p, q = cargo[index].get_world_pose()
            yaw = math.atan2(2*(q[0]*q[3]+q[1]*q[2]), 1-2*(q[2]**2+q[3]**2))
            t.move(arm, [p[0], p[1], carry], yaw)
            t.grip(arm, initial['gripper']['preopen'])
            t.move(arm, [p[0], p[1], p[2]+.002], yaw)
            t.grip(arm, initial['gripper']['close'])
            t.move(arm, [p[0], p[1], carry], yaw)
            if not all(free_lift(s['boxes'][index], arm, float(p[2])) for s in t.samples(36)):
                raise ValueError('regrasp lift failed')
            t.move(arm, [*item['target'][:2], carry])
            await_prefix(index, t.snapshot, t.step, fixture)
            command = None
            for k in range(iterations):
                if k == 0:  # the IK teacher descends on the estimate
                    command = packing_target(index, lambda: estimate(t.snapshot(), index, fixture, estimate_rng),
                                             t.step, float(p[2]), fixture, command)
                else:
                    seen = estimate(t.snapshot(), index, fixture, estimate_rng)
                    command, noise = policy_command(corrector, residual, seen, index, fixture, k, estimate_rng,
                                                    sigma=fixture['release_exploration_sigma_m'])
                    record['decisions'].append(dict(iteration=k, observation=observation(seen, index, fixture, k),
                                                    noise=noise))
                t.move(arm, command)
            packing_target(index, t.snapshot, t.step, float(p[2]), fixture)  # measured prior-stack check
            ready = t.snapshot()
            truth = cube_release_target(index, ready, float(p[2]), fixture=fixture)
            record['release_error_mm'] = 1000*math.dist(truth, ready['tcps'][arm])
            if not cube_release_ready(index, ready, float(p[2]), fixture=fixture):
                raise ValueError('cube release correction did not converge; opening blocked')
            t.grip(arm, initial['gripper']['release'], release=True)
            t.move(arm, [*item['target'][:2], carry])
            t.move(arm, home(arm, True, fixture=fixture))
            settled = measured_motion(settle_stack(index, t.snapshot, t.step, fixture))[-1]
            box = settled['boxes'][index]
            record['outcome'] = dict(position_error_mm=1000*math.dist(box['position'], item['target']),
                                     stable=stable_box(box, index, True, fixture=fixture),
                                     gaps_mm=[1000*g for g in row_gaps(settled, fixture, index+1)])
        except (ValueError, RuntimeError) as exc:
            record['error'] = str(exc)[:300]
        episodes.append(record)
        print('RELEASE_EPISODE', number, index, record['outcome'], record.get('error'), flush=True)
    return episodes
