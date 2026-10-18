"""Bounded collection orchestration; uses the existing command owner, never powers hardware."""
import shutil
import time

from camera_quality import advancing_frame
from collection_profile import digest, number, require, validate_profile, validate_teacher
from collection_store import RawCollection, append, save


def validate_environment(receipt, profile, *, now_ns):
    require(isinstance(receipt, dict) and receipt.get('policy') == 'omx-photometric-v3', 'environment policy differs')
    stamp, expires = receipt.get('recorded_ns'), receipt.get('expires_ns')
    require(type(stamp) is int and type(expires) is int and 0 < stamp <= now_ns < expires
            and now_ns-stamp <= 750_000_000, 'environment receipt stale/future')
    require(isinstance(receipt.get('run_id'), str) and bool(receipt['run_id'])
            and isinstance(receipt.get('profile_sha256'), str) and len(receipt['profile_sha256']) == 64
            and all(c in '0123456789abcdef' for c in receipt['profile_sha256']),
            'environment run/profile missing')
    require(receipt.get('motion_admitted') is False and receipt.get('physical_acceptance') is False,
            'camera receipt scope differs')
    for role in ('top', 'front'):
        item = receipt.get('observations', {}).get(role, {})
        plan = receipt.get('environment', {}).get(role, {})
        require(advancing_frame(item, (0., 0)) and item['quality'].get('usable') is True
                and item['quality'].get('condition') == 'NORMAL', role+' image insufficient')
        quality = item['quality']
        require(all(number(quality.get(key)) and 0 <= quality[key] <= 255
                    for key in ('mean_intensity', 'spatial_contrast', 'p5', 'p95'))
                and all(number(quality.get(key)) and 0 <= quality[key] <= 1
                        for key in ('dark_fraction', 'clipped_fraction')), role+' invalid quality metrics')
        require(plan.get('state') in ('NORMAL', 'WAITING_FRAME') and plan.get('condition') == 'NORMAL'
                and plan.get('pending') == 'NORMAL' and type(plan.get('confirmations')) is int
                and plan['confirmations'] >= 3, role+' environment not stable')
        require(all(type(plan.get(key)) is int and plan[key] >= 0
                    for key in ('environment_epoch','control_generation')), role+' environment generation invalid')
        require(number(plan.get('source_after')) and item['source_stamp'] > plan['source_after'],
                role+' frame predates control settlement')
        require(0 <= now_ns/1e9-item['source_stamp'] <= profile['max_image_age_s']
                and number(item.get('receipt_age_s')) and 0 <= item['receipt_age_s'] <= profile['max_image_age_s'],
                role+' image stale')
    return receipt


def validate_observation(sample, profile, now_ns):
    validate_environment(sample['environment'], profile, now_ns=now_ns)
    require(type(sample.get('time_ns')) is int and 0 <= now_ns-sample['time_ns'] <= 100_000_000,
            'observation clock stale/future')
    for key, maximum in (('state_age_s', 'max_state_age_s'), ('reference_age_s', 'max_reference_age_s')):
        require(number(sample.get(key)) and 0 <= sample[key] <= profile[maximum], key+' stale')
    for key in ('observation_state', 'action'):
        values = sample.get(key)
        require(isinstance(values, list) and len(values) == 6 and all(number(v) for v in values)
                and all(-100 <= v <= 100 for v in values[:5]) and 0 <= values[5] <= 100, key+' invalid')
    positions = sample.get('joint_positions')
    require(isinstance(positions, list) and len(positions) == 6 and all(number(v) for v in positions),
            'native joint positions invalid')
    stamps = [sample.get('joint_source_stamp'), sample.get('reference_source_stamp')]
    require(set(sample['images']) == {'top', 'front'}, 'two original images required')
    for role, image in sample['images'].items():
        height, width, _ = profile['camera_shapes'][role]
        require(image['width'] == width and image['height'] == height
                and isinstance(image['data'], bytes) and len(image['data']) == height*width*3, role+' RGB differs')
        stamps.append(image['source_stamp'])
        require(image['source_stamp'] == sample['environment']['observations'][role]['source_stamp'],
                role+' environment is not bound to this original frame')
    require(all(number(stamp) and 0 <= now_ns/1e9-stamp <= profile['max_image_age_s'] for stamp in stamps),
            'source clock stale/future')
    require(max(stamps)-min(stamps) <= profile.get('max_skew_s', .2), 'sensor/reference skew exceeds envelope')


