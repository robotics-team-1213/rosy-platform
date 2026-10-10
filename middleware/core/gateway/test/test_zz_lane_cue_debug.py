from test_line_follow_lane_cue import Rig


def test_debug():
    rig = Rig()
    print("A", rig.cue("WRONG_WAY", 1, turn_deg=-170.0))
    rig.step()
    rig.t += 0.5
    print("B", rig.cue("WRONG_WAY", 2, turn_deg=-170.0), rig.m._cue_streak, rig.m._cue_yaw0)
    rig.t += 0.1
    rig.feed()
    now = rig.t + 0.01
    pose = rig.m._fresh_pose(now)
    print("pose", pose, rig.m._return_evidence.epoch, rig.m._lane_cue_busy(now))
    import math
    print("yaw0key", rig.m._cue_yaw0[0], (rig.m._return_evidence.epoch, pose.frame), rig.m._cue_yaw0[0] == (rig.m._return_evidence.epoch, pose.frame))
    print("plan", rig.m._lane_cue_plan(now, 1.0), rig.m._pivot, rig.m._cue_latch)
    assert False
