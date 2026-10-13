"""D-468 positive current IR floor observation; not a swept-floor classifier.

Keep cliff response in hazard policy. Saturation is unknown here even when the
legacy cliff detector deliberately returns False for two saturated channels.
"""


def floor_observed(values, *, fresh, enabled, cliff, tilt, pickup):
    flags=(fresh,enabled,cliff,tilt,pickup)
    if any(type(flag) is not bool for flag in flags):
        return False
    if not fresh or not enabled or cliff or tilt or pickup:
        return False
    if not isinstance(values,(tuple,list)) or len(values)!=3:
        return False
    if any(type(value) is not int or not 0<=value<=4095 for value in values):
        return False
    return sum(value<4000 for value in values)>=2
