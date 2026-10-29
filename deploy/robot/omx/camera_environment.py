"""Environment epochs and bounded recovery; image proxies do not measure lux or safety."""
from collections import deque
import math
import time
import urllib.request
import json
import uuid
import copy

CONDITIONS = {'NORMAL', 'UNDEREXPOSED', 'OVEREXPOSED', 'MIXED_LIGHTING',
              'LOW_CONTRAST', 'LOW_SPATIAL_SIGNAL', 'TEMPORAL_CHANGE'}


class ExposureRecovery:
    """Debounce entry and exit, scope exhaustion to epochs, and settle after controls."""
    def __init__(self, *, dark_count, bright_count):
        self.sizes = dict(dark=dark_count, bright=bright_count)
        self.condition = None
        self.pending = None
        self.confirmations = 0
        self.epoch = 0
        self.generation = 0
        self.attempts = 0
        self.finished = False
        self.next_change = 0.
        self.settle_until = 0.
        self.source_after = 0.
        self.last_source = 0.
        self.state = 'OBSERVING'
        self.budget_limited = False
        self.intensities = deque(maxlen=4)

    def observe(self, condition, now, *, source_stamp, intensity=None):
        if not math.isfinite(now):
            raise ValueError('finite monotonic time required')
        if (condition not in CONDITIONS or type(source_stamp) not in (float, int)
                or not math.isfinite(source_stamp) or source_stamp <= self.last_source):
            self.pending, self.confirmations = None, 0
            self.intensities.clear()
            self.state = 'STALE'
            return None
        self.last_source = source_stamp
        if now < self.settle_until or source_stamp <= self.source_after:
            self.pending, self.confirmations = None, 0
            self.intensities.clear()
            self.state = 'SETTLING'
            return None
        if intensity is not None:
            if not math.isfinite(intensity):
                raise ValueError('finite intensity required')
            self.intensities.append(intensity)
            if len(self.intensities) == 4 and max(self.intensities)-min(self.intensities) >= 30:
                condition = 'TEMPORAL_CHANGE'
        if condition == self.pending:
            self.confirmations += 1
        else:
            self.pending, self.confirmations = condition, 1
        if self.confirmations < 3:
            self.state = 'OBSERVING'
            return None
        if condition != self.condition:
            self.condition = condition
            self.epoch += 1
            self.attempts, self.finished = 0, False
            self.budget_limited = False
        if condition == 'NORMAL':
            self.state = 'NORMAL'
            return None
        kind = {'UNDEREXPOSED': 'dark', 'OVEREXPOSED': 'bright'}.get(condition)
        if kind is None or self.sizes[kind] == 0:
            self.state = 'UNSUPPORTED'
            return None
        if self.finished:
            self.state = 'EXHAUSTED'
            return None
        if now < self.next_change:
            self.state = 'BUDGET_LIMITED' if self.budget_limited else 'COOLDOWN'
            return None
        action = dict(kind=kind, index=self.attempts, epoch=self.epoch)
        if self.attempts >= self.sizes[kind]:
            action['kind'] = 'finish'
            self.finished = True
        else:
            self.attempts += 1
        self.next_change = now+5
        self.state = 'ADJUSTING'
        return action

    def applied(self, *, monotonic, wall):
        self.generation += 1
        self.settle_until = monotonic+1
        self.source_after = wall+1
        self.next_change = max(self.next_change, monotonic+5)
        self.intensities.clear()
        self.pending, self.confirmations = None, 0
        self.budget_limited = False
        self.state = 'SETTLING'

    def defer(self, action):
        if action['kind'] == 'finish':
            self.finished = False
        else:
            self.attempts -= 1
        self.budget_limited = True
        self.state = 'BUDGET_LIMITED'

    def snapshot(self):
        return dict(condition=self.condition, state=self.state, environment_epoch=self.epoch,
                    control_generation=self.generation, pending=self.pending,
                    confirmations=self.confirmations, attempts=self.attempts,
                    source_after=self.source_after, illumination_lux=None,
                    exposure_timestamp_verified=False, flicker_verified=False)


