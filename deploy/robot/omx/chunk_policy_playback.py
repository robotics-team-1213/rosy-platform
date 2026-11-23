"""Per-tick expiry and measured handoff for a guarded runner policy chunk."""
import math

from cell_policy_entry import finite_stamp as _finite
from chunk_runner_guards import safe_stderr


class Handoff:
    def __init__(self, spec, kin):
        required = ("min_z", "x", "y", "yaw_deg", "xy_tol", "angle_tol_deg", "close_target", "empty_stop")
        vals = {k: _finite(spec.get(k)) for k in required} if isinstance(spec, dict) else {}
        raw_cur = spec.get("hold_current_ma") if isinstance(spec, dict) else None
        cur = None if raw_cur is None else _finite(raw_cur)
        if (not isinstance(spec, dict) or any(vals[k] is None for k in required)
                or type(spec.get("hold_frames")) is not int or not 1 <= spec["hold_frames"] <= 30
                or vals["xy_tol"] <= 0 or vals["angle_tol_deg"] <= 0
                or not -360.0 <= vals["yaw_deg"] <= 360.0
                or (raw_cur is not None and (cur is None or cur < 0))):
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


class JawGate:
    def __init__(self, spec, kin, *, tcp_x_m: float | None = None, library: dict | None = None, params=None,
                 rim_z_m: float | None = None, trusted_grasp: dict | None = None):
        import cell_params as prm
        from cell_policy_shape import validate_jaw_gate_geometry

        tol_lo, tol_hi = prm.DEFAULTS["policy.approach_yaw_tol_deg"][2:]
        required = ("x", "y", "z_m", "xy_radius_m", "yaw_deg", "tol_deg", "max_tilt_rad")
        square = spec.get("square", False) if isinstance(spec, dict) else None
        vals = {k: _finite(spec.get(k)) for k in required} if isinstance(spec, dict) else {}
        if (not isinstance(spec, dict) or any(vals[k] is None for k in required) or type(square) is not bool
                or not 0.02 <= vals["xy_radius_m"] <= 0.25 or not -360.0 <= vals["yaw_deg"] <= 360.0
                or not (tol_lo <= vals["tol_deg"] <= tol_hi and (not square or vals["tol_deg"] < tol_hi))
                or not 0.0 < vals["max_tilt_rad"] <= 0.45):
            raise ValueError("invalid policy jaw_gate parameters")
        validate_jaw_gate_geometry(spec, kin, library, params=params, rim_z_m=rim_z_m, trusted_grasp=trusted_grasp)
        self.spec, self.kin = spec, kin
        tcp_offset = getattr(kin, "tcp_offset", None)
        self.tcp_x_m = float(tcp_offset[0]) if tcp_offset is not None else tcp_x_m

    def same_as(self, other) -> bool:
        if other is None:
            return False
        keys = ("x", "y", "z_m", "xy_radius_m", "yaw_deg", "tol_deg", "max_tilt_rad")
        if (any(self.spec[k] != other.spec[k] for k in keys)
                or self.spec.get("square", False) != other.spec.get("square", False)
                or self.spec.get("rim_z_m") != other.spec.get("rim_z_m")):
            return False
        if self.tcp_x_m is None or other.tcp_x_m is None:
            return self.tcp_x_m is other.tcp_x_m
        return math.isclose(self.tcp_x_m, other.tcp_x_m, abs_tol=1e-6)

    def check_tick(self, present, goal) -> None:
        from cell_jaw_axis import wrap90
        from grasp_planner import norm_to_rad

        s = self.spec
        p_pose = self.kin.fk([norm_to_rad(float(v)) for v in present[:5]])
        g_pose = self.kin.fk([norm_to_rad(float(v)) for v in goal[:5]])
        in_zone = lambda pose: math.hypot(pose.x - s["x"], pose.y - s["y"]) <= s["xy_radius_m"] and pose.z <= s["z_m"]
        present_in = in_zone(p_pose)
        checks = []
        if present_in:
            checks.append(("measured", p_pose))
        if present_in or in_zone(g_pose):
            checks.append(("goal", g_pose))
        for tag, pose in checks:
            if pose.tool_down_error_rad > s["max_tilt_rad"]:
                raise ValueError(f"{tag} jaw tilt {math.degrees(pose.tool_down_error_rad):.1f} deg exceeds "
                                 f"{math.degrees(s['max_tilt_rad']):.1f} deg in grasp zone")
            diff = math.degrees(pose.yaw) - s["yaw_deg"]
            err = abs((diff + 45.0) % 90.0 - 45.0) if s.get("square") else abs(wrap90(diff))
            if err > s["tol_deg"]:
                raise ValueError(f"{tag} jaw yaw {math.degrees(pose.yaw):.1f} deg is {err:.1f} deg "
                                 f"from target {s['yaw_deg']:.1f} deg (tol {s['tol_deg']:.1f} deg)")


