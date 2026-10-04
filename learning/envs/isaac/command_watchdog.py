"""Simulator-only wheel command freshness; never publishes ROS motion.

Receipt must come from ROS2SubscribeTwist.execOut (a newly received message),
not a playback tick or a changed vector. Identical new commands remain valid.
"""

import math


class CommandWatchdog:
    def __init__(self, timeout: float = 0.5):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Command timeout must be finite and positive")
        self.timeout = timeout
        self.command_at = None
        self.graph_at = None
        self.sim_time = None

    def reset(self):
        self.command_at = None
        self.graph_at = None
        self.sim_time = None

    def receive(self, now: float):
        if not math.isfinite(now):
            self.reset()
            return
        self.command_at = now

    def graph_tick(self, now: float, sim_time: float):
        if (not math.isfinite(now) or not math.isfinite(sim_time)
                or (self.graph_at is not None and now < self.graph_at)
                or (self.sim_time is not None and sim_time < self.sim_time)):
            self.reset()
        if math.isfinite(now) and math.isfinite(sim_time):
            self.graph_at, self.sim_time = now, sim_time

    def filter(self, wheels, now: float, playing: bool = True):
        try:
            wheel_values_valid = len(wheels) == 2 and all(math.isfinite(value) for value in wheels)
        except (TypeError, ValueError):
            wheel_values_valid = False
        valid = (playing and math.isfinite(now) and self.command_at is not None and self.graph_at is not None
                 and 0 <= now - self.command_at < self.timeout and 0 <= now - self.graph_at < self.timeout
                 and wheel_values_valid)
        if not valid:
            self.command_at = None
            return (0.0, 0.0)
        return tuple(wheels)


# Installed by the runner, shared by its two in-memory trusted ScriptNodes.
ACTIVE_WATCHDOG = None

RECEIPT_SCRIPT = '''
import time
import command_watchdog

def compute(db):
    command_watchdog.ACTIVE_WATCHDOG.receive(time.monotonic())
    return True
'''

GATE_SCRIPT = '''
import time
import omni.timeline
import command_watchdog

def compute(db):
    timeline = omni.timeline.get_timeline_interface()
    now = time.monotonic()
    guard = command_watchdog.ACTIVE_WATCHDOG
    guard.graph_tick(now, timeline.get_current_time())
    db.outputs.velocityCommand = guard.filter(db.inputs.wheelVelocity, now, timeline.is_playing())
    db.outputs.execOut = og.ExecutionAttributeState.ENABLED
    return True
'''