def monitor(profile, root, digest, duration, io):
    from camera_quality import Readiness, advancing_frame, same_fresh_frame
    baseline = io.prepare(profile, root, digest)
    gate = Readiness()
    plans = {role: ExposureRecovery(dark_count=len(spec['candidates']),
                                   bright_count=len(spec.get('bright_candidates', [])))
             for role, spec in profile['cameras'].items()}
    current = {role: dict(spec['original']) for role, spec in baseline['cameras'].items()}
    previous = dict(top=(0., 0), front=(0., 0))
    previous_quality = {}
    best, epochs = {}, {}
    changes = []
    run_id = uuid.uuid4().hex
    checks = dict.fromkeys(plans, 0.)
    resets = dict.fromkeys(plans, 0)
    signature = None
    began = time.monotonic()

    def guard(role):
        saved = baseline['cameras'][role]
        device = profile['cameras'][role]['device']
        if io.identity(device) != saved['identity'] or io.producer(saved.get('unit', role), device) != saved['producer']:
            raise RuntimeError('camera producer changed during environmental recovery')

    try:
        io.save(root/'control-run.json', dict(run_id=run_id))
        while duration == 0 or time.monotonic()-began < duration:
            try:
                with urllib.request.urlopen(profile['viewer_url']+'/state.json', timeout=2) as response:
                    state = json.load(response)
                if state.get('read_only') is not True:
                    raise ValueError('read-only observation viewer required')
                observation_error = None
            except Exception as exc:
                state, observation_error = {}, repr(exc)
            assessment = gate.update(state)
            for role, spec in profile['cameras'].items():
                plan = plans[role]
                item = state.get(role, {})
                quality = item.get('quality') or {}
                if same_fresh_frame(item, previous[role], previous_quality.get(role)):
                    plan.state = 'WAITING_FRAME'
                    continue
                valid = advancing_frame(item, previous[role])
                stamp = item.get('source_stamp') or 0
                if valid:
                    previous[role] = (stamp, item['sequence'])
                    previous_quality[role] = copy.deepcopy(quality)
                    now = time.monotonic()
                    if now >= checks[role]:
                        guard(role)
                        actual = io.get_controls(spec['device'], current[role])
                        guard(role)
                        checks[role] = now+5
                        if actual != current[role]:
                            if actual != baseline['cameras'][role]['original']:
                                raise RuntimeError('unowned camera controls changed during recovery')
                            old = plan
                            plan = plans[role] = ExposureRecovery(dark_count=old.sizes['dark'], bright_count=old.sizes['bright'])
                            plan.epoch, plan.generation = old.epoch+1, old.generation
                            plan.next_change, plan.settle_until = old.next_change, now+1
                            plan.source_after = time.time()+1
                            current[role] = dict(actual)
                            best.pop(role, None)
                            gate.counts[role] = 0
                            resets[role] += 1
                            assessment['photometric_ready'] = False
                action = plan.observe(quality.get('condition') if valid else None, time.monotonic(),
                                      source_stamp=stamp, intensity=quality.get('mean_intensity') if valid else None)
                if epochs.get(role) != plan.epoch:
                    best.pop(role, None)
                    epochs[role] = plan.epoch
                attributable = (valid and plan.state not in {'SETTLING', 'OBSERVING', 'STALE'}
                                and quality.get('condition') == plan.condition)
                if attributable:
                    score = quality['spatial_contrast']*(1-quality['clipped_fraction'])
                    if role not in best or score > best[role]['score']:
                        best[role] = dict(score=score, controls=dict(current[role]))
                if action is None:
                    continue
                if action['kind'] == 'finish':
                    selected = best.get(role, {}).get('controls', current[role])
                    if selected == current[role]:
                        plan.state = 'EXHAUSTED'
                        continue
                else:
                    key = 'candidates' if action['kind'] == 'dark' else 'bright_candidates'
                    candidates = spec[key]
                    completed = [i for i, candidate in enumerate(candidates)
                                 if all(current[role].get(n) == v for n, v in candidate.items())]
                    index = max(action['index'], max(completed, default=-1)+1)
                    if index >= len(candidates):
                        plan.attempts, plan.finished, plan.state = len(candidates), True, 'EXHAUSTED'
                        continue
                    action['index'], plan.attempts = index, index+1
                    selected = {**current[role], **candidates[index]}
                saved = baseline['cameras'][role]
                device = spec['device']
                guard(role)
                before = io.get_controls(device, current[role])
                guard(role)
                if before != current[role]:
                    if before != saved['original']:
                        raise RuntimeError('unowned camera controls changed before write')
                    plan.defer(action)
                    checks[role] = 0
                    continue
                try:
                    io.reserve_budget(root)
                except io.BudgetExhausted:
                    plan.defer(action)
                    continue
                entry = dict(run_id=run_id, role=role, action=action, requested=selected, time_ns=time.time_ns())
                intent = io.control_intent(root, role, saved, digest, run_id, before, selected,
                                           phase='restoring' if action['kind'] == 'finish' else 'applying')
                changes.append(entry)
                io.save(root/'changes.json', changes)
                io.save(root/'readiness.json', dict(state='ADJUSTING', photometric_ready=False,
                                                    motion_admitted=False, expires_ns=0))
                if action['kind'] == 'finish':
                    errors = io.restore_controls(selected, lambda n, v: io.write_control(device, n, v))
                    if errors:
                        raise RuntimeError('best settings restoration failed')
                else:
                    io.apply_candidate(selected, lambda n, v: io.write_control(device, n, v))
                actual = io.get_controls(device, selected)
                entry['actual'] = actual
                io.save(root/'changes.json', changes)
                if actual != selected:
                    raise RuntimeError('environmental recovery readback differs')
                intent['actual'] = actual
                io.save(root/f'control-intent-{role}.json', intent)
                current[role] = dict(selected)
                plan.applied(monotonic=time.monotonic(), wall=time.time())
                gate.counts[role] = 0
            environment = {role: plan.snapshot() for role, plan in plans.items()}
            ready = assessment['photometric_ready'] and all(p.state == 'NORMAL' for p in plans.values())
            now_ns = time.time_ns()
            assessment.update(state='READY' if ready else 'INSUFFICIENT', photometric_ready=ready,
                              recorded_ns=now_ns, expires_ns=now_ns+750_000_000, profile_sha256=digest,
                              run_id=run_id, environment=environment, observations=state,
                              observation_error=observation_error, control_resets=dict(resets))
            changed = tuple((r, p.condition, p.state, p.epoch, p.generation) for r, p in plans.items())
            if changed != signature:
                io.append_event(root/'environment.jsonl', assessment)
                signature = changed
            io.save(root/'readiness.json', assessment)
            time.sleep(.2)
    finally:
        try:
            io.save(root/'readiness.json', dict(state='STOPPED', photometric_ready=False,
                                               motion_admitted=False, expires_ns=0))
        finally:
            io.restore(root)