class Playback:
    def __init__(self, spec, fps):
        from omx_adapter.chunk_library import GUARD_UNITS_PER_S

        keys = ("start", "observed", "max_age", "max_step")
        vals = {k: _finite(spec.get(k)) for k in keys} if isinstance(spec, dict) else {}
        if (not isinstance(spec, dict) or any(vals[k] is None for k in keys)
                or not 0 < vals["max_step"] <= GUARD_UNITS_PER_S / fps
                or not 0 < vals["max_age"] <= 5 or vals["observed"] > vals["start"]):
            raise ValueError("invalid policy playback timing")
        self.spec, self.period = spec, 1 / fps
        self.due, self.index, self.dropped = spec["start"], 0, 0
        self.times, self.handoff, self.jaw_gate = [], None, None

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


def _trusted_tcp(runner):
    t = getattr(runner, "trusted_tcp", None)
    return (getattr(runner, "trusted_grasp", None) or {}).get("tcp_x_m") if t is None else t


def start_jaw_gate(runner, gate: dict) -> JawGate:
    from cell_policy_shape import resolve_gate_tcp
    from grasp_planner import load_kinematics
    if not isinstance(gate, dict):
        raise ValueError("invalid policy jaw_gate parameters")
    lib = getattr(runner, "library", None)
    resolved_tcp = resolve_gate_tcp(gate.get("tcp_x_m"), (lib or {}).get("tcp_x_m"), _trusted_tcp(runner))
    kin, _, _ = load_kinematics(None, resolved_tcp)
    return JawGate(gate, kin, tcp_x_m=resolved_tcp, library=lib, params=getattr(runner, "params", None),
                   rim_z_m=getattr(runner, "rim_z_m", None), trusted_grasp=getattr(runner, "trusted_grasp", None))


def halt_policy_gate(runner) -> bool:
    """On a non-human fault/contact stop, freeze retimer momentum and retain any active jaw gate for idle ticks."""
    play = getattr(runner, "policy_playback", None)
    gate = (play.jaw_gate if play is not None else None) or getattr(runner, "jaw_gate", None)
    had_gate = gate is not None or getattr(runner, "_trailing_jaw_gate", None) is not None
    if gate is not None and not getattr(runner, "human_hold_latched", False):
        runner._trailing_jaw_gate = gate
    runner.policy_playback = runner.jaw_gate = None
    if had_gate:
        stop = getattr(getattr(getattr(runner, "robot", None), "motion", None), "stop_streaming", None)
        if callable(stop):
            stop()
    return had_gate


def report_policy_halt(runner, present, gated: bool, **fields) -> None:
    try:
        runner.report(present=present, **fields)
    except OSError as write_error:
        if not gated:
            raise
        runner.policy_playback = runner.jaw_gate = runner._trailing_jaw_gate = None
        if not getattr(runner, "human_hold_latched", False):
            runner.hold(present, fields.get("error") or "status write failed", human=True)
        safe_stderr({"command": fields.get("command", "fault"), "status_write_failed": str(write_error)[:300]})


def _has_jaw_gate(runner) -> bool:
    play = getattr(runner, "policy_playback", None)
    return (play is not None and play.jaw_gate is not None) or any(
        getattr(runner, attr, None) is not None for attr in ("jaw_gate", "_trailing_jaw_gate"))


def _is_holding(runner) -> bool:
    return bool(getattr(runner, "holding", False) or (getattr(runner, "_committed_grip", None) or (None, False))[1]
                or getattr(runner, "_release_until", None) is not None)


