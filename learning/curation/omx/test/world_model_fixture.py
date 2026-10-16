"""Synthetic closed hardware-mode sessions for D-782 pipeline tests. Never evidence of a real demonstration.

States follow next = state + gain*(action - state), so a correct M1 beats both the hold and the reach baseline.
"""
import hashlib
import json
import random

TEACHER = dict(schema='rosy.omx-collection-teacher.v1', steps=[dict(positions=[0.]*6, duration_s=.1)])


def _rows(rng, frames, start, gain):
    state = [rng.uniform(-40, 40) for _ in range(5)] + [rng.uniform(20, 80)]
    rows = []
    for index in range(frames):
        action = [rng.uniform(-50, 50) for _ in range(5)] + [rng.uniform(10, 90)]
        rows.append({'frame_index': index, 'time_ns': start+1+index, 'joint_source_stamp': 1.+index/10,
                     'reference_source_stamp': 1.+index/10, 'requested_target_rad': [0.]*6,
                     'observation.state': [round(v, 6) for v in state], 'action': [round(v, 6) for v in action]})
        state = [s + gain*(a - s) for s, a in zip(state, action)]
    return rows


def _events(cycle, start, end, complete):
    command = cycle+'-0'
    rows = [dict(kind='INTENT', command_id=command, cycle_id=cycle, step=TEACHER['steps'][0], time_ns=start),
            dict(kind='SUBMISSION', command_id=command, cycle_id=cycle, decision=dict(accepted=True),
                 time_ns=start+1)]
    if complete:
        rows += [dict(kind='GOAL_ACCEPTED', command_id=command, goal_id=cycle+'-goal', sequence=1,
                      observed_at_monotonic_s=1.),
                 dict(kind='TERMINAL_RESULT', command_id=command, goal_id=cycle+'-goal', sequence=2,
                      observed_at_monotonic_s=2., status=4, result_code=0),
                 dict(kind='TERMINAL', command_id=command, cycle_id=cycle, time_ns=end-1,
                      result=dict(succeeded=True, source='native_follow_joint_trajectory'))]
    else:
        rows.append(dict(kind='ABORT', cycle_id=cycle, reason='synthetic stop', time_ns=end-1))
    return rows


def session(root, *, session_id, start, attempts=(True,), frames=8, gain=.5, seed=0, still=False):
    """Write one closed session; `attempts` lists each attempt's completion flag."""
    rng = random.Random(seed)
    root.mkdir()
    image = bytes([100, 110, 120]) * 1024
    episodes, events = [], []
    for index, complete in enumerate(attempts):
        begin, end = start + index*(frames+10), start + index*(frames+10) + frames + 2
        folder = root/f'episodes/{index:06d}'
        folder.mkdir(parents=True)
        images = {}
        for role in ('top', 'front'):
            relative = f'episodes/{index:06d}/{role}.rgb'
            (root/relative).write_bytes(image)
            images[role] = dict(path=relative, width=32, height=32, sha256=hashlib.sha256(image).hexdigest(),
                                source_stamp=1.)
        rows = _rows(rng, frames, begin, 0. if still else gain)
        if still:
            for row in rows:
                row['observation.state'] = rows[0]['observation.state']
        (folder/'samples.jsonl').write_text(''.join(json.dumps(dict(r, images=images))+'\n' for r in rows),
                                            encoding='utf-8')
        cycle = f'{session_id}-cycle-{index}'
        events += _events(cycle, begin, end, complete)
        episodes.append(dict(episode_index=index, cycle_id=cycle, start_ns=begin, end_ns=end, run_id='run-1',
                             profile_sha256='a'*64, complete=complete, frames=frames,
                             samples_path=f'episodes/{index:06d}/samples.jsonl',
                             reason='' if complete else 'ABORT: synthetic stop', outcome='unknown'))
    environment = dict(policy='omx-photometric-v3', run_id='run-1', profile_sha256='a'*64, recorded_ns=start,
                       motion_admitted=False, physical_acceptance=False, photometric_ready=False, observations={},
                       environment={r: dict(state='OBSERVING', condition=None, environment_epoch=0,
                                            control_generation=0) for r in ('top', 'front')})
    (root/'environment.jsonl').write_text(json.dumps(environment)+'\n', encoding='utf-8')
    (root/'teacher.json').write_text(json.dumps(TEACHER)+'\n')
    (root/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    manifest = dict(schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
                    source_mode='scripted_teacher', session_id=session_id, rig_revision='rig-1',
                    calibration_revision='cal-1', fps=10, task='synthetic', episodes=episodes,
                    teacher_sha256=hashlib.sha256(json.dumps(TEACHER, sort_keys=True,
                                                             separators=(',', ':')).encode()).hexdigest(),
                    camera_shapes={'top': [32, 32, 3], 'front': [32, 32, 3]},
                    body_units='normalized_-100_100', gripper_units='normalized_0_100',
                    stop=dict(hold_requested=True, terminal_observed=True, physical_stop_verified=False))
    manifest['files'] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in root.rglob('*') if p.is_file()}
    (root/'manifest.json').write_text(json.dumps(manifest)+'\n', encoding='utf-8')
    return manifest


def sessions(tmp_path, **kwargs):
    """train (one complete, one aborted attempt), eval and test sessions with disjoint clocks."""
    roots = {}
    for offset, (name, split, attempts) in enumerate((('s-train', 'train', (True, False)),
                                                      ('s-eval', 'eval', (True,)),
                                                      ('s-test', 'test', (True,)))):
        root = tmp_path/name
        session(root, session_id=name, start=1000*(offset+1), attempts=attempts, seed=offset, **kwargs)
        roots[name] = (root, split)
    return roots
