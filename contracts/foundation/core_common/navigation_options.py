"""Pure option shape of a bounded navigation session (shared by the drive node and the robot web page)."""
import math


STRATEGIES = {'gain': 'explore', 'nearest': 'explore_nearest', 'coverage': 'coverage'}


def validate_options(value):
    if not isinstance(value, dict) or set(value) != {'strategy', 'duration_s', 'stall_s'}:
        raise ValueError('strategy, duration_s and stall_s are required')
    if not isinstance(value['strategy'], str) or value['strategy'] not in STRATEGIES:
        raise ValueError('Unknown navigation strategy')
    for key, low, high in (('duration_s', 10, 3600), ('stall_s', 10, 600)):
        v = value[key]
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{key} must be between {low} and {high} seconds')
    if value['stall_s'] > value['duration_s']:
        raise ValueError('stall_s cannot exceed duration_s')
    return dict(value)
