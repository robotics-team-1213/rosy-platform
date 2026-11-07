"""Which robots' demonstrations the uploaded study path trains, and what their data must look like.

OMX-AI is the only adapter. Another robot gets a function here that accepts or converts its data, and a row in ADAPTERS.
"""

OMX_JOINTS = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')


def _omx_ai(*arms):
    names = [f'{arm}{joint}.pos' for arm in arms for joint in OMX_JOINTS]

    def check(info):
        for key in ('observation.state', 'action'):
            feature = info['features'][key]
            if feature['shape'] != [len(names)] or feature.get('names') not in (None, names):
                raise ValueError(f'OMX-AI {key} must be {len(names)} joints named {names[0]}...')
    return check


ADAPTERS = {'omx_follower': _omx_ai(''), 'bi_omx_follower': _omx_ai('arm_a.', 'arm_b.')}


def check(info):
    """Refuses a robot without an adapter and data its adapter does not accept. `info` has its vectors checked already."""
    adapter = ADAPTERS.get(info.get('robot_type'))
    if adapter is None:
        raise ValueError('no adapter for this robot; supported: ' + ', '.join(ADAPTERS))
    adapter(info)
