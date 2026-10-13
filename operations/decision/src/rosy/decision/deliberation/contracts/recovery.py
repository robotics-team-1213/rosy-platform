"""Closed observed CORE episode facts, not execution authority."""


def recovery_context(value):
    if (type(value) is not dict or set(value) != {'phase', 'attempts', 'max_attempts', 'local_enabled', 'cause'}
            or value['phase'] != 'ASKING' or value['local_enabled'] is not True
            or type(value['cause']) is not str or value['cause'] not in {'lane_lost', 'no_motion', 'obstacle_ahead'}
            or type(value['attempts']) is not int or type(value['max_attempts']) is not int
            or not 0 <= value['attempts'] < value['max_attempts'] <= 8):
        raise ValueError('INVALID_RECOVERY_CONTEXT')
    return dict(value)
