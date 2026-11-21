"""Per-tick expiry and measured handoff for a guarded runner policy chunk."""
import math


class Handoff:
    def __init__(self, spec, kin):
        required = ("min_z", "x", "y", "yaw_deg", "xy_tol", "angle_tol_deg", "close_target", "empty_stop")
        if (not isinstance(spec, dict)
                or not all(type(spec.get(k)) in (int, float) and math.isfinite(spec[k]) for k in required)
                or type(spec.get("hold_frames")) is not int or not 1 <= spec["hold_frames"] <= 30
                or spec["xy_tol"] <= 0 or spec["angle_tol_deg"] <= 0):
            raise ValueError("invalid policy handoff parameters")
        self.spec, self.kin, self.count = spec, kin, 0
        self.last_jaw = None

    def pose(self, state):
        from grasp_planner import norm_to_rad

        return self.kin.fk([norm_to_rad(v) for v in state[:5]])

    def sample(self, present, target, pose=None, health=None):
        from chunk_runner_commands import EMPTY_MARGIN

        s = self.spec
        pose = self.pose(present) if pose is None else pose
        closed = target[5] <= s["close_target"]
        measured_hold = closed and present[5] > max(target[5] + EMPTY_MARGIN, s["empty_stop"])
        current = (health or {}).get("current_ma")
        if s.get("hold_current_ma") is not None:
            measured_hold = measured_hold and bool(current and abs(current[5]) >= s["hold_current_ma"])
        jaw_still = self.last_jaw is not None and abs(present[5] - self.last_jaw) < 0.3
        self.last_jaw = present[5]
        holding = measured_hold and jaw_still
        self.count = self.count + 1 if holding else 0
        xy_error = math.hypot(pose.x - s["x"], pose.y - s["y"])
        # Opposing jaws admit the two equivalent top-down roll branches.
        yaw_error = abs((math.degrees(pose.yaw) - s["yaw_deg"] + 90) % 180 - 90)
        down_error = math.degrees(pose.tool_down_error_rad)
        return dict(triggered=(self.count >= s["hold_frames"] and pose.z >= s["min_z"] and xy_error <= s["xy_tol"]
                               and max(yaw_error, down_error) <= s["angle_tol_deg"]),
                    holding=holding, measured_hold=measured_hold, jaw_still=jaw_still, closed=closed,
                    holding_frames=self.count, required_frames=s["hold_frames"],
                    tcp_z_m=pose.z, minimum_z_m=s["min_z"], xy_error_m=xy_error, xy_tol_m=s["xy_tol"],
                    yaw_error_deg=yaw_error, down_error_deg=down_error, angle_tol_deg=s["angle_tol_deg"],
                    jaw=present[5], jaw_target=target[5], gripper_current_ma=abs(current[5]) if current else None)


class Playback:
    def __init__(self, spec, fps):
        from omx_adapter.chunk_library import GUARD_UNITS_PER_S

        if (not isinstance(spec, dict)
                or not all(type(spec.get(k)) in (int, float) and math.isfinite(spec[k])
                    for k in ("start", "observed", "max_age", "max_step"))
                or not 0 < spec["max_step"] <= GUARD_UNITS_PER_S / fps
                or not 0 < spec["max_age"] <= 5 or spec["observed"] > spec["start"]):
            raise ValueError("invalid policy playback timing")
        self.spec, self.period = spec, 1 / fps
        self.due, self.index, self.dropped = spec["start"], 0, 0
        self.times, self.handoff = [], None

    def ready(self, queue, target, now):
        if not self.times and now - self.spec["observed"] > self.spec["max_age"]:
            raise ValueError("stale policy observation at playback")
        while queue and now >= self.due + self.period:
            queue.pop(0)
            self.advance()
            self.dropped += 1
        if not queue:
            raise ValueError("policy chunk is late")
        if max(abs(a - b) for a, b in zip(queue[0], target)) > self.spec["max_step"] + 1e-6:
            raise ValueError("policy frame exceeds the reviewed step after timing trim")
        return now >= self.due

    def advance(self):
        self.index += 1
        self.due = self.spec["start"] + self.index * self.period

    def sent(self, now, consumed=True):
        self.times.append(now)
        if consumed:
            self.advance()

    def receipt(self):
        return dict(first_command_mono=self.times[0] if self.times else None,
                    last_command_mono=self.times[-1] if self.times else None,
                    observation_age_s=self.times[0] - self.spec["observed"] if self.times else None,
                    command_gaps_s=[b - a for a, b in zip(self.times, self.times[1:])],
                    dropped_runner_frames=self.dropped)


def start(runner):
    play = Playback(runner.library["policy_playback"], runner.fps)
    if (spec := play.spec.get("handoff")) is not None:
        from grasp_planner import load_kinematics

        if not isinstance(spec, dict):
            raise ValueError("invalid policy handoff parameters")
        kin, _, _ = load_kinematics(None, spec.get("tcp_x_m"))
        play.handoff = Handoff(spec, kin)
    return play


def tick_ready(runner, play):
    try:
        ready = play.ready(runner.queue, runner.target, runner.clock())
        if ready and runner.jitter.get("shaking"):
            raise ValueError("runner detected jitter during policy playback")
        if ready and play.handoff and runner.holding:
            goal, s = runner.queue[0], play.handoff.spec
            if goal[5] > s["close_target"]:
                raise ValueError("policy requested an open jaw while holding")
            pose = play.handoff.pose(goal)
            if math.hypot(pose.x - s["x"], pose.y - s["y"]) > s["xy_tol"]:
                raise ValueError("policy requested travel outside the source while holding")
        return ready
    except ValueError as error:
        runner.report(command="run policy", ok=False, policy_stop=str(error), timing=play.receipt(),
                      present=runner.last_present)
        runner.chunk, runner.queue, runner.policy_playback = None, [], None
        runner.hold(runner.last_present, "human hold", human=True)
        return False


def finish_tick(runner, play, present, error, settle_tol):
    facts = None
    if play.handoff is not None:
        health = runner.read_health() if play.handoff.spec.get("hold_current_ma") is not None else None
        if health is not None:
            runner.health = health
        facts = play.handoff.sample(present, runner.target, health=health)
        previously_held = runner.holding
        runner.holding = facts["holding"] or (previously_held and facts["measured_hold"])
        if previously_held and not runner.holding:
            runner.report(command="run policy", ok=False, policy_stop="measured grip slipped", handoff=facts,
                          timing=play.receipt(), present=present)
            runner.chunk, runner.queue, runner.policy_playback = None, [], None
            runner.hold(present, "human hold", human=True)
            return
    if runner.queue and not (facts and facts["triggered"]):
        return
    runner.report(command="run policy", ok=True, settled=error <= settle_tol, timing=play.receipt(),
                  handoff=facts, present=present)
    runner.chunk, runner.queue, runner.policy_playback = None, [], None