def require_provable_motion(start, step, profile):
    """A step whose every joint stays within tolerance of its start could 'reach' without moving (D-793)."""
    require(any(abs(t-s) > tol for s, t, tol in zip(start, step['positions'], profile['reach_tolerance_rad'])),
            'teacher step moves no joint beyond its reach tolerance; motion would be unprovable')


def require_reached(backend, step, profile, session_end):
    """A successful terminal is not motion: the measured joints must settle at the step target (D-793)."""
    deadline = min(time.monotonic()+profile['max_sample_gap_s'], session_end)
    while True:
        sample = backend.observe()
        validate_observation(sample, profile, time.time_ns())
        errors = [abs(a-b) for a, b in zip(sample['joint_positions'], step['positions'])]
        if all(e <= t for e, t in zip(errors, profile['reach_tolerance_rad'])):
            return errors
        require(time.monotonic() < deadline, 'joints did not reach the teacher target after a successful terminal')
        time.sleep(.01)


def run_session(profile, teacher, output, backend, *, episodes=1):
    validate_profile(profile, mode=backend.mode, acceptance=getattr(backend, 'acceptance', None), teacher=teacher)
    validate_teacher(teacher, profile)
    require(type(episodes) is int and 1 <= episodes <= 100, 'bounded episode count required')
    store = RawCollection(output, profile, digest(teacher), backend.mode)
    save(store.root/'teacher.json', teacher)
    save(store.root/'profile.json', profile)
    if getattr(backend, 'acceptance', None) is not None:
        save(store.root/'acceptance.json', backend.acceptance)
    began = time.monotonic()
    if hasattr(backend, 'set_deadline'):
        backend.set_deadline(began+profile['max_session_s'])
    current, stop = None, None
    def stop_once(reason):
        try:
            return backend.stop(reason[:100])
        except Exception as exc:
            return dict(hold_requested=False, physical_stop_verified=False, error=repr(exc))
    try:
        for _ in range(episodes):
            sample = backend.observe()
            previous_end = store.manifest['episodes'][-1]['end_ns'] if store.manifest['episodes'] else 0
            window_deadline = time.monotonic()+profile['max_sample_gap_s']
            while sample['environment']['recorded_ns'] <= previous_end:
                require(time.monotonic() < window_deadline, 'new episode environment window unavailable')
                time.sleep(.01)
                sample = backend.observe()
            validate_observation(sample, profile, time.time_ns())
            current = store.begin(min(sample['time_ns'], sample['environment']['recorded_ns']), sample['environment'])
            store.environment(sample['environment'])
            store.camera_info(sample.get('camera_info'), sample['time_ns'])
            last_frame, last_identity = time.monotonic(), None
            identity = (current['run_id'], current['profile_sha256'])
            generations = {r: (sample['environment']['environment'][r]['environment_epoch'],
                                sample['environment']['environment'][r]['control_generation']) for r in ('top','front')}
            for ordinal, step in enumerate(teacher['steps']):
                command_id = f'{current["cycle_id"]}-{ordinal}'
                require(shutil.disk_usage(store.root).free >= profile['free_disk_bytes'], 'disk reserve exhausted')
                before = backend.observe()
                validate_observation(before, profile, time.time_ns())
                start = before['joint_positions']
                require_provable_motion(start, step, profile)
                append(store.root/'events.jsonl', dict(kind='INTENT', step=step, command_id=command_id,
                                                       time_ns=time.time_ns()))
                require(time.monotonic()-began < profile['max_session_s'], 'session deadline before dispatch')
                decision = backend.submit(step, command_id)
                append(store.root/'events.jsonl', dict(kind='SUBMISSION', decision=decision,
                                                       command_id=command_id, time_ns=time.time_ns()))
                require(decision.get('accepted') is True, 'existing owner rejected teacher command')
                terminal = None
                while terminal is None:
                    require(time.monotonic()-began < profile['max_session_s'], 'session deadline exceeded')
                    require(shutil.disk_usage(store.root).free >= profile['free_disk_bytes'], 'disk reserve exhausted')
                    sample = backend.observe()
                    store.environment(sample['environment'])
                    store.camera_info(sample.get('camera_info'), sample['time_ns'])
                    validate_observation(sample, profile, time.time_ns())
                    env = sample['environment']
                    require((env['run_id'], env['profile_sha256']) == identity, 'environment run/profile changed')
                    require(all((env['environment'][r]['environment_epoch'],
                                 env['environment'][r]['control_generation'])
                                == generations[r] for r in generations), 'environment/control generation changed')
                    for event in backend.drain_events():
                        append(store.root/'events.jsonl', event)
                    image_identity = tuple(sample['images'][role]['source_stamp'] for role in ('top', 'front'))
                    now = time.monotonic()
                    if last_identity is None or all(a > b for a, b in zip(image_identity, last_identity)):
                        if now-last_frame >= 1/profile['fps'] or last_identity is None:
                            if last_identity is not None:
                                expected = 1/profile['fps']
                                require(abs(now-last_frame-expected) <= profile.get('max_frame_jitter_s', .03),
                                        'capture cadence exceeds accepted jitter; no frame interpolation')
                            store.sample(current, sample, step['positions'])
                            last_identity, last_frame = image_identity, now
                    require(now-last_frame <= profile['max_sample_gap_s'], 'new synchronized frame deadline exceeded')
                    terminal = backend.terminal()
                    if terminal is not None:
                        for event in backend.drain_events():
                            append(store.root/'events.jsonl', event)
                        require(terminal.get('succeeded') is True, 'controller terminal was not successful')
                        append(store.root/'events.jsonl', dict(kind='TERMINAL', result=terminal,
                                                               command_id=command_id, time_ns=time.time_ns()))
                    time.sleep(.01)
                errors = require_reached(backend, step, profile, began+profile['max_session_s'])
                append(store.root/'events.jsonl', dict(kind='REACHED', command_id=command_id, errors_rad=errors,
                                                       start_rad=list(start),
                                                       tolerance_rad=list(profile['reach_tolerance_rad']),
                                                       time_ns=time.time_ns()))
            require(current['frames'] >= 2, 'insufficient distinct captured frames')
            current.update(complete=True, reason='', end_ns=time.time_ns())
            current = None
    except (Exception, KeyboardInterrupt) as exc:
        reason = f'{type(exc).__name__}: {exc}'
        # Stop is attempted before evidence writes, including full/unwritable disks.
        stop = stop_once(reason)
        if current is None:
            store.manifest['error'] = reason
        else:
            current.update(complete=False, reason=reason, end_ns=time.time_ns())
            try:
                append(store.root/'events.jsonl', dict(kind='ABORT', cycle_id=current['cycle_id'],
                                                       reason=reason, time_ns=time.time_ns()))
            except OSError:
                pass
    finally:
        if stop is None:
            stop = stop_once('collection session finished')
    for event in backend.drain_events():
        append(store.root/'events.jsonl', event)
    if stop.get('hold_requested') is not True or stop.get('terminal_observed') is False:
        for episode in store.manifest['episodes']:
            episode.update(complete=False, reason='owner HOLD/terminal could not be confirmed')
    return store.close(stop)
