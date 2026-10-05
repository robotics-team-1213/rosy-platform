"""Stdlib execution evidence semantics; no authority or dispatch dependencies."""
import math
import json
from uuid import UUID
from .artifacts import _fields, _hash, _names, _text


def number(value, *, minimum=None, positive=False):
    if (type(value) not in (int,float) or not math.isfinite(value)
            or (minimum is not None and value<minimum) or (positive and value<=0)):
        raise ValueError('finite bounded execution number required')
    return value


def ns(value):
    if type(value) is not int or not 0<=value<2**63:
        raise ValueError('nonnegative integer execution nanoseconds required')


def native_semantics(events):
    if not isinstance(events,list) or not events:raise ValueError('native event list required')
    kinds={'GOAL_ACCEPTED','GOAL_REJECTED','GOAL_ACCEPTANCE_UNKNOWN','RUNNING_FEEDBACK',
           'CANCEL_ACK','TERMINAL_RESULT','TERMINAL_UNKNOWN'}
    for event in events:
        _fields(event,'kind command_id phase_id goal_id observed_at_monotonic_s sequence status '
                      'result_code feedback_sequence cancel_acknowledged')
        if event['kind'] not in kinds:raise ValueError('original native event kind invalid')
        _text(event['command_id'])
        if event['phase_id'] is not None:_text(event['phase_id'])
        if event['kind'] in {'GOAL_REJECTED','GOAL_ACCEPTANCE_UNKNOWN'}:
            if event['goal_id'] is not None:raise ValueError('unaccepted event cannot have goal')
        else:
            goal=UUID(event['goal_id'])
            if goal.int==0 or str(goal)!=event['goal_id']:raise ValueError('original canonical UUID required')
        number(event['observed_at_monotonic_s'],minimum=0)
        if type(event['sequence']) is not int or event['sequence']<=0:raise ValueError('native sequence invalid')
        if event['kind']=='RUNNING_FEEDBACK':
            if type(event['feedback_sequence']) is not int or event['feedback_sequence']<=0:
                raise ValueError('native feedback sequence invalid')
        elif event['feedback_sequence'] is not None:raise ValueError('feedback only valid for native feedback')
        if event['kind']=='CANCEL_ACK':
            if type(event['cancel_acknowledged']) is not bool:raise ValueError('native cancel ACK type invalid')
        elif event['cancel_acknowledged'] is not None:raise ValueError('cancel acknowledgement kind invalid')
        if event['kind']=='TERMINAL_RESULT':
            if type(event['status']) is not int or event['status']<0:raise ValueError('native status invalid')
        elif event['status'] is not None:raise ValueError('native status kind invalid')
        if event['result_code'] is not None and (
                event['kind'] not in {'TERMINAL_RESULT','TERMINAL_UNKNOWN'} or type(event['result_code']) is not int):
            raise ValueError('native result code invalid')