def absorb_telemetry_error(runner, present, reason: str, error: Exception) -> bool:
    """Keep torque ON on telemetry/status OSError while jaw-gated, holding, latched, or interrupted."""
    from chunk_runner_guards import runner_has_configured_rim
    if getattr(runner, "human_hold_latched", False) or getattr(runner, "signals", None):
        return True
    if not (_has_jaw_gate(runner) or _is_holding(runner) or getattr(runner, "_stop_after_park", None)
            or runner_has_configured_rim(runner) or getattr(runner, "trusted_grasp", None) is not None):
        return False
    play = getattr(runner, "policy_playback", None) if getattr(runner, "chunk", None) == "policy" else None
    _hold_and_report(runner, present, f"{reason}: {error}", play.receipt() if play is not None else None)
    return True


def read_present_or_hold(runner, reason: str):
    """Read encoders; when jaw-gated, holding, latched, or interrupted, keep torque ON on read failure."""
    try:
        return runner.present(), True
    except Exception as error:  # noqa: BLE001
        fallback = getattr(runner, "last_present", None) or getattr(runner, "target", None)
        if fallback is None:
            raise
        fallback = list(fallback)
        if getattr(runner, "human_hold_latched", False):
            return fallback, True
        if not (_has_jaw_gate(runner) or _is_holding(runner) or getattr(runner, "_stop_after_park", None)):
            raise
        play = getattr(runner, "policy_playback", None) if getattr(runner, "chunk", None) == "policy" else None
        _hold_and_report(runner, fallback, f"{reason}: {error}", play.receipt() if play is not None else None)
        return fallback, False


def _hold_and_report(runner, present, reason: str, timing=None, **extra) -> bool:
    present = getattr(runner, "last_present", None) if present is None else present
    present = list(runner.target) if present is None else present
    if (getattr(runner, "_committed_grip", None) is None and runner.target is not None
            and len(runner.target) >= 6 and not runner.holding and len(present) >= 6 and runner.target[5] < present[5]):
        runner.target[5] = present[5]
    chunk_name = getattr(runner, "chunk", None)
    runner.policy_playback = runner.jaw_gate = runner._trailing_jaw_gate = None
    runner.hold(present, "human hold", human=True)
    cmd = f"run {chunk_name}" if chunk_name in ("policy", "entry") else "run policy"
    try:
        runner.report(command=cmd, ok=False, policy_stop=reason,
                      **({"timing": timing} if timing is not None else {}), present=present, **extra)
    except OSError as error:
        safe_stderr({"command": cmd, "policy_stop": reason, "status_write_failed": str(error)[:300]})
    return False


def active_jaw_gate(runner, play):
    if play is not None:
        return play.jaw_gate
    return getattr(runner, "jaw_gate", None) if runner.chunk in ("policy", "entry") else (
        getattr(runner, "_trailing_jaw_gate", None) if not runner.human_hold_latched else None)


def check_runner_jaw_gate(runner, gate: JawGate, goal, timing=None) -> bool:
    try:
        present = runner.present() if hasattr(runner, "present") else runner.last_present
        if present is None:
            raise ValueError("measured pose unavailable for jaw_gate")
        gate.check_tick(present, goal)
        return True
    except Exception as error:  # noqa: BLE001
        return _hold_and_report(runner, getattr(runner, "last_present", None), str(error), timing)


def make_goal_check(gate: JawGate):
    from omx_adapter.chunk_library import NAMES
    def _check(present_map, goal_map):
        try:
            if present_map is None or goal_map is None:
                return "measured or goal pose unavailable for jaw_gate"
            gate.check_tick([float(present_map[n]) for n in NAMES], [float(goal_map[n]) for n in NAMES])
            return None
        except Exception as error:  # noqa: BLE001
            return str(error)
    return _check


def send_hold_action(robot, target):
    from omx_adapter.chunk_library import NAMES
    action, checked = dict(zip(NAMES, target)), getattr(robot, "send_action_checked", None)
    return checked(action, None, hold_on_read_error=True, allow_stale_hold=True) if callable(checked) else robot.send_action(action)


