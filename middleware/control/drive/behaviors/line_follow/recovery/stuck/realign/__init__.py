"""D-607 8: CORE runs Fleet's REALIGN (PIVOT | KTURN) on an open D-407 stuck, re-checked every tick.

Fleet's rule picks it; CORE re-checks and drives it through the stuck action path (one cmd_vel, D-2).
Target: odom yaw at ``pose_stamp`` + ``angle_rad``, sign locked (``cue.odom_pivot.OdomPivot``: budget,
deadline, same odom run). PIVOT: in place, only with Fleet's ``turn_spot`` (the only place the IR centre
may see paint, D-344 §12); turn_m >= SWEEP_PAD_M + _TURN_CLEAR_M, all ROTATION_SECTORS seen. KTURN: reverse
arc (R >= back_radius_m, back_m odom metres, ``_back_refusal`` as is), then forward arc (R >= fwd_radius_m)
to the target. Every tick: scan fresh, URDF body, no calibration, D-573 gate not armed, IR guard, and the
D-422 body stop on the twist sent. Any failure: zero, ``local_aborted``. Done: settle, then lane + front
clear -> recovered, else Fleet again (never a local back-off). <= MAX_REALIGNS per stuck. E-stop/OFF/mode
change reset the stuck: never restarted. Off unless ``line_follow.stuck_realign_enabled``.
"""