def intent_semantics(intent, policy, binding, config):
    """Validate the original typed intent relationships, not their provenance trust."""
    lease,candidate,command=intent['lease'],intent['candidate'],intent['command']
    _fields(lease,'lease_id episode_id policy_revision identity issued_at_ns expires_at_ns owner_session_id')
    _fields(candidate,'lease_id episode_id policy_revision sequence observed_at_ns produced_at_ns positions '
                      'camera_frames camera_received_at_ns')
    _fields(command,'workcell_id instance_id command_id session_id owner positions duration_s '
                    'source_state_sequence calibration_revision joint_names trajectory_points phase_id '
                    'expected_start_state_positions start_state_tolerances')
    for name in ('lease_id','episode_id','policy_revision','owner_session_id'):_text(lease[name])
    for name in ('workcell_id','instance_id','command_id','session_id','owner','calibration_revision'):
        _text(command[name])
    for name in ('issued_at_ns','expires_at_ns'):ns(lease[name])
    if lease['expires_at_ns']<=lease['issued_at_ns']:raise ValueError('lease clock ordering differs')
    for name in ('sequence','observed_at_ns','produced_at_ns'):ns(candidate[name])
    ns(command['source_state_sequence'])
    if not lease['issued_at_ns']<=candidate['observed_at_ns']<=candidate['produced_at_ns']<lease['expires_at_ns']:
        raise ValueError('candidate clock/lease ordering differs')
    if command['phase_id'] is not None:_text(command['phase_id'])
    names=command['joint_names'];_names(names)
    if names!=policy['joint_names'] or names!=config['joint_names']:
        raise ValueError('original joint order differs')
    if (config['enabled'] is not True or 'learned_policy' not in config['allowed_owners']
            or command['calibration_revision']!=config['calibration_revision']
            or command['workcell_id']!=config['workcell_id'] or command['instance_id']!=config['instance_id']):
        raise ValueError('original enabled owner envelope differs')
    positions=command['positions']
    if set(positions)!=set(names) or len(candidate['positions'])!=len(names):
        raise ValueError('original command dimensions differ')
    for i,name in enumerate(names):
        number(positions[name]);number(candidate['positions'][i])
        low,high=config['position_limits'][name];number(low);number(high)
        a,b=binding['action_limits'][i];number(a);number(b)
        pl,ph=policy['action']['limits'][i]
        if not low<=a<=pl<ph<=b<=high or not pl<=positions[name]<=ph:
            raise ValueError('original installed action envelope exceeded')
    duration=number(command['duration_s'],positive=True)
    if duration>number(config['max_goal_duration_s'],positive=True):
        raise ValueError('original command exceeds owner duration')
    points=command['trajectory_points']
    if not isinstance(points,list) or not points:raise ValueError('original trajectory points required')
    previous=0
    for point in points:
        _fields(point,'time_from_start_s positions velocities accelerations')
        stamp=number(point['time_from_start_s'],positive=True)
        if stamp<=previous:raise ValueError('original trajectory times must increase')
        previous=stamp
        for field in ('positions','velocities','accelerations'):
            values=point[field]
            if values is None and field!='positions':continue
            if not isinstance(values,list) or len(values)!=len(names):
                raise ValueError('original trajectory dimensions differ')
            for i,value in enumerate(values):
                number(value)
                if field=='positions' and not config['position_limits'][names[i]][0]<=value<=config['position_limits'][names[i]][1]:
                    raise ValueError('original trajectory exceeds position envelope')
                limits=config.get({'velocities':'velocity_limits','accelerations':'acceleration_limits'}.get(field,''))
                if limits is not None and abs(value)>number(limits[names[i]],positive=True):
                    raise ValueError('original trajectory exceeds derivative envelope')
    if not math.isclose(previous,duration,rel_tol=0,abs_tol=1e-9) or points[-1]['positions']!=[positions[name] for name in names]:
        raise ValueError('original final trajectory time/positions differ')
    start,tolerance=command['expected_start_state_positions'],command['start_state_tolerances']
    if (start is None)!=(tolerance is None):raise ValueError('original start state pair required')
    if start is not None:
        if set(start)!=set(names) or set(tolerance)!=set(names):raise ValueError('original start state dimensions differ')
        for name in names:
            number(start[name]);number(tolerance[name],minimum=0)
            maximum=config['max_start_state_tolerances']
            if maximum is None or tolerance[name]>number(maximum[name],minimum=0):
                raise ValueError('original start tolerance exceeds owner envelope')
    frames,stamps=candidate['camera_frames'],candidate['camera_received_at_ns']
    if not isinstance(frames,list) or not isinstance(stamps,list) or len(frames)!=len(policy['cameras']):
        raise ValueError('original camera metadata dimensions differ')
    for frame in frames:_hash(frame)
    if stamps and len(stamps)!=len(frames):raise ValueError('original camera timestamp dimensions differ')
    for stamp in stamps:
        ns(stamp)
        if stamp>candidate['produced_at_ns']:raise ValueError('original camera causality differs')
    _fields(binding,'policy_revision profile robot_type environment device_profile_revision camera_profile_revision '
                    'owner cameras normalization_sha256 action_names action_limits timing')
    if (binding['policy_revision']!=policy['revision'] or binding['normalization_sha256']!=policy['normalization']['sha256']
            or binding['action_names']!=policy['action']['names'] or len(binding['action_limits'])!=len(names)
            or json.dumps(binding['owner'],sort_keys=True,separators=(',',':')) != json.dumps(
                policy['owner'],sort_keys=True,separators=(',',':'))
            or json.dumps(binding['cameras'],sort_keys=True,separators=(',',':')) != json.dumps(
                policy['cameras'],sort_keys=True,separators=(',',':'))
            or any(binding[name]!=policy[name] for name in (
                'profile','robot_type','environment','device_profile_revision','camera_profile_revision'))):
        raise ValueError('original installation differs from policy')
    if set(binding['timing'])!=set(policy['timing']):raise ValueError('original timing fields differ')
    for name,value in binding['timing'].items():
        if type(value) is not int or value<=0 or policy['timing'][name]>value:
            raise ValueError('original timing envelope differs')
    if binding['timing']['period_ns']!=policy['timing']['period_ns']:
        raise ValueError('original installed schedule differs')
