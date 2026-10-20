"""Fixed assisted-SIM evidence decisions; no command generation or correction."""
import math
from uuid import UUID


def contact_held(position,*,close,contact):
    if not all(math.isfinite(x) for x in (position,close,contact)) or not close<contact:
        raise ValueError('finite width-matched gripper contact required')
    # Six teacher grasps read 0.008–0.011rad above analytic contact; freeze before policy trials.
    return close+(contact-close)/2<=position<=contact+.015


def goal_succeeded(row):
    events=row['events'];goal=row['driver_goal_id']
    try:
        if not goal or str(UUID(goal))!=goal or not UUID(goal).int:return False
    except (ValueError,TypeError,AttributeError):return False
    return bool(len(events)>=2 and events[0]['kind']=='GOAL_ACCEPTED'
        and events[0]['goal_id']==goal and events[-1]['kind']=='TERMINAL_RESULT'
        and events[-1]['goal_id']==goal and events[-1]['status']==4
        and events[-1]['result_code']==0)


def object_transition(*,attached,ever_attached,held,released,gripper_position,contact_gripper,
                      xy_error_m,z_error_m):
    if not all(math.isfinite(x) for x in (gripper_position,contact_gripper,xy_error_m,z_error_m)):
        raise ValueError('finite actual gripper/object evidence required')
    if attached:
        return 'detach' if gripper_position>contact_gripper+.02 else None
    if ever_attached:
        return 'settle' if released else None
    if held and 0<=xy_error_m<=.01 and 0<=z_error_m<=.01:
        return 'attach'
    return None