def send_with_jaw_gate(runner, action: dict, gate, play, prev_target: list):
    """Validate guard-retimed Goal_Position before sync_write when `Guarded`; HOLD with torque ON if rejected."""
    from chunk_runner_settle import note_sent_grip
    protect = gate is not None or runner.human_hold_latched or _is_holding(runner) or bool(getattr(runner, "_stop_after_park", None))
    if not protect or not callable(getattr(runner.robot, "send_action_checked", None)):
        sent = runner.robot.send_action(action)
        note_sent_grip(runner, sent)
        return sent, True
    from guarded_native import GoalRejected
    from omx_adapter.chunk_library import NAMES
    try:
        check = make_goal_check(gate) if gate is not None else None
        stale = bool(runner.human_hold_latched and gate is None)
        sent = runner.robot.send_action_checked(action, check, hold_on_read_error=True, allow_stale_hold=stale)
        note_sent_grip(runner, sent)
        return sent, True
    except GoalRejected as error:
        if not runner.human_hold_latched:
            runner.target = list(prev_target)
        can_hold = getattr(error, "can_send_hold", True)
        raw = getattr(getattr(runner.robot, "motion", None), "last_present", None) if can_hold else None
        present = [float(raw[n]) for n in NAMES] if isinstance(raw, dict) else getattr(runner, "last_present", None)
        if not runner.human_hold_latched:
            _hold_and_report(runner, present, str(error), play.receipt() if play else None)
        if not can_hold:
            return None, False
        try:
            return send_hold_action(runner.robot, runner.target), False
        except GoalRejected:
            return None, False


def start(runner):
    from cell_policy_shape import resolve_gate_tcp
    from chunk_runner_guards import policy_requires_jaw_gate
    from grasp_planner import load_kinematics
    play = Playback(runner.library["policy_playback"], runner.fps)
    if (spec := play.spec.get("handoff")) is not None:
        if not isinstance(spec, dict):
            raise ValueError("invalid policy handoff parameters")
        kin, _, _ = load_kinematics(None, resolve_gate_tcp(spec.get("tcp_x_m"), (runner.library or {}).get("tcp_x_m"), _trusted_tcp(runner)))
        play.handoff = Handoff(spec, kin)
    gates = []
    for src in (play.spec, runner.library):
        if "jaw_gate" in src:
            if src["jaw_gate"] is None:
                raise ValueError("invalid policy jaw_gate parameters")
            gates.append(start_jaw_gate(runner, src["jaw_gate"]))
    if len(gates) == 2 and not gates[0].same_as(gates[1]):
        raise ValueError("policy_playback jaw_gate conflicts with library jaw_gate")
    play.jaw_gate = gates[0] if gates else None
    if play.jaw_gate is None and policy_requires_jaw_gate(runner):
        raise ValueError("policy chunk requires jaw_gate when grasp_pick or rim height is configured")
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
        return _hold_and_report(runner, getattr(runner, "last_present", None), str(error), play.receipt())


def finish_tick(runner, play, present, error, settle_tol):
    facts = None
    if play.handoff is not None:
        try:
            health = runner.read_health() if play.handoff.spec.get("hold_current_ma") is not None else None
            if health is not None:
                runner.health = health
            facts = play.handoff.sample(present, runner.target, health=health)
        except Exception as read_error:  # noqa: BLE001
            return _hold_and_report(runner, present, f"grip feedback unavailable: {read_error}", play.receipt())
        previously_held = runner.holding
        runner.holding = facts["holding"] or (previously_held and facts["measured_hold"])
        if previously_held and not runner.holding:
            return _hold_and_report(runner, present, "measured grip slipped", play.receipt(), handoff=facts)
    if runner.queue and not (facts and facts["triggered"]):
        return
    try:
        runner.report(command="run policy", ok=True, settled=error <= settle_tol, timing=play.receipt(), handoff=facts, present=present)
    except OSError as write_error:
        return _hold_and_report(runner, present, f"status write failed: {write_error}", play.receipt(), handoff=facts)
    if getattr(runner, "human_hold_latched", False):
        return
    runner._trailing_jaw_gate = play.jaw_gate
    runner.chunk, runner.queue, runner.policy_playback, runner.jaw_gate = None, [], None, None
